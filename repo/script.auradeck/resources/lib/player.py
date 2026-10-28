# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
Playback through Kodi's own player and music playlist.

Kodi plays everything: that keeps gapless playback, ReplayGain, crossfade,
visualisations, remote apps and media keys working. Aura-Deck only builds the
queue with direct stream URLs (or offline copies).
"""

import random
import urllib.parse

import xbmc
import xbmcgui

from resources.lib import items, kodi, offline


def _playlist():
    return xbmc.PlayList(xbmc.PLAYLIST_MUSIC)


def _playable(client, songs):
    for song in songs:
        if song.get('id'):
            item = items.playable(client, song)
            if item is not None:
                yield item


def play(client, songs, start=0, shuffle=False):
    """Replace the queue with songs and start at index ``start``."""
    songs = [s for s in songs if s.get('id')]
    if not songs:
        kodi.notify(kodi.L('nothing_to_play'))
        return
    if shuffle:
        songs = songs[:]
        random.shuffle(songs)
        start = 0
    start = max(0, min(start, len(songs) - 1))

    playlist = _playlist()
    playlist.clear()
    for item in _playable(client, songs):
        playlist.add(item.getPath(), item)
    if playlist.size() == 0:
        kodi.notify(kodi.L('nothing_to_play'))
        return
    # Our order is already shuffled; Kodi's own shuffle would reorder again.
    if xbmc.getCondVisibility('Playlist.IsRandom'):
        xbmc.executebuiltin('PlayerControl(RandomOff)')
    xbmc.Player().play(playlist, startpos=start)


def enqueue(client, songs, play_next=False):
    """Add songs to the running queue, either after the current track or at the end."""
    songs = [s for s in songs if s.get('id')]
    if not songs:
        return
    player = xbmc.Player()
    if not player.isPlayingAudio():
        play(client, songs)
        return
    playlist = _playlist()
    position = playlist.getposition() + 1 if play_next else -1
    for offset, item in enumerate(_playable(client, songs)):
        playlist.add(item.getPath(), item, position + offset if play_next else -1)
    kodi.notify(kodi.L('queued_next' if play_next else 'queued_end').format(len(songs)))


def play_radio(radio):
    item = xbmcgui.ListItem(radio.get('name', ''), path=radio.get('streamUrl', ''))
    item.getMusicInfoTag().setTitle(radio.get('name', ''))
    item.setArt({'thumb': kodi.media_path('placeholder_radio.png')})
    xbmc.Player().play(radio.get('streamUrl', ''), item)


def queue_snapshot():
    """(position, [ListItem]) of Kodi's music playlist."""
    playlist = _playlist()
    return playlist.getposition(), [playlist[i] for i in range(playlist.size())]


def play_queue_index(index):
    player = xbmc.Player()
    if player.isPlayingAudio():
        player.playselected(index)
    else:
        player.play(_playlist(), startpos=index)


def song_id_from_path(path):
    """Navidrome song id behind a stream URL or an offline copy, or None."""
    if not path:
        return None
    if '/rest/stream' in path:
        query = urllib.parse.urlparse(path.split('|', 1)[0]).query
        values = urllib.parse.parse_qs(query).get('id')
        return values[0] if values else None
    return offline.song_id_from_path(path)


def current_song_id():
    player = xbmc.Player()
    try:
        if player.isPlayingAudio():
            return song_id_from_path(player.getPlayingFile())
    except RuntimeError:
        pass
    return None
