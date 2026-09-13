"""Tests de los endpoints REST de recomendación y atipicalidad.

Mocan los servicios externos (clientes Last.fm y capa de caché) para no hacer
llamadas reales a las APIs. Cubren la validación de rangos del serializer, el
armado de candidatos y el detalle del album atípico.
"""
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from catalog.models import Album, Artist
from catalog.services import similarity


def _make_album(artist, title, tag_document=""):
    return Album.objects.create(
        artist=artist,
        title=title,
        tags=[],
        tag_document=tag_document,
    )


def _fake_album_fetch(seed, candidate):
    """Side effect de ``get_or_fetch_album`` que no depende del orden de hilos."""

    def fetch(artist, title):
        if artist == seed.artist.name and title == seed.title:
            return seed
        if artist == candidate.artist.name and title == candidate.title:
            return candidate
        raise AssertionError(f"Unexpected fetch: {artist} - {title}")

    return fetch


class RecommendationsViewTests(TestCase):
    def setUp(self):
        self.url = reverse("catalog:recommendations")

    def test_rejects_zero_seeds(self):
        response = self.client.post(
            self.url,
            {"seeds": [], "n_results": 3},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("seeds", response.json())

    def test_rejects_more_than_five_seeds(self):
        seeds = [{"artist": f"A{i}", "album": f"B{i}"} for i in range(6)]
        response = self.client.post(
            self.url,
            {"seeds": seeds, "n_results": 3},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("seeds", response.json())

    def test_rejects_n_results_out_of_range(self):
        response = self.client.post(
            self.url,
            {"seeds": [{"artist": "A", "album": "B"}], "n_results": 16},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("n_results", response.json())

    @mock.patch("catalog.views.similarity.recommend")
    @mock.patch("catalog.views.lastfm_client.get_top_albums")
    @mock.patch("catalog.views.lastfm_client.get_similar_artists")
    @mock.patch("catalog.views.cache.get_or_fetch_album")
    def test_builds_candidates_and_returns_rounded_scores(
        self, mock_get_album, mock_similar, mock_top, mock_recommend
    ):
        seed = _make_album(Artist.objects.create(name="Spiritbox"), "Eternal Blue")
        candidate = _make_album(
            Artist.objects.create(name="Architects"), "For Those That Wish to Exist"
        )

        mock_get_album.side_effect = _fake_album_fetch(seed, candidate)
        mock_similar.return_value = ["Architects"]
        mock_top.return_value = [("For Those That Wish to Exist", "Architects")]
        mock_recommend.return_value = [
            {
                "album": candidate,
                "score": 0.735,
                "matched_seed": seed,
                "matched_seeds": [{"album": seed, "score": 0.735}],
            }
        ]

        response = self.client.post(
            self.url,
            {
                "seeds": [{"artist": "Spiritbox", "album": "Eternal Blue"}],
                "n_results": 15,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["artist"], "Architects")
        self.assertEqual(payload[0]["album"], "For Those That Wish to Exist")
        self.assertEqual(payload[0]["score"], 74)
        self.assertEqual(payload[0]["matched_seed"]["artist"], "Spiritbox")
        self.assertEqual(payload[0]["matched_seeds"], [
            {"artist": "Spiritbox", "album": "Eternal Blue", "score": 74}
        ])
        mock_similar.assert_called_once_with("Spiritbox", limit=6)
        mock_top.assert_called_once_with("Architects", limit=2)
        mock_get_album.assert_any_call("Architects", "For Those That Wish to Exist")
        mock_get_album.assert_any_call("Spiritbox", "Eternal Blue")


class AtypicalAlbumsViewTests(TestCase):
    def test_artist_not_found_returns_404(self):
        response = self.client.get("/api/artists/999/atypical-albums/")

        self.assertEqual(response.status_code, 404)

    def test_returns_albums_sorted_by_distance_descending(self):
        artist = Artist.objects.create(name="Opeth")
        _make_album(artist, "Blackwater Park", tag_document="progressive metal")
        _make_album(artist, "Damnation", tag_document="progressive rock")
        _make_album(artist, "Heritage", tag_document="prog jazz old style")

        response = self.client.get(f"/api/artists/{artist.id}/atypical-albums/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 3)
        distances = [row["distance"] for row in payload]
        self.assertEqual(distances, sorted(distances, reverse=True))
        self.assertTrue(all("distance" in row and "album" in row for row in payload))

    def test_artist_without_albums_returns_400(self):
        artist = Artist.objects.create(name="Sin discografía")

        response = self.client.get(f"/api/artists/{artist.id}/atypical-albums/")

        self.assertEqual(response.status_code, 400)