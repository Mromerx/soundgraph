"""Tests unitarios del motor de similitud musical.

Usan la base de datos de test de Django con álbumes de prueba hardcodeados:
no dependen de la base de datos real ni de la API de Last.fm. Los
``tag_document`` se fijan a mano para aislar la lógica del TF-IDF,
del score (mezcla max-promedio) y del ranking por MMR.
"""
import numpy as np

from django.test import TestCase

from catalog.models import Album, AlbumSimilarity, Artist
from catalog.services.similarity import (
    _blend_score,
    _rank_with_diversity,
    build_tag_document,
    compute_artist_centroid,
    compute_similarity_matrix,
    ensure_tag_document,
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

        document = build_tag_document(album.tags)

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

        document = build_tag_document(album.tags)

        self.assertEqual(document, "")

    def test_minimum_repetition_is_one(self):
        album = _make_album(
            _make_artist("Death"),
            "Human",
            tags=[{"name": "metal", "count": 5}],
        )

        document = build_tag_document(album.tags)

        # 5 // 20 == 0, pero max(1, 0) == 1: el tag no se pierde.
        self.assertEqual(document, "metal")

    def test_is_pure_against_the_raw_tags(self):
        self.assertEqual(build_tag_document([]), "")
        self.assertEqual(build_tag_document([{"name": "Rock"}]), "")

    def test_has_one_single_source_of_truth_with_cache_layer(self):
        # El builder canónico es el que usa la capa de cache al persistir; acá
        # se importa desde el mismo módulo que consume cache.py para garantizar
        # que no exista una segunda definición del documento.
        from catalog.services.cache import build_tag_document as cache_builder

        self.assertIs(cache_builder, build_tag_document)


class EnsureTagDocumentTests(TestCase):
    def test_persists_document_on_saved_album(self):
        album = _make_album(
            _make_artist("NIN"),
            "The Downward Spiral",
            tags=[{"name": "Industrial", "count": 60}],
        )

        ensure_tag_document(album)

        album.refresh_from_db()
        self.assertEqual(album.tag_document, "industrial industrial industrial")

    def test_reuses_existing_document_without_rebuilding(self):
        artist = _make_artist("NIN")
        album = _make_album(
            artist,
            "Pretty Hate Machine",
            tags=[{"name": "Industrial", "count": 60}],
            tag_document="already built",
        )

        self.assertEqual(ensure_tag_document(album), "already built")
        album.refresh_from_db()
        self.assertEqual(album.tag_document, "already built")


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


class BlendScoreTests(TestCase):
    def test_weights_max_and_mean_over_all_seeds(self):
        row = np.array([1.0, 0.0, 0.0])
        self.assertAlmostEqual(_blend_score(row), 0.6 * 1.0 + 0.4 * (1.0 / 3.0))

    def test_single_seed_reduces_to_pure_cosine(self):
        # Con una sola semilla mean == max, así que la mezcla es el coseno puro.
        self.assertAlmostEqual(_blend_score(np.array([0.7])), 0.7)

    def test_no_overlap_scores_zero(self):
        self.assertAlmostEqual(_blend_score(np.array([0.0, 0.0])), 0.0)


class RankWithDiversityTests(TestCase):
    """MMR: penaliza la redundancia con los ya elegidos y el mismo artista."""

    def test_prefers_distinct_artist_over_same_artist_repeat(self):
        artist_x = _make_artist("X")
        artist_y = _make_artist("Y")
        items = [
            {"album": _make_album(artist_x, "one"), "mat_index": 0, "score": 1.0},
            {"album": _make_album(artist_y, "two"), "mat_index": 1, "score": 0.8},
            {"album": _make_album(artist_x, "three"), "mat_index": 2, "score": 0.99},
        ]
        matrix = np.array(
            [
                [1.0, 0.2, 1.0],
                [0.2, 1.0, 0.2],
                [1.0, 0.2, 1.0],
            ]
        )

        ranked = _rank_with_diversity(items, matrix, diversity=0.6)

        # El mejor candidato va primero; luego se prefiere al artista distinto
        # (Y, más similar por contenido pero recién puntúa 0.8 con el centro
        # de su score) antes que al tercer álbum del mismo artista X, que paga
        # la penalización de artista forzada a 1.
        order = [item["album"] for item in ranked]
        self.assertIs(order[0], items[0]["album"])
        self.assertIs(order[1], items[1]["album"])
        self.assertIs(order[2], items[2]["album"])

    def test_content_redundancy_penalizes_clones(self):
        # Dos álbumes de artistas distintos pero con documentos casi idénticos
        # (clone en contenido, coseno 1.0): el clon pierde prioridad frente a
        # un tercero de artista distinto y sonido distinto, aunque su score sea
        # menor. El tercero no paga penalización por redundancia.
        artist_a = _make_artist("A")
        artist_b = _make_artist("B")
        artist_c = _make_artist("C")
        items = [
            {"album": _make_album(artist_a, "one"), "mat_index": 0, "score": 1.0},
            {"album": _make_album(artist_b, "two"), "mat_index": 1, "score": 1.0},
            {"album": _make_album(artist_c, "three"), "mat_index": 2, "score": 0.6},
        ]
        matrix = np.array(
            [
                [1.0, 1.0, 0.1],
                [1.0, 1.0, 0.1],
                [0.1, 0.1, 1.0],
            ]
        )

        ranked = _rank_with_diversity(items, matrix, diversity=0.6)

        # Primero uno de los clones; luego un album distinto (0.6*0.6 - 0.4*0.1
        # = 0.32) por delante del clon restante (0.6*1.0 - 0.4*1.0 = 0.2).
        self.assertIs(ranked[0]["album"], items[0]["album"])
        self.assertIs(ranked[1]["album"], items[2]["album"])
        self.assertIs(ranked[2]["album"], items[1]["album"])


class RecommendTests(TestCase):
    def _seed(self, name, document):
        return _make_album(_make_artist(name), "seed", tag_document=document)

    def _candidate(self, name, document):
        return _make_album(_make_artist(name), "candidate", tag_document=document)

    def test_score_is_max_mean_blend_of_the_seed_rows(self):
        seed_metal = self._seed("Metallica", "metal rock")
        seed_jazz = self._seed("Dream Theater", "metal progressive")
        broad = self._candidate("Haken", "metal progressive rock")

        matrix, _ = compute_similarity_matrix([seed_metal, seed_jazz, broad])
        row = matrix[2, :2]

        results = recommend([seed_metal, seed_jazz], [broad])

        self.assertEqual(len(results), 1)
        self.assertIs(results[0]["album"], broad)
        self.assertAlmostEqual(
            results[0]["score"],
            _blend_score(row),
            places=6,
        )

    def test_score_lists_every_connected_seed_with_raw_cosine(self):
        seed_metal = self._seed("Metallica", "metal thrash")
        seed_jazz = self._seed("Miles Davis", "jazz fusion")
        bridging = self._candidate("Chimaira", "metal thrash jazz")

        results = recommend([seed_metal, seed_jazz], [bridging])

        self.assertEqual(len(results), 1)
        self.assertIs(results[0]["matched_seed"], seed_metal)
        connected = {item["album"]: item["score"] for item in results[0]["matched_seeds"]}
        self.assertEqual(set(connected), {seed_metal, seed_jazz})
        self.assertGreater(connected[seed_metal], 0)
        self.assertGreater(connected[seed_jazz], 0)

    def test_single_seed_score_equals_cosine(self):
        # Con una semilla la mezcla max-promedio se reduce al coseno puro.
        seed = self._seed("Metallica", "metal thrash")
        partial = self._candidate("Pantera", "metal")

        matrix, _ = compute_similarity_matrix([seed, partial])

        results = recommend([seed], [partial])

        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0]["score"], matrix[0, 1], places=6)

    def test_breaks_ties_among_equal_max_in_favor_of_more_coverage(self):
        # Dos candidatos con el mismo match máximo contra alguna semilla: el
        # que además conecta con la segunda semilla suma en el promedio y gana.
        seed_metal = self._seed("Metallica", "metal rock")
        seed_melodic = self._seed("Dream Theater", "metal progressive")
        thin = self._candidate("Pantera", "metal rock")
        broad = self._candidate("Haken", "metal rock progressive")

        matrix, _ = compute_similarity_matrix(
            [seed_metal, seed_melodic, thin, broad]
        )
        thin_score = _blend_score(matrix[2, :2])
        broad_score = _blend_score(matrix[3, :2])

        results = recommend([seed_metal, seed_melodic], [broad, thin])

        # Ambos se recomiendan; el de mayor coverage va primero.
        self.assertEqual(len(results), 2)
        if broad_score > thin_score:
            self.assertIs(results[0]["album"], broad)
        else:
            self.assertIs(results[0]["album"], thin)
        self.assertGreater(results[0]["score"], results[1]["score"])

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

    def test_drops_candidates_with_zero_cosine(self):
        seed = self._seed("Metallica", "metal thrash")
        unrelated = self._candidate("Golden Earring", "baroque classical")

        results = recommend([seed], [unrelated])

        self.assertEqual(results, [])

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
            recommend([seed], candidates, n_results=16)


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