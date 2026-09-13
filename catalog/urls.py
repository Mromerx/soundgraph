"""Rutas de la app ``catalog``: endpoints de recomendación y atipicalidad."""
from django.urls import path

from .views import (
    ArtistAlbumsView,
    ArtistSearchView,
    AtypicalAlbumsView,
    ConnectionSearchCreateView,
    ConnectionSearchEventsView,
    ConnectionSearchStatusView,
    RecommendationsView,
)

app_name = "catalog"

urlpatterns = [
    path(
        "recommendations/",
        RecommendationsView.as_view(),
        name="recommendations",
    ),
    path(
        "search/artists/",
        ArtistSearchView.as_view(),
        name="search-artists",
    ),
    path(
        "search/albums/",
        ArtistAlbumsView.as_view(),
        name="artist-albums",
    ),
    path(
        "artists/<int:artist_id>/atypical-albums/",
        AtypicalAlbumsView.as_view(),
        name="atypical-albums",
    ),
    path(
        "connections/",
        ConnectionSearchCreateView.as_view(),
        name="connections",
    ),
    path(
        "connections/<uuid:search_id>/",
        ConnectionSearchStatusView.as_view(),
        name="connections-detail",
    ),
    path(
        "connections/<uuid:search_id>/events",
        ConnectionSearchEventsView.as_view(),
        name="connections-events",
    ),
]