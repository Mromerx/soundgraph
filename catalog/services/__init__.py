"""Servicios externos de catalog: clientes de Discogs/Last.fm y capa de caché.

El resto del sistema debe acceder a datos de álbumes únicamente a través de
``catalog.services.cache.get_or_fetch_album``.
"""