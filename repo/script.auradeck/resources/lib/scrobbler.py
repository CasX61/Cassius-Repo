# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
Background service: reports "now playing" and scrobbles to Navidrome for
everything Aura-Deck queued, whether from the window, a widget or Kodi's own
playlist, and publishes the playing song id for the skin.

Listening time is counted from the player position, so pauses and seeks do
not count. A track scrobbles after the configured share of its length or
after four minutes, whichever comes first (the Last.fm rule).
"""

import threading

import xbmc

from resources.lib import connection, kodi, player, subsonic

TICK = 1.0
MAX_STEP = 3.0        # larger position jumps are seeks, not listening
MIN_LENGTH = 30       # tracks shorter than this never scrobble
SCROBBLE_CAP = 240


class Service(xbmc.Monitor):

    def __init__(self):
        super().__init__()
        self.client = None
        self.song_id = None
        self.duration = 0
        self.listened = 0.0
        self.last_position = 0.0
        self.scrobbled = False
        self.reload()

    def onSettingsChanged(self):
        self.reload()

    def reload(self):
        self.client = connection.client_from_settings()
        self.enabled = kodi.setting_bool('scrobble', True)
        self.now_playing = kodi.setting_bool('now_playing', True)
        self.threshold = max(10, min(90, kodi.setting_int('scrobble_percent', 50))) / 100.0

    def run(self):
        kodi.log('service started')
        while not self.abortRequested():
            if self.waitForAbort(TICK):
                break
            try:
                self.tick()
            except RuntimeError:
                pass  # player changed state between two calls
        kodi.set_home_property(kodi.PROP_PLAYING, '')

    def tick(self):
        kodi_player = xbmc.Player()
        song_id = player.current_song_id()
        if song_id != self.song_id:
            self.start(song_id, kodi_player)
            return
        if not song_id or xbmc.getCondVisibility('Player.Paused'):
            return

        position = kodi_player.getTime()
        step = position - self.last_position
        self.last_position = position
        if 0 < step <= MAX_STEP:
            self.listened += step

        if self.enabled and not self.scrobbled and self.duration >= MIN_LENGTH:
            if self.listened >= min(self.duration * self.threshold, SCROBBLE_CAP):
                self.scrobbled = True
                self.report(song_id, True)

    def start(self, song_id, kodi_player):
        self.song_id = song_id
        self.scrobbled = False
        self.listened = 0.0
        kodi.set_home_property(kodi.PROP_PLAYING, song_id or '')
        if not song_id:
            return
        try:
            self.duration = kodi_player.getTotalTime()
            self.last_position = kodi_player.getTime()
        except RuntimeError:
            self.duration, self.last_position = 0, 0.0
        if self.enabled and self.now_playing:
            self.report(song_id, False)

    def report(self, song_id, submission):
        client = self.client
        if client is None:
            return

        def send():
            try:
                client.scrobble(song_id, submission=submission)
                kodi.log(f"{'scrobbled' if submission else 'now playing'} {song_id}")
            except subsonic.ApiError as exc:
                kodi.log(f'scrobble {song_id} failed: {exc}')
        # Off the service loop so a slow server never stalls the timing.
        threading.Thread(target=send, daemon=True).start()


def run():
    Service().run()
