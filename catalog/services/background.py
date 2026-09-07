"""Lanzador de búsquedas de artistas puente en un thread en background.

``launch_search`` crea el ``ConnectionSearch`` y lo corre en un thread daemon
para no bloquear el request; el BFS en sí (``run_full_search``) vive en
``catalog.services.connection_search`` y actualiza la búsqueda en la base a
medida que avanza.
"""
import threading

from catalog.models import ConnectionSearch

from .connection_search import run_full_search


def launch_search(seed_artists):
    """Crea un ``ConnectionSearch`` y dispara el BFS en un thread daemon.

    Cada semilla arranca su propia "frontera" y sus "visitados" con ella misma
    como único nodo (BFS multi-fuente). Devuelve la búsqueda recién creada con
    ``status="pending"``; el hilo corre en paralelo y la actualiza.

    Args:
        seed_artists: lista de 2 a 5 nombres de artistas.

    Returns:
        La instancia ``ConnectionSearch`` recién creada.

    Raises:
        ValueError: si no hay entre 2 y 5 artistas semilla.
    """
    if not 2 <= len(seed_artists) <= 5:
        raise ValueError("Debes enviar entre 2 y 5 artistas semilla.")

    frontier = {artist: [artist] for artist in seed_artists}
    search = ConnectionSearch.objects.create(
        seed_artists=seed_artists,
        status="pending",
        frontier_per_seed=frontier,
        visited_per_seed=frontier,
    )
    threading.Thread(
        target=run_full_search,
        args=(search.id,),
        daemon=True,
    ).start()
    return search