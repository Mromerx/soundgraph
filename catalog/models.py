import uuid

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
    genres = models.JSONField(default=list)      # Discogs: ["Rock", "Electronic"]
    styles = models.JSONField(default=list)      # Discogs: ["Synth-pop", "Shoegaze"]
    tags = models.JSONField(default=list)        # Last.fm: [{"name": "melancholic", "count": 45}, ...]
    listeners = models.IntegerField(default=0)   # Last.fm
    playcount = models.IntegerField(default=0)   # Last.fm
    tag_document = models.TextField(blank=True)  # documento de texto ya mezclado, para TF-IDF
    discogs_enriched = models.BooleanField(default=False)  # sabe si ya pasó por Discogs
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


class ConnectionSearch(models.Model):
    STATUS_CHOICES = [
        ("pending", "pending"),
        ("running", "running"),
        ("found", "found"),
        ("exhausted", "exhausted"),
        ("failed", "failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seed_artists = models.JSONField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    visited_per_seed = models.JSONField(default=dict)
    frontier_per_seed = models.JSONField(default=dict)
    came_from = models.JSONField(default=dict)
    bridge_artist = models.CharField(max_length=255, null=True, blank=True)
    current_depth = models.IntegerField(default=0)
    max_depth = models.IntegerField(default=6)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{' / '.join(self.seed_artists)} ({self.status})"