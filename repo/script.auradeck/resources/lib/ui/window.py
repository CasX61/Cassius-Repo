# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
The Aura-Deck main window.

One WindowXML hosts every page: the skin defines four views ('rows', 'grid',
'tracks', 'detail') and Python switches between them with the window
property 'view', keeping its own back stack. Network work always runs on
worker threads so the interface never freezes.
"""

import threading
import time
import traceback

import xbmc
import xbmcgui

from resources.lib import actions, connection, items, kodi, offline, player, subsonic
from resources.lib.ui import ids, pages
from resources.lib.ui.nowplaying import NowPlaying

L = kodi.L

XML = 'script-auradeck-main.xml'

BACK_ACTIONS = (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU)
CONTEXT_ACTIONS = (xbmcgui.ACTION_CONTEXT_MENU, xbmcgui.ACTION_MOUSE_RIGHT_CLICK)
SCROLL_ACTIONS = (
    xbmcgui.ACTION_MOVE_DOWN, xbmcgui.ACTION_MOVE_RIGHT, xbmcgui.ACTION_PAGE_DOWN,
    xbmcgui.ACTION_MOUSE_WHEEL_DOWN, getattr(xbmcgui, 'ACTION_SCROLL_DOWN', 112),
)
INFO_ACTIONS = (xbmcgui.ACTION_SHOW_INFO,)

ALL_LISTS = ids.BUTTON_BARS + ids.CONTENT_LISTS

# Every page-specific window property, cleared between pages
PAGE_PROPS = (
    'hero', 'empty', 'backdrop', 'page.title', 'page.subtitle',
    'hero.title', 'hero.subtitle', 'artist.name', 'artist.meta', 'artist.bio',
    'search.query', 'search.active', 'tracks.title',
    'detail.title', 'detail.artist', 'detail.meta', 'detail.meta2', 'detail.cover',
) + tuple(f'shelf{i}.title' for i in range(ids.SHELF_COUNT))

GRID_PREFETCH = 24
MINI_PLAYER = (ids.MINI_OPEN, ids.MINI_PREV, ids.MINI_PLAY, ids.MINI_NEXT)


class MainWindow(xbmcgui.WindowXML):

    def setup(self, client, start=None):
        self.client = client
        self.start = start
        self.stack = []
        self.token = 0
        self.busy = 0
        self.busy_lock = threading.Lock()
        self.initialized = False
        self.closing = False
        self.window_id = None
        self.nav_items = {}
        self.playing_id = None

    @property
    def page(self):
        return self.stack[-1] if self.stack else None

    # Lifecycle
    def onInit(self):
        if self.initialized:
            self.restore_focus()
            return
        self.initialized = True
        self.window_id = xbmcgui.getCurrentWindowId()
        self.build_sidebar()
        threading.Thread(target=self.ticker, daemon=True).start()
        if self.start and self.handle_command(self.start):
            return
        self.navigate('home' if self.client else 'offline')

    def ticker(self):
        """Heartbeat for the widget plugin, and deep links from it."""
        monitor = xbmc.Monitor()
        while not self.closing and not monitor.abortRequested():
            kodi.set_home_property(kodi.PROP_HEARTBEAT, int(time.time()))
            playing = player.current_song_id()
            if playing != self.playing_id:
                self.playing_id = playing
                self.mark_playing()
            command = kodi.home_property(kodi.PROP_COMMAND)
            if command:
                kodi.set_home_property(kodi.PROP_COMMAND, '')
                if self.window_id and xbmcgui.getCurrentWindowId() != self.window_id:
                    xbmc.executebuiltin(f'ActivateWindow({self.window_id})')
                self.handle_command(command)
            if monitor.waitForAbort(0.5):
                break
        if monitor.abortRequested():
            self.quit()

    def quit(self):
        self.closing = True
        kodi.set_home_property(kodi.PROP_HEARTBEAT, '')
        self.close()

    def handle_command(self, command):
        kind, _, value = command.partition(':')
        if kind == 'nowplaying':
            if not self.stack:
                self.navigate('home' if self.client else 'offline')
            self.open_now_playing()
            return True
        if self.client is None:
            return False
        page = {
            'album': pages.AlbumPage,
            'artist': pages.ArtistPage,
            'playlist': pages.PlaylistPage,
            'genre': pages.GenrePage,
        }.get(kind)
        if page and value:
            self.open(page(value), root=not self.stack)
            return True
        if kind in pages.ROOT_PAGES:
            self.navigate(kind)
            return True
        return False

    # Background work
    def set_busy(self, delta):
        with self.busy_lock:
            self.busy = max(0, self.busy + delta)
            self.setProperty('busy', '1' if self.busy else '')

    def run(self, work, done=None, busy=True):
        """Run ``work`` on a thread, then ``done(result, error)`` on that thread."""
        # Count the job before the thread starts so 'busy' is never briefly false.
        if busy:
            self.set_busy(1)

        def target():
            result = error = None
            try:
                result = work()
            except Exception as exc:
                error = exc
                if not isinstance(exc, subsonic.ApiError):
                    kodi.log_error(traceback.format_exc())
            finally:
                if busy:
                    self.set_busy(-1)
            if done and not self.closing:
                try:
                    done(result, error)
                except Exception:
                    kodi.log_error(traceback.format_exc())
        threading.Thread(target=target, daemon=True).start()

    def play_async(self, loader, shuffle=False, start=0):
        def done(songs, error):
            if error:
                kodi.notify(connection.describe_error(error), error=True)
            else:
                player.play(self.client, songs or [], start=start, shuffle=shuffle)
        self.run(loader, done)

    def with_songs(self, kind, model, then):
        def done(songs, error):
            if error:
                kodi.notify(connection.describe_error(error), error=True)
            elif songs:
                then(songs)
        self.run(lambda: actions.songs_for(self.client, kind, model['id']), done)

    # Navigation
    def build_sidebar(self):
        self.nav_items = {}
        entries = []
        for key, label, icon in pages.NAVIGATION:
            if key == 'offline' and not offline.enabled():
                continue
            item = items.ui_nav(key, L(label), icon)
            self.nav_items[key] = item
            entries.append(item)
        self.fill(ids.SIDEBAR, entries)

    def mark_nav(self, key):
        if not key:
            return
        for index, (nav_key, item) in enumerate(self.nav_items.items()):
            item.setProperty('active', '1' if nav_key == key else '')
            if nav_key == key:
                self.getControl(ids.SIDEBAR).selectItem(index)

    def navigate(self, key):
        if key == 'settings':
            self.open_settings()
            return
        page_class = pages.ROOT_PAGES.get(key)
        if page_class is None:
            return
        if self.client is None and key not in pages.OFFLINE_CAPABLE:
            message = L('err_not_configured') if not connection.configured() else L('err_title')
            self.open(pages.ErrorPage(message), root=True)
            return
        self.open(page_class(), root=True)

    def open(self, page, root=False):
        if self.page is not None and not root:
            self.save_state(self.page)
        if root:
            self.stack = []
        self.stack.append(page)
        self.show(page)

    def back(self):
        self.stack.pop()
        page = self.page
        if getattr(page, 'nav', None) in ('favourites', 'playlists', 'offline') or isinstance(page, pages.PlaylistPage):
            page.invalidate()
        self.show(page)

    def show(self, page):
        """
        Show a page. The previous page stays on screen (with the spinner) until
        the new one has loaded, then the views are swapped in one go.
        """
        self.token += 1
        token = self.token
        self.mark_nav(page.nav)
        if page.loaded:
            self.swap(page)
            return

        def done(_result, error):
            if token != self.token:
                return
            if error:
                self.load_failed(page, error)
            else:
                self.swap(page)
        self.run(lambda: page.load(self), done)

    def swap(self, page):
        # Park focus on an invisible control while lists are emptied, or Kodi
        # moves it to the sidebar for a moment and the sidebar flickers open.
        if self.getFocusId() != ids.SIDEBAR:
            self.setFocusId(ids.FOCUS_PARK)
        self.clear_view()
        self.render(page)

    def load_failed(self, page, error):
        kodi.log_error(f'loading {type(page).__name__} failed: {error}')
        message = connection.describe_error(error) if isinstance(error, subsonic.ApiError) \
            else L('err_unexpected')
        failed = pages.ErrorPage(message, retry=page)
        self.stack[-1] = failed
        self.swap(failed)

    def open_settings(self):
        kodi.open_settings()
        # "Connect to a server" closes the settings and runs the wizard as a
        # separate script; pick up its result once it has finished.
        def wait_for_wizard():
            monitor = xbmc.Monitor()
            monitor.waitForAbort(0.5)
            while connection.wizard_running() and not monitor.abortRequested():
                monitor.waitForAbort(0.25)
        self.run(wait_for_wizard, lambda _r, _e: self.reconnect(), busy=False)

    def run_setup(self):
        if connection.run_wizard():
            self.reconnect()

    def reconnect(self):
        self.client = connection.client_from_settings()
        self.build_sidebar()
        self.navigate('home' if self.client else 'offline')

    # Rendering
    def fill(self, control_id, list_items):
        control = self.getControl(control_id)
        control.reset()
        if list_items:
            control.addItems(list_items)

    def clear_view(self):
        for control_id in ALL_LISTS:
            self.getControl(control_id).reset()
        for key in PAGE_PROPS:
            self.clearProperty(key)

    def set_prop(self, key, value):
        if value in (None, ''):
            self.clearProperty(key)
        else:
            self.setProperty(key, str(value))

    def render(self, page):
        self.setProperty('view', page.view)
        getattr(self, f'render_{page.view}')(page)
        self.set_prop('empty', page.empty)
        self.set_prop('backdrop', page.backdrop)
        self.after_render(page)

    def button_bar(self, page):
        if page.view == 'rows':
            return ids.ARTIST_BUTTONS if page.hero == 'artist' else ids.HERO_BUTTONS
        return {
            'grid': ids.GRID_BUTTONS,
            'tracks': ids.TRACKLIST_BUTTONS,
            'detail': ids.DETAIL_BUTTONS,
        }[page.view]

    def render_buttons(self, page):
        bar = self.button_bar(page)
        control = self.getControl(bar)
        position = control.getSelectedPosition()
        self.fill(bar, [items.ui_button(b.action, b.label, b.icon, b.style) for b in page.buttons])
        if 0 <= position < control.size():
            control.selectItem(position)

    def make_items(self, kind, models, start=0):
        client = self.client
        if kind == 'album':
            return [items.ui_album(client, m, start + i) for i, m in enumerate(models)]
        if kind == 'artist':
            return [items.ui_artist(client, m, start + i) for i, m in enumerate(models)]
        if kind == 'playlist':
            return [items.ui_playlist(client, m, start + i) for i, m in enumerate(models)]
        if kind == 'genre':
            return [items.ui_genre(client, m, start + i) for i, m in enumerate(models)]
        if kind == 'radio':
            return [items.ui_radio(m, start + i) for i, m in enumerate(models)]
        return self.song_items(models, start=start)

    def song_items(self, songs, numbered=False, show_cover=True, start=0):
        cached = offline.cached_ids() if offline.enabled() else set()
        return [items.ui_song(self.client, song, start + i, cached, numbered, show_cover, self.playing_id)
                for i, song in enumerate(songs)]

    def mark_playing(self):
        """Move the 'playing' flag the skin highlights to the current track."""
        for control_id in ids.SONG_LISTS:
            try:
                control = self.getControl(control_id)
                for index in range(control.size()):
                    item = control.getListItem(index)
                    flag = '1' if self.playing_id and item.getProperty('id') == self.playing_id else ''
                    if item.getProperty('playing') != flag:
                        item.setProperty('playing', flag)
            except RuntimeError:
                pass

    def render_rows(self, page):
        self.set_prop('hero', page.hero)
        for key, value in page.props.items():
            self.set_prop(key, value)
        if page.buttons:
            self.render_buttons(page)
        if page.hero == 'search':
            self.fill(ids.SEARCH_HISTORY, [items.ui_history(q) for q in page.history])

        tracks = page.tracks
        page.lists = {}
        if tracks and tracks.models:
            shown = tracks.models[:tracks.limit] if tracks.limit else tracks.models
            entries = self.song_items(shown)
            if tracks.more:
                entries.append(items.ui_more(L('show_all'), tracks.more))
            self.set_prop('tracks.title', tracks.title)
            self.fill(ids.TRACKS_SHELF, entries)
            # The shelf sits in a grouplist: size it to its rows, no gap below.
            self.getControl(ids.TRACKS_SHELF).setHeight(len(entries) * ids.TRACK_ROW_HEIGHT)
            page.lists[ids.TRACKS_SHELF] = tracks.models

        for index in range(ids.SHELF_COUNT):
            section = page.shelves[index] if index < len(page.shelves) else None
            if not section:
                continue
            entries = self.make_items(section.kind, section.models)
            if section.more:
                entries.append(items.ui_more(L('show_all'), section.more))
            self.set_prop(f'shelf{index}.title', section.title)
            self.fill(ids.shelf(index), entries)
            page.lists[ids.shelf(index)] = section.models

    def render_grid(self, page):
        self.set_prop('page.title', page.title)
        self.set_prop('page.subtitle', page.subtitle)
        self.render_buttons(page)
        self.fill(ids.GRID, self.make_items(page.kind, page.models))
        page.lists = {ids.GRID: page.models}

    def render_tracks(self, page):
        self.set_prop('page.title', page.title)
        self.set_prop('page.subtitle', page.subtitle)
        self.render_buttons(page)
        self.fill(ids.TRACKLIST, self.make_items(page.kind, page.models))
        page.lists = {ids.TRACKLIST: page.models}

    def render_detail(self, page):
        for key, value in page.props.items():
            self.set_prop(key, value)
        self.render_buttons(page)
        cached = offline.cached_ids() if offline.enabled() else set()
        discs = {song.get('discNumber') or 1 for song in page.songs}
        entries = []
        last_disc = None
        for index, song in enumerate(page.songs):
            disc = song.get('discNumber') or 1
            if len(discs) > 1 and disc != last_disc:
                entries.append(items.ui_separator(page.disc_titles.get(disc) or L('disc').format(disc)))
                last_disc = disc
            entries.append(items.ui_song(self.client, song, index, cached, page.numbered, page.show_cover,
                                         self.playing_id))
        self.fill(ids.DETAIL_TRACKS, entries)
        page.lists = {ids.DETAIL_TRACKS: page.songs}

    # Focus
    def entry_for(self, control_id):
        if control_id in ids.SHELVES or control_id == ids.TRACKS_SHELF:
            return ids.ROWS
        if control_id == ids.SEARCH_HISTORY:
            return ids.SEARCH_FIELD
        return control_id if control_id in ids.ENTRY_POINTS else None

    def onFocus(self, control_id):
        if control_id == ids.ENTRY_ROUTER:
            self.restore_focus()
            return
        if control_id == ids.TOP_ROUTER:
            self.focus_header()
            return
        entry = self.entry_for(control_id)
        if entry:
            self.setProperty('entry', str(entry))

    def focus_header(self):
        """Up from the first shelf: the page's header buttons (or stay put)."""
        page = self.page
        target = ids.ROWS
        if page is not None and page.view == 'rows':
            if page.hero == 'search':
                target = ids.SEARCH_HISTORY if page.history else ids.SEARCH_FIELD
            elif page.hero and page.buttons:
                target = self.button_bar(page)
        self.focus(target)

    def focus(self, control_id):
        """setFocusId, retried while a view that just became visible settles."""
        for _ in range(12):
            try:
                self.setFocusId(control_id)
            except RuntimeError:
                pass
            focused = self.getFocusId()
            if focused == control_id or (control_id == ids.ROWS and self.entry_for(focused) == ids.ROWS):
                return True
            xbmc.sleep(25)
        return False

    def after_render(self, page):
        state = page.state
        target = page.default_focus()
        if state:
            for control_id, position in state.get('positions', {}).items():
                try:
                    control = self.getControl(control_id)
                    if 0 <= position < control.size():
                        control.selectItem(position)
                except RuntimeError:
                    pass
            target = state.get('focus') or target
        entry = self.entry_for(target)
        if entry:
            self.setProperty('entry', str(entry))
        if not self.focus(target):
            fallback = self.button_bar(page)
            if not self.focus(fallback):
                self.focus(ids.SIDEBAR)

    def save_state(self, page):
        focused = self.getFocusId()
        if focused == ids.SIDEBAR or focused in MINI_PLAYER or focused in ids.ROUTERS or not focused:
            focused = None
        positions = {}
        for control_id in list(page.lists) + [self.button_bar(page)]:
            try:
                positions[control_id] = self.getControl(control_id).getSelectedPosition()
            except RuntimeError:
                pass
        page.state = {'focus': focused, 'positions': positions}

    def restore_focus(self):
        entry = self.getProperty('entry')
        target = int(entry) if entry else (self.page.default_focus() if self.page else ids.SIDEBAR)
        if not self.focus(target) and self.page:
            self.focus(self.page.default_focus())

    # Input
    def onAction(self, action):
        action_id = action.getId()
        focused = self.getFocusId()
        if action_id in BACK_ACTIONS:
            if len(self.stack) > 1:
                self.back()
            elif focused != ids.SIDEBAR:
                self.focus(ids.SIDEBAR)
            else:
                self.quit()
        elif action_id in CONTEXT_ACTIONS:
            if focused in ids.CONTENT_LISTS:
                self.item_context(focused)
        elif action_id in INFO_ACTIONS:
            self.open_now_playing()
        elif focused == ids.GRID and action_id in SCROLL_ACTIONS:
            self.load_more()

    def onClick(self, control_id):
        page = self.page
        if self.busy and control_id != ids.SIDEBAR and page is not None and not page.loaded:
            return  # the next page is still loading; the old one on screen is stale
        if control_id == ids.SIDEBAR:
            item = self.getControl(ids.SIDEBAR).getSelectedItem()
            if item:
                self.navigate(item.getProperty('action'))
        elif control_id in ids.BUTTON_BARS:
            item = self.getControl(control_id).getSelectedItem()
            if item and page:
                page.action(self, item.getProperty('action'))
        elif control_id == ids.SEARCH_FIELD and page:
            page.action(self, 'search')
        elif control_id == ids.MINI_OPEN:
            self.open_now_playing()
        elif control_id in ids.CONTENT_LISTS:
            self.activate(control_id)

    def selected(self, control_id):
        item = self.getControl(control_id).getSelectedItem()
        if item is None:
            return None, None, None
        kind = item.getProperty('kind')
        return item, kind, self.model_for(control_id, item)

    def model_for(self, control_id, item):
        models = self.page.lists.get(control_id, []) if self.page else []
        try:
            index = int(item.getProperty('idx'))
            if 0 <= index < len(models):
                return models[index]
        except ValueError:
            pass
        return {'id': item.getProperty('id'), 'name': item.getLabel()}

    def activate(self, control_id):
        item, kind, model = self.selected(control_id)
        page = self.page
        if item is None or page is None:
            return
        if kind == 'more':
            page.more(self, item.getProperty('action'))
        elif kind == 'history':
            page.action(self, 'history:' + item.getLabel())
        elif kind == 'song':
            player.play(self.client, page.lists.get(control_id, []), start=int(item.getProperty('idx')))
        elif kind == 'radio':
            player.play_radio(model)
        elif kind == 'album':
            self.open(pages.AlbumPage(model['id']))
        elif kind == 'artist':
            self.open(pages.ArtistPage(model['id'], model.get('name', '')))
        elif kind == 'playlist':
            self.open(pages.PlaylistPage(model['id']))
        elif kind == 'genre':
            self.open(pages.GenrePage(model.get('value') or model['id']))

    def load_more(self):
        page = self.page
        if not page or page.view != 'grid' or not page.has_more or page.loading_more:
            return
        control = self.getControl(ids.GRID)
        if control.getSelectedPosition() < control.size() - GRID_PREFETCH:
            return
        page.loading_more = True
        token = self.token

        def done(batch, error):
            page.loading_more = False
            if error or token != self.token or not batch:
                return
            start = len(page.models) - len(batch)
            control.addItems(self.make_items(page.kind, batch, start))
        self.run(lambda: page.load_more(self), done, busy=False)

    # Context menus
    def item_context(self, control_id):
        item, kind, model = self.selected(control_id)
        if item is None or kind not in ('song', 'album', 'artist', 'playlist', 'genre', 'radio'):
            return
        self.context_menu(kind, model, control_id, item)

    def context_menu(self, kind, model, control_id=None, item=None):
        client = self.client
        entries = []

        def add(label_key, handler):
            entries.append((L(label_key), handler))

        def set_starred(state):
            if state is not None and item is not None:
                item.setProperty('starred', '1' if state else '')

        if kind == 'radio':
            add('ctx_play', lambda: player.play_radio(model))
        elif kind == 'song':
            add('ctx_play_next', lambda: player.enqueue(client, [model], play_next=True))
            add('ctx_queue', lambda: player.enqueue(client, [model]))
            if client:
                add('ctx_song_mix', lambda: self.play_async(
                    lambda: [model] + client.similar_songs(model['id'], 80)))
                add('ctx_add_playlist', lambda: actions.add_to_playlist(client, [model['id']]))
                add('ctx_unfavourite' if model.get('starred') else 'ctx_favourite',
                    lambda: set_starred(pages.toggle_favourite(self, 'song', model)))
                add('ctx_rate', lambda: actions.rate(client, model['id'], model.get('title', ''),
                                                     model.get('userRating') or 0))
            if offline.enabled():
                if offline.get(model['id']):
                    add('ctx_remove_download', lambda: self.after(actions.remove_downloads([model['id']])))
                elif client:
                    add('ctx_download', lambda: actions.download_async(client, [model], model.get('title', '')))
            if client and model.get('albumId'):
                add('ctx_go_album', lambda: self.open(pages.AlbumPage(model['albumId'])))
            if client and model.get('artistId'):
                add('ctx_go_artist', lambda: self.open(pages.ArtistPage(model['artistId'], model.get('artist', ''))))
            page = self.page
            if isinstance(page, pages.PlaylistPage) and control_id == ids.DETAIL_TRACKS and page.editable:
                index = model.get('_pos', int(item.getProperty('idx')))
                add('ctx_remove_from_playlist', lambda: self.remove_from_playlist(page, index))
        elif client is None:
            return
        elif kind == 'album':
            add('ctx_play', lambda: self.with_songs(kind, model, lambda s: player.play(client, s)))
            add('ctx_shuffle', lambda: self.with_songs(kind, model, lambda s: player.play(client, s, shuffle=True)))
            add('ctx_play_next', lambda: self.with_songs(kind, model, lambda s: player.enqueue(client, s, True)))
            add('ctx_queue', lambda: self.with_songs(kind, model, lambda s: player.enqueue(client, s)))
            add('ctx_unfavourite' if model.get('starred') else 'ctx_favourite',
                lambda: set_starred(pages.toggle_favourite(self, 'album', model)))
            add('ctx_rate', lambda: actions.rate(client, model['id'], model.get('name', ''),
                                                 model.get('userRating') or 0))
            add('ctx_add_playlist', lambda: self.with_songs(
                kind, model, lambda s: actions.add_to_playlist(client, [x['id'] for x in s])))
            if offline.enabled():
                add('ctx_download', lambda: self.with_songs(
                    kind, model, lambda s: actions.download_async(client, s, model.get('name', ''))))
            if model.get('artistId') and not isinstance(self.page, pages.ArtistPage):
                add('ctx_go_artist', lambda: self.open(pages.ArtistPage(model['artistId'], model.get('artist', ''))))
        elif kind == 'artist':
            add('ctx_shuffle', lambda: self.play_async(lambda: actions.artist_songs(client, model['id']), shuffle=True))
            add('ctx_artist_mix', lambda: self.play_async(lambda: client.similar_songs(model['id'], 100)))
            add('ctx_unfavourite' if model.get('starred') else 'ctx_favourite',
                lambda: set_starred(pages.toggle_favourite(self, 'artist', model)))
            add('ctx_rate', lambda: actions.rate(client, model['id'], model.get('name', ''),
                                                 model.get('userRating') or 0))
        elif kind == 'playlist':
            add('ctx_play', lambda: self.with_songs(kind, model, lambda s: player.play(client, s)))
            add('ctx_shuffle', lambda: self.with_songs(kind, model, lambda s: player.play(client, s, shuffle=True)))
            add('ctx_queue', lambda: self.with_songs(kind, model, lambda s: player.enqueue(client, s)))
            if offline.enabled():
                add('ctx_download', lambda: self.with_songs(
                    kind, model, lambda s: actions.download_async(client, s, model.get('name', ''))))
            if not model.get('readonly'):
                add('ctx_rename', lambda: self.after(actions.rename_playlist(client, model)))
                add('ctx_delete', lambda: self.playlist_deleted(actions.delete_playlist(client, model)))
        elif kind == 'genre':
            name = model.get('value') or model.get('id')
            add('ctx_genre_mix', lambda: self.play_async(lambda: client.random_songs(150, genre=name)))

        if not entries:
            return
        choice = xbmcgui.Dialog().contextmenu([label for label, _ in entries])
        if choice >= 0:
            entries[choice][1]()

    def after(self, changed):
        """Reload the current page in place after a change to its data."""
        if changed and self.page:
            self.save_state(self.page)
            self.page.invalidate()
            self.show(self.page)

    def playlist_deleted(self, deleted):
        if not deleted:
            return
        if isinstance(self.page, pages.PlaylistPage) and len(self.stack) > 1:
            self.back()
        else:
            self.after(True)

    def remove_from_playlist(self, page, index):
        if actions.remove_from_playlist(self.client, page.item_id, index):
            self.after(True)

    # Now playing
    def open_now_playing(self):
        if not xbmc.Player().isPlayingAudio():
            kodi.notify(L('np_nothing'))
            return
        dialog = NowPlaying(NowPlaying.XML, kodi.addon_path(), 'Default', '1080i')
        dialog.setup(self.client)
        dialog.doModal()
        intent = dialog.intent
        del dialog
        if intent and self.client:
            kind, item_id, name = intent
            if kind == 'album':
                self.open(pages.AlbumPage(item_id))
            elif kind == 'artist':
                self.open(pages.ArtistPage(item_id, name))
