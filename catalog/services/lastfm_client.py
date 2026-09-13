"""Cliente para la API de Last.fm (https://www.last.fm/api).

Expone artistas similares, top álbumes, tags y stats de un álbum, con un
pequeño throttle preventivo (~5 requests/segundo, límite oficial de Last.fm).
"""
import logging
import threading
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://ws.audioscrobbler.com/2.0/"

# Last.fm permite ~5 requests/segundo; espaciamos un poco más para estar
# holgados y no saturar la API.
RATE_LIMIT_INTERVAL = 0.22  # segundos entre llamadas (~4.5 req/seg)

REQUEST_TIMEOUT = 15

# Cuando Last.fm limita las consultas responde 429/502/503. Retransmitir con
# backoff acotado permite sobrevivir throttling transitorio; tras varios
# intentos falla con un mensaje claro en vez de romper la búsqueda en silencio.
RETRYABLE_STATUSES = {429, 502, 503}
MAX_API_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0  # segundos: 2, 4 para reintentos 1 y 2


class LastFMError(Exception):
    """Se lanza cuando la API de Last.fm responde con un error inesperado."""
    pass


class _RateLimiter:
    """Throttle simple y thread-safe: espacia las llamadas a la API.

    ``min_interval`` es la separación mínima en segundos entre dos llamadas
    consecutivas; los hilos que llegan antes de tiempo se bloquean hasta que
    les toca su turno.
    """

    def __init__(self, min_interval):
        self.min_interval = min_interval
        self._last_call = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            wait_for = self._last_call + self.min_interval - now
            if wait_for > 0:
                time.sleep(wait_for)
                now = time.monotonic()
            self._last_call = now


_lastfm_throttle = _RateLimiter(RATE_LIMIT_INTERVAL)


def _to_int(value):
    """Convierte un valor (string, int, None) a int, anteponiendo 0 si no es parseable."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _retry_delay(response, attempt):
    """Espera entre reintentos: respeta ``Retry-After`` o backoff exponencial."""
    base = RETRY_BACKOFF_BASE * (2 ** attempt)
    if response is None:
        return base
    try:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            parsed = int(retry_after)
            if parsed > 0:
                return parsed
    except (AttributeError, TypeError, ValueError):
        pass
    return base


def _request(method, params):
    """GET a la API respetando el throttle y con reintentos por límite.

    Args:
        method: método de la API (ej: ``artist.getsimilar``).
        params: parámetros específicos del método.

    Returns:
        JSON parseado, o ``None`` cuando Last.fm responde un error "amable"
        (error en el body con HTTP 200) o un 404 HTTP.

    Raises:
        LastFMError: si la conexión falla, si la API responde con un status
            inesperado, o si tras reintentos sigue limitando (429/502/503) o
            responde un error de límite de API en el body (códigos 15/29).
    """
    _lastfm_throttle.wait()
    query = {
        "method": method,
        "api_key": settings.LASTFM_API_KEY,
        "format": "json",
        **params,
    }

    for attempt in range(MAX_API_RETRIES):
        try:
            response = requests.get(BASE_URL, params=query, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            if attempt < MAX_API_RETRIES - 1:
                logger.warning("Last.fm request failed for %s (%s); reintentando", method, exc)
                time.sleep(_retry_delay(None, attempt))
                continue
            logger.warning("Last.fm request failed for %s: %s", method, exc)
            raise LastFMError(f"request failed for {method}: {exc}") from exc

        if response.status_code in RETRYABLE_STATUSES:
            if attempt < MAX_API_RETRIES - 1:
                logger.warning(
                    "Last.fm %s for %s; reintentando en %ss",
                    response.status_code, method, _retry_delay(response, attempt),
                )
                time.sleep(_retry_delay(response, attempt))
                continue
            logger.error("Last.fm %s for %s agotó los reintentos", response.status_code, method)
            raise LastFMError(
                f"Last.fm está limitando las consultas ({response.status_code} "
                f"para {method}). Esperá un momento y volvé a intentar."
            )

        if response.status_code == requests.codes.not_found:
            logger.info("Last.fm returned 404 for %s", method)
            return None

        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Last.fm returned status %s for %s", response.status_code, method)
            raise LastFMError(f"unexpected status {response.status_code} for {method}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            logger.warning("Last.fm returned invalid JSON for %s", method)
            raise LastFMError(f"invalid JSON for {method}") from exc

        if isinstance(data, dict) and data.get("error"):
            code = data.get("error")
            if code in (15, 29):
                # 15: temporary error, 29: rate limit exceeded. Devuelto como
                # error explícito para no confundir "sin datos" con "limitado".
                logger.warning("Last.fm límite de API (%s) para %s", code, method)
                raise LastFMError(
                    f"Last.fm está limitando las consultas ({data.get('message') or code}). "
                    "Esperá un momento y volvé a intentar."
                )
            logger.info("Last.fm error %s for %s: %s", data.get("error"), method, data.get("message"))
            return None

        return data

    raise LastFMError(f"no se pudo completar {method} tras {MAX_API_RETRIES} intentos")


def _as_list(value):
    """Normaliza un item suelto de Last.fm (dict) a lista, tolerando None."""
    if not value:
        return []
    if isinstance(value, dict):
        return [value]
    return value


def search_artists(query, limit=10):
    """Busca artistas por nombre en Last.fm.

    Llama a ``artist.search``. Pensada para alimentar un autocomplete del
    frontend: filtra por fragmento de texto y devuelve las coincidencias con
    su MBID y cantidad de listeners.

    Args:
        query: fragmento de texto a buscar (nombre del artista).
        limit: cantidad máxima de resultados a pedir.

    Returns:
        Lista de dicts ``[{"name": str, "mbid": str, "listeners": int}, ...]``.
        Vacía si la API no devuelve datos o responde un error amable.
    """
    data = _request("artist.search", {"artist": query, "limit": limit})
    if data is None:
        return []
    matches = _as_list(((data.get("results") or {}).get("artistmatches") or {}).get("artist"))
    return [
        {
            "name": artist.get("name"),
            "mbid": artist.get("mbid") or "",
            "listeners": _to_int(artist.get("listeners")),
        }
        for artist in matches
        if artist.get("name")
    ]


def get_artist_albums(artist_name, limit=100):
    """Devuelve los álbumes más populares de un artista.

    Llama a ``artist.gettopalbums``. Pensada para alimentar un select de
    álbumes del artista ya elegido en el frontend.

    Args:
        artist_name: nombre del artista.
        limit: cantidad máxima de álbumes a pedir.

    Returns:
        Lista de dicts ``[{"title": str, "mbid": str}, ...]``. Vacía si la API
        no devuelve datos o responde un error amable.
    """
    data = _request("artist.gettopalbums", {"artist": artist_name, "limit": limit})
    if data is None:
        return []
    albums = _as_list((data.get("topalbums") or {}).get("album"))
    return [
        {"title": album.get("name"), "mbid": album.get("mbid") or ""}
        for album in albums
        if album.get("name")
    ]


def get_similar_artists(artist_name, limit=10):
    """Devuelve los nombres de los artistas similares a ``artist_name``.

    Llama a ``artist.getsimilar``.

    Args:
        artist_name: nombre del artista.
        limit: cantidad máxima de artistas similares a pedir.

    Returns:
        Lista de strings con los nombres de los artistas similares. Vacía si la
        API no devuelve datos o responde un error amable.
    """
    data = _request("artist.getsimilar", {"artist": artist_name, "limit": limit})
    if data is None:
        return []
    artists = _as_list((data.get("similarartists") or {}).get("artist"))
    return [artist.get("name") for artist in artists if artist.get("name")]


def get_top_albums(artist_name, limit=3):
    """Devuelve los álbumes más populares de un artista.

    Llama a ``artist.gettopalbums``.

    Args:
        artist_name: nombre del artista.
        limit: cantidad máxima de álbumes a pedir.

    Returns:
        Lista de tuplas ``(album_name, artist_name)``. Vacía si la API no
        devuelve datos o responde un error amable.
    """
    data = _request("artist.gettopalbums", {"artist": artist_name, "limit": limit})
    if data is None:
        return []
    albums = _as_list((data.get("topalbums") or {}).get("album"))
    result = []
    for album in albums:
        title = album.get("name")
        artist_field = album.get("artist") or {}
        artist = artist_field.get("name") if isinstance(artist_field, dict) else artist_field
        if title and artist:
            result.append((title, artist))
    return result


def get_album_tags(artist_name, album_title):
    """Devuelve los tags más usados de un álbum.

    Llama a ``album.gettoptags``.

    Args:
        artist_name: nombre del artista.
        album_title: título del álbum.

    Returns:
        Lista de dicts ``[{"name": str, "count": int}, ...]``. Vacía si la API
        no devuelve datos o responde un error amable.
    """
    data = _request("album.gettoptags", {"artist": artist_name, "album": album_title})
    if data is None:
        return []
    tags = _as_list((data.get("toptags") or {}).get("tag"))
    return [
        {"name": tag.get("name"), "count": _to_int(tag.get("count"))}
        for tag in tags
        if tag.get("name")
    ]


def get_album_full_info(artist_name, album_title):
    """Devuelve tags y estadísticas de escucha de un álbum en una sola llamada.

    Llama a ``album.getinfo``, que ya incluye los top tags del álbum además de
    los campos de popularidad. Pensada para enriquecer álbumes candidatos sin
    hacer dos llamadas separadas (tags + stats).

    Args:
        artist_name: nombre del artista.
        album_title: título del álbum.

    Returns:
        dict con las claves ``listeners``, ``playcount`` (ints) y ``tags``
        (lista de ``{"name": str, "count": int}``), o ``{}`` si la API no
        devuelve datos o responde un error amable.
    """
    data = _request("album.getinfo", {"artist": artist_name, "album": album_title})
    if data is None:
        return {}
    album = data.get("album") or {}
    tags = _as_list((album.get("toptags") or {}).get("tag"))
    if not tags:
        # album.getinfo dejó de incluir "toptags" para muchos álbumes; se
        # recuperan con album.gettoptags como respaldo.
        try:
            tags = get_album_tags(artist_name, album_title)
        except LastFMError:
            tags = []
    return {
        "listeners": _to_int(album.get("listeners")),
        "playcount": _to_int(album.get("playcount")),
        "tags": [
            {"name": tag.get("name"), "count": _to_int(tag.get("count"))}
            for tag in tags
            if tag.get("name")
        ],
    }


def get_album_info(artist_name, album_title):
    """Devuelve estadísticas de escucha de un álbum.

    Llama a ``album.getinfo``.

    Args:
        artist_name: nombre del artista.
        album_title: título del álbum.

    Returns:
        dict con las claves ``listeners`` y ``playcount`` (ints), o ``{}`` si
        la API no devuelve datos o responde un error amable.
    """
    data = _request("album.getinfo", {"artist": artist_name, "album": album_title})
    if data is None:
        return {}
    album = data.get("album") or {}
    return {
        "listeners": _to_int(album.get("listeners")),
        "playcount": _to_int(album.get("playcount")),
    }