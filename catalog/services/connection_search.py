"""Búsqueda BFS multi-fuente de un artista puente entre artistas semilla.

Explora el grafo de afinidad de Last.fm nivel por nivel: cada semilla mantiene
su propia frontera de expansión y su conjunto de visitados; el objetivo es
encontrar un artista que aparezca en TODOS los conjuntos de visitados a la
vez (intersección). Una vez hallado, se reconstruye el camino desde cada
semilla hasta el puente usando ``came_from``.

**Acotado en memoria**: el grafo de artistas similares de Last.fm crece
exponencialmente (~10x por nivel), y artistas muy populares explotan la
frontera. Para que el proceso nunca se quede sin RAM, la expansión respeta un
``node_limit`` (nodos totales descubiertos entre todas las semillas). Al
alcanzarlo la búsqueda se detiene limpio con ``status="exhausted"`` y
``stopped_reason="node_limit"`` en lugar de colapsar el servidor.

**Anti-zombi**: el BFS corre en un hilo daemon del proceso Django. Si el
proceso se cae a mitad de corrida, el hilo muere sin poder marcar su estado
final y la fila quedaría ``running`` para siempre, bloqueando nuevas
búsquedas (el guard de concurrencia la contaría como "en curso"). Para que eso
no pueda pasar, mientras trabaja emite un heartbeat (toca ``updated_at`` cada
``HEARTBEAT_INTERVAL_SECONDS``) y cualquier ``pending/running`` sin actividad
por más de ``SOUNDGRAPH_STALE_SEARCH_SECONDS`` se considera zombi y se expira
con ``expire_stale_searches()`` desde los puntos de entrada (POST/GET) y al
arrancar Django.

Las funciones ``expand_one_level``, ``find_intersection`` y
``reconstruct_path`` son puras: mutan/asumen el objeto ``ConnectionSearch`` en
memoria y NO tocan la base de datos. La persistencia la decide el llamador;
``run_full_search`` es la única que orquesta la corrida completa persistiendo
nivel a nivel.
"""
import logging
import threading
import time
from datetime import timedelta

from django.conf import settings as django_settings
from django.utils import timezone

from catalog.models import ConnectionSearch
from catalog.services.lastfm_client import get_similar_artists

logger = logging.getLogger(__name__)

# Período del bucle de espera mientras una búsqueda está pausada. Al
# reanudar/detener desde el frontend la latencia máxima es de ~1 segundo.
PAUSE_POLL_INTERVAL_SECONDS = 1

# Máximos de nodos vecinos pedidos a Last.fm por artista de la frontera.
SIMILAR_LIMIT = 10

# Tope de nombres devueltos por el endpoint de status. El frontend nunca
# renderiza más de MAX_CONNECTION_NODES, así que devolver el grafo completo
# solo infla la RAM del backend y del browser.
STATUS_VISITED_SAMPLE = 1200
STATUS_FRONTIER_SAMPLE = 800

# Intervalo del heartbeat que mantiene vivo el ``updated_at`` de una búsqueda
# mientras expande un nivel (entre guards la fila ya se toca con ``save``).
# Un nivel con frontera grande tarda minutos en API; sin heartbeat caería en
# el corte de "sin actividad" y se expiraría una búsqueda LEGÍTIMA.
HEARTBEAT_INTERVAL_SECONDS = 10


class _PauseInterrupt(Exception):
    """El heartbeat detectó una pausa y debe interrumpir la expansión."""


class _StopInterrupt(Exception):
    """El heartbeat detectó una detención y debe interrumpir la expansión."""


# Control pausar/reanudar/detener de las búsquedas en curso.
#
# ``run_full_search`` registra su ``search_id`` en ``_controls`` mientras corre
# en este proceso y lo desregistra en el ``finally``. El heartbeat (que corre
# dentro del hilo real de la búsqueda) consulta este registro en cada artista
# de la frontera: regresar el control es un dict lookup + ``Event.is_set()``,
# sin tocar la base. Para el caso multi-proceso (powerless en este proyecto,
# pero el estado en la base es la fuente de verdad), el heartbeat también relee
# el ``status`` de la fila con cada latido cuando el registro no existe en el
# proceso.
_controls = {}
_controls_lock = threading.Lock()


def _control_for(search_id):
    with _controls_lock:
        return _controls.get(search_id)


def register_search_control(search_id):
    """Registra el control en memoria para una búsqueda que arranca aquí.

    El evento nace ``set()`` (significa "no pausada"): ``threading.Event()``
    por defecto queda cleared, y ``_check_control`` interpretaría "pausada"
    durante la primera expansión.
    """
    with _controls_lock:
        paused_event = threading.Event()
        paused_event.set()
        _controls[search_id] = {
            "paused_event": paused_event,
            "stop_requested": False,
        }


def unregister_search_control(search_id):
    with _controls_lock:
        _controls.pop(search_id, None)


def set_search_paused(search_id, paused):
    """Pausa o reanuda la búsqueda si corre en este proceso.

    Returns:
        ``True`` si la búsqueda está registrada en este proceso (el control es
        inmediato); ``False`` si vive en otro proceso y solo se verá cuando el
        hilo relea el ``status`` de la base.
    """
    with _controls_lock:
        ctrl = _controls.get(search_id)
        if ctrl is None:
            return False
        if paused:
            ctrl["paused_event"].clear()
        else:
            ctrl["paused_event"].set()
        return True


def set_search_stopped(search_id):
    """Solicita la detención de la búsqueda si corre en este proceso.

    Además de marcar la flag, ``set()`` desbloquea el bucle de espera por si la
    búsqueda estaba pausada (así la detención es inmediata en ambos estados).

    Returns:
        ``True`` si la búsqueda está registrada en este proceso.
    """
    with _controls_lock:
        ctrl = _controls.get(search_id)
        if ctrl is None:
            return False
        ctrl["stop_requested"] = True
        ctrl["paused_event"].set()
        return True


def _db_status(search_id):
    return ConnectionSearch.objects.filter(pk=search_id).values_list("status", flat=True).first()


def _check_control(search, force_db=False):
    """Lanza la interrupción que corresponda si la búsqueda fue pausada/detenida.

    Primero mira el registro en memoria (mismo proceso, rápido); con
    ``force_db`` (o sin registro en este proceso) relee el ``status`` desde la
    base como fuente de verdad, cubriendo el caso en que otra instancia del
    servidor cambió el estado.

    Args:
        search: ``ConnectionSearch`` cargado en memoria.
        force_db: si ``True`` ignora el registro en memoria.

    Raises:
        _PauseInterrupt: la búsqueda está pausada.
        _StopInterrupt: la búsqueda fue detenida.
    """
    ctrl = None if force_db else _control_for(search.id)
    if ctrl is not None:
        if ctrl["stop_requested"]:
            raise _StopInterrupt()
        if not ctrl["paused_event"].is_set():
            raise _PauseInterrupt()
        return
    status = _db_status(search.id)
    if status == "stopped":
        raise _StopInterrupt()
    if status == "paused":
        raise _PauseInterrupt()


def _wait_while_paused(search_id, refresh_timestamp):
    """Bloquea mientras la búsqueda quede pausada, refrescando el heartbeat.

    ``refresh_timestamp`` (callback) mantiene ``updated_at`` al día para que la
    expiración anti-zombi no mate una pausa legítima; NO chequea el control de
    pausa (esa decisión ya se tomó: estamos dentro de la pausa).

    Args:
        search_id: id de la búsqueda pausada.
        refresh_timestamp: callback que solo refresca el timestamp del latido.

    Returns:
        ``"running"`` si la búsqueda fue reanudada, ``"stopped"`` si el
        usuario la detuvo mientras estaba pausada.
    """
    ctrl = _control_for(search_id)
    if ctrl is None:
        # Defensa multi-proceso: el thread siempre se registra en el proceso
        # donde corre, así que esto solo aplicaría a un escenario híbrido.
        while True:
            refresh_timestamp()
            time.sleep(PAUSE_POLL_INTERVAL_SECONDS)
            status = _db_status(search_id)
            if status != "paused":
                return "stopped" if status == "stopped" else "running"

    while not ctrl["paused_event"].is_set():
        refresh_timestamp()
        time.sleep(PAUSE_POLL_INTERVAL_SECONDS)
        if ctrl["stop_requested"]:
            return "stopped"
    return "running"


def _visited_set_for(search, seed):
    """Devuelve el ``set`` de visitados de la semilla, cacheados en el objeto.

    El set se usa para deduplicar en O(1). Se cachea en un atributo de solo
    memoria del objeto porque ``expand_one_level``/``find_intersection`` mutan
    el mismo objeto a lo largo de la corrida sin recargarlo de la base.
    """
    cache = getattr(search, "_visited_sets", None)
    if cache is None:
        cache = {}
        search._visited_sets = cache
    visited_set = cache.get(seed)
    if visited_set is None:
        visited_set = set(search.visited_per_seed.get(seed, []))
        cache[seed] = visited_set
    return visited_set


def _similar_cache_for(search, artist, limit):
    """Devuelve los similares de ``artist`` consultándolos UNA sola vez.

    El mismo artista aparece muchas veces en el grafo (fronteras de distintas
    semillas, niveles sucesivos). Sin memoria intermedia, cada aparición
    contaría una llamada a Last.fm, abusando del límite de la API. El caché
    vive en memoria durante la corrida y está acotado por ``node_limit``.
    """
    cache = getattr(search, "_similar_cache", {})
    neighbors = cache.get(artist)
    if neighbors is None:
        neighbors = get_similar_artists(artist, limit=limit)
        cache[artist] = neighbors
        search._similar_cache = cache
    return neighbors


def expand_one_level(search, on_progress=None):
    """Expande un nivel de BFS para todas las semillas, con tope de nodos.

    Por cada semilla toma su frontera actual, consulta los similares de cada
    artista de esa frontera en Last.fm (``get_similar_artists`` respeta su
    propio throttle), agrega a ``visited_per_seed[semilla]`` los nombres que
    aún no estuvieran visitados y registra en ``came_from`` quién trajo a cada
    uno (sin pisar un padre ya registrado por otra semilla). La frontera de la
    semilla pasa a ser exactamente los artistas recién descubiertos.

    Si la semilla no tiene frontera previa (primer nivel), se usa la semilla
    misma como punto de partida.

    Cuando ``search.total_discovered`` alcanza ``search.node_limit``, la
    expansión se detiene inmediatamente y se marca ``search.over_limit``
    (atributo de solo memoria) para que el llamador cierre la búsqueda.

    Args:
        search: ``ConnectionSearch`` cargado en memoria.
        on_progress: callback opcional invocado después de procesar cada
            artista de la frontera. Sirve de heartbeat: ``run_full_search``
            lo usa para refrescar ``updated_at`` mientras un nivel largo
            consume los minutos del throttle de Last.fm.

    Returns:
        El mismo objeto ``search`` con los conjuntos de visitados, fronteras y
        ``came_from`` actualizados. No lo guarda en la base.
    """
    if getattr(search, "over_limit", False):
        return search

    # Las semillas son raíces del came_from: nunca pueden tener padre (una
    # semilla descubierta por otra semilla como "similar" crearía un ciclo
    # S1->S2->S1 en came_from y reconstruct_path colgaría para siempre).
    seed_set = set(search.seed_artists)

    for seed in search.seed_artists:
        if seed not in search.visited_per_seed:
            search.visited_per_seed[seed] = [seed]
        if seed not in search.frontier_per_seed:
            search.frontier_per_seed[seed] = [seed]

    node_limit = search.node_limit or 0
    for seed in search.seed_artists:
        # Snapshot de la frontera: se recorre SOLO lo descubierto en el nivel
        # anterior. Si frontier_per_seed y visited_per_seed compartieran el
        # mismo objeto de lista, iterar la frontera mientras se agregan
        # visitados convertiría el nivel en un flood del grafo entero.
        frontier = list(search.frontier_per_seed[seed])
        visited = search.visited_per_seed[seed]
        visited_set = _visited_set_for(search, seed)
        new_artists = []

        for artist in frontier:
            for similar in _similar_cache_for(search, artist, SIMILAR_LIMIT):
                if similar in visited_set:
                    continue
                if node_limit and search.total_discovered >= node_limit:
                    search.over_limit = True
                    search.frontier_per_seed[seed] = new_artists
                    return search

                visited_set.add(similar)
                visited.append(similar)
                search.total_discovered += 1
                new_artists.append(similar)
                if similar not in search.came_from and similar not in seed_set:
                    search.came_from[similar] = artist
            if on_progress is not None:
                on_progress()

        search.frontier_per_seed[seed] = new_artists

    return search


def find_intersection(search):
    """Devuelve un artista presente en TODOS los conjuntos de visitados.

    Args:
        search: ``ConnectionSearch`` con ``visited_per_seed`` poblado.

    Returns:
        El primer artista en orden alfabético que aparece en los visitados de
        todas las semillas, o ``None`` si no hay intersección.
    """
    if not search.visited_per_seed:
        return None

    # ``&`` (no ``&=``): la intersección no debe mutar los sets cacheados por
    # semilla, porque expand_one_level los usa para deduplicar.
    common = _visited_set_for(search, search.seed_artists[0])
    for seed in search.seed_artists[1:]:
        common = common & _visited_set_for(search, seed)
        if not common:
            return None

    return min(common) if common else None


def reconstruct_path(search, bridge):
    """Reconstruye el camino desde cada semilla hasta el puente.

    Usa ``came_from`` para recorrer hacia atrás desde el puente hasta la
    semilla raíz de su cadena (la primera que lo descubrió). Esa semilla
    recibe el camino completo; el resto recibe ``[semilla, puente]`` porque
    ``came_from`` solo preserva el primer hallazgo. Si el puente ES una
    semilla, su camino es ``[semilla]``.

    El recorrido está acotado por construcción: ``came_from`` se arma según el
    primer descubrimiento global y las semillas son raíces (no entran como
    claves), así que la cadena siempre termina en una semilla. Por defensa
    extra (filas viejas que quedaron en la base con datos corruptos), se corta
    el bucle al volver a una semilla o al detectar un ciclo; en ese caso se
    degrada a caminos de dos saltos para no colgar el endpoint.

    Args:
        search: ``ConnectionSearch`` con ``came_from`` poblado.
        bridge: nombre del artista puente hallado.

    Returns:
        Dict ``{semilla: [camino...]}`` con el camino de cada semilla al
        puente.
    """
    seed_set = set(search.seed_artists)

    if bridge in seed_set:
        paths = {}
        for seed in search.seed_artists:
            if seed == bridge:
                paths[seed] = [seed]
            else:
                paths[seed] = [seed, bridge]
        return paths

    chain = [bridge]
    current = bridge
    seen = {bridge}
    cyclic = False
    while current in search.came_from:
        current = search.came_from[current]
        if current in seen:
            cyclic = True
            break
        seen.add(current)
        chain.append(current)
        if current in seed_set:
            break
    chain.reverse()

    root = chain[0]
    if cyclic or root not in seed_set:
        # came_from corrupto (ciclo o cadena huérfana): no hay un camino
        # confiable. Devolver la aproximación de dos saltos para todas las
        # semillas en vez de entrar en un bucle infinito.
        return {seed: [seed, bridge] for seed in search.seed_artists}

    paths = {}
    for seed in search.seed_artists:
        if seed == bridge:
            paths[seed] = [seed]
        elif seed == root:
            paths[seed] = chain
        else:
            paths[seed] = [seed, bridge]
    return paths


def build_status_payload(search, visited_sample=STATUS_VISITED_SAMPLE, frontier_sample=STATUS_FRONTIER_SAMPLE, full=False):
    """Arma el payload del estado de una búsqueda.

    En modo compacto (default) devuelve cuentas en vez de listas completas,
    una muestra acotada de los visitados y de la frontera por semilla, y solo
    los ``came_from`` referidos a la muestra. Devolver el grafo completo
    (decenas de MB) cada segundo al frontend era una de las causas del colapso
    de RAM.

    Con ``full=True`` omite el acotado y devuelve el grafo explorado completo
    (``visited_per_seed``, ``frontier_per_seed`` y ``came_from`` sin recortar).
    Es un pedido puntual del frontend (botón "ver grafo completo"), no el poll
    periódico de 1 segundo.

    Args:
        search: ``ConnectionSearch`` cargado en memoria.
        visited_sample: tamaño máximo de la muestra de visitados por semilla.
        frontier_sample: tamaño máximo de la muestra de la frontera por semilla.
        full: si es ``True`` devuelve el grafo completo sin acotar.

    Returns:
        Dict con ``visited_per_seed``, ``frontier_per_seed``,
        ``visited_count_per_seed``, ``frontier_count_per_seed``, ``came_from``
        (acotados salvo ``full``), ``total_discovered`` y ``stopped_reason``.
    """
    keep = set()
    visited_per_seed = {}
    frontier_per_seed = {}
    visited_count_per_seed = {}
    frontier_count_per_seed = {}

    for seed in search.seed_artists:
        visited = search.visited_per_seed.get(seed, [])
        frontier = search.frontier_per_seed.get(seed, [])

        visited_count_per_seed[seed] = len(visited)
        frontier_count_per_seed[seed] = len(frontier)

        visited_sample_list = visited if full else visited[:visited_sample]
        frontier_sample_list = frontier if full else frontier[:frontier_sample]

        visited_per_seed[seed] = visited_sample_list
        frontier_per_seed[seed] = frontier_sample_list
        keep.update(visited_sample_list)
        keep.update(frontier_sample_list)

    came_from = {}
    for name in keep:
        parent = search.came_from.get(name)
        if parent:
            came_from[name] = parent

    return {
        "visited_per_seed": visited_per_seed,
        "frontier_per_seed": frontier_per_seed,
        "visited_count_per_seed": visited_count_per_seed,
        "frontier_count_per_seed": frontier_count_per_seed,
        "came_from": came_from,
        "total_discovered": search.total_discovered,
        "stopped_reason": search.stopped_reason or None,
    }


def expire_stale_searches(stale_seconds=None):
    """Expira búsquedas zombi: ``pending/running`` sin actividad reciente.

    El BFS corre en un hilo daemon. Si el proceso se cae, muere el hilo y su
    fila quedaría ``running`` para siempre (bloqueando nuevas búsquedas). Como
    mientras trabaja el hilo emite heartbeat (``updated_at`` reciente), toda
    ``pending/running`` cuyo ``updated_at`` sea anterior al corte es, por
    definición, un zombi.

    Se invoca desde los puntos de entrada (POST/GET de conexiones) y al arrancar
    Django, así una corrida muerta se detecta la primera vez que alguien
    interactúa con el backend (o al reiniciar), sin quedar clavada.

    Args:
        stale_seconds: antigüedad a partir de la cual se considera zombi.
            Default: ``settings.SOUNDGRAPH_STALE_SEARCH_SECONDS`` (60).

    Returns:
        Cantidad de búsquedas expiradas.
    """
    if stale_seconds is None:
        stale_seconds = getattr(
            django_settings, "SOUNDGRAPH_STALE_SEARCH_SECONDS", 60
        )
    cutoff = timezone.now() - timedelta(seconds=stale_seconds)
    expired = ConnectionSearch.objects.filter(
        status__in=["pending", "running", "paused"],
        updated_at__lt=cutoff,
    ).update(
        status="failed",
        error_message=(
            "Búsqueda abandonada: sin actividad por más de "
            f"{stale_seconds} segundos (el servidor puede haberse reiniciado). "
            "Volvé a lanzarla."
        ),
    )
    if expired:
        logger.warning("Se expiraron %s búsqueda(s) zombi por inactividad.", expired)
    return expired


def _retire_orphan(search_id):
    """Anti-zombi de último recurso: cierra estados nunca finalizados.

    Este ``finally`` corre en el hilo de la búsqueda. Si por cualquier causa el
    cuerpo principal devolvió sin marcar ``found``/``exhausted``/``failed``
    (excepción fuera de los ``except``, retorno inesperado), la fila quedaría
    ``running`` para siempre. Aquí se la pasa a ``failed`` para que el guard de
    concurrencia nunca quede bloqueado por un cadáver.
    """
    retired = ConnectionSearch.objects.filter(
        pk=search_id,
        status__in=["pending", "running", "paused"],
    ).update(
        status="failed",
        error_message=(
            "Búsqueda interrumpida: el hilo terminó sin reportar un estado "
            "final. Volvé a lanzarla."
        ),
    )
    if retired:
        logger.warning("Búsqueda %s retirada por hilo muerto sin estado final.", search_id)


def run_full_search(search_id, sleep_between_levels=0, heartbeat_interval=HEARTBEAT_INTERVAL_SECONDS):
    """Ejecuta la búsqueda completa de forma sincrónica.

    Expande nivel por nivel hasta encontrar un puente, agotar
    ``max_depth`` o alcanzar ``node_limit``, persistiendo el estado después de
    cada nivel. Cualquier excepción se captura y se deja registrada en el
    objeto sin propagarse.

    Mientras expande también emite un heartbeat: un nivel con frontera grande
    consume minutos en llamadas a Last.fm (throttle), y sin tocar
    ``updated_at`` periódicamente la propia expiración anti-zombi terminaría
    matando una búsqueda LEGÍTIMA. Ese mismo heartbeat es el punto de control
    de pausa: cada artista de la frontera consulta el registro en memoria
    (``_controls``) y, si el usuario pidió pausar o detener, interrumpe la
    expansión del nivel. Al pausar, la búsqueda persiste ``status="paused"`` y
    se queda esperando (con heartbeat activo); al detener persiste
    ``status="stopped"`` con ``stopped_reason="user_stop"`` y termina.

    Al final, un ``finally`` retira la fila si quedó sin estado final (nunca
    debería quedar un ``running`` solo).

    Args:
        search_id: id del ``ConnectionSearch`` a cargar.
        sleep_between_levels: pausa en segundos entre niveles (para no
            saturar la API en pruebas largas).
        heartbeat_interval: segundos entre heartbeats durante la expansión.

    Returns:
        El ``ConnectionSearch`` con su estado final:
        ``found`` (con ``bridge_artist`` set), ``exhausted``, ``failed`` o
        ``stopped`` (por pedido del usuario). Si se agotó por el tope de
        nodos, ``stopped_reason="node_limit"``; si la detuvo el usuario,
        ``stopped_reason="user_stop"``.
    """
    try:
        search = ConnectionSearch.objects.get(id=search_id)
    except Exception:
        logger.exception("No se pudo cargar la búsqueda %s para correr el BFS", search_id)
        return None

    search.status = "running"
    search.save()

    last_beat = time.monotonic()
    register_search_control(search_id)

    def refresh_timestamp():
        """Solo refresca ``updated_at`` (heartbeat acotado, sin chequeo de control)."""
        nonlocal last_beat
        now = time.monotonic()
        if now - last_beat >= heartbeat_interval:
            ConnectionSearch.objects.filter(pk=search.id).update(updated_at=timezone.now())
            last_beat = now

    def heartbeat():
        # Check en memoria primero: si el usuario pausó/detuvo, interrumpir la
        # expansión en el siguiente artista de la frontera.
        _check_control(search)
        nonlocal last_beat
        now = time.monotonic()
        if now - last_beat >= heartbeat_interval:
            # UPDATE acotado: no re-serializar JSON completo, solo el timestamp.
            ConnectionSearch.objects.filter(pk=search.id).update(updated_at=timezone.now())
            last_beat = now
            # Respaldo cross-process: otra instancia del servidor pudo cambiar
            # el estado (pausa/detención) sin tocar el registro en memoria.
            _check_control(search, force_db=True)

    try:
        while search.current_depth < search.max_depth:
            try:
                _check_control(search)
                expand_one_level(search, on_progress=heartbeat)
            except _PauseInterrupt:
                search.status = "paused"
                search.save()
                logger.info(
                    "Búsqueda %s pausada a profundidad %s (%s descubiertos).",
                    search.id,
                    search.current_depth,
                    search.total_discovered,
                )
                if _wait_while_paused(search.id, refresh_timestamp) == "stopped":
                    search.status = "stopped"
                    search.stopped_reason = "user_stop"
                    search.save()
                    logger.info(
                        "Búsqueda %s detenida por el usuario mientras estaba pausada.",
                        search.id,
                    )
                    return search
                search.status = "running"
                search.save()
                logger.info("Búsqueda %s reanudada.", search.id)
                continue
            except _StopInterrupt:
                search.status = "stopped"
                search.stopped_reason = "user_stop"
                search.save()
                logger.info("Búsqueda %s detenida por el usuario.", search.id)
                return search

            search.save()
            heartbeat()

            if getattr(search, "over_limit", False):
                search.status = "exhausted"
                search.stopped_reason = "node_limit"
                search.save()
                logger.info(
                    "Búsqueda %s detenida por tope de nodos (%s) a profundidad %s.",
                    search.id,
                    search.total_discovered,
                    search.current_depth,
                )
                return search

            bridge = find_intersection(search)
            if bridge:
                search.bridge_artist = bridge
                search.status = "found"
                search.save()
                logger.info("Puente encontrado en profundidad %s: %s", search.current_depth + 1, bridge)
                return search

            search.current_depth += 1
            search.save()

            if sleep_between_levels:
                time.sleep(sleep_between_levels)

        search.status = "exhausted"
        search.stopped_reason = ""
        search.save()
        logger.info(
            "Búsqueda agotada tras %s niveles sin encontrar intersección.",
            search.max_depth,
        )
        return search

    except MemoryError:
        search.status = "failed"
        search.error_message = (
            "La búsqueda se detuvo por falta de memoria (límite del proceso). "
            "Reducí la cantidad de artistas semilla o el tope de nodos."
        )
        search.save()
        logger.exception("Búsqueda %s agotó la memoria del proceso", search.id)
        return search

    except Exception as exc:
        search.status = "failed"
        search.error_message = str(exc)
        search.save()
        logger.exception("Búsqueda falló en profundidad %s", search.current_depth)
        return search

    finally:
        unregister_search_control(search_id)
        # Si el cuerpo salió sin estado final (return por excepción no capturada,
        # KeyboardInterrupt, bug futuro), nadie puede marcar la fila: hazlo aquí.
        _retire_orphan(search_id)