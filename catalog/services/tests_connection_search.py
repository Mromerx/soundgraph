"""Tests unitarios del motor de búsqueda de conexión entre artistas.

Solo cubren las funciones puras ``find_intersection`` y ``reconstruct_path``
con datos construidos en memoria: no tocan la API de Last.fm. La validación
del comportamiento end-to-end (``expand_one_level`` + ``run_full_search``)
se hace contra la API real en la corrida manual, no acá.
"""
from django.test import SimpleTestCase

from catalog.models import ConnectionSearch
from catalog.services.connection_search import find_intersection, reconstruct_path


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