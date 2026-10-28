# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
ListItem builders.

``ui_*`` items feed Aura-Deck's own window and carry what the skin XML needs
as properties. ``playable`` builds the items handed to Kodi's player and to
widgets, with a full music info tag.
"""

import zlib

import xbmcgui

from resources.lib import kodi, offline

GRID_ART = 300
DETAIL_ART = 600
PLAYER_ART = 800
FANART = 1280

MIME_BY_SUFFIX = {
    'mp3': 'audio/mpeg',
    'flac': 'audio/flac',
    'ogg': 'audio/ogg',
    'oga': 'audio/ogg',
    'opus': 'audio/ogg',
    'm4a': 'audio/mp4',
    'mp4': 'audio/mp4',
    'aac': 'audio/aac',
    'alac': 'audio/mp4',
    'wav': 'audio/wav',
    'aif': 'audio/aiff',
    'aiff': 'audio/aiff',
    'wma': 'audio/x-ms-wma',
    'ape': 'audio/x-ape',
    'wv': 'audio/x-wavpack',
    'dsf': 'audio/x-dsf',
}

GENRE_TILES = 12  # media/genre_<n>.png, picked by a stable hash of the name


def song_artist(song):
    return song.get('displayArtist') or song.get('artist') or ''


def album_artist(album):
    return album.get('displayArtist') or album.get('artist') or ''


def cover(client, cover_id, size=GRID_ART):
    """Server cover URL, or the offline copy when there is no server."""
    if client is not None and cover_id:
        return client.cover_url(cover_id, size)
    return offline.cover_path(cover_id)


def artist_image(client, artist, size=GRID_ART):
    # artistImageUrl is a public share link: no credentials, stable, cacheable
    url = artist.get('artistImageUrl')
    if url:
        return url
    return cover(client, artist.get('coverArt'), size)


def artist_fanart(client, artist_id):
    if client is None or not artist_id:
        return ''
    return client.cover_url(f'ar-{artist_id}', FANART)


def _new(label, label2='', kind='', item_id='', idx=None):
    item = xbmcgui.ListItem(label, label2, offscreen=True)
    item.setProperty('kind', kind)
    if item_id:
        item.setProperty('id', str(item_id))
    if idx is not None:
        item.setProperty('idx', str(idx))
    return item


# Aura-Deck window items
def ui_album(client, album, idx=None):
    item = _new(album.get('name', ''), album_artist(album), 'album', album.get('id'), idx)
    item.setArt({'thumb': cover(client, album.get('coverArt'))})
    item.setProperty('year', str(album.get('year') or ''))
    item.setProperty('starred', '1' if album.get('starred') else '')
    return item


def ui_artist(client, artist, idx=None):
    count = artist.get('albumCount')
    label2 = kodi.fmt_count(count, 'count_album', 'count_albums') if count else ''
    item = _new(artist.get('name', ''), label2, 'artist', artist.get('id'), idx)
    item.setArt({'thumb': artist_image(client, artist)})
    item.setProperty('starred', '1' if artist.get('starred') else '')
    return item


def ui_playlist(client, playlist, idx=None):
    label2 = kodi.fmt_count(playlist.get('songCount'), 'count_song', 'count_songs')
    item = _new(playlist.get('name', ''), label2, 'playlist', playlist.get('id'), idx)
    item.setArt({'thumb': cover(client, playlist.get('coverArt'))})
    return item


def genre_tile(name):
    index = zlib.crc32((name or '').encode('utf-8')) % GENRE_TILES
    return kodi.media_path(f'genre_{index}.png')


def ui_genre(client, genre, idx=None):
    """Genre tile: an album cover of the genre (if known) under its colour."""
    name = genre.get('value', '')
    label2 = kodi.fmt_count(genre.get('albumCount'), 'count_album', 'count_albums')
    item = _new(name, label2, 'genre', name, idx)
    tile = genre_tile(name)
    item.setArt({'thumb': cover(client, genre.get('_cover'), GRID_ART) or tile})
    item.setProperty('tile', tile)
    return item


def ui_song(client, song, idx, offline_ids=(), numbered=False, show_cover=True, playing_id=None):
    item = _new(song.get('title', ''), song_artist(song), 'song', song.get('id'), idx)
    item.setProperty('playing', '1' if playing_id and song.get('id') == playing_id else '')
    item.setArt({'thumb': cover(client, song.get('coverArt'))})
    item.setProperty('number', str(song.get('track') or '') if numbered else '')
    item.setProperty('cover', '1' if show_cover else '')
    item.setProperty('duration', kodi.fmt_duration(song.get('duration')))
    item.setProperty('album', song.get('album', ''))
    item.setProperty('starred', '1' if song.get('starred') else '')
    item.setProperty('offline', '1' if song.get('id') in offline_ids else '')
    return item


def ui_radio(radio, idx):
    homepage = (radio.get('homePageUrl') or '').split('//')[-1].split('/')[0]
    item = _new(radio.get('name', ''), homepage, 'radio', radio.get('id'), idx)
    item.setArt({'thumb': kodi.media_path('placeholder_radio.png')})
    item.setProperty('cover', '1')
    return item


def ui_separator(text):
    return _new(text, '', 'separator')


def ui_more(label, action):
    item = _new(label, '', 'more')
    item.setProperty('action', action)
    return item


def ui_button(action, label, icon, style=''):
    """style: 'primary' (accent pill), 'pill' (text pill) or '' (round icon)."""
    item = _new(label, '', 'button')
    item.setProperty('action', action)
    item.setProperty('icon', f'icon_{icon}.png')
    item.setProperty('style', style or 'icon')
    return item


def ui_history(query):
    item = _new(query, '', 'history')
    item.setProperty('action', 'history')
    return item


def ui_nav(key, label, icon):
    item = _new(label, '', 'nav')
    item.setProperty('action', key)
    item.setProperty('icon', f'icon_{icon}.png')
    return item


# Kodi player / widget items
def mime_type(client, song, local_path=None):
    if local_path:
        return MIME_BY_SUFFIX.get(local_path.rsplit('.', 1)[-1].lower(), '')
    if client is not None and client.transcode:
        return MIME_BY_SUFFIX.get(client.transcode[0], 'audio/mpeg')
    return song.get('contentType') or MIME_BY_SUFFIX.get((song.get('suffix') or '').lower(), '')


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def playable(client, song, prefer_offline=True):
    """
    A ListItem Kodi can play directly. Offline copies win over the stream so
    downloaded music keeps working without a server.
    """
    local = offline.get(song.get('id')) if prefer_offline and offline.enabled() else None
    if local:
        path = local
    elif client is not None:
        path = client.stream_url(song['id'])
    else:
        return None

    item = xbmcgui.ListItem(song.get('title', ''), song_artist(song), path=path, offscreen=True)
    tag = item.getMusicInfoTag()
    tag.setMediaType('song')
    tag.setTitle(song.get('title', ''))
    tag.setArtist(song_artist(song))
    tag.setAlbum(song.get('album', ''))
    tag.setAlbumArtist(song.get('displayAlbumArtist') or song.get('artist') or '')
    tag.setTrack(_int(song.get('track')))
    tag.setDisc(_int(song.get('discNumber')))
    tag.setDuration(_int(song.get('duration')))
    if _int(song.get('year')):
        tag.setYear(_int(song.get('year')))
    genres = [g.get('name') for g in song.get('genres') or [] if g.get('name')]
    if not genres and song.get('genre'):
        genres = [song['genre']]
    if genres:
        tag.setGenres(genres)
    if _int(song.get('userRating')):
        tag.setUserRating(_int(song.get('userRating')) * 2)

    item.setArt({
        'thumb': cover(client, song.get('coverArt'), PLAYER_ART),
        'fanart': artist_fanart(client, song.get('artistId')),
    })
    item.setProperty('auradeck_id', song['id'])
    mime = mime_type(client, song, local)
    if mime:
        item.setMimeType(mime)
    item.setContentLookup(False)
    return item
