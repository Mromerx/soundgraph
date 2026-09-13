"""Capa de "cache-first" para los datos de álbumes.

``get_or_fetch_album`` es la ÚNICA puerta de entrada que el resto del sistema
debe usar para obtener datos de álbumes: primero consulta la base de datos y
solo si el registro no existe o expiró llama al cliente de Last.fm. Los álbumes
llevan únicamente datos de Last.fm (tags, listeners y playcount).
"""
import logging
from datetime import timedelta

from django.utils import timezone

from catalog.models import Album, Artist

from . import lastfm_client

logger = logging.getLogger(__name__)


def _build_tag_document(tags):
    """Arma el documento de texto plano que alimenta el vector TF-IDF.

    Une en un único string en minúsculas los nombres de los tags de Last.fm.
    """
    parts = [tag["name"] for tag in tags if tag.get("name")]
    return " ".join(parts).lower()


def cached_similar_artists(artist_name, limit=6, ttl_days=30):
    """Devuelve los artistas similares a ``artist_name``, cacheados por artista.

    Vuelca la lista en ``Artist.similar_artists`` para no llamar a Last.fm en
    cada request. Respeta el mismo esquema cache-first de get_or_fetch_album.
    """
    artist, _ = Artist.objects.get_or_create(name=artist_name)
    cutoff = timezone.now() - timedelta(days=ttl_days)
    if artist.similar_artists and artist.cached_at >= cutoff:
        return artist.similar_artists

    artists = lastfm_client.get_similar_artists(artist_name, limit=limit)
    artist.similar_artists = artists
    artist.save(update_fields=["similar_artists", "cached_at"])
    logger.info("Cached %s similar artists for %s", len(artists), artist_name)
    return artists


def cached_top_albums(artist_name, limit=2, ttl_days=30):
    """Devuelve los álbumes más populares de un artista, cacheados por artista.

    Almacena la lista como ``[{"title": ..., "artist": ...}, ...]`` en
    ``Artist.top_albums``.
    """
    artist, _ = Artist.objects.get_or_create(name=artist_name)
    cutoff = timezone.now() - timedelta(days=ttl_days)
    if artist.top_albums and artist.cached_at >= cutoff:
        return artist.top_albums

    albums = [
        {"title": title, "artist": artist_name}
        for title, artist_name in lastfm_client.get_top_albums(artist_name, limit=limit)
    ]
    artist.top_albums = albums
    artist.save(update_fields=["top_albums", "cached_at"])
    logger.info("Cached %s top albums for %s", len(albums), artist_name)
    return albums


def get_or_fetch_album(artist_name, album_title, ttl_days=60):
    """Obtiene un álbum sin llamar a la API si el caché está fresco.

    Estrategia cache-first:

    1. Busca ``Album`` por ``artist__name`` y ``title``.
    2. Si existe y ``cached_at`` es más reciente que ``ttl_days`` atrás, lo
       devuelve tal cual (sin tocar las APIs).
    3. Si no existe o expiró, llama a Last.fm (tags, listeners/playcount vía
       ``album.getinfo``), arma el ``tag_document`` y hace ``update_or_create``
       (creando el ``Artist`` con ``get_or_create`` si falta).
    4. Devuelve el ``Album`` actualizado.

    Args:
        artist_name: nombre del artista.
        album_title: título del álbum.
        ttl_days: días de validez del caché antes de refetch (default 60).

    Returns:
        El objeto ``Album`` correspondiente, fresco o recién actualizado.
    """
    try:
        album = Album.objects.select_related("artist").get(
            artist__name=artist_name, title=album_title
        )
    except Album.DoesNotExist:
        album = None

    cutoff = timezone.now() - timedelta(days=ttl_days)
    if (
        album is not None
        and album.cached_at >= cutoff
        and album.tag_document
    ):
        return album

    info = lastfm_client.get_album_full_info(artist_name, album_title)
    tags = info.get("tags") or []

    artist, _ = Artist.objects.get_or_create(name=artist_name)
    album, _ = Album.objects.update_or_create(
        artist=artist,
        title=album_title,
        defaults={
            "tags": tags,
            "listeners": info.get("listeners", 0),
            "playcount": info.get("playcount", 0),
            "tag_document": _build_tag_document(tags),
        },
    )
    logger.info("Fetched and cached album %s - %s", artist_name, album_title)
    return album