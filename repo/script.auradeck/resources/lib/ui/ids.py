# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
Control ids shared by the Python UI and tools/make_skin.py, which generates
the skin XML from them. Change an id here and regenerate the skin.
"""

# Main window
SIDEBAR = 100

# Invisible 1 px buttons. Kodi's conditional navigation proved unreliable
# (a grouplist wraps around instead), so the skin navigates to these with
# fixed ids and Python forwards focus from there.
FOCUS_PARK = 1097       # holds focus while a view is swapped
ENTRY_ROUTER = 1098     # -> back to the content the user came from
TOP_ROUTER = 1099       # up from the first shelf -> the page's header buttons
ROUTERS = (FOCUS_PARK, ENTRY_ROUTER, TOP_ROUTER)

# 'rows' view: a hero header above a vertical grouplist of shelves
ROWS = 1000
HERO_BUTTONS = 1110           # home / generic hero
ARTIST_BUTTONS = 1210         # artist hero
SEARCH_FIELD = 1301
SEARCH_HISTORY = 1310
TRACKS_SHELF = 1401           # vertical song list inside the grouplist
TRACKS_SHELF_LABEL = 1400
TRACK_ROW_HEIGHT = 80         # height of one song row in every song list
SHELF_COUNT = 8


def shelf(index):
    """List id of the cover shelf ``index`` (0-based)."""
    return 1511 + index * 10


def shelf_label(index):
    return 1510 + index * 10


SHELVES = [shelf(i) for i in range(SHELF_COUNT)]

# 'grid' view
GRID = 2000
GRID_BUTTONS = 2010

# 'tracks' view
TRACKLIST = 3000
TRACKLIST_BUTTONS = 3010

# 'detail' view (album / playlist)
DETAIL_TRACKS = 4000
DETAIL_BUTTONS = 4010

# Mini player
MINI_OPEN = 9001
MINI_PREV = 9002
MINI_PLAY = 9003
MINI_NEXT = 9004

BUTTON_BARS = (HERO_BUTTONS, ARTIST_BUTTONS, GRID_BUTTONS, TRACKLIST_BUTTONS, DETAIL_BUTTONS)
CONTENT_LISTS = tuple(SHELVES) + (TRACKS_SHELF, GRID, TRACKLIST, DETAIL_TRACKS, SEARCH_HISTORY)
SONG_LISTS = (TRACKS_SHELF, TRACKLIST, DETAIL_TRACKS)

# Focus targets the sidebar and the mini player return to, by name
ENTRY_POINTS = (
    HERO_BUTTONS, ARTIST_BUTTONS, SEARCH_FIELD, ROWS,
    GRID_BUTTONS, GRID, TRACKLIST_BUTTONS, TRACKLIST, DETAIL_BUTTONS, DETAIL_TRACKS,
)

# Now playing dialog
NP_TAB_LYRICS = 6001
NP_TAB_QUEUE = 6002
NP_SLIDER = 6020
NP_SHUFFLE = 6011
NP_PREV = 6012
NP_PLAY = 6013
NP_NEXT = 6014
NP_REPEAT = 6015
NP_FAVOURITE = 6016
NP_MORE = 6017
NP_LYRICS = 6100
NP_QUEUE = 6200
