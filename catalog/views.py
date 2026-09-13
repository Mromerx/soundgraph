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
- ``ConnectionSearchStatusView``: ``GET /api/connections/{search_id}/`` reporta
  el progreso del BFS y, con ``PATCH`` de la misma URL, pausa/reanuda/detiene
  la búsqueda (``{"action": "pause" | "resume" | "stop"}``).
"""
from concurrent.futures import ThreadPoolExecutor
import logging

from django.core.cache import cache as django_cache
from django.http import Http404, HttpResponse, StreamingHttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Artist, ConnectionSearch

from .serializers import (
    AlbumSearchSerializer,
    ArtistSearchSerializer,
    AtypicalAlbumSerializer,
    ConnectionSearchControlSerializer,
    ConnectionSearchRequestSerializer,
    RecommendationsRequestSerializer,
)
from .services import background, cache, connection_search, events, similarity, lastfm_client
from .services.connection_search import (
    build_status_payload,
    publish_search_state,
    save_with_revision,
    set_search_paused,
    set_search_stopped,
)
from .services.lastfm_client import LastFMError

logger = logging.getLogger(__name__)


def _connection_status_payload(search, full=False):
    """Arma el payload de estado de una búsqueda, compacto o completo.

    Compartido por ``GET`` y ``PATCH`` de ``/api/connections/{search_id}/``
    para que el frontend siempre reciba la misma forma de respuesta.
    """
    payload = {
        "search_id": str(search.id),
        "status": search.status,
        "current_depth": search.current_depth,
        "max_depth": search.max_depth,
        "bridge_artist": search.bridge_artist,
        "seed_artists": search.seed_artists,
        **build_status_payload(search, full=full),
    }
    if search.status == "found":
        payload["path"] = connection_search.reconstruct_path(search, search.bridge_artist)
    elif search.status == "failed":
        payload["error_message"] = search.error_message
    return payload


def _status_etag(search):
    return f'"{search.id}-{search.payload_revision}"'


def _cached_status_payload(search_id, etag, full):
    """Payload de status cacheado por revisión, o ``None`` si aún no está.

    La revisión cambia solo cuando se persiste estado (nivel terminado, found,
    pause, etc.), así que dentro del mismo estado el poll de respaldo no vuelve
    a reconstruir el payload (~174KB) ni a releer el JSON completo de la fila.
    """
    return django_cache.get(f"csearch:status:{search_id}:{'full' if full else 'compact'}:{etag}")


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

        Todos los álbumes usan SOLO Last.fm. Un fallo en
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
    """Reporta el estado de una búsqueda de artista puente y la controla.

    ``GET /api/connections/{search_id}/`` expone el progreso del BFS en tiempo
    real (``status``, ``current_depth``, ``max_depth``); si terminó con
    ``status="found"`` incluye además el path reconstruido entre semillas, y si
    falló, el ``error_message``.

    ``PATCH /api/connections/{search_id}/`` con ``{"action": ...}`` pausa
    (``pause``), reanuda (``resume``) o detiene (``stop``) la búsqueda. La
    pausa/detención se persiste en el ``status`` de la fila (``paused`` /
    ``stopped``) y, si la búsqueda corre en este proceso, se notifica al hilo en
    memoria para que corte la expansión en el siguiente artista de la frontera.

    Por defecto el payload viene compacto (muestras acotadas del grafo). Con
    ``?graph=full`` se devuelve el grafo explorado completo
    (``visited_per_seed``/``came_from`` sin recortar), para que el frontend
    pueda visualizar toda la exploración que llevó al puente.
    """

    FINAL_STATUSES = ["found", "exhausted", "failed", "stopped"]

    # TTL del payload cacheado por revisión. Mientras la búsqueda esté quieta
    # (paused, found, exhausted) todos los polls dan al mismo payload; un TTL
    # largo alcanza con creces porque la revisión cambia con cada estado nuevo.
    STATUS_PAYLOAD_CACHE_TTL_SECONDS = 3600

    def get(self, request, search_id):
        # Expira zombis antes de leer: si se pide el estado de una búsqueda a
        # la que nunca llegó un "estado final" (hilo muerto por reinicio), que
        # el recurso devuelva su cierre en vez de un running eterno.
        from .services.connection_search import expire_stale_searches

        expire_stale_searches()

        # Lectura liviana de la revisión: la mayoría de las consultas dentro
        # del mismo estado terminan acá en 304 sin cargar el JSON gigante.
        row = ConnectionSearch.objects.filter(pk=search_id).values(
            "payload_revision", "status"
        ).first()
        if row is None:
            raise Http404("Búsqueda no encontrada.")

        etag = f'"{search_id}-{row["payload_revision"]}"'
        if request.headers.get("If-None-Match") == etag:
            return HttpResponse(status=304)

        full_graph = request.query_params.get("graph") == "full"

        payload = _cached_status_payload(search_id, etag, full_graph)
        if payload is None:
            search = ConnectionSearch.objects.get(pk=search_id)
            payload = _connection_status_payload(search, full=full_graph)
            django_cache.set(
                f"csearch:status:{search_id}:{'full' if full_graph else 'compact'}:{etag}",
                payload,
                timeout=self.STATUS_PAYLOAD_CACHE_TTL_SECONDS,
            )

        response = Response(payload)
        response["ETag"] = etag
        return response

    def patch(self, request, search_id):
        serializer = ConnectionSearchControlSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        from .services.connection_search import expire_stale_searches

        expire_stale_searches()

        try:
            search = ConnectionSearch.objects.get(pk=search_id)
        except ConnectionSearch.DoesNotExist:
            raise Http404("Búsqueda no encontrada.")

        if search.status in self.FINAL_STATUSES:
            return Response(
                {
                    "detail": (
                        f"No se puede controlar una búsqueda {search.status}."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        action = serializer.validated_data["action"]

        if action == "pause":
            if search.status == "paused":
                return Response(
                    {"detail": "La búsqueda ya está pausada."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            search.status = "paused"
            save_with_revision(search)
            publish_search_state(search)
            handled = set_search_paused(search_id, True)
        elif action == "resume":
            if search.status != "paused":
                return Response(
                    {
                        "detail": (
                            "Solo se puede reanudar una búsqueda pausada "
                            f"(estado actual: {search.status})."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            search.status = "running"
            save_with_revision(search)
            publish_search_state(search)
            handled = set_search_paused(search_id, False)
        else:  # stop
            search.status = "stopped"
            search.stopped_reason = "user_stop"
            save_with_revision(search)
            publish_search_state(search)
            handled = set_search_stopped(search_id)

        logger.info(
            "Acción '%s' aplicada a la búsqueda %s (control en este proceso: %s).",
            action,
            search_id,
            "sí" if handled else "no (se verá al releer la base)",
        )
        return Response(_connection_status_payload(search))


class ConnectionSearchEventsView(APIView):
    """Stream SSE del estado de una búsqueda de conexión.

    ``GET /api/connections/{search_id}/events`` abre un ``text/event-stream``
    que emite un evento ``data: {payload}`` cada vez que el hilo de la búsqueda
    publica un cambio al bus en memoria (fin de nivel, pausa, resume, stop o
    estado final). Al llegar un estado final el stream se cierra solo.

    El bus vive en el proceso, así que con ``runserver`` es exactamente el hilo
    real del BFS el que publica (conexión -> grafo "al instante"). Para el caso
    en que el stream se caiga o el cambio ocurra en otro proceso, el frontend
    mantiene el poll con ETag/304 como respaldo.
    """

    FINAL_STATUSES = ["found", "exhausted", "failed", "stopped"]
    PING_INTERVAL_SECONDS = 15

    def get(self, request, search_id):
        from .services.connection_search import expire_stale_searches
        import queue

        expire_stale_searches()

        search = ConnectionSearch.objects.filter(pk=search_id).first()
        if search is None:
            raise Http404("Búsqueda no encontrada.")

        subscriber = events.subscribe_search_events(search_id)
        final_statuses = self.FINAL_STATUSES

        def event_stream():
            try:
                # Estado al momento de conectarse: se calcula desde la base
                # (fuente de verdad) en vez de fiarse de eventos encolados que
                # podrían quedar obsoletos por la carrera suscripción/lectura.
                current = ConnectionSearch.objects.get(pk=search_id)
                yield _sse_event(connection_search.status_event(current))
                if current.status in final_statuses:
                    return

                while True:
                    try:
                        payload = subscriber.get(timeout=self.PING_INTERVAL_SECONDS)
                    except queue.Empty:
                        # Rechequeo anti-carrera: si el estado final se guardó
                        # sin que llegara el evento (proceso distinto, bug),
                        # que el stream igual cierre y avise.
                        row = ConnectionSearch.objects.filter(pk=search_id).values(
                            "status"
                        ).first()
                        if row and row["status"] in final_statuses:
                            final = ConnectionSearch.objects.get(pk=search_id)
                            yield _sse_event(connection_search.status_event(final))
                            return
                        yield ": keep-alive\n\n"
                        continue

                    yield _sse_event(payload)
                    if payload.get("status") in final_statuses:
                        return
            except ConnectionSearch.DoesNotExist:
                pass
            finally:
                events.unsubscribe_search_events(search_id, subscriber)

        return StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
        )


def _sse_event(payload):
    """Formatea un payload como un evento SSE ``data: json``."""
    import json

    return f"data: {json.dumps(payload)}\n\n"