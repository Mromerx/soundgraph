"""Tests de ETag/304 y del stream SSE del estado de una búsqueda de conexión.

Verifican que el GET de status responda 304 cuando nada cambió (sin re-serializar
el payload gigante), que subir ``payload_revision`` invalide el ETag, y que el
endpoint SSE entregue el payload final (con path y muestras) cuando la búsqueda
ya terminó.
"""
import json

from django.test import TestCase
from django.urls import reverse
from rest_framework import status

from catalog.models import ConnectionSearch
from catalog.services.connection_search import save_with_revision


def _final_search():
    return ConnectionSearch.objects.create(
        seed_artists=["A", "B"],
        status="found",
        bridge_artist="B",
        frontier_per_seed={"A": ["A"], "B": ["B"]},
        visited_per_seed={"A": ["A", "B"], "B": ["B"]},
    )


class ConnectionStatusETagTests(TestCase):
    def setUp(self):
        self.search = _final_search()
        self.url = reverse("catalog:connections-detail", args=[self.search.id])

    def test_first_get_returns_200_with_etag(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("ETag", response)
        self.assertEqual(response.json()["status"], "found")
        self.assertEqual(response.json()["path"]["A"][-1], "B")

    def test_same_etag_returns_304_without_rebuilding(self):
        first = self.client.get(self.url)
        etag = first["ETag"]

        response = self.client.get(self.url, HTTP_IF_NONE_MATCH=etag)

        self.assertEqual(response.status_code, status.HTTP_304_NOT_MODIFIED)
        self.assertEqual(response.content, b"")

    def test_revision_bump_invalidates_etag(self):
        first = self.client.get(self.url)
        old_etag = first["ETag"]

        # La búsqueda persiste un nuevo estado (fin de nivel, pause, etc.):
        # la revisión sube y el mismo If-None-Match ya no sirve -> 200 con ETag nuevo.
        self.search.status = "paused"
        save_with_revision(self.search)
        self.search.status = "found"
        save_with_revision(self.search)

        response = self.client.get(self.url, HTTP_IF_NONE_MATCH=old_etag)

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response["ETag"], old_etag)

    def test_unknown_search_404(self):
        url = reverse(
            "catalog:connections-detail", args=["00000000-0000-0000-0000-000000000000"]
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class ConnectionEventsTests(TestCase):
    def setUp(self):
        self.search = _final_search()
        self.url = reverse("catalog:connections-events", args=[self.search.id])

    def test_stream_yields_final_event_and_closes(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")

        chunks = b"".join(response.streaming_content).decode()
        events = [c for c in chunks.split("\n\n") if c.startswith("data: ")]
        self.assertEqual(len(events), 1)
        payload = json.loads(events[0][len("data: "):])
        self.assertEqual(payload["status"], "found")
        self.assertEqual(payload["bridge_artist"], "B")
        self.assertEqual(payload["path"]["A"][-1], "B")
        self.assertIn("visited_per_seed", payload)

    def test_events_endpoint_404(self):
        url = reverse(
            "catalog:connections-events",
            args=["00000000-0000-0000-0000-000000000000"],
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)