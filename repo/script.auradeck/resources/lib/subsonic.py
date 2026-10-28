# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 CasX61
"""
Subsonic / OpenSubsonic client for Navidrome.

Only the documented Subsonic REST API (``/rest/...``) is used. Navidrome's
internal ``/api`` endpoints belong to its web UI and change without notice.

Authentication uses token auth (``t``/``s``) with a salt that is generated
once at setup and then kept. The password itself is never stored, and
because the salt is stable every cover URL stays byte-for-byte identical
across sessions, which keeps Kodi's texture cache effective.

This module must stay free of Kodi imports so it can be tested standalone.
"""

import gzip
import hashlib
import http.client
import json
import random
import re
import ssl
import string
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API_VERSION = '1.16.1'
CLIENT_NAME = 'AuraDeck'
USER_AGENT = 'AuraDeck/1.0 (Kodi; +https://www.navidrome.org)'

# Servers cap a single response at 500 rows whatever is asked for.
MAX_PAGE = 500

EXT_SONG_LYRICS = 'songLyrics'

# Subsonic error codes
ERR_WRONG_CREDENTIALS = 40
ERR_TOKEN_UNSUPPORTED = 41
ERR_NOT_AUTHORIZED = 50
ERR_NOT_FOUND = 70


class ApiError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class AuthError(ApiError):
    pass


class NetworkError(ApiError):
    pass


class TlsError(NetworkError):
    pass


def make_salt(length=16):
    alphabet = string.ascii_letters + string.digits
    return ''.join(random.SystemRandom().choice(alphabet) for _ in range(length))


def make_token(password, salt):
    return hashlib.md5((password + salt).encode('utf-8')).hexdigest()


def normalize_url(url):
    """Accept what people paste: missing scheme, trailing /app/ or /rest."""
    url = (url or '').strip()
    if not url:
        return ''
    if not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', url):
        url = 'http://' + url
    url = url.rstrip('/')
    for suffix in ('/app/#', '/app', '/rest'):
        if url.endswith(suffix):
            url = url[:-len(suffix)].rstrip('/')
    return url


def redact(url):
    """Strip credentials from a URL before it goes to a log."""
    return re.sub(r'([?&](?:t|s|p|u)=)[^&|]*', r'\1***', url or '')


def strip_html(text):
    text = re.sub(r'<a [^>]*>.*?</a>', '', text or '', flags=re.S)
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text).strip()


class _Memo:
    """Tiny thread-safe TTL cache for read-only API responses."""

    def __init__(self):
        self._data = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self._data.get(key)
            if hit and hit[0] > time.time():
                return hit[1]
            return None

    def put(self, key, value, ttl):
        with self._lock:
            self._data[key] = (time.time() + ttl, value)

    def drop(self, prefix=''):
        with self._lock:
            for key in [k for k in self._data if k.startswith(prefix)]:
                del self._data[key]


class Client:
    """
    One Navidrome account.

    ``transcode`` is None for the original file or a (format, bitrate) tuple.
    """

    def __init__(self, base_url, username, salt, token, verify_tls=True,
                 ca_file='', timeout=15, transcode=None):
        self.base_url = normalize_url(base_url)
        self.username = username
        self.salt = salt
        self.token = token
        self.verify_tls = verify_tls
        self.timeout = timeout
        self.transcode = transcode
        self.memo = _Memo()
        self._extensions = None
        self._ssl = self._ssl_context(verify_tls, ca_file)

    # Transport
    @staticmethod
    def _ssl_context(verify, ca_file):
        if not verify:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            return context
        if ca_file:
            try:
                return ssl.create_default_context(cafile=ca_file)
            except (OSError, ssl.SSLError):
                pass
        return ssl.create_default_context()

    def _query(self, params):
        query = [
            ('u', self.username),
            ('t', self.token),
            ('s', self.salt),
            ('v', API_VERSION),
            ('c', CLIENT_NAME),
            ('f', 'json'),
        ]
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                query.extend((key, v) for v in value)
            elif isinstance(value, bool):
                query.append((key, 'true' if value else 'false'))
            else:
                query.append((key, value))
        return urllib.parse.urlencode(query)

    def url(self, endpoint, **params):
        return f'{self.base_url}/rest/{endpoint}?{self._query(params)}'

    def kodi_url(self, url):
        """Kodi fetches streams and art with its own cURL, not our SSL context."""
        if url and not self.verify_tls and url.lower().startswith('https://'):
            return url + '|verifypeer=false'
        return url

    def _open(self, url, timeout=None, compressed=False):
        headers = {'User-Agent': USER_AGENT}
        if compressed:
            headers['Accept'] = 'application/json'
            headers['Accept-Encoding'] = 'gzip'
        request = urllib.request.Request(url, headers=headers)
        try:
            return urllib.request.urlopen(request, timeout=timeout or self.timeout, context=self._ssl)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise AuthError(f'HTTP {exc.code}', ERR_WRONG_CREDENTIALS) from exc
            raise NetworkError(f'HTTP {exc.code} {exc.reason}', exc.code) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLError):
                raise TlsError(str(exc.reason)) from exc
            raise NetworkError(str(exc.reason)) from exc
        except ssl.SSLError as exc:
            raise TlsError(str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise NetworkError(str(exc)) from exc

    def _fetch_json(self, url):
        try:
            with self._open(url, compressed=True) as response:
                self._follow_redirect(url, response.geturl())
                body = response.read()
                if response.headers.get('Content-Encoding') == 'gzip':
                    body = gzip.decompress(body)
                return body
        except (OSError, EOFError, http.client.HTTPException) as exc:
            raise NetworkError(str(exc)) from exc

    def _follow_redirect(self, requested, final):
        """
        Adopt a permanent move of the server (typically http -> https) so
        streams and covers Kodi fetches itself don't bounce through it.
        """
        marker = '/rest/'
        if final and final != requested and marker in final:
            base = final.split(marker, 1)[0]
            if base != self.base_url:
                self.base_url = base

    def call(self, endpoint, **params):
        """Run one API call and return the inner subsonic-response dict."""
        try:
            body = self._fetch_json(self.url(endpoint, **params))
        except NetworkError as exc:
            # Proxies and busy servers drop the odd keep-alive or parallel
            # connection; one more try is cheap for these read-mostly calls.
            cause = exc.__cause__
            if isinstance(cause, urllib.error.URLError):
                cause = cause.reason
            if not isinstance(cause, (ConnectionError, http.client.HTTPException)):
                raise
            body = self._fetch_json(self.url(endpoint, **params))
        try:
            payload = json.loads(body.decode('utf-8'))['subsonic-response']
        except (ValueError, KeyError) as exc:
            raise NetworkError('Not a Subsonic server (unexpected response)') from exc

        if payload.get('status') != 'ok':
            error = payload.get('error') or {}
            code = error.get('code')
            message = error.get('message') or 'Unknown error'
            if code in (ERR_WRONG_CREDENTIALS, ERR_TOKEN_UNSUPPORTED, ERR_NOT_AUTHORIZED):
                raise AuthError(message, code)
            raise ApiError(message, code)
        return payload

    def cached(self, key, ttl, loader):
        value = self.memo.get(key)
        if value is None:
            value = loader()
            self.memo.put(key, value, ttl)
        return value

    def invalidate(self, prefix=''):
        self.memo.drop(prefix)

    # System
    def ping(self):
        """Returns server info: type, serverVersion, openSubsonic."""
        response = self.call('ping')
        return {
            'type': response.get('type', 'subsonic'),
            'version': response.get('serverVersion') or response.get('version', ''),
            'openSubsonic': bool(response.get('openSubsonic')),
        }

    def extensions(self):
        if self._extensions is None:
            try:
                response = self.call('getOpenSubsonicExtensions')
                self._extensions = {e.get('name') for e in response.get('openSubsonicExtensions', [])}
            except ApiError:
                self._extensions = set()
        return self._extensions

    # Browsing
    def artists(self):
        def load():
            indexes = self.call('getArtists').get('artists', {}).get('index', [])
            return [artist for index in indexes for artist in index.get('artist', [])]
        return self.cached('artists', 600, load)

    def artist(self, artist_id):
        return self.call('getArtist', id=artist_id).get('artist', {})

    def artist_info(self, artist_id, similar=12):
        def load():
            try:
                info = self.call('getArtistInfo2', id=artist_id, count=similar,
                                 includeNotPresent=False).get('artistInfo2', {})
            except ApiError:
                return {}
            info['biography'] = strip_html(info.get('biography', ''))
            return info
        return self.cached(f'artistinfo:{artist_id}', 3600, load)

    def top_songs(self, artist_name, count=10):
        try:
            return self.call('getTopSongs', artist=artist_name, count=count).get('topSongs', {}).get('song', [])
        except ApiError:
            return []

    def album(self, album_id):
        return self.call('getAlbum', id=album_id).get('album', {})

    def album_list(self, kind, size=50, offset=0, **extra):
        """
        kind: random, newest, highest, frequent, recent, starred,
              alphabeticalByName, alphabeticalByArtist, byYear, byGenre
        """
        params = {'type': kind, 'size': min(size, MAX_PAGE), 'offset': offset}
        params.update(extra)
        return self.call('getAlbumList2', **params).get('albumList2', {}).get('album', [])

    def song(self, song_id):
        return self.call('getSong', id=song_id).get('song', {})

    def random_songs(self, size=100, genre=None):
        return self.call('getRandomSongs', size=min(size, MAX_PAGE), genre=genre) \
            .get('randomSongs', {}).get('song', [])

    def starred(self):
        def load():
            data = self.call('getStarred2').get('starred2', {})
            return {
                'artist': data.get('artist', []),
                'album': data.get('album', []),
                'song': data.get('song', []),
            }
        return self.cached('starred', 120, load)

    def genres(self):
        def load():
            items = [g for g in self.call('getGenres').get('genres', {}).get('genre', [])
                     if (g.get('value') or '').strip()]
            return sorted(items, key=lambda g: g['value'].lower())
        return self.cached('genres', 900, load)

    def genre_cover(self, genre):
        """Cover id of one album in a genre, to illustrate the genre's tile."""
        def load():
            try:
                albums = self.album_list('byGenre', 1, genre=genre)
            except ApiError:
                return ''
            return albums[0].get('coverArt', '') if albums else ''
        return self.cached(f'genrecover:{genre}', 6 * 3600, load)

    def songs_by_genre(self, genre, count=100, offset=0):
        return self.call('getSongsByGenre', genre=genre, count=min(count, MAX_PAGE), offset=offset) \
            .get('songsByGenre', {}).get('song', [])

    def similar_songs(self, item_id, count=50):
        """Instant mix seeded by a song, album or artist id."""
        try:
            return self.call('getSimilarSongs2', id=item_id, count=count).get('similarSongs2', {}).get('song', [])
        except ApiError:
            return []

    def radios(self):
        return self.call('getInternetRadioStations') \
            .get('internetRadioStations', {}).get('internetRadioStation', [])

    def search(self, query, artists=12, albums=20, songs=30, song_offset=0):
        result = self.call('search3', query=query, artistCount=artists, albumCount=albums,
                           songCount=min(songs, MAX_PAGE), songOffset=song_offset)
        data = result.get('searchResult3', {})
        return {
            'artist': data.get('artist', []),
            'album': data.get('album', []),
            'song': data.get('song', []),
        }

    # Playlists
    def playlists(self):
        return self.cached('playlists', 60, lambda: self.call('getPlaylists')
                           .get('playlists', {}).get('playlist', []))

    def playlist(self, playlist_id):
        return self.call('getPlaylist', id=playlist_id).get('playlist', {})

    def create_playlist(self, name, song_ids=()):
        self.invalidate('playlists')
        return self.call('createPlaylist', name=name, songId=list(song_ids)).get('playlist', {})

    def update_playlist(self, playlist_id, name=None, add=(), remove_indexes=()):
        self.invalidate('playlists')
        self.call('updatePlaylist', playlistId=playlist_id, name=name,
                  songIdToAdd=list(add), songIndexToRemove=list(remove_indexes))

    def delete_playlist(self, playlist_id):
        self.invalidate('playlists')
        self.call('deletePlaylist', id=playlist_id)

    # Annotation
    def star(self, kind, item_id, starred=True):
        key = {'song': 'id', 'album': 'albumId', 'artist': 'artistId'}.get(kind, 'id')
        self.call('star' if starred else 'unstar', **{key: item_id})
        self.invalidate('starred')

    def set_rating(self, item_id, rating):
        self.call('setRating', id=item_id, rating=max(0, min(5, int(rating))))

    def scrobble(self, song_id, submission=True):
        self.call('scrobble', id=song_id, submission=submission, time=int(time.time() * 1000))

    def lyrics(self, song):
        """
        Lyrics for a song dict as {'synced': bool, 'lines': [(ms|None, text)]}
        or None. Prefers OpenSubsonic structured (synced) lyrics.
        """
        if EXT_SONG_LYRICS in self.extensions():
            try:
                entries = self.call('getLyricsBySongId', id=song['id']) \
                    .get('lyricsList', {}).get('structuredLyrics', [])
            except ApiError:
                entries = []
            # Main lyrics before translations/pronunciations, synced before plain
            entries.sort(key=lambda e: ((e.get('kind') or 'main') != 'main', not e.get('synced')))
            for entry in entries:
                # A positive offset means the lyrics appear sooner
                offset = int(entry.get('offset') or 0)
                lines = [
                    ((int(line['start']) - offset) if entry.get('synced') and 'start' in line else None,
                     line.get('value', ''))
                    for line in entry.get('line', [])
                ]
                if any(text.strip() for _, text in lines):
                    return {'synced': bool(entry.get('synced')), 'lines': lines}
            # getLyricsBySongId already covers everything the server has; the
            # legacy lookup by artist/title can take many seconds on Navidrome.
            return None
        try:
            text = self.call('getLyrics', artist=song.get('artist', ''), title=song.get('title', '')) \
                .get('lyrics', {}).get('value', '')
        except ApiError:
            text = ''
        if text.strip():
            return {'synced': False, 'lines': [(None, line) for line in text.splitlines()]}
        return None

    # Media URLs
    def cover_url(self, cover_id, size=300):
        if not cover_id:
            return ''
        return self.kodi_url(self.url('getCoverArt', id=cover_id, size=size))

    def stream_url(self, song_id, for_kodi=True):
        if self.transcode:
            fmt, bitrate = self.transcode
            url = self.url('stream', id=song_id, format=fmt, maxBitRate=bitrate, estimateContentLength=True)
        else:
            url = self.url('stream', id=song_id, format='raw')
        return self.kodi_url(url) if for_kodi else url

    def stream_suffix(self, song):
        if self.transcode:
            return self.transcode[0]
        return (song.get('suffix') or 'mp3').lower()

    def open_stream(self, song_id):
        """Raw HTTP response for downloading a track (caller closes it)."""
        return self._open(self.stream_url(song_id, for_kodi=False), timeout=max(self.timeout, 30))

    def fetch(self, url):
        clean = url.split('|', 1)[0]
        with self._open(clean) as response:
            return response.read()
