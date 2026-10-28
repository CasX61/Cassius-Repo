# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
Thin helpers around the Kodi Python API shared by the UI, the widget plugin
and the background service.
"""

import os
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.lib.strings import STRINGS

ADDON_ID = 'script.auradeck'
ADDON_NAME = 'Aura-Deck'

HOME_WINDOW = 10000

# Home window properties shared between the UI, the service and the plugin
PROP_PLAYING = 'auradeck.playing'      # Navidrome id of the track playing now
PROP_HEARTBEAT = 'auradeck.heartbeat'  # time.time() of the UI's last tick
PROP_COMMAND = 'auradeck.command'      # deep link for an already open UI
HEARTBEAT_TIMEOUT = 5

_strings = {}


def addon():
    # A fresh instance every time: an Addon object keeps the settings it was
    # created with, and both the UI and the service live long enough for the
    # user to change them underneath us.
    return xbmcaddon.Addon(ADDON_ID)


def addon_path():
    return xbmcvfs.translatePath(addon().getAddonInfo('path'))


def profile_dir():
    path = addon().getAddonInfo('profile') or f'special://profile/addon_data/{ADDON_ID}/'
    return path if path.endswith('/') else path + '/'


def media_path(name):
    return f'{addon_path()}/resources/skins/Default/media/{name}'


def L(key):
    """Localized string for a key from resources/lib/strings.py."""
    text = _strings.get(key)
    if text is None:
        string_id = STRINGS.get(key)
        text = addon().getLocalizedString(string_id) if string_id else ''
        text = text or key
        _strings[key] = text
    return text


# Settings
def setting(key, default=''):
    try:
        value = addon().getSetting(key)
    except Exception:
        return default
    return value if value != '' else default


def setting_bool(key, default=False):
    raw = setting(key, None)
    if raw is None:
        return default
    return str(raw).lower() == 'true'


def setting_int(key, default=0):
    try:
        return int(float(setting(key, default)))
    except (TypeError, ValueError):
        return default


def set_setting(key, value):
    if isinstance(value, bool):
        value = 'true' if value else 'false'
    addon().setSetting(key, str(value))


def open_settings():
    addon().openSettings()


# Logging and feedback
def log(message, level=xbmc.LOGDEBUG):
    if level == xbmc.LOGDEBUG and setting_bool('debug'):
        level = xbmc.LOGINFO
    xbmc.log(f'[{ADDON_ID}] {message}', level)


def log_error(message):
    log(message, xbmc.LOGERROR)


def notify(message, error=False, time_ms=3000):
    icon = xbmcgui.NOTIFICATION_ERROR if error else addon().getAddonInfo('icon')
    xbmcgui.Dialog().notification(ADDON_NAME, message, icon, time_ms, False)


# Home window properties
def home_property(key):
    return xbmcgui.Window(HOME_WINDOW).getProperty(key)


def set_home_property(key, value):
    window = xbmcgui.Window(HOME_WINDOW)
    if value in (None, ''):
        window.clearProperty(key)
    else:
        window.setProperty(key, str(value))


# Formatting
def fmt_duration(seconds):
    seconds = int(seconds or 0)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f'{hours}:{minutes:02d}:{secs:02d}'
    return f'{minutes}:{secs:02d}'


def fmt_total(seconds):
    """Long form duration for headers: '1 hr 12 min' / '43 min'."""
    minutes = int(seconds or 0) // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return L('fmt_hours_minutes').format(hours, minutes)
    return L('fmt_minutes').format(minutes)


def fmt_count(count, one_key, many_key):
    count = int(count or 0)
    return L(one_key if count == 1 else many_key).format(count)


def join_meta(*parts):
    return '  ·  '.join(str(p) for p in parts if p not in (None, '', 0))


# App window
def ui_running():
    try:
        return time.time() - int(home_property(PROP_HEARTBEAT) or 0) < HEARTBEAT_TIMEOUT
    except ValueError:
        return False


def open_app(command=''):
    """
    Open the Aura-Deck window, optionally on a deep link like 'album:<id>'.
    An already open window is told where to go instead of opening twice.
    """
    if ui_running():
        set_home_property(PROP_COMMAND, command or 'show')
        return
    script = os.path.join(addon_path(), 'default.py')
    args = [f'"{script}"'] + (command.split(':', 1) if command else [])
    xbmc.executebuiltin(f"RunScript({','.join(args)})")
