# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
The full screen app. The plugin starts it with RunScript on this addon's
default.py (see kodi.open_app):

    default.py                       open Aura-Deck
    default.py album <id>            open on an album (also artist, playlist,
                                     genre)
    default.py nowplaying            open the now playing screen
    default.py setup                 connection wizard
    default.py clear_offline         empty the offline cache
"""

from resources.lib import actions, connection, kodi, offline
from resources.lib.ui.window import XML, MainWindow


def run(argv):
    args = [a for a in argv[1:] if a]
    command = ':'.join(args[:2]) if args else ''

    if command == 'setup':
        connection.run_wizard()
        return
    if command == 'clear_offline':
        actions.clear_offline()
        return

    # A deep link while the window is already open is handed over instead of
    # stacking a second window on top of the first.
    if kodi.ui_running():
        kodi.set_home_property(kodi.PROP_COMMAND, command or 'show')
        return

    # Without a server the window still opens on the offline library.
    if not connection.configured() and not connection.run_wizard() and not offline.cached_ids():
        return

    window = MainWindow(XML, kodi.addon_path(), 'Default', '1080i')
    window.setup(connection.client_from_settings(), start=command or None)
    try:
        window.doModal()
    finally:
        window.closing = True
        kodi.set_home_property(kodi.PROP_HEARTBEAT, '')
        del window
