"""Cliente para la API de Discogs (https://www.discogs.com/developers/).

Expone la búsqueda de releases y el detalle de un release (géneros/estilos),
respetando el rate limit de 60 requests/minuto con un throttle simple.
"""
import logging
import threading
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.discogs.com"

# Discogs autenticado permite 60 requests/minuto; usamos un intervalo un poco
# mayor para quedar cómodamente por debajo del límite (~57 req/min).
RATE_LIMIT_INTERVAL = 1.05  # segundos entre llamadas

# Timeout duro para que una API colgada nunca bloquee un request para siempre.
REQUEST_TIMEOUT = 15

# User-Agent requerido por la política de uso de la API de Discogs.
USER_AGENT = "Soundgraph/1.0"


class DiscogsError(Exception):
    """Se lanza cuando la API de Discogs responde con un error inesperado."""
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


_discogs_throttle = _RateLimiter(RATE_LIMIT_INTERVAL)


def _auth_headers():
    """Headers de autenticación y user-agent para toda llamada a Discogs."""
    return {
        "Authorization": f"Discogs token={settings.DISCOGS_TOKEN}",
        "User-Agent": USER_AGENT,
    }


def _request(url, params):
    """GET a la API respetando el throttle.

    Devuelve el JSON parseado, o ``None`` si la API responde 404. Los errores
    de conexión o cualquier otro status HTTP no esperado lanzan ``DiscogsError``.
    """
    _discogs_throttle.wait()
    try:
        response = requests.get(
            url, params=params, headers=_auth_headers(), timeout=REQUEST_TIMEOUT
        )
    except requests.RequestException as exc:
        logger.warning("Discogs request failed for %s: %s", url, exc)
        raise DiscogsError(f"request failed for {url}: {exc}") from exc

    if response.status_code == requests.codes.not_found:
        logger.info("Discogs returned 404 for %s", url)
        return None

    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Discogs returned status %s for %s", response.status_code, url)
        raise DiscogsError(f"unexpected status {response.status_code} for {url}") from exc

    try:
        return response.json()
    except ValueError as exc:
        logger.warning("Discogs returned invalid JSON for %s", url)
        raise DiscogsError(f"invalid JSON for {url}") from exc


def search_release(artist_name, album_title):
    """Busca un release en ``/database/search`` y devuelve el id del primer resultado.

    Args:
        artist_name: nombre del artista.
        album_title: título del álbum.

    Returns:
        int con el ``release_id`` del primer resultado, o ``None`` si la API
        devuelve 404 o no hay resultados (loggeando el evento sin excepción).
    """
    params = {
        "artist": artist_name,
        "release_title": album_title,
        "type": "release",
        "per_page": 1,
    }
    data = _request(f"{BASE_URL}/database/search", params=params)
    if data is None:
        return None

    results = data.get("results") or []
    if not results:
        logger.info("Discogs search found no results for %s - %s", artist_name, album_title)
        return None

    release_id = results[0].get("id")
    logger.info("Discogs search matched release id %s for %s - %s", release_id, artist_name, album_title)
    return release_id


def get_release_detail(release_id):
    """Obtiene el detalle de un release en ``/releases/{id}``.

    Args:
        release_id: id numérico del release en Discogs.

    Returns:
        dict con las claves ``genres`` y ``styles`` (listas de strings), o
        ``None`` si la API devuelve 404 o el release no existe.
    """
    data = _request(f"{BASE_URL}/releases/{release_id}", params={})
    if data is None:
        return None

    return {
        "genres": data.get("genres") or [],
        "styles": data.get("styles") or [],
    }