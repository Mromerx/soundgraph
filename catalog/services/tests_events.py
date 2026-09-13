"""Tests del bus de eventos SSE y de la publicación de estado del BFS.

Cubren (a) el pub/sub del bus en memoria, (b) que ``run_full_search`` publica
el estado final completo (bridge + path + muestras) por el bus, y (c) que cada
save de estado avanza ``payload_revision`` (la base del ETag/304 del GET).
"""
import queue
from unittest import mock

from django.test import TestCase

from catalog.models import ConnectionSearch
from catalog.services import events
from catalog.services.connection_search import (
    compact_status_event,
    run_full_search,
    save_with_revision,
    status_event,
)


class EventBusTests(TestCase):
    def test_publish_reaches_subscriber(self):
        search = ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            frontier_per_seed={"A": ["A"], "B": ["B"]},
            visited_per_seed={"A": ["A"], "B": ["B"]},
        )
        subscriber = events.subscribe_search_events(search.id)
        self.addCleanup(lambda: events.unsubscribe_search_events(search.id, subscriber))

        events.publish_search_event(search.id, {"status": "found"})

        self.assertEqual(subscriber.get(timeout=2), {"status": "found"})

    def test_publish_is_silent_without_subscribers(self):
        search = ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            frontier_per_seed={"A": ["A"], "B": ["B"]},
            visited_per_seed={"A": ["A"], "B": ["B"]},
        )

        # No debe lanzar: publicar sin nadie escuchando es un no-op.
        events.publish_search_event(search.id, {"status": "found"})

    def test_unsubscribe_removes_binding(self):
        search = ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            frontier_per_seed={"A": ["A"], "B": ["B"]},
            visited_per_seed={"A": ["A"], "B": ["B"]},
        )
        subscriber = events.subscribe_search_events(search.id)

        events.unsubscribe_search_events(search.id, subscriber)
        events.publish_search_event(search.id, {"status": "found"})

        with self.assertRaises(queue.Empty):
            subscriber.get_nowait()


class SaveWithRevisionTests(TestCase):
    def test_save_advances_revision(self):
        search = ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            frontier_per_seed={"A": ["A"], "B": ["B"]},
            visited_per_seed={"A": ["A"], "B": ["B"]},
        )

        save_with_revision(search)
        search.refresh_from_db()

        self.assertEqual(search.payload_revision, 1)

    def test_state_event_compact_vs_final(self):
        search = ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            status="running",
            frontier_per_seed={"A": ["A"], "B": ["B"]},
            visited_per_seed={"A": ["A"], "B": ["B"]},
        )

        progress = compact_status_event(search)
        self.assertEqual(progress["status"], "running")
        self.assertNotIn("visited_per_seed", progress)
        self.assertEqual(progress["visited_count_per_seed"], {"A": 1, "B": 1})

        search.status = "found"
        search.bridge_artist = "B"
        full = status_event(search)
        self.assertEqual(full["status"], "found")
        self.assertIn("visited_per_seed", full)
        self.assertEqual(full["path"]["A"][-1], "B")


class RunFullSearchPublishTests(TestCase):
    def _search(self, **kwargs):
        return ConnectionSearch.objects.create(
            seed_artists=["A", "B"],
            node_limit=100,
            frontier_per_seed={"A": ["A"], "B": ["B"]},
            visited_per_seed={"A": ["A"], "B": ["B"]},
            **kwargs,
        )

    def _drain_last_event(self, subscriber):
        last = subscriber.get(timeout=5)
        while True:
            try:
                last = subscriber.get_nowait()
            except queue.Empty:
                return last

    def _drain_all(self, subscriber):
        events_ = [subscriber.get(timeout=5)]
        while True:
            try:
                events_.append(subscriber.get_nowait())
            except queue.Empty:
                return events_

    @mock.patch("catalog.services.connection_search.expand_one_level")
    def test_found_publishes_final_event_with_path_and_samples(self, mock_expand):
        def expand(search, on_progress=None, on_artist_added=None):
            search.visited_per_seed = {
                "A": ["A", "bridge"],
                "B": ["B", "bridge"],
            }
            search.frontier_per_seed = {"A": [], "B": []}

        mock_expand.side_effect = expand
        search = self._search()
        subscriber = events.subscribe_search_events(search.id)
        self.addCleanup(lambda: events.unsubscribe_search_events(search.id, subscriber))

        run_full_search(search.id)

        event = self._drain_last_event(subscriber)
        self.assertEqual(event["status"], "found")
        self.assertEqual(event["bridge_artist"], "bridge")
        self.assertEqual(event["path"]["A"][-1], "bridge")
        self.assertIn("visited_count_per_seed", event)
        self.assertIn("total_discovered", event)
        search.refresh_from_db()
        self.assertEqual(search.payload_revision, 3)

    @mock.patch("catalog.services.connection_search.expand_one_level")
    def test_exhausted_publishes_final_event(self, mock_expand):
        mock_expand.return_value = None
        search = self._search(max_depth=0)

        subscriber = events.subscribe_search_events(search.id)
        self.addCleanup(lambda: events.unsubscribe_search_events(search.id, subscriber))

        run_full_search(search.id)

        event = self._drain_last_event(subscriber)
        self.assertEqual(event["status"], "exhausted")
        search.refresh_from_db()
        self.assertEqual(search.payload_revision, 2)

    @mock.patch("catalog.services.connection_search.expand_one_level")
    def test_progress_events_reflect_each_artist_and_carry_graph_samples(self, mock_expand):
        def expand(search, on_progress=None, on_artist_added=None):
            for name in ["x", "y", "z"]:
                search.visited_per_seed["A"].append(name)
                search.total_discovered += 1
                if on_artist_added is not None:
                    on_artist_added()
            search.frontier_per_seed = {"A": [], "B": []}

        mock_expand.side_effect = expand
        search = self._search(max_depth=1)
        subscriber = events.subscribe_search_events(search.id)
        self.addCleanup(lambda: events.unsubscribe_search_events(search.id, subscriber))

        run_full_search(search.id)

        events_ = self._drain_all(subscriber)
        progress = [e for e in events_ if e.get("status") == "running"]

        # Progreso estrictamente por artista: inicial (0), y un evento por cada
        # uno descubierto (1, 2, 3), cada uno con su muestra del grafo
        # reflejando SOLO al artista recién agregado.
        totals = [e["total_discovered"] for e in progress]
        self.assertEqual(totals[:4], [0, 1, 2, 3])
        self.assertIn("visited_per_seed", progress[1])
        self.assertEqual(progress[1]["visited_per_seed"]["A"], ["A", "x"])
        self.assertEqual(progress[2]["visited_per_seed"]["A"], ["A", "x", "y"])

        self.assertEqual(events_[-1]["status"], "exhausted")
        self.assertIn("visited_per_seed", events_[-1])