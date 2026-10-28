# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
Pages of the Aura-Deck window.

A page only fetches and describes data; MainWindow renders it into one of
four views ('rows', 'grid', 'tracks', 'detail'). ``load`` runs on a worker
thread and may block on the network, everything else runs on the UI side.
"""

import datetime
import random
from concurrent.futures import ThreadPoolExecutor

import xbmcgui

from resources.lib import actions, items, kodi, offline, player, storage
from resources.lib.ui import ids

L = kodi.L

SHELF_SIZE = 20
TRACK_PREVIEW = 6


class Button:
    """
    style: 'primary' (accent pill with text), 'pill' (text pill),
    'accent' (round accent icon) or '' (round icon).
    """

    def __init__(self, action, label, icon, style=''):
        self.action = action
        self.label = label
        self.icon = icon
        self.style = style


class Section:
    def __init__(self, title, kind, models, more=None, limit=None):
        self.title = title
        self.kind = kind
        self.models = models
        self.more = more
        self.limit = limit


def fav_button(starred):
    if starred:
        return Button('favourite', L('btn_unfavourite'), 'favourite')
    return Button('favourite', L('btn_favourite'), 'favourite_outline')


def toggle_favourite(win, kind, model):
    state = actions.set_star(win.client, kind, model['id'], not model.get('starred'))
    if state is not None:
        model['starred'] = 'now' if state else None
    return state


class Page:
    view = ''
    nav = None          # sidebar entry to highlight

    def __init__(self):
        self.loaded = False
        self.state = None    # focus/positions saved when navigating away
        self.lists = {}      # control id -> models rendered in it
        self.buttons = []
        self.backdrop = ''
        self.empty = ''

    def load(self, win):
        self.loaded = True

    def action(self, win, name):
        pass

    def more(self, win, name):
        pass

    def default_focus(self):
        return ids.SIDEBAR

    def invalidate(self):
        self.loaded = False


# Rows: hero header + shelves
class RowsPage(Page):
    view = 'rows'
    hero = ''

    def __init__(self):
        super().__init__()
        self.props = {}
        self.tracks = None
        self.shelves = []
        self.history = []

    def default_focus(self):
        return {
            'home': ids.HERO_BUTTONS,
            'artist': ids.ARTIST_BUTTONS,
            'search': ids.SEARCH_FIELD,
        }.get(self.hero, ids.ROWS)


GENRE_COVER_LIMIT = 80


def add_genre_covers(client, genres):
    """Look up one album cover per genre (cached for hours) for the tiles."""
    with ThreadPoolExecutor(max_workers=6) as pool:
        covers = pool.map(lambda g: client.genre_cover(g['value']), genres[:GENRE_COVER_LIMIT])
        for genre, cover_id in zip(genres, covers):
            genre['_cover'] = cover_id
    return genres


def greeting():
    hour = datetime.datetime.now().hour
    if 5 <= hour < 11:
        return L('greeting_morning')
    if 11 <= hour < 17:
        return L('greeting_day')
    return L('greeting_evening')


class HomePage(RowsPage):
    nav = 'home'
    hero = 'home'

    # (album list type, shelf title); playlists slot in after the third
    SOURCES = (
        ('recent', 'home_recent'),
        ('newest', 'home_newest'),
        ('starred', 'home_starred'),
        ('random', 'home_discover'),
        ('frequent', 'home_frequent'),
        ('highest', 'home_highest'),
    )

    def load(self, win):
        client = win.client
        with ThreadPoolExecutor(max_workers=7) as pool:
            jobs = {kind: pool.submit(client.album_list, kind, SHELF_SIZE + 1) for kind, _ in self.SOURCES}
            playlists_job = pool.submit(client.playlists)
            results = {kind: job.result() for kind, job in jobs.items()}
            playlists = playlists_job.result()

        self.props = {
            'hero.title': greeting(),
            'hero.subtitle': L('home_subtitle'),
        }
        self.buttons = [
            Button('mix', L('btn_random_mix'), 'shuffle', 'primary'),
            Button('favmix', L('btn_fav_mix'), 'favourite'),
            Button('search', L('nav_search'), 'search'),
        ]
        self.shelves = []
        for index, (kind, title) in enumerate(self.SOURCES):
            albums = results[kind]
            if albums:
                more = kind if len(albums) > SHELF_SIZE else None
                self.shelves.append(Section(L(title), 'album', albums[:SHELF_SIZE], more))
            if index == 1 and playlists:
                self.shelves.append(Section(L('home_playlists'), 'playlist', playlists[:SHELF_SIZE],
                                            'playlists' if len(playlists) > SHELF_SIZE else None))
        if not self.shelves:
            self.empty = L('home_empty')
        self.loaded = True

    def action(self, win, name):
        if name == 'mix':
            win.play_async(lambda: win.client.random_songs(150))
        elif name == 'favmix':
            win.play_async(lambda: win.client.starred()['song'], shuffle=True)
        elif name == 'search':
            win.navigate('search')

    def more(self, win, name):
        if name == 'playlists':
            win.open(PlaylistsPage())
            return
        title = dict(self.SOURCES).get(name)
        win.open(AlbumListPage(L(title), name))


class ErrorPage(RowsPage):
    """Shown instead of the home page when the server cannot be reached."""
    nav = 'home'
    hero = 'home'

    def __init__(self, message, retry=None):
        super().__init__()
        self.retry = retry
        if retry is not None:
            self.nav = retry.nav
        self.props = {'hero.title': L('err_title'), 'hero.subtitle': message}
        self.buttons = [
            Button('retry', L('btn_retry'), 'history', 'primary'),
            Button('offline', L('nav_offline'), 'offline'),
            Button('setup', L('btn_setup'), 'settings'),
        ]
        self.loaded = True

    def action(self, win, name):
        if name == 'retry':
            if self.retry is None:
                win.navigate('home')
            else:
                self.retry.invalidate()
                win.stack[-1] = self.retry
                win.show(self.retry)
        elif name == 'offline':
            win.navigate('offline')
        elif name == 'setup':
            win.run_setup()


class SearchPage(RowsPage):
    nav = 'search'
    hero = 'search'

    def __init__(self, query=''):
        super().__init__()
        self.query = query

    def load(self, win):
        self.history = storage.search_history()
        self.tracks = None
        self.shelves = []
        self.empty = ''
        self.props = {
            'search.query': self.query or L('search_placeholder'),
            'search.active': '1' if self.query else '',
        }
        if self.query:
            found = win.client.search(self.query, artists=20, albums=30, songs=60)
            songs = found['song']
            if songs:
                self.tracks = Section(L('search_songs'), 'song', songs,
                                      'songs' if len(songs) > TRACK_PREVIEW else None, TRACK_PREVIEW)
            if found['artist']:
                self.shelves.append(Section(L('search_artists'), 'artist', found['artist']))
            if found['album']:
                self.shelves.append(Section(L('search_albums'), 'album', found['album']))
            if not (songs or found['artist'] or found['album']):
                self.empty = L('search_nothing').format(self.query)
        else:
            genres = [dict(g) for g in win.client.genres()[:30]]
            if genres:
                self.shelves.append(Section(L('search_browse'), 'genre', add_genre_covers(win.client, genres)))
        self.loaded = True

    def default_focus(self):
        if self.query and (self.tracks or self.shelves):
            return ids.ROWS
        return ids.SEARCH_FIELD

    def action(self, win, name):
        if name == 'search':
            query = xbmcgui.Dialog().input(L('search_heading'), defaultt=self.query)
            if query:
                self.run_query(win, query)
        elif name.startswith('history:'):
            self.run_query(win, name.split(':', 1)[1])

    def run_query(self, win, query):
        storage.remember_search(query)
        self.query = query.strip()
        self.state = None
        self.invalidate()
        win.show(self)

    def more(self, win, name):
        if name == 'songs':
            query = self.query
            win.open(SongListPage(L('search_songs_for').format(query),
                                  lambda client: client.search(query, 0, 0, 500)['song']))


class ArtistPage(RowsPage):
    hero = 'artist'

    def __init__(self, artist_id, name=''):
        super().__init__()
        self.artist_id = artist_id
        self.artist = {'id': artist_id, 'name': name}

    def load(self, win):
        client = win.client
        with ThreadPoolExecutor(max_workers=3) as pool:
            artist_job = pool.submit(client.artist, self.artist_id)
            info_job = pool.submit(client.artist_info, self.artist_id)
            artist = artist_job.result()
            top_job = pool.submit(client.top_songs, artist.get('name', ''), 10)
            info = info_job.result()
            top = top_job.result()
        self.artist = artist

        albums = sorted(artist.get('album', []), key=lambda a: a.get('year') or 0, reverse=True)
        groups = {'album': [], 'single': [], 'compilation': []}
        for album in albums:
            types = {t.lower() for t in album.get('releaseTypes') or []}
            if types & {'single', 'ep'}:
                groups['single'].append(album)
            elif 'compilation' in types or album.get('isCompilation'):
                groups['compilation'].append(album)
            else:
                groups['album'].append(album)

        genres = sorted({g.get('name') for a in albums for g in a.get('genres') or [] if g.get('name')})
        self.props = {
            'artist.name': artist.get('name', ''),
            'artist.meta': kodi.join_meta(
                kodi.fmt_count(len(albums), 'count_album', 'count_albums'),
                ', '.join(genres[:3])),
            'artist.bio': info.get('biography', ''),
        }
        self.backdrop = info.get('largeImageUrl') or items.artist_image(client, artist, 1000)

        self.buttons = [Button('shuffle', L('btn_shuffle'), 'shuffle', 'primary')]
        if top:
            self.buttons.append(Button('top', L('btn_top_songs'), 'play'))
        self.buttons += [
            Button('mix', L('btn_artist_mix'), 'mix'),
            fav_button(artist.get('starred')),
            Button('more', L('btn_more'), 'more'),
        ]

        self.tracks = Section(L('artist_top'), 'song', top, limit=5) if top else None
        self.shelves = []
        for key, title in (('album', 'artist_albums'), ('single', 'artist_singles'),
                           ('compilation', 'artist_compilations')):
            if groups[key]:
                self.shelves.append(Section(L(title), 'album', groups[key]))
        similar = [a for a in info.get('similarArtist', []) if a.get('id')]
        if similar:
            self.shelves.append(Section(L('artist_similar'), 'artist', similar))
        self.loaded = True

    def action(self, win, name):
        client = win.client
        if name == 'shuffle':
            win.play_async(lambda: actions.artist_songs(client, self.artist_id), shuffle=True)
        elif name == 'top' and self.tracks:
            player.play(client, self.tracks.models)
        elif name == 'mix':
            win.play_async(lambda: client.similar_songs(self.artist_id, 100))
        elif name == 'favourite':
            if toggle_favourite(win, 'artist', self.artist) is not None:
                self.buttons[-2] = fav_button(self.artist.get('starred'))
                win.render_buttons(self)
        elif name == 'more':
            win.context_menu('artist', self.artist)


class FavouritesPage(RowsPage):
    nav = 'favourites'
    hero = 'home'

    def load(self, win):
        starred = win.client.starred()
        songs, albums, artists = starred['song'], starred['album'], starred['artist']
        self.props = {
            'hero.title': L('nav_favourites'),
            'hero.subtitle': kodi.join_meta(*[
                kodi.fmt_count(len(models), one, many)
                for models, one, many in ((songs, 'count_song', 'count_songs'),
                                          (albums, 'count_album', 'count_albums'),
                                          (artists, 'count_artist', 'count_artists'))
                if models]),
        }
        self.buttons = [
            Button('play', L('btn_play_favs'), 'play', 'primary'),
            Button('shuffle', L('btn_shuffle'), 'shuffle'),
        ]
        self.tracks = Section(L('fav_songs'), 'song', songs,
                              'songs' if len(songs) > TRACK_PREVIEW else None, TRACK_PREVIEW) if songs else None
        self.shelves = []
        if albums:
            self.shelves.append(Section(L('fav_albums'), 'album', albums))
        if artists:
            self.shelves.append(Section(L('fav_artists'), 'artist', artists))
        if not (songs or albums or artists):
            self.empty = L('fav_empty')
        self.loaded = True

    def action(self, win, name):
        songs = self.tracks.models if self.tracks else []
        if name == 'play':
            player.play(win.client, songs)
        elif name == 'shuffle':
            player.play(win.client, songs, shuffle=True)

    def more(self, win, name):
        if name == 'songs':
            win.open(SongListPage(L('fav_songs'), lambda client: client.starred()['song']))


# Grid: covers in a panel, paged while scrolling
class GridPage(Page):
    view = 'grid'
    kind = 'album'
    page_size = 120

    def __init__(self, title=''):
        super().__init__()
        self.title = title
        self.subtitle = ''
        self.models = []
        self.has_more = False
        self.loading_more = False

    def fetch(self, win, offset, size):
        return []

    def describe(self, win):
        """Set subtitle and buttons once the first page is in."""

    def load(self, win):
        self.models = self.fetch(win, 0, self.page_size)
        self.has_more = len(self.models) >= self.page_size
        self.describe(win)
        if not self.models:
            self.empty = L('empty_generic')
        self.loaded = True

    def load_more(self, win):
        batch = self.fetch(win, len(self.models), self.page_size)
        known = {m.get('id') for m in self.models}
        batch = [m for m in batch if m.get('id') not in known]
        self.has_more = len(batch) >= self.page_size
        self.models.extend(batch)
        return batch

    def default_focus(self):
        return ids.GRID if self.models else ids.GRID_BUTTONS


class LocalGridPage(GridPage):
    """Grid over a list the server returns in one piece (artists, genres...)."""
    sorts = ()

    def __init__(self, title=''):
        super().__init__(title)
        self.all = None
        self.sort = storage_pref(self.pref_key(), 0)

    def pref_key(self):
        return f'sort.{type(self).__name__}'

    def load_all(self, win):
        return []

    def sort_all(self):
        """Reorder self.all in place for the chosen sort."""

    def sort_key(self):
        return self.sorts[self.sort][0] if 0 <= self.sort < len(self.sorts) else ''

    def fetch(self, win, offset, size):
        if self.all is None or offset == 0:
            self.all = self.load_all(win)
            self.sort_all()
        return self.all[offset:offset + size]

    def change_sort(self, win):
        labels = [L(key) for _, key in self.sorts]
        choice = xbmcgui.Dialog().select(L('sort_title'), labels, preselect=self.sort)
        if choice >= 0 and choice != self.sort:
            self.sort = choice
            set_storage_pref(self.pref_key(), choice)
            self.state = None
            self.invalidate()
            win.show(self)


def storage_pref(key, default):
    prefs = storage.read_json(storage.path('prefs.json')) or {}
    return prefs.get(key, default)


def set_storage_pref(key, value):
    prefs = storage.read_json(storage.path('prefs.json')) or {}
    prefs[key] = value
    storage.write_json(storage.path('prefs.json'), prefs)


class AlbumsPage(GridPage):
    nav = 'albums'
    SORTS = (
        ('alphabeticalByName', 'sort_name'),
        ('alphabeticalByArtist', 'sort_artist'),
        ('newest', 'sort_newest'),
        ('byYear', 'sort_year'),
        ('recent', 'sort_recent'),
        ('frequent', 'sort_frequent'),
        ('highest', 'sort_rating'),
        ('random', 'sort_random'),
    )

    def __init__(self):
        super().__init__(L('nav_albums'))
        self.sort = storage_pref('sort.albums', 0)
        if not 0 <= self.sort < len(self.SORTS):
            self.sort = 0

    def fetch(self, win, offset, size):
        kind = self.SORTS[self.sort][0]
        extra = {'fromYear': 9999, 'toYear': 0} if kind == 'byYear' else {}
        return win.client.album_list(kind, size, offset, **extra)

    def describe(self, win):
        self.subtitle = L('sorted_by').format(L(self.SORTS[self.sort][1]))
        self.buttons = [
            Button('sort', L(self.SORTS[self.sort][1]), 'sort', 'pill'),
            Button('mix', L('btn_random_mix'), 'shuffle'),
        ]

    def action(self, win, name):
        if name == 'sort':
            labels = [L(key) for _, key in self.SORTS]
            choice = xbmcgui.Dialog().select(L('sort_title'), labels, preselect=self.sort)
            if choice >= 0 and choice != self.sort:
                self.sort = choice
                set_storage_pref('sort.albums', choice)
                self.state = None
                self.invalidate()
                win.show(self)
        elif name == 'mix':
            win.play_async(lambda: win.client.random_songs(150))


class AlbumListPage(GridPage):
    """Any getAlbumList2 type, e.g. 'Recently added' from a home shelf."""

    def __init__(self, title, list_type, **extra):
        super().__init__(title)
        self.list_type = list_type
        self.extra = extra

    def fetch(self, win, offset, size):
        return win.client.album_list(self.list_type, size, offset, **self.extra)


class GenrePage(AlbumListPage):
    def __init__(self, genre):
        super().__init__(genre, 'byGenre', genre=genre)
        self.genre = genre

    def describe(self, win):
        self.subtitle = L('kind_genre')
        self.buttons = [Button('mix', L('btn_genre_mix'), 'shuffle', 'primary')]

    def action(self, win, name):
        if name == 'mix':
            win.play_async(lambda: win.client.random_songs(150, genre=self.genre))


class ArtistsPage(LocalGridPage):
    nav = 'artists'
    kind = 'artist'
    page_size = 150
    sorts = (('name', 'sort_name'), ('albums', 'sort_album_count'), ('random', 'sort_random'))

    def __init__(self):
        super().__init__(L('nav_artists'))

    def load_all(self, win):
        return list(win.client.artists())

    def sort_all(self):
        key = self.sort_key()
        if key == 'albums':
            self.all.sort(key=lambda a: a.get('albumCount') or 0, reverse=True)
        elif key == 'random':
            random.shuffle(self.all)

    def describe(self, win):
        self.subtitle = kodi.fmt_count(len(self.all or []), 'count_artist', 'count_artists')
        self.buttons = [Button('sort', L(self.sorts[self.sort][1]), 'sort', 'pill')]

    def action(self, win, name):
        if name == 'sort':
            self.change_sort(win)


class GenresPage(LocalGridPage):
    nav = 'genres'
    kind = 'genre'
    page_size = 300
    sorts = (('name', 'sort_name'), ('albums', 'sort_album_count'), ('songs', 'sort_song_count'))

    def __init__(self):
        super().__init__(L('nav_genres'))

    def load_all(self, win):
        return add_genre_covers(win.client, [dict(g) for g in win.client.genres()])

    def sort_all(self):
        key = self.sort_key()
        if key == 'albums':
            self.all.sort(key=lambda g: g.get('albumCount') or 0, reverse=True)
        elif key == 'songs':
            self.all.sort(key=lambda g: g.get('songCount') or 0, reverse=True)

    def describe(self, win):
        self.subtitle = kodi.fmt_count(len(self.all or []), 'count_genre', 'count_genres')
        self.buttons = [Button('sort', L(self.sorts[self.sort][1]), 'sort', 'pill')]

    def action(self, win, name):
        if name == 'sort':
            self.change_sort(win)


class PlaylistsPage(LocalGridPage):
    nav = 'playlists'
    kind = 'playlist'
    page_size = 300

    def __init__(self):
        super().__init__(L('nav_playlists'))

    def load_all(self, win):
        win.client.invalidate('playlists')
        return list(win.client.playlists())

    def describe(self, win):
        self.subtitle = kodi.fmt_count(len(self.all or []), 'count_playlist', 'count_playlists')
        self.buttons = [Button('new', L('playlist_new'), 'add', 'pill')]

    def action(self, win, name):
        if name == 'new' and actions.create_playlist(win.client):
            self.invalidate()
            win.show(self)


# Tracks: one long song list
class TracksPage(Page):
    view = 'tracks'
    kind = 'song'

    def __init__(self, title=''):
        super().__init__()
        self.title = title
        self.subtitle = ''
        self.models = []

    def default_focus(self):
        return ids.TRACKLIST if self.models else ids.TRACKLIST_BUTTONS

    def song_buttons(self):
        return [
            Button('play', L('btn_play'), 'play', 'primary'),
            Button('shuffle', L('btn_shuffle'), 'shuffle'),
            Button('queue', L('btn_queue'), 'queue'),
        ]

    def describe_songs(self):
        total = sum(int(s.get('duration') or 0) for s in self.models)
        self.subtitle = kodi.join_meta(kodi.fmt_count(len(self.models), 'count_song', 'count_songs'),
                                       kodi.fmt_total(total) if total else '')

    def action(self, win, name):
        if name == 'play':
            player.play(win.client, self.models)
        elif name == 'shuffle':
            player.play(win.client, self.models, shuffle=True)
        elif name == 'queue':
            player.enqueue(win.client, self.models)
        elif name == 'download':
            actions.download_async(win.client, self.models, self.title)


class SongListPage(TracksPage):
    def __init__(self, title, loader):
        super().__init__(title)
        self.loader = loader

    def load(self, win):
        self.models = self.loader(win.client)
        self.describe_songs()
        self.buttons = self.song_buttons()
        if offline.enabled():
            self.buttons.append(Button('download', L('btn_download'), 'download'))
        if not self.models:
            self.empty = L('empty_generic')
        self.loaded = True


class RadioPage(TracksPage):
    nav = 'radio'
    kind = 'radio'

    def __init__(self):
        super().__init__(L('nav_radio'))

    def load(self, win):
        self.models = win.client.radios()
        self.subtitle = kodi.fmt_count(len(self.models), 'count_station', 'count_stations')
        if not self.models:
            self.empty = L('radio_empty')
        self.loaded = True


class OfflinePage(TracksPage):
    nav = 'offline'

    def __init__(self):
        super().__init__(L('nav_offline'))

    def load(self, win):
        self.models = offline.entries()
        used = offline.total_size() / (1024 * 1024)
        self.subtitle = kodi.join_meta(kodi.fmt_count(len(self.models), 'count_song', 'count_songs'),
                                       f'{used:.0f} MB')
        self.buttons = []
        if self.models:
            self.buttons = self.song_buttons() + [Button('clear', L('btn_clear_offline'), 'delete')]
        else:
            self.empty = L('offline_empty')
        self.loaded = True

    def action(self, win, name):
        if name == 'clear':
            if actions.clear_offline():
                self.invalidate()
                win.show(self)
            return
        super().action(win, name)


# Detail: album or playlist with its track list
class DetailPage(Page):
    view = 'detail'
    kind = ''
    numbered = False
    show_cover = True

    def __init__(self, item_id):
        super().__init__()
        self.item_id = item_id
        self.model = {'id': item_id}
        self.props = {}
        self.songs = []
        self.disc_titles = {}

    def default_focus(self):
        return ids.DETAIL_BUTTONS

    def play_buttons(self):
        # Round buttons only: the detail column is narrow
        return [
            Button('play', L('btn_play'), 'play', 'accent'),
            Button('shuffle', L('btn_shuffle'), 'shuffle'),
        ]

    def action(self, win, name):
        client = win.client
        if name == 'play':
            player.play(client, self.songs)
        elif name == 'shuffle':
            player.play(client, self.songs, shuffle=True)
        elif name == 'download':
            actions.download_async(client, self.songs, self.model.get('name', ''))
        elif name == 'more':
            win.context_menu(self.kind, self.model)


class AlbumPage(DetailPage):
    kind = 'album'
    numbered = True
    show_cover = False

    def load(self, win):
        client = win.client
        album = client.album(self.item_id)
        self.model = album
        self.songs = album.get('song', [])
        self.disc_titles = {d.get('disc'): d.get('title') for d in album.get('discTitles') or [] if d.get('title')}

        types = {t.lower() for t in album.get('releaseTypes') or []}
        if 'single' in types:
            kind_label = L('kind_single')
        elif 'ep' in types:
            kind_label = L('kind_ep')
        elif 'compilation' in types or album.get('isCompilation'):
            kind_label = L('kind_compilation')
        else:
            kind_label = L('kind_album')

        genres = [g.get('name') for g in album.get('genres') or [] if g.get('name')] or \
            ([album['genre']] if album.get('genre') else [])
        plays = album.get('playCount') or 0
        rating = album.get('userRating') or 0

        art = items.cover(client, album.get('coverArt'), items.DETAIL_ART)
        self.props = {
            'detail.title': album.get('name', ''),
            'detail.artist': items.album_artist(album),
            'detail.meta': kodi.join_meta(
                kind_label,
                album.get('year') or '',
                kodi.fmt_count(len(self.songs), 'count_song', 'count_songs'),
                kodi.fmt_total(album.get('duration'))),
            'detail.meta2': kodi.join_meta(
                ', '.join(genres[:2]),
                L('rating_short').format(rating) if rating else '',
                L('play_count').format(plays) if plays else ''),
            'detail.cover': art,
        }
        self.backdrop = art
        self.buttons = self.play_buttons() + [fav_button(album.get('starred'))]
        if offline.enabled():
            self.buttons.append(Button('download', L('btn_download'), 'download'))
        if album.get('artistId'):
            self.buttons.append(Button('artist', L('btn_go_artist'), 'artist'))
        self.buttons.append(Button('more', L('btn_more'), 'more'))
        self.loaded = True

    def action(self, win, name):
        if name == 'favourite':
            if toggle_favourite(win, 'album', self.model) is not None:
                self.buttons[2] = fav_button(self.model.get('starred'))
                win.render_buttons(self)
        elif name == 'artist':
            win.open(ArtistPage(self.model['artistId'], self.model.get('artist', '')))
        else:
            super().action(win, name)


class PlaylistPage(DetailPage):
    kind = 'playlist'
    SORTS = (
        ('order', 'sort_playlist_order'),
        ('added', 'sort_recently_added'),
        ('title', 'sort_title_az'),
        ('artist', 'sort_artist'),
        ('album', 'sort_album'),
        ('duration', 'sort_duration'),
    )

    def __init__(self, item_id):
        super().__init__(item_id)
        self.sort = storage_pref('sort.playlist', 0)
        if not 0 <= self.sort < len(self.SORTS):
            self.sort = 0
        self.entries = []

    def sorted_songs(self):
        """
        The playlist in the chosen order. Subsonic has no "added on" date for
        playlist entries; new songs are appended, so 'recently added' is the
        playlist order reversed.
        """
        key = self.SORTS[self.sort][0]
        songs = list(self.entries)
        text = lambda field: lambda s: (s.get(field) or '').lower()
        if key == 'added':
            songs.reverse()
        elif key == 'title':
            songs.sort(key=text('title'))
        elif key == 'artist':
            songs.sort(key=lambda s: (items.song_artist(s).lower(), (s.get('album') or '').lower(),
                                      s.get('discNumber') or 0, s.get('track') or 0))
        elif key == 'album':
            songs.sort(key=lambda s: ((s.get('album') or '').lower(), s.get('discNumber') or 0, s.get('track') or 0))
        elif key == 'duration':
            songs.sort(key=lambda s: s.get('duration') or 0)
        return songs

    def sort_button(self):
        return Button('sort', L('sorted_by').format(L(self.SORTS[self.sort][1])), 'sort')

    def load(self, win):
        client = win.client
        playlist = client.playlist(self.item_id)
        self.model = playlist
        self.entries = playlist.get('entry', [])
        for position, song in enumerate(self.entries):
            song['_pos'] = position  # index in the playlist, for removing entries
        self.songs = self.sorted_songs()
        art = items.cover(client, playlist.get('coverArt'), items.DETAIL_ART)
        self.props = {
            'detail.title': playlist.get('name', ''),
            'detail.artist': L('playlist_owner').format(playlist.get('owner', '')) if playlist.get('owner') else '',
            'detail.meta': kodi.join_meta(
                L('kind_playlist'),
                kodi.fmt_count(len(self.songs), 'count_song', 'count_songs'),
                kodi.fmt_total(playlist.get('duration'))),
            'detail.meta2': playlist.get('comment', ''),
            'detail.cover': art,
        }
        self.backdrop = art
        self.buttons = self.play_buttons() + [self.sort_button()]
        if offline.enabled():
            self.buttons.append(Button('download', L('btn_download'), 'download'))
        self.buttons.append(Button('more', L('btn_more'), 'more'))
        if not self.songs:
            self.empty = L('playlist_empty')
        self.loaded = True

    def action(self, win, name):
        if name != 'sort':
            super().action(win, name)
            return
        labels = [L(key) for _, key in self.SORTS]
        choice = xbmcgui.Dialog().select(L('sort_title'), labels, preselect=self.sort)
        if choice < 0 or choice == self.sort:
            return
        self.sort = choice
        set_storage_pref('sort.playlist', choice)
        self.songs = self.sorted_songs()
        self.buttons[2] = self.sort_button()
        self.state = None
        win.show(self)

    @property
    def editable(self):
        return not self.model.get('readonly')


# Sidebar destinations
NAVIGATION = (
    ('home', 'nav_home', 'home'),
    ('search', 'nav_search', 'search'),
    ('artists', 'nav_artists', 'artist'),
    ('albums', 'nav_albums', 'album'),
    ('playlists', 'nav_playlists', 'playlist'),
    ('favourites', 'nav_favourites', 'favourite'),
    ('genres', 'nav_genres', 'genre'),
    ('radio', 'nav_radio', 'radio'),
    ('offline', 'nav_offline', 'offline'),
    ('settings', 'nav_settings', 'settings'),
)

ROOT_PAGES = {
    'home': HomePage,
    'search': SearchPage,
    'artists': ArtistsPage,
    'albums': AlbumsPage,
    'playlists': PlaylistsPage,
    'favourites': FavouritesPage,
    'genres': GenresPage,
    'radio': RadioPage,
    'offline': OfflinePage,
}

# Pages that work without a server
OFFLINE_CAPABLE = {'offline'}
