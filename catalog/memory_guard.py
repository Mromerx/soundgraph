"""Límite de memoria a nivel proceso (POSIX).

``apply_memory_limit`` capa la memoria virtual del proceso entero con
``resource.setrlimit(RLIMIT_AS)``. Es la salvaguarda final: aunque todo lo
demás falle, el proceso no puede crecer más allá del tope configurado
(``SOUNDGRAPH_MEMORY_LIMIT_MB``, default 4096 MB); cualquier asignación que
lo exceda lanza ``MemoryError``, que ``run_full_search`` ya maneja y le pone
estado ``failed`` a la búsqueda en vez de matar el servidor.

En plataformas sin ``resource`` (Windows, por ejemplo) no hace nada: ahí el
acotado por nodos y concurrencia sigue activo.
"""
import logging
import os

logger = logging.getLogger(__name__)


def apply_memory_limit():
    """Aplica el tope de RAM del proceso si el sistema lo permite."""
    limit_mb = int(os.environ.get("SOUNDGRAPH_MEMORY_LIMIT_MB", "4096"))
    if limit_mb <= 0:
        return

    try:
        import resource
    except ImportError:
        return

    limit_bytes = limit_mb * 1024 * 1024
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    except (ValueError, OSError) as exc:
        logger.warning("No se pudo leer el límite de memoria: %s", exc)
        return

    if hard != resource.RLIM_INFINITY and hard < limit_bytes:
        limit_bytes = hard

    try:
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
    except (ValueError, OSError) as exc:
        logger.warning("No se pudo aplicar el límite de memoria de %s MB: %s", limit_mb, exc)
        return

    logger.info(
        "Límite de memoria aplicado: %s MB para el proceso (PID %s).",
        limit_bytes // (1024 * 1024),
        os.getpid(),
    )