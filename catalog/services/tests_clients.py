"""Tests del cliente de Last.fm y de la capa de caché.

Todos usan ``unittest.mock`` para simular las respuestas de Last.fm: no se
hace NINGUNA llamada real a la API. El throttle se desactiva para no ralentizar
los tests.
"""
from datetime import timedelta
from unittest import mock

import requests
from django.test import TestCase
from django.utils import timezone

from catalog.models import Album, Artist
from catalog.services import cache, lastfm_client


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


class LastFmSimilarArtistsTests(_ClientTestCase):
    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_returns_artist_names(self, mock_get):
        mock_get.return_value = _mock_response(
            payload={
                "similarartists": {
                    "artist": [
                        {"name": "Tool"},
                        {"name": "Porcupine Tree"},
                        {"name": "A Perfect Circle"},
                    ]
                }
            }
        )

        self.assertEqual(
            lastfm_client.get_similar_artists("Opeth"),
            ["Tool", "Porcupine Tree", "A Perfect Circle"],
        )

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_single_result_dict_is_normalized(self, mock_get):
        mock_get.return_value = _mock_response(
            payload={"similarartists": {"artist": {"name": "Tool"}}}
        )

        self.assertEqual(lastfm_client.get_similar_artists("Opeth"), ["Tool"])

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_api_error_returns_empty_list(self, mock_get):
        mock_get.return_value = _mock_response(payload={"error": 6, "message": "Artist not found"})

        self.assertEqual(lastfm_client.get_similar_artists("Nobody"), [])


class LastFmTopAlbumsTests(_ClientTestCase):
    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_returns_album_tuples(self, mock_get):
        mock_get.return_value = _mock_response(
            payload={
                "topalbums": {
                    "artist": "Opeth",
                    "album": [
                        {"name": "Blackwater Park", "artist": {"name": "Opeth"}},
                        {"name": "Ghost Reveries", "artist": {"name": "Opeth"}},
                    ],
                }
            }
        )

        self.assertEqual(
            lastfm_client.get_top_albums("Opeth"),
            [("Blackwater Park", "Opeth"), ("Ghost Reveries", "Opeth")],
        )

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_string_artist_is_supported(self, mock_get):
        mock_get.return_value = _mock_response(
            payload={"topalbums": {"artist": "Opeth", "album": [{"name": "Watershed", "artist": "Opeth"}]}}
        )

        self.assertEqual(lastfm_client.get_top_albums("Opeth"), [("Watershed", "Opeth")])


class LastFmAlbumTagsTests(_ClientTestCase):
    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_returns_tag_dicts_with_int_counts(self, mock_get):
        mock_get.return_value = _mock_response(
            payload={
                "toptags": {
                    "tag": [
                        {"name": "progressive metal", "count": "100"},
                        {"name": "melancholic", "count": "45"},
                    ]
                }
            }
        )

        self.assertEqual(
            lastfm_client.get_album_tags("Opeth", "Blackwater Park"),
            [{"name": "progressive metal", "count": 100}, {"name": "melancholic", "count": 45}],
        )

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_single_tag_dict_is_normalized(self, mock_get):
        mock_get.return_value = _mock_response(
            payload={"toptags": {"tag": {"name": "metal", "count": "5"}}}
        )

        self.assertEqual(lastfm_client.get_album_tags("Opeth", "Watershed"), [{"name": "metal", "count": 5}])


class LastFmAlbumInfoTests(_ClientTestCase):
    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_returns_listeners_and_playcount_as_ints(self, mock_get):
        mock_get.return_value = _mock_response(
            payload={"album": {"name": "Blackwater Park", "listeners": "123456", "playcount": "7894561"}}
        )

        self.assertEqual(
            lastfm_client.get_album_info("Opeth", "Blackwater Park"),
            {"listeners": 123456, "playcount": 7894561},
        )

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_missing_album_returns_empty_dict(self, mock_get):
        mock_get.return_value = _mock_response(payload={"error": 6, "message": "Album not found"})

        self.assertEqual(lastfm_client.get_album_info("Opeth", "Nope"), {})


class LastFmAlbumFullInfoTests(_ClientTestCase):
    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_returns_tags_and_stats_in_one_call(self, mock_get):
        mock_get.return_value = _mock_response(
            payload={
                "album": {
                    "name": "Blackwater Park",
                    "listeners": "123456",
                    "playcount": "7894561",
                    "toptags": {
                        "tag": [
                            {"name": "progressive metal", "count": "100"},
                            {"name": "melancholic", "count": "45"},
                        ]
                    },
                }
            }
        )

        self.assertEqual(
            lastfm_client.get_album_full_info("Opeth", "Blackwater Park"),
            {
                "listeners": 123456,
                "playcount": 7894561,
                "tags": [
                    {"name": "progressive metal", "count": 100},
                    {"name": "melancholic", "count": 45},
                ],
            },
        )

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_missing_album_returns_empty_dict(self, mock_get):
        mock_get.return_value = _mock_response(payload={"error": 6, "message": "Album not found"})

        self.assertEqual(lastfm_client.get_album_full_info("Opeth", "Nope"), {})

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_falls_back_to_gettoptags_when_info_has_no_tags(self, mock_get):
        """Si ``album.getinfo`` ya no trae ``toptags``, usa ``album.gettoptags``."""
        from itertools import count

        api_key = lastfm_client.settings.LASTFM_API_KEY
        calls = count()
        payloads = [
            {"album": {"listeners": "100", "playcount": "500", "name": "Blackwater Park"}},
            {"toptags": {"tag": [{"name": "progressive metal", "count": "100"}]}},
        ]

        def side_effect(url, params, timeout):
            call = next(calls)
            return _mock_response(payload=payloads[call])

        mock_get.side_effect = side_effect

        info = lastfm_client.get_album_full_info("Opeth", "Blackwater Park")

        self.assertEqual(info["listeners"], 100)
        self.assertEqual(
            info["tags"], [{"name": "progressive metal", "count": 100}]
        )
        self.assertEqual(mock_get.call_count, 2)
        second_params = mock_get.call_args_list[1].kwargs["params"]
        self.assertEqual(second_params["method"], "album.gettoptags")
        self.assertEqual(second_params["api_key"], api_key)


class LastFmRateLimitTests(_ClientTestCase):
    """Reintentos y errores claros cuando Last.fm limita las consultas."""

    def _get_mock(self, payload=None):
        return mock.patch("catalog.services.lastfm_client.requests.get")

    def _no_sleep(self):
        return mock.patch("catalog.services.lastfm_client.time.sleep")

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_transient_503_is_retried_and_returns_data(self, mock_get):
        mock_get.side_effect = [
            _mock_response(status_code=503),
            _mock_response(
                payload={"similarartists": {"artist": [{"name": "Tool"}]}}
            ),
        ]
        with self._no_sleep():
            result = lastfm_client.get_similar_artists("Opeth")

        self.assertEqual(result, ["Tool"])
        self.assertEqual(mock_get.call_count, 2)

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_persistent_503_raises_friendly_error(self, mock_get):
        mock_get.side_effect = [
            _mock_response(status_code=503),
            _mock_response(status_code=503),
            _mock_response(status_code=503),
        ]
        with self._no_sleep():
            with self.assertRaises(lastfm_client.LastFMError) as ctx:
                lastfm_client.get_similar_artists("Opeth")

        self.assertIn("limitando", str(ctx.exception))
        self.assertEqual(mock_get.call_count, 3)

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_body_rate_limit_error_raises_instead_of_empty_list(self, mock_get):
        mock_get.return_value = _mock_response(
            payload={"error": 29, "message": "Rate limit exceeded"}
        )

        with self.assertRaises(lastfm_client.LastFMError) as ctx:
            lastfm_client.get_similar_artists("Opeth")

        self.assertIn("limitando", str(ctx.exception))

    @mock.patch("catalog.services.lastfm_client.requests.get")
    def test_other_body_errors_still_return_none(self, mock_get):
        mock_get.return_value = _mock_response(
            payload={"error": 6, "message": "Artist not found"}
        )

        self.assertEqual(lastfm_client.get_similar_artists("Nobody"), [])


class CachedArtistGraphTests(TestCase):
    """Tests del caché de artistas similares y top albums por artista."""

    def setUp(self):
        self._lastfm_interval = lastfm_client._lastfm_throttle.min_interval
        lastfm_client._lastfm_throttle.min_interval = 0

    def tearDown(self):
        lastfm_client._lastfm_throttle.min_interval = self._lastfm_interval

    @mock.patch("catalog.services.lastfm_client.get_similar_artists")
    def test_similar_artists_are_cached_per_artist(self, mock_similar):
        mock_similar.return_value = ["Tool", "Porcupine Tree"]

        first = cache.cached_similar_artists("Opeth")
        second = cache.cached_similar_artists("Opeth")

        self.assertEqual(first, ["Tool", "Porcupine Tree"])
        self.assertEqual(second, ["Tool", "Porcupine Tree"])
        mock_similar.assert_called_once_with("Opeth", limit=6)
        artist = Artist.objects.get(name="Opeth")
        self.assertEqual(artist.similar_artists, ["Tool", "Porcupine Tree"])

    @mock.patch("catalog.services.lastfm_client.get_top_albums")
    def test_top_albums_are_cached_per_artist(self, mock_top):
        mock_top.return_value = [("Blackwater Park", "Opeth"), ("Watershed", "Opeth")]

        first = cache.cached_top_albums("Opeth")
        second = cache.cached_top_albums("Opeth")

        self.assertEqual(
            first,
            [
                {"title": "Blackwater Park", "artist": "Opeth"},
                {"title": "Watershed", "artist": "Opeth"},
            ],
        )
        self.assertEqual(second, first)
        mock_top.assert_called_once_with("Opeth", limit=2)


class GetOrFetchAlbumCacheTests(TestCase):
    """Tests de la capa cache-first con las APIs mockeadas."""

    def setUp(self):
        self._lastfm_interval = lastfm_client._lastfm_throttle.min_interval
        lastfm_client._lastfm_throttle.min_interval = 0

    def tearDown(self):
        lastfm_client._lastfm_throttle.min_interval = self._lastfm_interval

    @mock.patch("catalog.services.lastfm_client.get_album_full_info")
    def test_fetches_and_creates_album_from_lastfm(self, mock_info):
        mock_info.return_value = {
            "listeners": 1000,
            "playcount": 5000,
            "tags": [{"name": "melancholic", "count": 45}],
        }

        album = cache.get_or_fetch_album("Opeth", "Blackwater Park")

        mock_info.assert_called_once_with("Opeth", "Blackwater Park")

        self.assertEqual(Album.objects.count(), 1)
        self.assertEqual(Artist.objects.count(), 1)
        self.assertEqual(album.artist.name, "Opeth")
        self.assertEqual(album.title, "Blackwater Park")
        self.assertEqual(album.tags, [{"name": "melancholic", "count": 45}])
        self.assertEqual(album.listeners, 1000)
        self.assertEqual(album.playcount, 5000)
        self.assertEqual(album.tag_document, "melancholic")

    @mock.patch("catalog.services.lastfm_client.get_album_full_info")
    def test_second_call_uses_cache_without_api(self, mock_info):
        mock_info.return_value = {
            "listeners": 100,
            "playcount": 200,
            "tags": [{"name": "art rock", "count": 10}],
        }

        first = cache.get_or_fetch_album("Radiohead", "OK Computer")
        second = cache.get_or_fetch_album("Radiohead", "OK Computer")

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Album.objects.count(), 1)
        mock_info.assert_called_once()

    @mock.patch("catalog.services.lastfm_client.get_album_full_info")
    def test_fresh_album_without_tags_is_refetched(self, mock_info):
        """Un álbum fresco pero sin tags se vuelve a pedir para rehidratarlo."""
        mock_info.return_value = {
            "listeners": 100,
            "playcount": 200,
            "tags": [{"name": "art rock", "count": 10}],
        }

        first = cache.get_or_fetch_album("Radiohead", "Pablo Honey")
        Album.objects.filter(pk=first.pk).update(tag_document="")

        second = cache.get_or_fetch_album("Radiohead", "Pablo Honey")

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(mock_info.call_count, 2)
        self.assertEqual(second.tag_document, "art rock")

    @mock.patch("catalog.services.lastfm_client.get_album_full_info")
    def test_expired_cache_triggers_refetch(self, mock_info):
        artist = Artist.objects.create(name="Massive Attack")
        album = Album.objects.create(artist=artist, title="Mezzanine", listeners=1, playcount=1)
        Album.objects.filter(pk=album.pk).update(cached_at=timezone.now() - timedelta(days=90))

        mock_info.return_value = {"listeners": 200, "playcount": 900}

        refreshed = cache.get_or_fetch_album("Massive Attack", "Mezzanine")

        mock_info.assert_called_once()
        self.assertEqual(refreshed.pk, album.pk)
        refreshed.refresh_from_db()
        self.assertEqual(refreshed.tags, [])
        self.assertEqual(refreshed.listeners, 200)

    @mock.patch("catalog.services.lastfm_client.get_album_full_info")
    def test_api_is_down_creates_album_with_defaults(self, mock_info):
        mock_info.return_value = {}

        album = cache.get_or_fetch_album("Unknown Artist", "Unknown Album")

        self.assertEqual(album.tags, [])
        self.assertEqual(album.listeners, 0)
        self.assertEqual(album.playcount, 0)
        self.assertEqual(album.tag_document, "")

    @mock.patch("catalog.services.lastfm_client.get_album_full_info")
    def test_reuses_existing_artist(self, mock_info):
        Artist.objects.create(name="Pink Floyd")
        mock_info.return_value = {}

        cache.get_or_fetch_album("Pink Floyd", "Dark Side of the Moon")
        cache.get_or_fetch_album("Pink Floyd", "The Wall")

        self.assertEqual(Artist.objects.count(), 1)
        self.assertEqual(Album.objects.count(), 2)