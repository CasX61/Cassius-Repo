# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
Files under the addon profile, always through xbmcvfs so it works on every
platform Kodi runs on (Android, UWP, LibreELEC, network profiles, ...).
"""

import json
import time

import xbmcvfs

from resources.lib import kodi

_SAFE = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.')


def path(*parts):
    base = kodi.profile_dir().rstrip('/')
    return '/'.join([base] + [str(p).strip('/') for p in parts if str(p).strip('/')])


def safe_name(name):
    text = ''.join(c if c in _SAFE else '_' for c in str(name)).strip('.') or 'item'
    return text[:96]


def exists(target):
    try:
        return bool(xbmcvfs.exists(target))
    except Exception:
        return False


def ensure_dir(target):
    if not target.endswith('/'):
        target += '/'
    if exists(target):
        return True
    try:
        xbmcvfs.mkdirs(target)
    except Exception as exc:
        kodi.log(f'mkdirs {target} failed: {exc}')
    return exists(target)


def delete(target):
    try:
        return bool(xbmcvfs.delete(target))
    except Exception:
        return False


def listdir(target):
    if not target.endswith('/'):
        target += '/'
    if not exists(target):
        return [], []
    try:
        dirs, files = xbmcvfs.listdir(target)
        return list(dirs), list(files)
    except Exception:
        return [], []


def size_of(target):
    try:
        return int(xbmcvfs.Stat(target).st_size())
    except Exception:
        return 0


def mtime_of(target):
    try:
        return float(xbmcvfs.Stat(target).st_mtime())
    except Exception:
        return 0.0


def read_bytes(target):
    if not exists(target):
        return None
    handle = xbmcvfs.File(target)
    try:
        return bytes(handle.readBytes())
    except Exception:
        return None
    finally:
        handle.close()


def write_bytes(target, data):
    if not ensure_dir(target.rsplit('/', 1)[0]):
        return False
    handle = xbmcvfs.File(target, 'w')
    try:
        return bool(handle.write(bytearray(data)))
    except Exception as exc:
        kodi.log(f'write {target} failed: {exc}')
        return False
    finally:
        handle.close()


def read_json(target, max_age=None):
    if max_age is not None and time.time() - mtime_of(target) > max_age:
        return None
    raw = read_bytes(target)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode('utf-8'))
    except ValueError:
        return None


def write_json(target, value):
    return write_bytes(target, json.dumps(value).encode('utf-8'))


# Search history
HISTORY_FILE = 'search_history.json'
HISTORY_SIZE = 8


def search_history():
    data = read_json(path(HISTORY_FILE))
    return data if isinstance(data, list) else []


def remember_search(query):
    query = query.strip()
    if not query:
        return
    history = [q for q in search_history() if q.lower() != query.lower()]
    write_json(path(HISTORY_FILE), [query] + history[:HISTORY_SIZE - 1])


def clear_search_history():
    delete(path(HISTORY_FILE))
