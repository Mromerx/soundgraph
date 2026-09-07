"""Tests de la API de búsqueda de artistas puente.

Cubren la validación de rango (2-5 semillas) del serializer y que el POST
dispare la creación de la búsqueda y devuelva 202 con un ``search_id`` válido.
No testean el contenido del BFS en sí: ``run_full_search`` se mockea para que
el test no golpee Last.fm ni dependa del progreso real.
"""
from unittest import mock
from uuid import UUID

from django.test import TestCase
from django.urls import reverse

from catalog.models import ConnectionSearch
from catalog.serializers import ConnectionSearchRequestSerializer

URL = reverse("catalog:connections")


class ConnectionSearchRequestSerializerTests(TestCase):
    def test_accepts_two_seeds(self):
        serializer = ConnectionSearchRequestSerializer(data={"seed_artists": ["A", "B"]})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_accepts_five_seeds(self):
        serializer = ConnectionSearchRequestSerializer(
            data={"seed_artists": [f"A{i}" for i in range(5)]}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_rejects_single_seed(self):
        serializer = ConnectionSearchRequestSerializer(data={"seed_artists": ["A"]})
        self.assertFalse(serializer.is_valid())
        self.assertIn("seed_artists", serializer.errors)

    def test_rejects_empty_list(self):
        serializer = ConnectionSearchRequestSerializer(data={"seed_artists": []})
        self.assertFalse(serializer.is_valid())

    def test_rejects_more_than_five_seeds(self):
        serializer = ConnectionSearchRequestSerializer(
            data={"seed_artists": [f"A{i}" for i in range(6)]}
        )
        self.assertFalse(serializer.is_valid())


class ConnectionSearchApiTests(TestCase):
    @mock.patch("catalog.services.background.run_full_search")
    def test_post_creates_search_and_returns_valid_search_id(self, mock_run):
        response = self.client.post(
            URL,
            {"seed_artists": ["Lil Peep", "Eminem", "Opeth"]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertEqual(payload["status"], "pending")
        UUID(payload["search_id"])

        search = ConnectionSearch.objects.get(pk=payload["search_id"])
        self.assertEqual(search.seed_artists, ["Lil Peep", "Eminem", "Opeth"])
        self.assertEqual(search.status, "pending")
        mock_run.assert_called_once()

    @mock.patch("catalog.services.background.run_full_search")
    def test_post_initializes_frontier_and_visited_per_seed(self, mock_run):
        response = self.client.post(
            URL,
            {"seed_artists": ["A", "B"]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 202)
        search = ConnectionSearch.objects.get(pk=response.json()["search_id"])
        expected = {"A": ["A"], "B": ["B"]}
        self.assertEqual(search.frontier_per_seed, expected)
        self.assertEqual(search.visited_per_seed, expected)

    def test_post_rejects_single_seed(self):
        response = self.client.post(
            URL,
            {"seed_artists": ["A"]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("seed_artists", response.json())

    def test_post_rejects_more_than_five_seeds(self):
        response = self.client.post(
            URL,
            {"seed_artists": [f"A{i}" for i in range(6)]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_get_unknown_search_id_returns_404(self):
        response = self.client.get(f"/api/connections/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(response.status_code, 404)

    def test_get_invalid_uuid_returns_404(self):
        response = self.client.get("/api/connections/not-a-uuid/")
        self.assertEqual(response.status_code, 404)

    @mock.patch("catalog.services.background.run_full_search")
    def test_get_running_search_reports_progress(self, mock_run):
        post = self.client.post(
            URL,
            {"seed_artists": ["A", "B"]},
            content_type="application/json",
        )
        search_id = post.json()["search_id"]

        ConnectionSearch.objects.filter(pk=search_id).update(
            status="running", current_depth=3
        )

        response = self.client.get(f"/api/connections/{search_id}/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["current_depth"], 3)
        self.assertEqual(payload["seed_artists"], ["A", "B"])
        self.assertNotIn("path", payload)
        self.assertNotIn("error_message", payload)

    @mock.patch("catalog.services.background.run_full_search")
    def test_get_failed_search_includes_error_message(self, mock_run):
        post = self.client.post(
            URL,
            {"seed_artists": ["A", "B"]},
            content_type="application/json",
        )
        search_id = post.json()["search_id"]

        ConnectionSearch.objects.filter(pk=search_id).update(
            status="failed", error_message="boom"
        )

        response = self.client.get(f"/api/connections/{search_id}/")
        self.assertEqual(response.json()["status"], "failed")
        self.assertEqual(response.json()["error_message"], "boom")

    @mock.patch("catalog.services.background.run_full_search")
    @mock.patch("catalog.services.connection_search.reconstruct_path")
    def test_get_found_search_includes_path(self, mock_path, mock_run):
        mock_path.return_value = {"A": ["A", "Bridge"], "B": ["B", "Bridge"]}

        post = self.client.post(
            URL,
            {"seed_artists": ["A", "B"]},
            content_type="application/json",
        )
        search_id = post.json()["search_id"]

        ConnectionSearch.objects.filter(pk=search_id).update(
            status="found",
            bridge_artist="Bridge",
            came_from={"A": None, "Bridge": "A", "B": "Bridge"},
        )

        response = self.client.get(f"/api/connections/{search_id}/")
        payload = response.json()
        self.assertEqual(payload["status"], "found")
        self.assertEqual(payload["bridge_artist"], "Bridge")
        self.assertEqual(
            payload["path"], {"A": ["A", "Bridge"], "B": ["B", "Bridge"]}
        )
        mock_path.assert_called_once()