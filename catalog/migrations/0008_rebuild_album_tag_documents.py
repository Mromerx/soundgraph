"""Regenera los ``tag_document`` con el builder canónico.

Antes de esta migración existían dos definiciones del documento TF-IDF: la de
``cache._build_tag_document`` (todos los tags, sin ponderar) que se persistía
al fetch, y la de ``similarity.build_tag_document`` (filtra count >= 5 y repite
por count // 20) que quedaba como código muerto. Esta migración repara las
filas ya cacheadas de forma idempotente con la misma lógica que ahora usa
``similarity.build_tag_document``.
"""
from django.db import migrations


def rebuild_tag_documents(apps, schema_editor):
    Album = apps.get_model("catalog", "Album")
    for album in Album.objects.all().iterator():
        tokens = []
        for entry in album.tags or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name", "")
            try:
                count = int(entry.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            if count >= 5:
                tokens.extend([name] * max(1, count // 20))
        document = " ".join(tokens).lower()
        if album.tag_document != document:
            album.tag_document = document
            album.save(update_fields=["tag_document"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0007_connectionsearch_payload_revision_and_more"),
    ]

    operations = [
        migrations.RunPython(rebuild_tag_documents, noop_reverse),
    ]