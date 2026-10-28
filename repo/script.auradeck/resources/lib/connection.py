# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
Server configuration: building a client from the settings and the setup
wizard that fills them in.
"""

import time

import xbmcgui
import xbmcvfs

from resources.lib import kodi, subsonic

# Index of the 'transcode' setting -> (format, max bitrate); None = original
TRANSCODE_OPTIONS = [
    None,
    ('mp3', 320),
    ('mp3', 192),
    ('mp3', 128),
    ('opus', 160),
    ('opus', 96),
    ('aac', 256),
]


def configured():
    return all(kodi.setting(k) for k in ('server_url', 'username', 'auth_salt', 'auth_token'))


def _transcode():
    index = kodi.setting_int('transcode', 0)
    return TRANSCODE_OPTIONS[index] if 0 <= index < len(TRANSCODE_OPTIONS) else None


ROUTE_PROPERTY = 'auradeck.route'   # "<local url>|<reachable 1/0>|<checked at>"
ROUTE_TTL = 300


def _server_url():
    """
    The local address when one is set and answers, else the public one. The
    result is shared through a home window property for a few minutes so the
    widget plugin doesn't probe on every call.
    """
    public = kodi.setting('server_url')
    local = subsonic.normalize_url(kodi.setting('local_url'))
    if not local or local == subsonic.normalize_url(public):
        return public
    cached = kodi.home_property(ROUTE_PROPERTY).split('|')
    if len(cached) == 3 and cached[0] == local:
        try:
            if time.time() - float(cached[2]) < ROUTE_TTL:
                return local if cached[1] == '1' else public
        except ValueError:
            pass
    try:
        subsonic.Client(local, kodi.setting('username'), kodi.setting('auth_salt'), kodi.setting('auth_token'),
                        verify_tls=kodi.setting_bool('verify_tls', True), timeout=2).ping()
        reachable = True
    except subsonic.ApiError:
        reachable = False
    kodi.set_home_property(ROUTE_PROPERTY, f'{local}|{int(reachable)}|{time.time()}')
    kodi.log(f'local address {local} {"reachable" if reachable else "not reachable"}')
    return local if reachable else public


def client_from_settings():
    if not configured():
        return None
    ca_file = kodi.setting('ca_file')
    return subsonic.Client(
        _server_url(),
        kodi.setting('username'),
        kodi.setting('auth_salt'),
        kodi.setting('auth_token'),
        verify_tls=kodi.setting_bool('verify_tls', True),
        ca_file=xbmcvfs.translatePath(ca_file) if ca_file else '',
        timeout=kodi.setting_int('timeout', 15),
        transcode=_transcode(),
    )


def describe_error(exc):
    """One user-facing sentence for an API exception."""
    if isinstance(exc, subsonic.AuthError):
        if exc.code == subsonic.ERR_TOKEN_UNSUPPORTED:
            return kodi.L('err_token_unsupported')
        return kodi.L('err_auth')
    if isinstance(exc, subsonic.TlsError):
        return kodi.L('err_tls')
    if isinstance(exc, subsonic.NetworkError):
        return kodi.L('err_network').format(exc)
    return kodi.L('err_server').format(exc)


WIZARD_PROPERTY = 'auradeck.wizard'


def wizard_running():
    return bool(kodi.home_property(WIZARD_PROPERTY))


def run_wizard():
    """Ask for server, user and password, verify them, then save. True on success."""
    kodi.set_home_property(WIZARD_PROPERTY, '1')
    try:
        return _wizard()
    finally:
        kodi.set_home_property(WIZARD_PROPERTY, '')


def _wizard():
    dialog = xbmcgui.Dialog()
    title = kodi.L('wizard_title')

    url = dialog.input(kodi.L('wizard_url'), defaultt=kodi.setting('server_url') or 'http://')
    url = subsonic.normalize_url(url)
    if not url or url in ('http:', 'https:'):
        return False
    username = dialog.input(kodi.L('wizard_user'), defaultt=kodi.setting('username'))
    if not username:
        return False
    password = dialog.input(kodi.L('wizard_password'), option=xbmcgui.ALPHANUM_HIDE_INPUT)
    if not password:
        return False

    salt = subsonic.make_salt()
    token = subsonic.make_token(password, salt)
    verify = kodi.setting_bool('verify_tls', True)

    while True:
        progress = xbmcgui.DialogProgress()
        progress.create(title, kodi.L('wizard_testing').format(url))
        try:
            client = subsonic.Client(url, username, salt, token, verify_tls=verify,
                                     timeout=kodi.setting_int('timeout', 15))
            info = client.ping()
            break
        except subsonic.TlsError:
            progress.close()
            if not dialog.yesno(title, kodi.L('wizard_tls_question')):
                return False
            verify = False
        except subsonic.ApiError as exc:
            progress.close()
            dialog.ok(title, describe_error(exc))
            return False
        finally:
            progress.close()

    kodi.set_setting('server_url', client.base_url)  # may have followed a redirect
    kodi.set_setting('username', username)
    kodi.set_setting('auth_salt', salt)
    kodi.set_setting('auth_token', token)
    kodi.set_setting('verify_tls', verify)

    server = 'Navidrome' if info['type'] == 'navidrome' else info['type'].capitalize()
    kodi.notify(kodi.L('wizard_connected').format(server, info['version']))
    return True
