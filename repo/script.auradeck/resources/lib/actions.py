# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
User actions shared by the Aura-Deck window and the widget plugin: favourites,
ratings, playlists, downloads and resolving "all songs of X".
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import xbmcgui

from resources.lib import connection, kodi, offline, subsonic


def _fail(exc):
    kodi.log_error(f'action failed: {exc}')
    kodi.notify(connection.describe_error(exc), error=True)


# Resolving songs
def album_songs(client, album_id):
    return client.album(album_id).get('song', [])


def playlist_songs(client, playlist_id):
    return client.playlist(playlist_id).get('entry', [])


def artist_songs(client, artist_id, limit=400):
    """Every song of an artist's albums, newest album first."""
    albums = client.artist(artist_id).get('album', [])
    albums.sort(key=lambda a: a.get('year') or 0, reverse=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda a: album_songs(client, a['id']), albums))
    songs = [song for album in results for song in album]
    return songs[:limit]


def songs_for(client, kind, item_id):
    """Songs behind any browsable item, for play/queue/download actions."""
    if kind == 'album':
        return album_songs(client, item_id)
    if kind == 'playlist':
        return playlist_songs(client, item_id)
    if kind == 'artist':
        return artist_songs(client, item_id)
    if kind == 'genre':
        return client.random_songs(200, genre=item_id)
    if kind == 'song':
        return [client.song(item_id)]
    return []


# Favourites and ratings
def set_star(client, kind, item_id, starred):
    """Star or unstar; returns the new state, or None when it failed."""
    try:
        client.star(kind, item_id, starred)
    except subsonic.ApiError as exc:
        _fail(exc)
        return None
    kodi.notify(kodi.L('fav_added' if starred else 'fav_removed'))
    return starred


def rate(client, item_id, name, current=0):
    labels = [kodi.L('rating_none')] + [
        kodi.L('rating_stars_one') if n == 1 else kodi.L('rating_stars').format(n) for n in range(1, 6)
    ]
    choice = xbmcgui.Dialog().select(kodi.L('rating_title').format(name), labels, preselect=current)
    if choice < 0:
        return None
    try:
        client.set_rating(item_id, choice)
    except subsonic.ApiError as exc:
        _fail(exc)
        return None
    return choice


# Playlists
def add_to_playlist(client, song_ids):
    song_ids = [s for s in song_ids if s]
    if not song_ids:
        return False
    try:
        playlists = [p for p in client.playlists() if not p.get('readonly')]
    except subsonic.ApiError as exc:
        _fail(exc)
        return False

    dialog = xbmcgui.Dialog()
    labels = [f"+  {kodi.L('playlist_new')}"] + [p.get('name', '') for p in playlists]
    choice = dialog.select(kodi.L('playlist_add_title'), labels)
    if choice < 0:
        return False
    try:
        if choice == 0:
            name = dialog.input(kodi.L('playlist_name'))
            if not name:
                return False
            client.create_playlist(name, song_ids)
        else:
            name = playlists[choice - 1].get('name', '')
            client.update_playlist(playlists[choice - 1]['id'], add=song_ids)
    except subsonic.ApiError as exc:
        _fail(exc)
        return False
    kodi.notify(kodi.L('playlist_added').format(len(song_ids), name))
    return True


def create_playlist(client):
    name = xbmcgui.Dialog().input(kodi.L('playlist_name'))
    if not name:
        return None
    try:
        return client.create_playlist(name)
    except subsonic.ApiError as exc:
        _fail(exc)
        return None


def rename_playlist(client, playlist):
    name = xbmcgui.Dialog().input(kodi.L('playlist_name'), defaultt=playlist.get('name', ''))
    if not name or name == playlist.get('name'):
        return None
    try:
        client.update_playlist(playlist['id'], name=name)
    except subsonic.ApiError as exc:
        _fail(exc)
        return None
    return name


def delete_playlist(client, playlist):
    if not xbmcgui.Dialog().yesno(kodi.ADDON_NAME, kodi.L('playlist_delete_confirm').format(playlist.get('name', ''))):
        return False
    try:
        client.delete_playlist(playlist['id'])
    except subsonic.ApiError as exc:
        _fail(exc)
        return False
    return True


def remove_from_playlist(client, playlist_id, index):
    try:
        client.update_playlist(playlist_id, remove_indexes=[index])
    except subsonic.ApiError as exc:
        _fail(exc)
        return False
    return True


# Offline
def download_async(client, songs, title):
    threading.Thread(target=offline.download, args=(client, songs, title), daemon=True).start()


def remove_downloads(song_ids):
    for song_id in song_ids:
        offline.remove(song_id)
    kodi.notify(kodi.L('offline_removed'))
    return True


def clear_offline():
    used = offline.total_size() / (1024 * 1024)
    if xbmcgui.Dialog().yesno(kodi.ADDON_NAME, kodi.L('offline_clear_confirm').format(used)):
        offline.clear()
        kodi.notify(kodi.L('offline_cleared'))
        return True
    return False
