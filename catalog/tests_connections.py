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


class ConnectionStatusPayloadTests(TestCase):
    """El endpoint de status no devuelve el grafo completo explorado."""

    @mock.patch("catalog.services.background.run_full_search")
    def test_status_payload_truncates_visited_and_reports_counts(self, mock_run):
        post = self.client.post(
            URL,
            {"seed_artists": ["A", "B"]},
            content_type="application/json",
        )
        search_id = post.json()["search_id"]

        big_visited = [f"artist-{i}" for i in range(5000)]
        big_frontier = [f"front-{i}" for i in range(5000)]
        ConnectionSearch.objects.filter(pk=search_id).update(
            status="running",
            current_depth=3,
            total_discovered=5000,
            visited_per_seed={"A": big_visited, "B": big_visited},
            frontier_per_seed={"A": big_frontier, "B": big_frontier},
            came_from={f"artist-{i}": f"artist-{max(i - 1, 0)}" for i in range(5000)},
        )

        response = self.client.get(f"/api/connections/{search_id}/")
        payload = response.json()

        self.assertEqual(payload["total_discovered"], 5000)
        self.assertEqual(payload["visited_count_per_seed"]["A"], 5000)
        self.assertEqual(payload["frontier_count_per_seed"]["A"], 5000)
        self.assertLessEqual(len(payload["visited_per_seed"]["A"]), 1200)
        self.assertLessEqual(len(payload["frontier_per_seed"]["A"]), 800)
        self.assertLessEqual(len(payload["came_from"]), 1200)

    @mock.patch("catalog.services.background.run_full_search")
    def test_full_graph_param_skips_sampling(self, mock_run):
        """?graph=full devuelve el grafo explorado completo (sin muestrear),
        para que el frontend pueda visualizar toda la búsqueda que llevó al
        puente."""
        post = self.client.post(
            URL,
            {"seed_artists": ["A", "B"]},
            content_type="application/json",
        )
        search_id = post.json()["search_id"]

        big_visited = [f"artist-{i}" for i in range(5000)]
        big_frontier = [f"front-{i}" for i in range(5000)]
        ConnectionSearch.objects.filter(pk=search_id).update(
            status="found",
            bridge_artist="artist-4999",
            visited_per_seed={"A": big_visited, "B": big_visited},
            frontier_per_seed={"A": big_frontier, "B": big_frontier},
            came_from={f"artist-{i}": f"artist-{max(i - 1, 0)}" for i in range(5000)},
        )

        response = self.client.get(f"/api/connections/{search_id}/?graph=full")
        payload = response.json()

        self.assertEqual(payload["status"], "found")
        self.assertEqual(payload["search_id"], search_id)
        self.assertEqual(len(payload["visited_per_seed"]["A"]), 5000)
        self.assertEqual(len(payload["frontier_per_seed"]["A"]), 5000)
        self.assertEqual(len(payload["came_from"]), 5000)

        # El modo compacto por defecto sigue acotado.
        compact = self.client.get(f"/api/connections/{search_id}/").json()
        self.assertLessEqual(len(compact["visited_per_seed"]["A"]), 1200)

    @mock.patch("catalog.services.background.run_full_search")
    def test_status_payload_reports_stopped_reason(self, mock_run):
        post = self.client.post(
            URL,
            {"seed_artists": ["A", "B"]},
            content_type="application/json",
        )
        search_id = post.json()["search_id"]

        ConnectionSearch.objects.filter(pk=search_id).update(
            status="exhausted",
            stopped_reason="node_limit",
            total_discovered=50_000,
            current_depth=2,
        )

        response = self.client.get(f"/api/connections/{search_id}/")
        payload = response.json()

        self.assertEqual(payload["status"], "exhausted")
        self.assertEqual(payload["stopped_reason"], "node_limit")


class ConnectionConcurrencyTests(TestCase):
    """No se permiten más búsquedas en paralelo que el máximo configurado."""

    @mock.patch("catalog.services.background.run_full_search")
    def test_rejects_second_concurrent_search(self, mock_run):
        first = self.client.post(
            URL,
            {"seed_artists": ["A", "B"]},
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 202)

        second = self.client.post(
            URL,
            {"seed_artists": ["C", "D"]},
            content_type="application/json",
        )
        self.assertEqual(second.status_code, 400)
        self.assertIn("en curso", second.json()["detail"])

    @mock.patch("catalog.services.background.run_full_search")
    def test_paused_search_still_counts_as_active(self, mock_run):
        """Una búsqueda pausada sigue en curso: su hilo vive y mantiene RAM,
        así que no debe permitir lanzar otra en paralelo."""
        first = self.client.post(URL, {"seed_artists": ["A", "B"]}, content_type="application/json")
        search_id = first.json()["search_id"]
        ConnectionSearch.objects.filter(pk=search_id).update(status="paused")

        second = self.client.post(URL, {"seed_artists": ["C", "D"]}, content_type="application/json")

        self.assertEqual(second.status_code, 400)
        self.assertIn("en curso", second.json()["detail"])


class ConnectionControlApiTests(TestCase):
    """PATCH /api/connections/{search_id}/ pausa, reanuda y detiene la búsqueda."""

    def setUp(self):
        self.patcher = mock.patch("catalog.services.background.run_full_search")
        self.mock_run = self.patcher.start()
        self.addCleanup(self.patcher.stop)

        response = self.client.post(
            URL, {"seed_artists": ["A", "B"]}, content_type="application/json"
        )
        self.search_id = response.json()["search_id"]

    def patch(self, action):
        return self.client.patch(
            f"/api/connections/{self.search_id}/",
            {"action": action},
            content_type="application/json",
        )

    def test_pause_then_resume_updates_status(self):
        pause = self.patch("pause")
        self.assertEqual(pause.status_code, 200)
        self.assertEqual(pause.json()["status"], "paused")
        self.assertEqual(
            ConnectionSearch.objects.get(pk=self.search_id).status, "paused"
        )

        resume = self.patch("resume")
        self.assertEqual(resume.status_code, 200)
        self.assertEqual(resume.json()["status"], "running")
        self.assertEqual(
            ConnectionSearch.objects.get(pk=self.search_id).status, "running"
        )

    def test_stop_marks_stopped_with_user_stop(self):
        stop = self.patch("stop")
        self.assertEqual(stop.status_code, 200)
        self.assertEqual(stop.json()["status"], "stopped")
        self.assertEqual(stop.json()["stopped_reason"], "user_stop")

        search = ConnectionSearch.objects.get(pk=self.search_id)
        self.assertEqual(search.status, "stopped")
        self.assertEqual(search.stopped_reason, "user_stop")

    def test_stop_works_while_paused(self):
        self.assertEqual(self.patch("pause").status_code, 200)
        self.assertEqual(self.patch("stop").status_code, 200)
        self.assertEqual(
            ConnectionSearch.objects.get(pk=self.search_id).status, "stopped"
        )

    def test_resume_without_pause_is_rejected(self):
        response = self.patch("resume")
        self.assertEqual(response.status_code, 400)
        self.assertIn("pausada", response.json()["detail"])

    def test_double_pause_is_rejected(self):
        self.assertEqual(self.patch("pause").status_code, 200)
        response = self.patch("pause")
        self.assertEqual(response.status_code, 400)
        self.assertIn("pausada", response.json()["detail"])

    def test_invalid_action_is_rejected(self):
        response = self.patch("fast-forward")
        self.assertEqual(response.status_code, 400)
        self.assertIn("action", response.json())

    def test_control_unknown_search_returns_404(self):
        response = self.client.patch(
            "/api/connections/00000000-0000-0000-0000-000000000000/",
            {"action": "stop"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_control_final_search_is_rejected(self):
        ConnectionSearch.objects.filter(pk=self.search_id).update(status="exhausted")
        response = self.patch("stop")
        self.assertEqual(response.status_code, 400)
        self.assertIn("exhausted", response.json()["detail"])


class ConnectionZombieExpiryTests(TestCase):
    """Las búsquedas cuyo hilo murió nunca quedan clavadas en "running".

    El BFS corre en un hilo daemon: si el proceso se reinicia a mitad de
    corrida, la fila quedaría ``running`` para siempre. Como el hilo emite
    heartbeat mientras trabaja, toda ``pending/running`` sin actividad reciente
    es un zombi y debe expirar sola (status=failed) la primera vez que alguien
    consulte el backend.
    """

    @staticmethod
    def backdate(search_id, seconds):
        from django.utils import timezone
        from datetime import timedelta

        ConnectionSearch.objects.filter(pk=search_id).update(
            updated_at=timezone.now() - timedelta(seconds=seconds)
        )

    @mock.patch("catalog.services.background.run_full_search")
    def test_get_expires_a_stale_running_search(self, mock_run):
        post = self.client.post(URL, {"seed_artists": ["A", "B"]}, content_type="application/json")
        search_id = post.json()["search_id"]
        ConnectionSearch.objects.filter(pk=search_id).update(status="running")
        self.backdate(search_id, 120)
        self.assertEqual(ConnectionSearch.objects.get(pk=search_id).status, "running")

        response = self.client.get(f"/api/connections/{search_id}/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "failed")
        self.assertIn("Volvé a lanzarla", payload["error_message"])
        self.assertEqual(ConnectionSearch.objects.get(pk=search_id).status, "failed")

    @mock.patch("catalog.services.background.run_full_search")
    def test_fresh_running_search_is_not_expired(self, mock_run):
        post = self.client.post(URL, {"seed_artists": ["A", "B"]}, content_type="application/json")
        search_id = post.json()["search_id"]

        response = self.client.get(f"/api/connections/{search_id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "pending")

    @mock.patch("catalog.services.background.run_full_search")
    def test_stale_search_does_not_block_concurrency(self, mock_run):
        # Un zombi no puede bloquear nuevas búsquedas: antes de contar "en
        # curso", el guard expira lo que está sin actividad.
        post = self.client.post(URL, {"seed_artists": ["A", "B"]}, content_type="application/json")
        search_id = post.json()["search_id"]
        ConnectionSearch.objects.filter(pk=search_id).update(status="running")
        self.backdate(search_id, 120)

        second = self.client.post(URL, {"seed_artists": ["C", "D"]}, content_type="application/json")

        self.assertEqual(second.status_code, 202)
        self.assertNotEqual(second.json()["search_id"], search_id)