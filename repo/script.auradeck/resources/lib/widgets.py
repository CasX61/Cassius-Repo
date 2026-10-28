# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
Plugin entry point.

    plugin://script.auradeck/                         opens the Aura-Deck window
    plugin://script.auradeck/?action=widgets          widget sources
    plugin://script.auradeck/?action=albums&type=newest
    plugin://script.auradeck/?action=songs&source=random
    plugin://script.auradeck/?action=playlists
    plugin://script.auradeck/?action=open&target=album:<id>
    plugin://script.auradeck/?action=setup | clear_offline

Albums and playlists open as folders of directly playable songs; their
context menu can jump into the full Aura-Deck window.
"""

import urllib.parse

import xbmcgui
import xbmcplugin

from resources.lib import actions, connection, items, kodi, offline, player, subsonic

L = kodi.L
WIDGET_SIZE = 40

ALBUM_SOURCES = (
    ('recent', 'home_recent'),
    ('newest', 'home_newest'),
    ('starred', 'home_starred'),
    ('random', 'home_discover'),
    ('frequent', 'home_frequent'),
    ('highest', 'home_highest'),
)

# Clients survive between invocations (reuselanguageinvoker), so their
# response cache keeps widgets fast when the home screen refreshes.
_clients = {}


def _client():
    key = tuple(kodi.setting(k) for k in ('server_url', 'username', 'auth_salt', 'auth_token',
                                          'verify_tls', 'ca_file', 'transcode'))
    if key not in _clients:
        _clients.clear()
        client = connection.client_from_settings()
        if client is None:
            return None
        _clients[key] = client
    return _clients[key]


class Plugin:
    def __init__(self, argv):
        self.base = argv[0]
        self.handle = int(argv[1])
        self.params = dict(urllib.parse.parse_qsl(argv[2].lstrip('?')))

    def url(self, **params):
        return f'{self.base}?{urllib.parse.urlencode(params)}'

    def run(self):
        action = self.params.get('action', 'root')
        handler = getattr(self, f'route_{action}', None)
        if handler is None:
            kodi.log(f'unknown plugin action {action}')
            return self.end(False)
        try:
            handler()
        except subsonic.ApiError as exc:
            kodi.notify(connection.describe_error(exc), error=True)
            self.end(False)

    def end(self, succeeded=True, content=None, cache=False):
        if self.handle < 0:
            return
        if content:
            xbmcplugin.setContent(self.handle, content)
        xbmcplugin.endOfDirectory(self.handle, succeeded=succeeded, cacheToDisc=cache)

    def require_client(self):
        client = _client()
        if client is None:
            kodi.notify(L('err_not_configured'), error=True)
        return client

    # Item builders
    def folder(self, label, url, icon=None, label2='', context=None):
        item = xbmcgui.ListItem(label, label2, offscreen=True)
        if icon:
            item.setArt({'icon': icon, 'thumb': icon})
        if context:
            item.addContextMenuItems(context)
        xbmcplugin.addDirectoryItem(self.handle, url, item, isFolder=True)

    def open_entry(self, kind, item_id):
        return (L('ctx_open_in_app'), f"RunPlugin({self.url(action='open', target=f'{kind}:{item_id}')})")

    def play_entries(self, kind, item_id):
        return [
            (L('ctx_play'), f"RunPlugin({self.url(action='play', kind=kind, id=item_id)})"),
            (L('ctx_shuffle'), f"RunPlugin({self.url(action='play', kind=kind, id=item_id, shuffle=1)})"),
        ]

    def add_albums(self, client, albums):
        for album in albums:
            item = xbmcgui.ListItem(album.get('name', ''), items.album_artist(album), offscreen=True)
            tag = item.getMusicInfoTag()
            tag.setMediaType('album')
            tag.setTitle(album.get('name', ''))
            tag.setAlbum(album.get('name', ''))
            tag.setArtist(items.album_artist(album))
            if album.get('year'):
                tag.setYear(int(album['year']))
            art = items.cover(client, album.get('coverArt'), items.GRID_ART)
            item.setArt({'thumb': art, 'poster': art, 'fanart': items.artist_fanart(client, album.get('artistId'))})
            item.addContextMenuItems([self.open_entry('album', album['id'])] + self.play_entries('album', album['id']))
            xbmcplugin.addDirectoryItem(self.handle, self.url(action='album', id=album['id']), item, isFolder=True)

    def add_songs(self, client, songs):
        for song in songs:
            item = items.playable(client, song)
            if item is None:
                continue
            context = []
            if client and song.get('albumId'):
                context.append(self.open_entry('album', song['albumId']))
            if client and song.get('artistId'):
                context.append((L('ctx_go_artist'),
                                f"RunPlugin({self.url(action='open', target='artist:' + song['artistId'])})"))
            item.addContextMenuItems(context)
            xbmcplugin.addDirectoryItem(self.handle, item.getPath(), item, isFolder=False)

    # Routes
    def route_root(self):
        self.end(False)
        kodi.open_app()

    def route_open(self):
        self.end(False)  # in case Kodi called this as a directory
        kodi.open_app(self.params.get('target', ''))

    def route_setup(self):
        connection.run_wizard()

    def route_clear_offline(self):
        actions.clear_offline()

    def route_widgets(self):
        icon = kodi.media_path
        for list_type, key in ALBUM_SOURCES:
            self.folder(L(key), self.url(action='albums', type=list_type), icon('icon_album.png'))
        self.folder(L('nav_playlists'), self.url(action='playlists'), icon('icon_playlist.png'))
        self.folder(L('widget_random_songs'), self.url(action='songs', source='random'), icon('icon_shuffle.png'))
        self.folder(L('fav_songs'), self.url(action='songs', source='starred'), icon('icon_favourite.png'))
        if offline.enabled():
            self.folder(L('nav_offline'), self.url(action='songs', source='offline'), icon('icon_offline.png'))
        self.end(cache=True)

    def route_albums(self):
        client = self.require_client()
        if client is None:
            return self.end(False)
        list_type = self.params.get('type', 'newest')
        albums = client.cached(f'widget:{list_type}', 120,
                               lambda: client.album_list(list_type, WIDGET_SIZE))
        self.add_albums(client, albums)
        self.end(content='albums')

    def route_album(self):
        client = self.require_client()
        if client is None:
            return self.end(False)
        self.add_songs(client, client.album(self.params['id']).get('song', []))
        xbmcplugin.addSortMethod(self.handle, xbmcplugin.SORT_METHOD_UNSORTED)
        self.end(content='songs')

    def route_playlists(self):
        client = self.require_client()
        if client is None:
            return self.end(False)
        for playlist in client.playlists():
            art = items.cover(client, playlist.get('coverArt'), items.GRID_ART)
            label2 = kodi.fmt_count(playlist.get('songCount'), 'count_song', 'count_songs')
            context = [self.open_entry('playlist', playlist['id'])] + self.play_entries('playlist', playlist['id'])
            self.folder(playlist.get('name', ''), self.url(action='playlist', id=playlist['id']),
                        art, label2, context)
        self.end(content='albums')

    def route_playlist(self):
        client = self.require_client()
        if client is None:
            return self.end(False)
        self.add_songs(client, client.playlist(self.params['id']).get('entry', []))
        self.end(content='songs')

    def route_songs(self):
        source = self.params.get('source', 'random')
        if source == 'offline':
            self.add_songs(_client(), offline.entries())
            return self.end(content='songs')
        client = self.require_client()
        if client is None:
            return self.end(False)
        if source == 'starred':
            songs = client.starred()['song']
        else:
            songs = client.random_songs(WIDGET_SIZE)
        self.add_songs(client, songs)
        self.end(content='songs')

    def route_play(self):
        client = self.require_client()
        if client is None:
            return
        songs = actions.songs_for(client, self.params.get('kind'), self.params.get('id'))
        player.play(client, songs, shuffle=self.params.get('shuffle') == '1')


def run(argv):
    Plugin(argv).run()
