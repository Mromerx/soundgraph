from django.contrib import admin

from .models import Album, AlbumSimilarity, Artist, ConnectionSearch, UserFavorite


@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = ("name", "mbid", "cached_at")
    search_fields = ("name", "mbid")


@admin.register(Album)
class AlbumAdmin(admin.ModelAdmin):
    list_display = ("title", "artist", "listeners", "playcount", "cached_at")
    list_filter = ("artist",)
    search_fields = ("title", "artist__name")


@admin.register(AlbumSimilarity)
class AlbumSimilarityAdmin(admin.ModelAdmin):
    list_display = ("album_a", "album_b", "score", "computed_at")
    list_filter = ("computed_at",)
    search_fields = ("album_a__title", "album_a__artist__name", "album_b__title", "album_b__artist__name")


@admin.register(UserFavorite)
class UserFavoriteAdmin(admin.ModelAdmin):
    list_display = ("user", "album", "added_at")
    search_fields = ("user__username", "album__title")


@admin.register(ConnectionSearch)
class ConnectionSearchAdmin(admin.ModelAdmin):
    list_display = ("seed_artists", "status", "current_depth", "bridge_artist", "updated_at")
    list_filter = ("status",)