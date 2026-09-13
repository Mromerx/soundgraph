"""Lanzador de búsquedas de artistas puente en un thread en background.

``launch_search`` crea el ``ConnectionSearch`` y lo corre en un thread daemon
para no bloquear el request; el BFS en sí (``run_full_search``) vive en
``catalog.services.connection_search`` y actualiza la búsqueda en la base a
medida que avanza.
"""
import threading

from django.conf import settings

from catalog.models import ConnectionSearch

from .connection_search import expire_stale_searches, run_full_search


def _max_concurrent_searches():
    return getattr(settings, "SOUNDGRAPH_MAX_CONCURRENT_SEARCHES", 1)


def _active_search_count():
    """Cantidad de búsquedas en curso (pending, running o paused).

    Primero expira zombis: si un hilo murió sin llegar a su estado final (ej.
    reinicio del servidor), la fila quedó ``running`` para siempre y bloquearía
    la concurrencia. Expirar antes de contar garantiza que un cadáver nunca
    impida lanzar una búsqueda válida. Una búsqueda ``paused`` sigue ocupando su
    slot de concurrencia: su hilo está vivo (esperando) y mantiene estado en RAM.
    """
    expire_stale_searches()
    return ConnectionSearch.objects.filter(
        status__in=["pending", "running", "paused"]
    ).count()


def launch_search(seed_artists):
    """Crea un ``ConnectionSearch`` y dispara el BFS en un thread daemon.

    Cada semilla arranca su propia "frontera" y sus "visitados" con ella misma
    como único nodo (BFS multi-fuente). Devuelve la búsqueda recién creada con
    ``status="pending"``; el hilo corre en paralelo y la actualiza.

    No permite superar ``SOUNDGRAPH_MAX_CONCURRENT_SEARCHES`` búsquedas
    simultáneas: cada BFS mantiene su estado en RAM, así que un número
    ilimitado de hilos paralelos dispararía el consumo de memoria.

    Args:
        seed_artists: lista de 2 a 5 nombres de artistas.

    Returns:
        La instancia ``ConnectionSearch`` recién creada.

    Raises:
        ValueError: si no hay entre 2 y 5 artistas semilla, o si ya hay una
            búsqueda en curso y no se permite otra.
    """
    if not 2 <= len(seed_artists) <= 5:
        raise ValueError("Debes enviar entre 2 y 5 artistas semilla.")

    max_concurrent = _max_concurrent_searches()
    if max_concurrent > 0 and _active_search_count() >= max_concurrent:
        raise ValueError(
            f"Ya hay {_active_search_count()} búsqueda(s) en curso. "
            "Esperá a que termine antes de lanzar otra."
        )

    # IMPORTANTE: visited_per_seed y frontier_per_seed NO pueden compartir los
    # mismos objetos de lista. Si comparten, la "frontera" del BFS es en la
    # práctica todo lo ya visitado y expand_one_level se convierte en un flood
    # del grafo completo (colapso de RAM con artistas muy populares).
    visited = {artist: [artist] for artist in seed_artists}
    frontier = {artist: list(names) for artist, names in visited.items()}
    search = ConnectionSearch.objects.create(
        seed_artists=seed_artists,
        status="pending",
        frontier_per_seed=frontier,
        visited_per_seed=visited,
    )
    threading.Thread(
        target=run_full_search,
        args=(search.id,),
        daemon=True,
    ).start()
    return search