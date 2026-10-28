# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
Full screen "now playing" dialog: artwork, transport controls, synced lyrics
and the play queue. Everything about the playing track that Kodi knows
(title, times, progress, shuffle/repeat state) comes straight from infolabels
in the skin; Python only adds lyrics, favourites and the queue list.
"""

import threading

import xbmc
import xbmcgui

from resources.lib import actions, connection, kodi, player, subsonic
from resources.lib.ui import ids

L = kodi.L

LYRICS_LEAD_MS = 250   # highlight a line a touch early, it reads more naturally
STOPPED_GRACE = 8      # ticks (x 0.25 s) without audio before the dialog closes


class NowPlaying(xbmcgui.WindowXMLDialog):
    XML = 'script-auradeck-nowplaying.xml'

    def setup(self, client):
        self.client = client
        self.intent = None
        self.closing = False
        self.song_id = None
        self.song = None
        self.lyrics = None
        self.lyric_index = -1
        self.queue_size = -1
        self.queue_pos = -2
        self.panel_chosen = False

    def onInit(self):
        self.setProperty('panel', 'queue')
        self.setFocusId(ids.NP_PLAY)
        threading.Thread(target=self.loop, daemon=True).start()

    def quit(self):
        self.closing = True
        self.close()

    def loop(self):
        monitor = xbmc.Monitor()
        kodi_player = xbmc.Player()
        idle = 0
        while not self.closing and not monitor.abortRequested():
            try:
                if kodi_player.isPlayingAudio():
                    idle = 0
                    self.sync_track()
                    self.sync_queue()
                    self.sync_lyrics(kodi_player)
                else:
                    idle += 1
                    if idle > STOPPED_GRACE:
                        self.quit()
                        break
            except RuntimeError:
                pass  # playback switched tracks mid-call
            if monitor.waitForAbort(0.25):
                break

    # Track
    def sync_track(self):
        song_id = player.current_song_id()
        if song_id == self.song_id:
            return
        self.song_id = song_id
        self.song = None
        self.lyrics = None
        self.lyric_index = -1
        self.getControl(ids.NP_LYRICS).reset()
        self.setProperty('starred', '')
        self.setProperty('lyrics', 'loading' if song_id and self.client else 'none')
        if song_id and self.client:
            threading.Thread(target=self.load_song, args=(song_id,), daemon=True).start()
        elif not self.panel_chosen:
            self.setProperty('panel', 'queue')

    def load_song(self, song_id):
        try:
            song = self.client.song(song_id)
        except subsonic.ApiError:
            return
        if song_id != self.song_id or self.closing:
            return
        self.song = song
        self.setProperty('starred', '1' if song.get('starred') else '')
        lyrics = self.client.lyrics(song)
        if song_id != self.song_id or self.closing:
            return
        self.lyrics = lyrics
        if not lyrics:
            self.setProperty('lyrics', 'none')
            if not self.panel_chosen:
                self.setProperty('panel', 'queue')
            return
        self.setProperty('lyrics', 'synced' if lyrics['synced'] else 'plain')
        if lyrics['synced']:
            # Blank synced lines only mark pauses; the previous line stays lit.
            lyrics['lines'] = [(start, text) for start, text in lyrics['lines'] if text.strip()]
        entries = []
        for start, text in lyrics['lines']:
            item = xbmcgui.ListItem(text.strip() or ' ', offscreen=True)
            item.setProperty('start', '' if start is None else str(start))
            entries.append(item)
        control = self.getControl(ids.NP_LYRICS)
        control.reset()
        control.addItems(entries)
        if not self.panel_chosen:
            self.setProperty('panel', 'lyrics')

    def sync_lyrics(self, kodi_player):
        lyrics = self.lyrics
        if not lyrics or not lyrics['synced'] or self.getFocusId() == ids.NP_LYRICS:
            return
        now = kodi_player.getTime() * 1000 + LYRICS_LEAD_MS
        index = 0
        for position, (start, _text) in enumerate(lyrics['lines']):
            if start is not None and start <= now:
                index = position
            elif start is not None:
                break
        if index != self.lyric_index:
            self.lyric_index = index
            self.getControl(ids.NP_LYRICS).selectItem(index)

    # Queue
    def sync_queue(self):
        position, size = None, None
        playlist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
        size = playlist.size()
        position = playlist.getposition()
        control = self.getControl(ids.NP_QUEUE)
        if size != self.queue_size:
            self.queue_size = size
            self.queue_pos = -2
            entries = []
            for index in range(size):
                source = playlist[index]
                tag = source.getMusicInfoTag()
                entry = xbmcgui.ListItem(tag.getTitle() or source.getLabel(), tag.getArtist(), offscreen=True)
                entry.setArt({'thumb': source.getArt('thumb')})
                entry.setProperty('duration', kodi.fmt_duration(tag.getDuration()))
                entry.setProperty('number', str(index + 1))
                entries.append(entry)
            control.reset()
            control.addItems(entries)
        if position != self.queue_pos:
            previous = self.queue_pos
            self.queue_pos = position
            for index in (previous, position):
                if 0 <= index < control.size():
                    control.getListItem(index).setProperty('current', '1' if index == position else '')
            if 0 <= position < control.size() and self.getFocusId() != ids.NP_QUEUE:
                control.selectItem(position)
            self.setProperty('queue.info', L('np_queue_info').format(max(position, 0) + 1, size))

    # Input
    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            self.quit()
        elif action.getId() in (xbmcgui.ACTION_CONTEXT_MENU, xbmcgui.ACTION_SHOW_INFO):
            self.more_menu()

    def onClick(self, control_id):
        if control_id == ids.NP_TAB_LYRICS:
            self.panel_chosen = True
            self.setProperty('panel', 'lyrics')
        elif control_id == ids.NP_TAB_QUEUE:
            self.panel_chosen = True
            self.setProperty('panel', 'queue')
        elif control_id == ids.NP_QUEUE:
            player.play_queue_index(self.getControl(ids.NP_QUEUE).getSelectedPosition())
        elif control_id == ids.NP_LYRICS:
            item = self.getControl(ids.NP_LYRICS).getSelectedItem()
            if item and item.getProperty('start'):
                xbmc.Player().seekTime(int(item.getProperty('start')) / 1000.0)
                self.setFocusId(ids.NP_PLAY)
        elif control_id == ids.NP_FAVOURITE:
            self.toggle_favourite()
        elif control_id == ids.NP_MORE:
            self.more_menu()

    def toggle_favourite(self):
        song = self.song
        if not song or not self.client:
            return
        state = actions.set_star(self.client, 'song', song['id'], not song.get('starred'))
        if state is not None:
            song['starred'] = 'now' if state else None
            self.setProperty('starred', '1' if state else '')

    def more_menu(self):
        song = self.song
        if not song or not self.client:
            return
        client = self.client
        entries = [(L('ctx_song_mix'), self.song_mix),
                   (L('ctx_add_playlist'), lambda: actions.add_to_playlist(client, [song['id']])),
                   (L('ctx_rate'), lambda: actions.rate(client, song['id'], song.get('title', ''),
                                                        song.get('userRating') or 0))]
        if song.get('albumId'):
            entries.append((L('ctx_go_album'), lambda: self.leave('album', song['albumId'], song.get('album', ''))))
        if song.get('artistId'):
            entries.append((L('ctx_go_artist'), lambda: self.leave('artist', song['artistId'], song.get('artist', ''))))
        choice = xbmcgui.Dialog().contextmenu([label for label, _ in entries])
        if choice >= 0:
            entries[choice][1]()

    def song_mix(self):
        song = self.song

        def work():
            try:
                similar = self.client.similar_songs(song['id'], 80)
            except subsonic.ApiError as exc:
                kodi.notify(connection.describe_error(exc), error=True)
                return
            player.enqueue(self.client, similar, play_next=True)
        threading.Thread(target=work, daemon=True).start()

    def leave(self, kind, item_id, name):
        self.intent = (kind, item_id, name)
        self.quit()
