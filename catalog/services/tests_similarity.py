"""Tests unitarios del motor de similitud musical.

Usan la base de datos de test de Django con álbumes de prueba hardcodeados:
no dependen de la base de datos real ni de la API de Last.fm. Los
``tag_document`` se fijan a mano para aislar la lógica del TF-IDF y la
selección por score máximo.
"""
import numpy as np

from django.test import TestCase

from catalog.models import Album, AlbumSimilarity, Artist
from catalog.services.similarity import (
    build_tag_document,
    compute_artist_centroid,
    compute_similarity_matrix,
    is_atypical_album,
    recommend,
)


def _make_artist(name):
    artist, _ = Artist.objects.get_or_create(name=name)
    return artist


def _make_album(artist, title, tag_document=None, tags=None):
    return Album.objects.create(
        artist=artist,
        title=title,
        tags=tags or [],
        tag_document=tag_document or "",
    )


class BuildTagDocumentTests(TestCase):
    def test_repeats_tags_by_count_and_lowercases(self):
        album = _make_album(
            _make_artist("Opeth"),
            "Blackwater Park",
            tags=[
                {"name": "Progressive", "count": 100},
                {"name": "Obscure", "count": 4},
                {"name": "Melancholic", "count": 40},
            ],
        )

        document = build_tag_document(album)

        # "Progressive" 100//20=5 veces; "Melancholic" 40//20=2 veces;
        # "Obscure" se descarta por ser < 5.
        self.assertEqual(
            document,
            "progressive progressive progressive progressive progressive "
            "melancholic melancholic",
        )

    def test_tags_below_five_are_filtered_out(self):
        album = _make_album(
            _make_artist("Yuri"),
            "Bajo el signo de Caín",
            tags=[
                {"name": "vibrante", "count": 4},
                {"name": "punk", "count": 2},
            ],
        )

        document = build_tag_document(album)

        self.assertEqual(document, "")

    def test_minimum_repetition_is_one(self):
        album = _make_album(
            _make_artist("Death"),
            "Human",
            tags=[{"name": "metal", "count": 5}],
        )

        document = build_tag_document(album)

        # 5 // 20 == 0, pero max(1, 0) == 1: el tag no se pierde.
        self.assertEqual(document, "metal")

    def test_persists_document_on_saved_album(self):
        album = _make_album(
            _make_artist("NIN"),
            "The Downward Spiral",
            tags=[{"name": "Industrial", "count": 60}],
        )

        build_tag_document(album)

        album.refresh_from_db()
        self.assertEqual(album.tag_document, "industrial industrial industrial")


class ComputeSimilarityMatrixTests(TestCase):
    def test_returns_symmetric_matrix_with_unit_diagonal(self):
        artist = _make_artist("Metallica")
        albums = [
            _make_album(artist, "Master of Puppets"),
            _make_album(artist, "Ride the Lightning"),
            _make_album(artist, "Load"),
        ]
        albums[0].tag_document = "metal thrash"
        albums[1].tag_document = "metal thrash speed"
        albums[2].tag_document = "alternative rock"

        matrix, returned = compute_similarity_matrix(albums)

        self.assertIs(returned, albums)
        self.assertEqual(matrix.shape, (3, 3))
        np.testing.assert_allclose(np.diag(matrix), np.ones(3), atol=1e-9)
        np.testing.assert_allclose(matrix, matrix.T, atol=1e-9)

    def test_builds_missing_tag_documents(self):
        artist = _make_artist("Pink Floyd")
        album = _make_album(artist, "The Wall", tags=[{"name": "Progressive", "count": 60}])

        compute_similarity_matrix([album])

        self.assertEqual(album.tag_document, "progressive progressive progressive")

    def test_identical_documents_are_perfectly_similar(self):
        artist = _make_artist("Black Sabbath")
        first = _make_album(artist, "Paranoid", tag_document="heavy metal")
        second = _make_album(artist, "Sabbath Bloody Sabbath", tag_document="heavy metal")

        matrix, _ = compute_similarity_matrix([first, second])

        self.assertAlmostEqual(matrix[0, 1], 1.0, places=6)

    def test_all_empty_documents_return_zero_matrix(self):
        artist = _make_artist("Sen Sin Tags")
        albums = [
            _make_album(artist, "Uno", tag_document=""),
            _make_album(artist, "Dos", tag_document=""),
            _make_album(artist, "Tres", tag_document=""),
        ]

        matrix, returned = compute_similarity_matrix(albums)

        self.assertIs(returned, albums)
        self.assertEqual(matrix.shape, (3, 3))
        np.testing.assert_allclose(matrix, np.zeros((3, 3)), atol=1e-9)

    def test_empty_documents_get_zero_rows(self):
        artist = _make_artist("Titular")
        first = _make_album(artist, "Con tags", tag_document="metal thrash")
        second = _make_album(artist, "Sin tags", tag_document="")

        matrix, _ = compute_similarity_matrix([first, second])

        self.assertEqual(matrix.shape, (2, 2))
        np.testing.assert_allclose(matrix[0], matrix[0])
        np.testing.assert_allclose(matrix[1], np.zeros(2), atol=1e-9)


class RecommendTests(TestCase):
    def _seed(self, name, document):
        return _make_album(_make_artist(name), "seed", tag_document=document)

    def _candidate(self, name, document):
        return _make_album(_make_artist(name), "candidate", tag_document=document)

    def test_uses_max_similarity_not_average(self):
        seed_metal = self._seed("Metallica", "metal thrash")
        seed_jazz = self._seed("Miles Davis", "jazz fusion")
        candidate = self._candidate("Pantera", "metal thrash")

        results = recommend([seed_metal, seed_jazz], [candidate])

        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0]["score"], 1.0, places=6)
        # Si el score fuera el promedio con "jazz fusion", sería < 1.0.
        self.assertIs(results[0]["matched_seed"], seed_metal)
        self.assertIs(results[0]["album"], candidate)
        # Solo conecta con las semillas con las que comparte etiquetas.
        self.assertEqual(len(results[0]["matched_seeds"]), 1)
        self.assertIs(results[0]["matched_seeds"][0]["album"], seed_metal)
        self.assertAlmostEqual(results[0]["matched_seeds"][0]["score"], 1.0, places=6)

    def test_lists_all_connected_seeds_with_their_own_cosine(self):
        seed_metal = self._seed("Metallica", "metal thrash")
        seed_jazz = self._seed("Miles Davis", "jazz fusion")
        bridging = self._candidate("Chimaira", "metal thrash jazz")

        results = recommend([seed_metal, seed_jazz], [bridging])

        self.assertEqual(len(results), 1)
        connected = {item["album"]: item["score"] for item in results[0]["matched_seeds"]}
        self.assertEqual(set(connected), {seed_metal, seed_jazz})
        self.assertGreater(connected[seed_metal], 0)
        self.assertGreater(connected[seed_jazz], 0)

    def test_drops_candidates_with_zero_cosine(self):
        seed = self._seed("Metallica", "metal thrash")
        unrelated = self._candidate("Golden Earring", "baroque classical")

        results = recommend([seed], [unrelated])

        self.assertEqual(results, [])

    def test_sorts_results_by_max_score_descending(self):
        seed_metal = self._seed("Metallica", "metal thrash")
        seed_jazz = self._seed("Miles Davis", "jazz fusion")
        metal_like = self._candidate("Pantera", "metal thrash")
        jazz_like = self._candidate("Coltrane", "jazz fusion")
        only_jazz = self._candidate("Bill Evans", "jazz")

        results = recommend([seed_metal, seed_jazz], [jazz_like, metal_like, only_jazz])

        self.assertAlmostEqual(results[0]["score"], 1.0, places=6)
        self.assertAlmostEqual(results[1]["score"], 1.0, places=6)
        # "only_jazz" comparte el vocabulario solo con la semilla de jazz y
        # queda último, con un score inferior a los que empatan exacto.
        self.assertIs(results[-1]["album"], only_jazz)
        self.assertIs(results[-1]["matched_seed"], seed_jazz)
        self.assertGreater(results[0]["score"], results[-1]["score"])

    def test_respects_n_results(self):
        seed = self._seed("Metallica", "metal thrash")
        candidates = [
            self._candidate("Pantera", "metal thrash"),
            self._candidate("Slayer", "metal thrash"),
            self._candidate("Dio", "metal thrash"),
        ]

        results = recommend([seed], candidates, n_results=2)

        self.assertEqual(len(results), 2)

    def test_persists_similarities_without_duplicates(self):
        seed = self._seed("Metallica", "metal thrash")
        candidates = [
            self._candidate("Pantera", "metal thrash"),
            self._candidate("Dio", "metal thrash"),
        ]

        first = recommend([seed], candidates)
        second = recommend([seed], candidates)

        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        self.assertEqual(AlbumSimilarity.objects.filter(album_a=seed).count(), 2)
        scores = {
            score.album_b_id: score.score
            for score in AlbumSimilarity.objects.filter(album_a=seed)
        }
        self.assertEqual(scores, {item["album"].id: item["score"] for item in first})

    def test_empty_candidates_returns_empty_list(self):
        seed = self._seed("Metallica", "metal thrash")

        self.assertEqual(recommend([seed], []), [])

    def test_all_empty_documents_do_not_crash(self):
        seed = _make_album(_make_artist("Vacío"), "semilla", tag_document="")
        candidate = _make_album(_make_artist("Vacío 2"), "candidato", tag_document="")

        results = recommend([seed], [candidate])

        self.assertEqual(results, [])

    def test_validates_seed_range(self):
        seed = self._seed("Metallica", "metal thrash")
        candidates = [self._candidate("Pantera", "metal thrash")]

        with self.assertRaises(ValueError):
            recommend([], candidates)
        with self.assertRaises(ValueError):
            recommend([seed] * 6, candidates)

    def test_validates_n_results_range(self):
        seed = self._seed("Metallica", "metal thrash")
        candidates = [self._candidate("Pantera", "metal thrash")]

        with self.assertRaises(ValueError):
            recommend([seed], candidates, n_results=0)
        with self.assertRaises(ValueError):
            recommend([seed], candidates, n_results=6)


class ComputeArtistCentroidTests(TestCase):
    def test_returns_centroid_and_fitted_vectorizer(self):
        artist = _make_artist("Opeth")
        _make_album(artist, "Blackwater Park", tag_document="progressive metal")
        _make_album(artist, "Damnation", tag_document="progressive rock")

        centroid, vectorizer = compute_artist_centroid(artist)

        self.assertIsInstance(centroid, np.ndarray)
        self.assertEqual(centroid.ndim, 1)
        self.assertEqual(centroid.shape, (len(vectorizer.get_feature_names_out()),))
        self.assertEqual(set(vectorizer.get_feature_names_out()), {"progressive", "metal", "rock"})

    def test_raises_for_artist_without_albums(self):
        artist = _make_artist("Sin Discografía")

        with self.assertRaises(ValueError):
            compute_artist_centroid(artist)

    def test_all_empty_documents_return_zero_centroid(self):
        artist = _make_artist("Álbumes Sin Tags")
        _make_album(artist, "Uno", tag_document="")
        _make_album(artist, "Dos", tag_document="")

        centroid, vectorizer = compute_artist_centroid(artist)

        self.assertEqual(centroid.shape, (len(vectorizer.get_feature_names_out()),))
        np.testing.assert_allclose(centroid, np.zeros(centroid.shape), atol=1e-9)

    def test_vectorizer_reuses_vocabulary_for_new_albums(self):
        artist = _make_artist("Opeth")
        _make_album(artist, "Blackwater Park", tag_document="progressive metal")
        _make_album(artist, "Damnation", tag_document="progressive rock")

        centroid, vectorizer = compute_artist_centroid(artist)
        album = _make_album(artist, "Heritage", tag_document="progressive metal old prog")

        vector = vectorizer.transform([album.tag_document])

        self.assertEqual(vector.shape, (1, centroid.shape[0]))


class IsAtypicalAlbumTests(TestCase):
    def setUp(self):
        self.artist = _make_artist("Metallica")
        _make_album(self.artist, "Master of Puppets", tag_document="metal thrash")
        _make_album(self.artist, "Ride the Lightning", tag_document="metal thrash")
        self.centroid, self.vectorizer = compute_artist_centroid(self.artist)

    def test_typical_album_returns_false_with_small_distance(self):
        typical = _make_album(self.artist, "Kill 'Em All", tag_document="metal thrash")

        atypical, distance = is_atypical_album(typical, self.centroid, self.vectorizer)

        self.assertFalse(atypical)
        self.assertAlmostEqual(distance, 0.0, places=6)

    def test_atypical_album_returns_true_with_high_distance(self):
        atypical = _make_album(self.artist, "Lulu", tag_document="spoken word noise ballad")

        result, distance = is_atypical_album(atypical, self.centroid, self.vectorizer)

        self.assertTrue(result)
        self.assertAlmostEqual(distance, 1.0, places=6)

    def test_custom_threshold(self):
        # Comparte solo una de las dos palabras del vocabulario del centroide,
        # así que la distancia queda en un valor intermedio (entre 0.1 y 0.9).
        atypical = _make_album(self.artist, "Some Kind of Monster", tag_document="metal")

        strict_result, distance = is_atypical_album(
            atypical, self.centroid, self.vectorizer, threshold=0.9
        )
        lax_result, _ = is_atypical_album(
            atypical, self.centroid, self.vectorizer, threshold=0.1
        )

        self.assertTrue(0.1 < distance < 0.9)
        self.assertFalse(strict_result)
        self.assertTrue(lax_result)

    def test_returns_exact_distance_even_when_below_threshold(self):
        typical = _make_album(self.artist, "Reload", tag_document="metal thrash")
        result, distance = is_atypical_album(
            typical, self.centroid, self.vectorizer, threshold=0.2
        )

        self.assertFalse(result)
        self.assertAlmostEqual(distance, 0.0, places=6)