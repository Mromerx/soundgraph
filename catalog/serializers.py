"""Serializers del catálogo.

Incluyen la validación de rango (1-5 seeds, 1-5 resultados) exigida por los
endpoints REST del sistema de recomendación, además del serializado plano de
las respuestas (sin referencias a modelos, para no acoplar el API a la ORM).
"""
from rest_framework import serializers


class SeedSerializer(serializers.Serializer):
    """Un par artista/álbum usado como semilla del grafo de afinidad."""

    artist = serializers.CharField(max_length=255)
    album = serializers.CharField(max_length=255)


class RecommendationsRequestSerializer(serializers.Serializer):
    """Valida el body de ``POST /api/recommendations/``.

    Exige entre 1 y 5 seeds y un ``n_results`` entre 1 y 15.
    """

    seeds = SeedSerializer(many=True)
    n_results = serializers.IntegerField(min_value=1, max_value=15)

    def validate_seeds(self, value):
        if not 1 <= len(value) <= 5:
            raise serializers.ValidationError(
                "Debes enviar entre 1 y 5 álbumes semilla."
            )
        return value


class ArtistSearchSerializer(serializers.Serializer):
    """Resultado de la búsqueda de artistas en Last.fm."""

    name = serializers.CharField()
    mbid = serializers.CharField(allow_blank=True)
    listeners = serializers.IntegerField()


class AlbumSearchSerializer(serializers.Serializer):
    """Resultado de la búsqueda de álbumes de un artista en Last.fm."""

    title = serializers.CharField()
    mbid = serializers.CharField(allow_blank=True)


class AtypicalAlbumSerializer(serializers.Serializer):
    """Un álbum evaluado contra el centroide de su artista."""

    artist = serializers.CharField()
    album = serializers.CharField()
    distance = serializers.FloatField()


class ConnectionSearchRequestSerializer(serializers.Serializer):
    """Valida el body de ``POST /api/connections/``.

    Exige entre 2 y 5 artistas semilla para correr la búsqueda de artista
    puente.
    """

    seed_artists = serializers.ListField(
        child=serializers.CharField(max_length=255),
        min_length=2,
        max_length=5,
    )

    def validate_seed_artists(self, value):
        if not 2 <= len(value) <= 5:
            raise serializers.ValidationError(
                "Debes enviar entre 2 y 5 artistas semilla."
            )
        return value


class ConnectionSearchControlSerializer(serializers.Serializer):
    """Valida el body de ``PATCH /api/connections/{search_id}/``.

    La acción de control aplica sobre una búsqueda en curso:
    ``pause``, ``resume`` o ``stop``.
    """

    action = serializers.ChoiceField(
        choices=["pause", "resume", "stop"],
        error_messages={"invalid_choice": "Acción de control no válida."},
    )