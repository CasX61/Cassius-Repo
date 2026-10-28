# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
Offline copies of tracks, stored in the addon profile.

Every cached track is the audio file plus a JSON sidecar holding the song's
metadata, and each album's cover is kept once next to them, so the offline
library can be browsed and played with the server unreachable.

    media/<song id>.<suffix>
    media/<song id>.json
    covers/<cover id>.jpg
"""

import threading
import time

import xbmc
import xbmcgui
import xbmcvfs

from resources.lib import kodi, storage

CHUNK = 256 * 1024
COVER_SIZE = 600

# Keys of a song dict worth keeping for offline browsing
SONG_KEYS = (
    'id', 'title', 'artist', 'displayArtist', 'album', 'albumId', 'artistId',
    'track', 'discNumber', 'duration', 'year', 'genre', 'suffix', 'coverArt',
    'starred', 'userRating',
)

_download_lock = threading.Lock()


def enabled():
    return kodi.setting_bool('offline_enabled', True)


def max_bytes():
    return max(0, kodi.setting_int('offline_size', 4000)) * 1024 * 1024


def media_dir():
    return storage.path('media')


def cover_dir():
    return storage.path('covers')


def song_id_from_path(playing_path):
    """Map a local file from this cache back to its song id."""
    normalized = (playing_path or '').replace('\\', '/')
    if kodi.ADDON_ID not in normalized or '/media/' not in normalized:
        return None
    name = normalized.rsplit('/', 1)[-1]
    return name.rsplit('.', 1)[0] or None


def _sidecar(song_id):
    return f'{media_dir()}/{storage.safe_name(song_id)}.json'


def get(song_id):
    """Playable local path of a cached song, or None."""
    if not song_id:
        return None
    meta = storage.read_json(_sidecar(song_id))
    if not meta:
        return None
    local = meta.get('_path')
    if local and storage.exists(local):
        return local
    storage.delete(_sidecar(song_id))
    return None


def cached_ids():
    _dirs, files = storage.listdir(media_dir())
    return {name[:-5] for name in files if name.endswith('.json')}


def entries():
    """Sidecars of every cached song, most recently downloaded first."""
    items = []
    for song_id in cached_ids():
        meta = storage.read_json(_sidecar(song_id))
        if isinstance(meta, dict) and meta.get('_path') and storage.exists(meta['_path']):
            items.append(meta)
    items.sort(key=lambda m: m.get('_cached_at', 0), reverse=True)
    return items


def total_size():
    total = 0
    for folder in (media_dir(), cover_dir()):
        _dirs, files = storage.listdir(folder)
        total += sum(storage.size_of(f'{folder}/{name}') for name in files)
    return total


def remove(song_id):
    meta = storage.read_json(_sidecar(song_id)) or {}
    if meta.get('_path'):
        storage.delete(meta['_path'])
    storage.delete(_sidecar(song_id))


def clear():
    for folder in (media_dir(), cover_dir()):
        _dirs, files = storage.listdir(folder)
        for name in files:
            storage.delete(f'{folder}/{name}')


def prune():
    """Drop the oldest downloads until the cache fits its size limit."""
    limit = max_bytes()
    if not limit:
        return 0
    total = total_size()
    removed = 0
    for meta in sorted(entries(), key=lambda m: m.get('_cached_at', 0)):
        if total <= limit:
            break
        total -= int(meta.get('_size', 0))
        remove(meta['id'])
        removed += 1
    return removed


def cover_path(cover_id):
    if not cover_id:
        return ''
    local = f'{cover_dir()}/{storage.safe_name(cover_id)}.jpg'
    return local if storage.exists(local) else ''


def _store_cover(client, cover_id):
    if not cover_id or cover_path(cover_id):
        return
    try:
        data = client.fetch(client.cover_url(cover_id, COVER_SIZE))
    except Exception as exc:
        kodi.log(f'cover {cover_id} not cached: {exc}')
        return
    storage.write_bytes(f'{cover_dir()}/{storage.safe_name(cover_id)}.jpg', data)


def _store_song(client, song, on_progress=None):
    song_id = song.get('id')
    if not song_id:
        return False
    if get(song_id):
        return True
    if not storage.ensure_dir(media_dir()):
        return False

    local = f'{media_dir()}/{storage.safe_name(song_id)}.{storage.safe_name(client.stream_suffix(song))}'
    try:
        response = client.open_stream(song_id)
    except Exception as exc:
        kodi.log_error(f'download {song_id} failed: {exc}')
        return False

    handle = xbmcvfs.File(local, 'w')
    written = 0
    ok = False
    try:
        total = int(response.headers.get('Content-Length') or 0)
        while True:
            chunk = response.read(CHUNK)
            if not chunk:
                break
            handle.write(bytearray(chunk))
            written += len(chunk)
            if on_progress and total:
                on_progress(written / total)
        ok = written > 0
    except Exception as exc:
        kodi.log_error(f'download {song_id} interrupted: {exc}')
    finally:
        handle.close()
        response.close()

    if not ok:
        storage.delete(local)
        return False

    meta = {key: song[key] for key in SONG_KEYS if key in song}
    meta.update({'_path': local, '_size': written, '_cached_at': time.time()})
    if not storage.write_json(_sidecar(song_id), meta):
        storage.delete(local)
        return False
    _store_cover(client, song.get('coverArt'))
    return True


def download(client, songs, title):
    """
    Download songs with a background progress dialog. Blocks, so callers in
    the UI run it on a worker thread.
    """
    songs = [s for s in songs if s.get('id') and not get(s['id'])]
    if not songs:
        kodi.notify(kodi.L('offline_already'))
        return
    if not _download_lock.acquire(blocking=False):
        kodi.notify(kodi.L('offline_busy'))
        return

    monitor = xbmc.Monitor()
    progress = xbmcgui.DialogProgressBG()
    progress.create(kodi.ADDON_NAME, kodi.L('offline_downloading').format(title))
    done = 0
    try:
        for index, song in enumerate(songs):
            if monitor.abortRequested():
                break
            label = f"{index + 1}/{len(songs)}  {song.get('title', '')}"

            def on_progress(fraction, index=index, label=label):
                progress.update(int((index + fraction) * 100 / len(songs)), message=label)

            on_progress(0)
            if _store_song(client, song, on_progress):
                done += 1
    finally:
        progress.close()
        _download_lock.release()

    prune()
    kodi.notify(kodi.L('offline_done').format(done, len(songs)), error=done < len(songs))
