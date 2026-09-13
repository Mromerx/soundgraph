import uuid

from django.conf import settings
from django.db import models


class Artist(models.Model):
    name = models.CharField(max_length=255, unique=True)
    mbid = models.CharField(max_length=100, null=True, blank=True)
    similar_artists = models.JSONField(default=list)  # caché: ["Tool", "Porcupine Tree", ...]
    top_albums = models.JSONField(default=list)       # caché: [{"title": ..., "artist": ...}, ...]
    cached_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Album(models.Model):
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name="albums")
    title = models.CharField(max_length=255)
    tags = models.JSONField(default=list)        # Last.fm: [{"name": "melancholic", "count": 45}, ...]
    listeners = models.IntegerField(default=0)   # Last.fm
    playcount = models.IntegerField(default=0)   # Last.fm
    tag_document = models.TextField(blank=True)  # documento de texto ya mezclado, para TF-IDF
    cached_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("artist", "title")

    def __str__(self):
        return f"{self.artist.name} - {self.title}"


class AlbumSimilarity(models.Model):
    album_a = models.ForeignKey(Album, related_name="similarities_as_a", on_delete=models.CASCADE)
    album_b = models.ForeignKey(Album, related_name="similarities_as_b", on_delete=models.CASCADE)
    score = models.FloatField()
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("album_a", "album_b")

    def __str__(self):
        return f"{self.album_a} ~ {self.album_b}: {self.score}"


class UserFavorite(models.Model):
    user = models.ForeignKey("auth.User", on_delete=models.CASCADE, related_name="favorites")
    album = models.ForeignKey(Album, on_delete=models.CASCADE)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "album")

    def __str__(self):
        return f"{self.user} -> {self.album}"


def _default_node_limit():
    return getattr(settings, "SOUNDGRAPH_NODE_LIMIT", 50_000)


class ConnectionSearch(models.Model):
    STATUS_CHOICES = [
        ("pending", "pending"),
        ("running", "running"),
        ("paused", "paused"),
        ("found", "found"),
        ("exhausted", "exhausted"),
        ("failed", "failed"),
        ("stopped", "stopped"),
    ]

    STOPPED_REASON_CHOICES = [
        ("", "none"),
        ("node_limit", "node_limit"),
        ("user_stop", "user_stop"),
    ]

    # Tope de nodos descubiertos en TODAS las semillas. Es la salvaguarda
    # principal de memoria/CPU: sin él, un BFS sobre artistas muy populares
    # explota exponencialmente (frontera ~10x por nivel) y mantiene todo el
    # estado en RAM y en un JSON gigante en la base.
    node_limit = models.IntegerField(default=_default_node_limit)
    total_discovered = models.IntegerField(default=0)
    stopped_reason = models.CharField(
        max_length=30, choices=STOPPED_REASON_CHOICES, blank=True, default=""
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seed_artists = models.JSONField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    visited_per_seed = models.JSONField(default=dict)
    frontier_per_seed = models.JSONField(default=dict)
    came_from = models.JSONField(default=dict)
    bridge_artist = models.CharField(max_length=255, null=True, blank=True)
    current_depth = models.IntegerField(default=0)
    max_depth = models.IntegerField(default=6)
    # Revisión del payload de status. Cada save que persiste ESTADO (nivel
    # terminado, found, exhausted, paused, stopped, failed) la avanza; los
    # heartbeats solo tocan ``updated_at`` y no la mueven. El GET de status la
    # usa como ETag: si el frontend manda el mismo If-None-Match devolvemos 304
    # sin re-serializar el payload (la búsqueda queda semanas en estado estático
    # con gráficos de 174KB; esta revisión es lo que permite cachear).
    payload_revision = models.IntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{' / '.join(self.seed_artists)} ({self.status})"