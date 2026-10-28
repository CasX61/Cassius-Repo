# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
Fits the window XML to the active skin's fonts.

The XML names Estuary's fonts, but a font name only means something in the
active skin's Font.xml: other skins size the same names differently, make
their "_title" fonts upper case or lack a name altogether (Kodi then falls
back to font13). So before a window opens, every Estuary font is mapped to the
skin font closest in size and weight, and the mapped XML is written to the
profile and opened from there. Kodi looks for textures next to the XML, so
that copy points at our media folder with full paths.

Whatever can't be read leaves the addon's own XML in place.
"""

import json
import os
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import xbmc
import xbmcvfs

from resources.lib import kodi, storage

LAYOUT_HEIGHT = 1080   # the window XML is laid out for 1080i

# Estuary's fonts the layout was made with: name -> (size, bold)
ESTUARY = {
    'font10': (23, False),
    'font12': (25, False),
    'font13': (30, False),
    'font14': (33, False),
    'font32': (32, False),
    'font45': (45, False),
    'font25_title': (25, True),
    'font30_title': (30, True),
    'font32_title': (32, True),
    'font45_title': (45, True),
}

# Fonts that draw symbols instead of letters
_SYMBOL_FONT = re.compile(r'icon|symbol|awesome|material|weather|glyph|emoji|dings', re.IGNORECASE)
_FONT_TAG = re.compile(r'<font>([^<]+)</font>')
_MEDIA_REF = re.compile(r'(?<=[>"])auradeck/')   # textures as tools/make_skin.py writes them


def window_path():
    """scriptPath for WindowXML: a copy fitted to the active skin, or the addon itself."""
    try:
        return _prepare()
    except Exception as exc:
        kodi.log(f'skin fonts: using the addon XML ({exc})')
        return kodi.addon_path()


def _prepare():
    fonts, scale = _skin_fonts()
    if not fonts:
        raise ValueError('no fonts found in the skin')
    mapping = {name: _closest(name, target, fonts, scale) for name, target in ESTUARY.items()}
    kodi.log(f'skin fonts for {xbmc.getSkinDir()}: {mapping}')

    source = os.path.join(kodi.addon_path(), 'resources', 'skins', 'Default', '1080i')
    root = xbmcvfs.translatePath(storage.path('skin'))
    target = os.path.join(root, 'resources', 'skins', 'Default', '1080i')
    os.makedirs(target, exist_ok=True)
    media = escape(kodi.media_path(''), {'"': '&quot;'})
    for name in os.listdir(source):
        if not name.endswith('.xml'):
            continue
        with open(os.path.join(source, name), encoding='utf-8') as handle:
            text = handle.read()
        text = _FONT_TAG.sub(lambda m: f'<font>{mapping.get(m.group(1), m.group(1))}</font>', text)
        text = _MEDIA_REF.sub(lambda m: media, text)
        _write_if_changed(os.path.join(target, name), text)
    return root


def _write_if_changed(path, text):
    try:
        with open(path, encoding='utf-8') as handle:
            if handle.read() == text:
                return
    except OSError:
        pass
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(text)


# Choosing a font
def _closest(name, target, fonts, scale):
    size, bold = target

    def cost(font):
        value = abs(font['size'] * scale - size) / size
        if font['bold'] != bold:
            value += 0.1
        if font['shaped']:
            value += 1   # upper case or italics changes how every text reads
        value += abs(font['linespacing'] - 1) * 0.5   # rows are sized for normal line spacing
        return value, font['name'] != name

    return min(fonts, key=cost)['name']


# Reading the skin
def _skin_fonts():
    """The active fontset's fonts and the factor from skin to layout pixels."""
    skin = xbmcvfs.translatePath('special://skin/')
    folder, height = _skin_resolution(skin)
    base = os.path.join(skin, folder)
    root = _parse(os.path.join(base, 'Font.xml'))
    includes = {}
    for element in root.findall('include'):
        if element.get('file'):
            _load_includes(base, element.get('file'), includes)

    fontsets = root.findall('fontset')
    if not fontsets:
        return [], 1.0
    wanted = _setting('lookandfeel.font').lower()
    # Kodi falls back to the first fontset when the chosen one is missing
    fontset = next((f for f in fontsets if (f.get('id') or '').lower() == wanted), fontsets[0])
    fonts = []
    _collect(fontset, base, includes, fonts)
    return fonts, LAYOUT_HEIGHT / height


def _skin_resolution(skin):
    """Folder and height of the skin's default resolution (where Font.xml lives)."""
    resolutions = _parse(os.path.join(skin, 'addon.xml')).iter('res')
    candidates = sorted(resolutions, key=lambda res: res.get('default') != 'true')
    for res in candidates:
        folder = res.get('folder', '')
        if os.path.exists(os.path.join(skin, folder, 'Font.xml')):
            return folder, float(res.get('height') or LAYOUT_HEIGHT)
    raise ValueError('no Font.xml in the skin')


def _collect(element, base, includes, fonts, depth=0):
    """Fonts below element, with <include> resolved as Kodi does."""
    if depth > 8:
        return
    for child in element:
        if child.tag == 'font':
            font = _font(child)
            if font:
                fonts.append(font)
        elif child.tag == 'include':
            if child.get('file'):
                _load_includes(base, child.get('file'), includes)
            name = child.get('content') or (child.text or '').strip()
            definition = includes.get(name)
            if definition is not None:
                body = definition.find('definition')
                _collect(definition if body is None else body, base, includes, fonts, depth + 1)


def _load_includes(base, filename, includes, depth=0):
    if depth > 8:
        return
    try:
        root = _parse(os.path.join(base, filename))
    except (OSError, ET.ParseError):
        return
    for element in root.iter('include'):
        if element.get('name'):
            includes.setdefault(element.get('name'), element)
        elif element.get('file'):
            _load_includes(base, element.get('file'), includes, depth + 1)


def _font(element):
    try:
        size = float(element.findtext('size'))
        linespacing = float(element.findtext('linespacing') or 1)
    except (TypeError, ValueError):
        return None   # e.g. a size given as $PARAM
    name = (element.findtext('name') or '').strip()
    style = (element.findtext('style') or '').lower()
    if not name or size <= 0 or _SYMBOL_FONT.search(name + ' ' + (element.findtext('filename') or '')):
        return None
    return {
        'name': name,
        'size': size,
        'bold': 'bold' in style,
        'shaped': any(word in style for word in ('uppercase', 'capitalize', 'italics')),
        'linespacing': linespacing,
    }


def _parse(path):
    with open(path, 'rb') as handle:
        return ET.fromstring(handle.read())


def _setting(key):
    request = {'jsonrpc': '2.0', 'id': 1, 'method': 'Settings.GetSettingValue', 'params': {'setting': key}}
    try:
        return str(json.loads(xbmc.executeJSONRPC(json.dumps(request)))['result']['value'] or '')
    except (KeyError, TypeError, ValueError):
        return ''
