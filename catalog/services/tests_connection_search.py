"""Tests unitarios del motor de búsqueda de conexión entre artistas.

Cubren las funciones puras ``find_intersection`` y ``reconstruct_path`` con
datos construidos en memoria (sin tocar Last.fm), y los límites de memoria del
BFS: ``expand_one_level``/``run_full_search`` respetan ``node_limit`` y
terminan en ``exhausted`` con ``stopped_reason="node_limit"`` antes de
explotar, y un ``MemoryError`` del proceso se convierte en ``failed``.
"""
from unittest import mock

import threading
import time

from django.test import SimpleTestCase, TestCase

from catalog.models import ConnectionSearch
from catalog.services.connection_search import (
    _retire_orphan,
    expand_one_level,
    find_intersection,
    reconstruct_path,
    run_full_search,
    set_search_paused,
    set_search_stopped,
)


class FindIntersectionTests(SimpleTestCase):
    def test_no_intersection_returns_none(self):
        search = ConnectionSearch(
            seed_artists=["A", "B"],
            visited_per_seed={"A": ["A", "x", "y"], "B": ["B", "z", "w"]},
        )

        self.assertIsNone(find_intersection(search))

    def test_intersection_returns_alphabetic_first(self):
        search = ConnectionSearch(
            seed_artists=["A", "B", "C"],
            visited_per_seed={
                "A": ["A", "zebra", "apple"],
                "B": ["B", "apple", "mango"],
                "C": ["C", "orange", "apple"],
            },
        )

        self.assertEqual(find_intersection(search), "apple")

    def test_repeated_intersection_does_not_corrupt_cached_visited_sets(self):
        """Regresión: la intersección no debe mutar los sets de visitados
        cacheados, sino la dedupe de expand_one_level se rompería."""
        search = ConnectionSearch(
            seed_artists=["A", "B", "C"],
            visited_per_seed={
                "A": ["A", "apple", "banana", "pear"],
                "B": ["B", "banana", "pear"],
                "C": ["C", "apple", "pear"],
            },
        )

        self.assertEqual(find_intersection(search), "pear")
        self.assertEqual(find_intersection(search), "pear")

        # El cache de la semilla A debe seguir intacto para la dedupe.
        self.assertEqual(
            set(search._visited_sets["A"]), {"A", "apple", "banana", "pear"}
        )


class ReconstructPathTests(SimpleTestCase):
    def test_bridge_is_a_seed_returns_single_artist_path(self):
        search = ConnectionSearch(
            seed_artists=["Lil Peep", "Eminem"],
            came_from={"Lil Peep": "X"},
        )

        paths = reconstruct_path(search, "Lil Peep")

        self.assertEqual(paths, {"Lil Peep": ["Lil Peep"], "Eminem": ["Eminem", "Lil Peep"]})

    def test_reconstructs_chain_from_root_seed(self):
        search = ConnectionSearch(
            seed_artists=["Opeth", "Eminem"],
            came_from={"Y": "X", "X": "Opeth"},
        )

        paths = reconstruct_path(search, "Y")

        self.assertEqual(paths, {"Opeth": ["Opeth", "X", "Y"], "Eminem": ["Eminem", "Y"]})

    def test_reconstruct_stops_at_seed_instead_of_cycling(self):
        """Regresión del MemoryError: semillas que se parecen entre sí (ej. 50
        Cent/Eminem/Lil Wayne) generaban en came_from un ciclo S1->S2->S1, y el
        bucle de reconstrucción oscilaba entre ambas sin terminar hasta agotar
        la RAM. Ahora la cadena se corta en la primera semilla."""
        search = ConnectionSearch(
            seed_artists=["50 Cent", "Eminem", "Lil Wayne"],
            came_from={
                "Eminem": "50 Cent",
                "50 Cent": "Eminem",
                "Wiz Khalifa": "Eminem",
            },
        )

        paths = reconstruct_path(search, "Wiz Khalifa")

        self.assertEqual(
            paths,
            {
                "50 Cent": ["50 Cent", "Wiz Khalifa"],
                "Eminem": ["Eminem", "Wiz Khalifa"],
                "Lil Wayne": ["Lil Wayne", "Wiz Khalifa"],
            },
        )

    def test_non_seed_cycle_degrades_to_two_hop_paths(self):
        """Defensa extra: si came_from llegó corrupto a la base (ciclo entre
        no-semillas o cadena huérfana), la reconstrucción no debe colgar el
        endpoint: degrada a caminos de dos saltos para todas las semillas."""
        search = ConnectionSearch(
            seed_artists=["A", "B"],
            came_from={"X": "Y", "Y": "X"},
        )

        self.assertEqual(
            reconstruct_path(search, "X"),
            {"A": ["A", "X"], "B": ["B", "X"]},
        )

    def test_orphan_chain_degrades_to_two_hop_paths(self):
        search = ConnectionSearch(
            seed_artists=["A", "B"],
            came_from={"X": "orphan"},
        )

        self.assertEqual(
            reconstruct_path(search, "X"),
            {"A": ["A", "X"], "B": ["B", "X"]},
        )


class ExpandOneLevelBoundsTests(TestCase):
    def _search(self, node_limit, seeds=("A", "B")):
        visited = {seed: [seed] for seed in seeds}
        frontier = {seed: list(names) for seed, names in visited.items()}
        return ConnectionSearch.objects.create(
            seed_artists=list(seeds),
            node_limit=node_limit,
            frontier_per_seed=frontier,
            visited_per_seed=visited,
        )

    @mock.patch("catalog.services.connection_search.get_similar_artists")
    def test_hits_node_limit_and_marks_over_limit(self, mock_similar):
        mock_similar.side_effect = lambda artist, limit: [
            f"{artist}.{i}" for i in range(10)
        ]

        search = self._search(node_limit=15)

        expand_one_level(search)

        self.assertTrue(search.over_limit)
        self.assertEqual(search.total_discovered, 15)
        self.assertLessEqual(len(search.visited_per_seed["B"]), 15)

    @mock.patch("catalog.services.connection_search.get_similar_artists")
    def test_does_not_exceed_node_limit(self, mock_similar):
        mock_similar.side_effect = lambda artist, limit: [
            f"{artist}.{i}" for i in range(10)
        ]

        search = self._search(node_limit=5)

        expand_one_level(search)

        self.assertTrue(search.over_limit)
        self.assertLessEqual(search.total_discovered, 5)

    @mock.patch("catalog.services.connection_search.get_similar_artists")
    def test_normal_expansion_under_limit(self, mock_similar):
        mock_similar.side_effect = lambda artist, limit: [
            f"{artist}.{i}" for i in range(10)
        ]

        search = self._search(node_limit=50)

        expand_one_level(search)

        self.assertFalse(getattr(search, "over_limit", False))
        self.assertEqual(search.total_discovered, 20)

    @mock.patch("catalog.services.connection_search.get_similar_artists")
    def test_expansion_does_not_flood_full_graph_on_shared_lists(self, mock_similar):
        """Regresión: si frontier y visited comparten objetos de lista (como los
        creaba background.launch_search), la expansión de un nivel debe recorrer
        SOLO la frontera previa y no todo el componente alcanzable."""
        mock_similar.side_effect = lambda artist, limit: [
            f"{artist}.{i}" for i in range(10)
        ]

        shared = {"A": ["A"], "B": ["B"]}
        search = ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            node_limit=50,
            frontier_per_seed=shared,
            visited_per_seed=shared,
        )

        expand_one_level(search)

        self.assertFalse(getattr(search, "over_limit", False))
        self.assertEqual(search.total_discovered, 20)
        self.assertEqual(search.frontier_per_seed["A"], [f"A.{i}" for i in range(10)])

    @mock.patch("catalog.services.connection_search.get_similar_artists")
    def test_similar_data_is_fetched_once_per_artist(self, mock_similar):
        """Regresión: el mismo artista en la frontera de varias semillas (o en
        niveles seguidos) no debe gatillar una llamada a Last.fm por aparición."""
        mock_similar.side_effect = lambda artist, limit: [f"{artist}.x"]

        search = ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            node_limit=100,
            visited_per_seed={"A": ["A", "shared"], "B": ["B", "shared"]},
            frontier_per_seed={"A": ["shared"], "B": ["shared"]},
        )

        expand_one_level(search)

        self.assertEqual(mock_similar.call_count, 1)
        self.assertEqual(search.visited_per_seed["A"], ["A", "shared", "shared.x"])
        self.assertEqual(search.visited_per_seed["B"], ["B", "shared", "shared.x"])

    @mock.patch("catalog.services.connection_search.get_similar_artists")
    def test_seeds_are_never_registered_as_came_from_keys(self, mock_similar):
        """Regresión del MemoryError: dos semillas que se descubren mutuamente
        (ej. 50 Cent <-> Eminem) no deben entrar en came_from, o la
        reconstrucción de camino oscilaría S1->S2->S1 de forma infinita."""
        mock_similar.side_effect = lambda artist, limit: (
            ["B"] if artist == "A" else ["A"]
        )

        search = ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            node_limit=100,
            visited_per_seed={"A": ["A"], "B": ["B"]},
            frontier_per_seed={"A": ["A"], "B": ["B"]},
        )

        expand_one_level(search)

        self.assertNotIn("A", search.came_from)
        self.assertNotIn("B", search.came_from)


class RunFullSearchBoundsTests(TestCase):
    @mock.patch("catalog.services.connection_search.get_similar_artists")
    def test_stops_cleanly_when_node_limit_reached(self, mock_similar):
        mock_similar.side_effect = lambda artist, limit: [
            f"x-{artist}-{i}" for i in range(10)
        ]

        search = ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            node_limit=13,
            frontier_per_seed={"A": ["A"], "B": ["B"]},
            visited_per_seed={"A": ["A"], "B": ["B"]},
            max_depth=6,
        )

        result = run_full_search(search.id)
        result.refresh_from_db()

        self.assertEqual(result.status, "exhausted")
        self.assertEqual(result.stopped_reason, "node_limit")
        self.assertLessEqual(result.total_discovered, 13)

    @mock.patch("catalog.services.connection_search.expand_one_level")
    def test_memory_error_becomes_failed(self, mock_expand):
        mock_expand.side_effect = MemoryError("oom")

        search = ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            node_limit=50_000,
            frontier_per_seed={"A": ["A"], "B": ["B"]},
            visited_per_seed={"A": ["A"], "B": ["B"]},
        )

        result = run_full_search(search.id)
        result.refresh_from_db()

        self.assertEqual(result.status, "failed")
        self.assertIn("memoria", result.error_message)


class ZombiePreventionTests(TestCase):
    """Una búsqueda cuyo hilo muere nunca queda clavada en running."""

    @mock.patch("catalog.services.connection_search.get_similar_artists")
    def test_expand_one_level_invokes_on_progress_heartbeat(self, mock_similar):
        mock_similar.side_effect = lambda artist, limit: [f"{artist}.x"]
        search = ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            node_limit=100,
            frontier_per_seed={"A": ["A"], "B": ["B"]},
            visited_per_seed={"A": ["A"], "B": ["B"]},
        )
        heartbeats = []

        expand_one_level(search, on_progress=lambda: heartbeats.append(1))

        # Un heartbeat por artista de la frontera (2 artistas = 2 latidos).
        self.assertEqual(len(heartbeats), 2)

    def test_retire_orphan_closes_unfinished_running_row(self):
        search = ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            status="running",
            frontier_per_seed={"A": ["A"], "B": ["B"]},
            visited_per_seed={"A": ["A"], "B": ["B"]},
        )

        _retire_orphan(search.id)
        search.refresh_from_db()

        self.assertEqual(search.status, "failed")
        self.assertIn("interrumpida", search.error_message)

    @mock.patch("catalog.services.connection_search.expand_one_level")
    def test_run_full_search_finally_retires_row_on_unhandled_exception(self, mock_expand):
        """Un BaseException (ej. KeyboardInterrupt) escapa del try/except; el
        finally de run_full_search debe retirar la fila para que no quede un
        running eterno bloqueando la concurrencia."""
        mock_expand.side_effect = KeyboardInterrupt()
        search = ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            node_limit=100,
            frontier_per_seed={"A": ["A"], "B": ["B"]},
            visited_per_seed={"A": ["A"], "B": ["B"]},
        )

        with self.assertRaises(KeyboardInterrupt):
            run_full_search(search.id)
        search.refresh_from_db()

        self.assertEqual(search.status, "failed")
        self.assertIn("interrumpida", search.error_message)


class SearchControlRunTests(TestCase):
    """Pausar/reanudar/detener una búsqueda en plena expansión."""

    def _search(self, **kwargs):
        return ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            node_limit=100,
            frontier_per_seed={"A": ["A"], "B": ["B"]},
            visited_per_seed={"A": ["A"], "B": ["B"]},
            **kwargs,
        )

    @mock.patch("catalog.services.connection_search.expand_one_level")
    def test_stop_during_expansion_marks_stopped(self, mock_expand):
        def interrupt_first(search, on_progress):
            search.total_discovered = 1
            search.visited_per_seed["A"] = ["A", "x"]
            set_search_stopped(search.id)
            on_progress()  # el heartbeat detecta la detención

        mock_expand.side_effect = interrupt_first
        search = self._search(max_depth=6)

        result = run_full_search(search.id)
        result.refresh_from_db()

        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.stopped_reason, "user_stop")
        self.assertEqual(result.total_discovered, 1)

    @mock.patch("catalog.services.connection_search.expand_one_level")
    def test_pause_wait_and_resume_continues(self, mock_expand):
        calls = []

        def expand(search, on_progress):
            calls.append(1)
            if len(calls) == 1:
                search.total_discovered = 1
                search.visited_per_seed["A"] = ["A", "x"]
                set_search_paused(search.id, True)
                on_progress()  # el heartbeat detecta la pausa y interrumpe
            else:
                search.total_discovered = 3

        def resume_soon():
            time.sleep(0.3)
            set_search_paused(search.id, False)

        mock_expand.side_effect = expand
        search = self._search(max_depth=1, current_depth=0)

        threading.Thread(target=resume_soon, daemon=True).start()
        result = run_full_search(search.id)
        result.refresh_from_db()

        # Tras reanudar se re-expande el mismo nivel y luego se agota max_depth.
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.status, "exhausted")
        self.assertEqual(result.total_discovered, 3)

    @mock.patch("catalog.services.connection_search.expand_one_level")
    def test_stop_while_paused_marks_stopped(self, mock_expand):
        def pause_first(search, on_progress):
            search.total_discovered = 1
            set_search_paused(search.id, True)
            on_progress()

        def stop_soon():
            time.sleep(0.3)
            set_search_stopped(search.id)

        mock_expand.side_effect = pause_first
        search = self._search(max_depth=6)

        threading.Thread(target=stop_soon, daemon=True).start()
        result = run_full_search(search.id)
        result.refresh_from_db()

        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.stopped_reason, "user_stop")
        self.assertEqual(result.total_discovered, 1)