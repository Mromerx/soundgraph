"""Búsqueda BFS multi-fuente de un artista puente entre artistas semilla.

Explora el grafo de afinidad de Last.fm nivel por nivel: cada semilla mantiene
su propia frontera de expansión y su conjunto de visitados; el objetivo es
encontrar un artista que aparezca en TODOS los conjuntos de visitados a la
vez (intersección). Una vez hallado, se reconstruye el camino desde cada
semilla hasta el puente usando ``came_from``.

Las funciones ``expand_one_level``, ``find_intersection`` y
``reconstruct_path`` son puras: mutan/asumen el objeto ``ConnectionSearch`` en
memoria y NO tocan la base de datos. La persistencia la decide el llamador;
``run_full_search`` es la única que orquesta la corrida completa persistiendo
nivel a nivel.
"""
import logging
import time

from catalog.models import ConnectionSearch
from catalog.services.lastfm_client import get_similar_artists

logger = logging.getLogger(__name__)


def expand_one_level(search):
    """Expande un nivel de BFS para todas las semillas.

    Por cada semilla toma su frontera actual, consulta los similares de cada
    artista de esa frontera en Last.fm (``get_similar_artists`` respeta su
    propio throttle), agrega a ``visited_per_seed[semilla]`` los nombres que
    aún no estuvieran visitados y registra en ``came_from`` quién trajo a cada
    uno (sin pisar un padre ya registrado por otra semilla). La frontera de la
    semilla pasa a ser exactamente los artistas recién descubiertos.

    Si la semilla no tiene frontera previa (primer nivel), se usa la semilla
    misma como punto de partida.

    Args:
        search: ``ConnectionSearch`` cargado en memoria.

    Returns:
        El mismo objeto ``search`` con los conjuntos de visitados, fronteras y
        ``came_from`` actualizados. No lo guarda en la base.
    """
    for seed in search.seed_artists:
        if seed not in search.visited_per_seed:
            search.visited_per_seed[seed] = [seed]
        if seed not in search.frontier_per_seed:
            search.frontier_per_seed[seed] = [seed]

        frontier = search.frontier_per_seed[seed]
        visited = search.visited_per_seed[seed]
        visited_set = set(visited)
        new_artists = []

        for artist in frontier:
            for similar in get_similar_artists(artist, limit=10):
                if similar not in visited_set:
                    visited_set.add(similar)
                    visited.append(similar)
                    new_artists.append(similar)
                    if similar not in search.came_from:
                        search.came_from[similar] = artist

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

    common = set(search.visited_per_seed[search.seed_artists[0]])
    for seed in search.seed_artists[1:]:
        common &= set(search.visited_per_seed[seed])
        if not common:
            return None

    return sorted(common)[0] if common else None


def reconstruct_path(search, bridge):
    """Reconstruye el camino desde cada semilla hasta el puente.

    Usa ``came_from`` para recorrer hacia atrás desde el puente hasta la
    semilla raíz de su cadena (la primera que lo descubrió). Esa semilla
    recibe el camino completo; el resto recibe ``[semilla, puente]`` porque
    ``came_from`` solo preserva el primer hallazgo. Si el puente ES una
    semilla, su camino es ``[semilla]``.

    Args:
        search: ``ConnectionSearch`` con ``came_from`` poblado.
        bridge: nombre del artista puente hallado.

    Returns:
        Dict ``{semilla: [camino...]}`` con el camino de cada semilla al
        puente.
    """
    chain = [bridge]
    current = bridge
    while current in search.came_from:
        current = search.came_from[current]
        chain.append(current)
    chain.reverse()

    root = chain[0]

    paths = {}
    for seed in search.seed_artists:
        if seed == bridge:
            paths[seed] = [seed]
        elif seed == root:
            paths[seed] = chain
        else:
            paths[seed] = [seed, bridge]
    return paths


def run_full_search(search_id, sleep_between_levels=0):
    """Ejecuta la búsqueda completa de forma sincrónica.

    Expande nivel por nivel hasta encontrar un puente o agotar
    ``max_depth``, persistiendo el estado después de cada nivel. Cualquier
    excepción se captura y se deja registrada en el objeto sin propagarse.

    Args:
        search_id: id del ``ConnectionSearch`` a cargar.
        sleep_between_levels: pausa en segundos entre niveles (para no
            saturar la API en pruebas largas).

    Returns:
        El ``ConnectionSearch`` con su estado final:
        ``found`` (con ``bridge_artist`` set), ``exhausted`` o ``failed``.
    """
    search = ConnectionSearch.objects.get(id=search_id)
    search.status = "running"
    search.save()

    try:
        while search.current_depth < search.max_depth:
            expand_one_level(search)
            search.save()

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
        search.save()
        logger.info(
            "Búsqueda agotada tras %s niveles sin encontrar intersección.",
            search.max_depth,
        )
        return search

    except Exception as exc:
        search.status = "failed"
        search.error_message = str(exc)
        search.save()
        logger.exception("Búsqueda falló en profundidad %s", search.current_depth)
        return search