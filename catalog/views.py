"""Endpoints REST del sistema de recomendación.

- ``RecommendationsView``: ``POST /api/recommendations/`` arma la lista de
  candidatos a partir de los artistas similares de cada semilla, puntúa con
  ``recommend`` y devuelve las recomendaciones en JSON plano.
- ``ArtistSearchView``: ``GET /api/search/artists/?q=`` busca artistas en
  Last.fm para el autocomplete del frontend.
- ``ArtistAlbumsView``: ``GET /api/search/albums/?artist=`` lista los álbumes
  más populares del artista elegido.
- ``AtypicalAlbumsView``: ``GET /api/artists/{id}/atypical-albums/`` detecta qué
  álbumes de un artista se desvían más de su centroide sonoro.
"""
from concurrent.futures import ThreadPoolExecutor

from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Artist, ConnectionSearch

from .serializers import (
    AlbumSearchSerializer,
    ArtistSearchSerializer,
    AtypicalAlbumSerializer,
    ConnectionSearchRequestSerializer,
    RecommendationsRequestSerializer,
)
from .services import background, cache, similarity, lastfm_client
from .services.lastfm_client import LastFMError


class RecommendationsView(APIView):
    """Recomienda álbumes usando el grafo de similitud."""

    def post(self, request):
        serializer = RecommendationsRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        payload = serializer.validated_data
        seeds = payload["seeds"]
        n_results = payload["n_results"]

        try:
            seed_albums, candidate_albums = self._fetch_seed_and_candidates(seeds)
            recommendations = similarity.recommend(
                seed_albums, candidate_albums, n_results=n_results
            )
        except LastFMError as exc:
            return Response(
                {"detail": f"No se pudieron obtener los datos de la API: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        response = [
            {
                "artist": item["album"].artist.name,
                "album": item["album"].title,
                "score": round(item["score"] * 100),
                "matched_seed": {
                    "artist": item["matched_seed"].artist.name,
                    "album": item["matched_seed"].title,
                },
                "matched_seeds": [
                    {
                        "artist": connected["album"].artist.name,
                        "album": connected["album"].title,
                        "score": round(connected["score"] * 100),
                    }
                    for connected in item["matched_seeds"]
                ],
            }
            for item in recommendations
        ]
        return Response(response)

    @staticmethod
    def _build_candidate_jobs(seeds, similar_limit=6, albums_per_artist=2):
        """Arma la lista de trabajos (artista, título) de álbumes candidatos.

        Por cada semilla consulta artistas similares cacheados
        (``cached_similar_artists``, limit 6) y, por cada artista similar, sus
        top álbumes cacheados (``cached_top_albums``, limit 2).
        """
        jobs = []
        seen = set()

        for seed in seeds:
            try:
                similar_artists = cache.cached_similar_artists(
                    seed["artist"], limit=similar_limit
                )
            except LastFMError:
                continue

            for similar_artist in similar_artists:
                try:
                    top_albums = cache.cached_top_albums(
                        similar_artist, limit=albums_per_artist
                    )
                except LastFMError:
                    continue

                for album in top_albums:
                    key = (album["artist"], album["title"])
                    if key in seen:
                        continue
                    seen.add(key)
                    jobs.append(key)

        return jobs

    @classmethod
    def _fetch_seed_and_candidates(cls, seeds):
        """Enriquece semillas y candidatos en paralelo en un único pool.

        Todos los álbumes usan SOLO Last.fm (Discogs desactivado). Un fallo en
        una semilla se propaga como ``LastFMError``; un candidato que falle se
        descarta.

        Returns:
            Tupla ``(seed_albums, candidate_albums)`` de objetos ``Album``.
        """
        candidate_jobs = cls._build_candidate_jobs(seeds)
        seed_keys = {(seed["artist"], seed["album"]) for seed in seeds}
        candidate_jobs = [job for job in candidate_jobs if job not in seed_keys]
        jobs = [(seed["artist"], seed["album"]) for seed in seeds] + candidate_jobs

        def fetch(job):
            artist, title = job
            is_seed = (artist, title) in seed_keys
            try:
                return cache.get_or_fetch_album(artist, title)
            except LastFMError as exc:
                if is_seed:
                    raise exc
                return None

        with ThreadPoolExecutor(max_workers=8) as executor:
            fetched = list(executor.map(fetch, jobs))

        n_seeds = len(seeds)
        seed_albums = fetched[:n_seeds]
        candidate_albums = [a for a in fetched[n_seeds:] if a is not None]
        return seed_albums, candidate_albums


class ArtistSearchView(APIView):
    """Busca artistas en Last.fm para el autocomplete del frontend.

    ``GET /api/search/artists/?q=...`` devuelve ``{"results": [...]}`` con los
    artistas encontrados (nombre, MBID y listeners).
    """

    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if not query:
            return Response(
                {"detail": "El parámetro 'q' es obligatorio."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            artists = lastfm_client.search_artists(query)
        except LastFMError as exc:
            return Response(
                {"detail": f"No se pudieron obtener los datos de la API: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"results": ArtistSearchSerializer(artists, many=True).data})


class ArtistAlbumsView(APIView):
    """Lista los álbumes más populares de un artista en Last.fm.

    ``GET /api/search/albums/?artist=...`` devuelve ``{"results": [...]}``.
    """

    def get(self, request):
        artist = request.query_params.get("artist", "").strip()
        if not artist:
            return Response(
                {"detail": "El parámetro 'artist' es obligatorio."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            albums = lastfm_client.get_artist_albums(artist)
        except LastFMError as exc:
            return Response(
                {"detail": f"No se pudieron obtener los datos de la API: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"results": AlbumSearchSerializer(albums, many=True).data})


class AtypicalAlbumsView(APIView):
    """Lista los álbumes de un artista ordenados por su atipicalidad."""

    def get(self, request, artist_id):
        try:
            artist = Artist.objects.get(pk=artist_id)
        except Artist.DoesNotExist:
            raise Http404("Artista no encontrado.")

        try:
            centroid, vectorizer = similarity.compute_artist_centroid(artist)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        rows = []
        for album in artist.albums.all():
            _, distance = similarity.is_atypical_album(album, centroid, vectorizer)
            rows.append(
                {
                    "artist": artist.name,
                    "album": album.title,
                    "distance": round(distance, 3),
                }
            )

        rows.sort(key=lambda row: row["distance"], reverse=True)
        return Response(AtypicalAlbumSerializer(rows, many=True).data)


class ConnectionSearchCreateView(APIView):
    """Dispara una búsqueda de artista puente en background.

    ``POST /api/connections/`` con ``{"seed_artists": ["A", "B"]}`` crea un
    ``ConnectionSearch`` (2-5 artistas) y corre el BFS multi-fuente en un
    thread daemon. Devuelve el ``search_id`` para luego consultar el progreso
    con ``GET /api/connections/{search_id}/``.
    """

    def post(self, request):
        serializer = ConnectionSearchRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            search = background.launch_search(serializer.validated_data["seed_artists"])
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"search_id": str(search.id), "status": search.status},
            status=status.HTTP_202_ACCEPTED,
        )


class ConnectionSearchStatusView(APIView):
    """Reporta el estado de una búsqueda de artista puente.

    ``GET /api/connections/{search_id}/`` expone el progreso del BFS en tiempo
    real (``status``, ``current_depth``, ``max_depth``); si terminó con
    ``status="found"`` incluye además el path reconstruido entre semillas, y si
    falló, el ``error_message``.
    """

    def get(self, request, search_id):
        try:
            search = ConnectionSearch.objects.get(pk=search_id)
        except ConnectionSearch.DoesNotExist:
            raise Http404("Búsqueda no encontrada.")

        payload = {
            "status": search.status,
            "current_depth": search.current_depth,
            "max_depth": search.max_depth,
            "bridge_artist": search.bridge_artist,
            "seed_artists": search.seed_artists,
            "visited_per_seed": search.visited_per_seed,
            "frontier_per_seed": search.frontier_per_seed,
            "came_from": search.came_from,
        }
        if search.status == "found":
            from .services.connection_search import reconstruct_path

            payload["path"] = reconstruct_path(search, search.bridge_artist)
        elif search.status == "failed":
            payload["error_message"] = search.error_message

        return Response(payload)