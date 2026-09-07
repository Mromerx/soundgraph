"""Tests de los endpoints y clientes de búsqueda en Last.fm.

Mocan ``requests.get`` (o los clientes) para no golpear la API real. El
throttle se desactiva en la base de tests de clientes, igual que en
``tests_clients``.
"""
from unittest import mock

import requests
from django.test import TestCase
from django.urls import reverse

from catalog.services import lastfm_client
from catalog.services.lastfm_client import LastFMError


def _mock_response(status_code=200, payload=None, http_error=False):
    """Construye un objeto response simulado de ``requests``."""
    response = mock.Mock(spec=requests.Response)
    response.status_code = status_code
    if http_error and status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    else:
        response.raise_for_status.return_value = None
    response.json.return_value = payload or {}
    return response


class _ClientTestCase(TestCase):
    """Base para tests de clientes: desactiva el throttle entre tests."""

    def setUp(self):
        self._lastfm_interval = lastfm_client._lastfm_throttle.min_interval
        lastfm_client._lastfm_throttle.min_interval = 0

    def tearDown(self):
        lastfm_client._lastfm_throttle.min_interval = self._lastfm_interval


class SearchArtistsClientTests(_ClientTestCase):
    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_returns_artists_with_mbid_and_listeners(self, mock_get):
        mock_get.return_value = _mock_response(
            payload={
                "results": {
                    "artistmatches": {
                        "artist": [
                            {"name": "Opeth", "mbid": "m-1", "listeners": "123456"},
                            {"name": "Oppenheimer", "mbid": "", "listeners": "999"},
                        ]
                    }
                }
            }
        )

        self.assertEqual(
            lastfm_client.search_artists("Op"),
            [
                {"name": "Opeth", "mbid": "m-1", "listeners": 123456},
                {"name": "Oppenheimer", "mbid": "", "listeners": 999},
            ],
        )

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_single_result_dict_is_normalized(self, mock_get):
        mock_get.return_value = _mock_response(
            payload={"results": {"artistmatches": {"artist": {"name": "Opeth", "mbid": "m"}}}}
        )

        self.assertEqual(
            lastfm_client.search_artists("Opeth"),
            [{"name": "Opeth", "mbid": "m", "listeners": 0}],
        )

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_api_error_returns_empty_list(self, mock_get):
        mock_get.return_value = _mock_response(payload={"error": 6, "message": "Artist not found"})

        self.assertEqual(lastfm_client.search_artists("Nobody"), [])


class GetArtistAlbumsClientTests(_ClientTestCase):
    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_returns_album_titles_with_mbid(self, mock_get):
        mock_get.return_value = _mock_response(
            payload={
                "topalbums": {
                    "artist": "Opeth",
                    "album": [
                        {"name": "Blackwater Park", "mbid": "a-1"},
                        {"name": "Ghost Reveries", "mbid": ""},
                    ],
                }
            }
        )

        self.assertEqual(
            lastfm_client.get_artist_albums("Opeth"),
            [
                {"title": "Blackwater Park", "mbid": "a-1"},
                {"title": "Ghost Reveries", "mbid": ""},
            ],
        )

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_single_result_dict_is_normalized(self, mock_get):
        mock_get.return_value = _mock_response(
            payload={"topalbums": {"album": {"name": "Watershed", "mbid": "a-2"}}}
        )

        self.assertEqual(
            lastfm_client.get_artist_albums("Opeth"),
            [{"title": "Watershed", "mbid": "a-2"}],
        )

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_api_error_returns_empty_list(self, mock_get):
        mock_get.return_value = _mock_response(payload={"error": 6, "message": "Album not found"})

        self.assertEqual(lastfm_client.get_artist_albums("Nobody"), [])


class ArtistSearchViewTests(TestCase):
    def setUp(self):
        self.url = reverse("catalog:search-artists")

    @mock.patch("catalog.views.lastfm_client.search_artists")
    def test_returns_parsed_artists(self, mock_search):
        mock_search.return_value = [
            {"name": "Opeth", "mbid": "m-1", "listeners": 123456}
        ]

        response = self.client.get(self.url, {"q": "Op"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"results": [{"name": "Opeth", "mbid": "m-1", "listeners": 123456}]},
        )
        mock_search.assert_called_once_with("Op")

    def test_missing_q_returns_400(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.json())

    @mock.patch("catalog.views.lastfm_client.search_artists")
    def test_lastfm_error_returns_502(self, mock_search):
        mock_search.side_effect = LastFMError("boom")

        response = self.client.get(self.url, {"q": "Op"})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "No se pudieron obtener los datos de la API: boom")


class ArtistAlbumsViewTests(TestCase):
    def setUp(self):
        self.url = reverse("catalog:artist-albums")

    @mock.patch("catalog.views.lastfm_client.get_artist_albums")
    def test_returns_parsed_albums(self, mock_albums):
        mock_albums.return_value = [{"title": "Blackwater Park", "mbid": "a-1"}]

        response = self.client.get(self.url, {"artist": "Opeth"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"results": [{"title": "Blackwater Park", "mbid": "a-1"}]},
        )
        mock_albums.assert_called_once_with("Opeth")

    def test_missing_artist_returns_400(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.json())

    @mock.patch("catalog.views.lastfm_client.get_artist_albums")
    def test_lastfm_error_returns_502(self, mock_albums):
        mock_albums.side_effect = LastFMError("boom")

        response = self.client.get(self.url, {"artist": "Opeth"})

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "No se pudieron obtener los datos de la API: boom")