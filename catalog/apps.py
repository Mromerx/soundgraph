from django.apps import AppConfig

from . import memory_guard


class CatalogConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'catalog'

    def ready(self):
        memory_guard.apply_memory_limit()
        self._expire_startup_zombies()

    def _expire_startup_zombies(self):
        """Al arrancar, cierra búsquedas zombi huérfanas del proceso anterior.

        Los hilos daemon del runserver anterior murieron con su proceso: toda
        ``pending/running`` en la base es, por definición, una búsqueda sin hilo
        vivo. Expirarla acá garantiza que al reiniciar no quede ningún zombi
        bloqueando la concurrencia (mensaje claro en la UI).

        Es defensivo: puede correr con la DB aún sin migrar (``migrate``
        arrancando) o en comandos sin tabla, así que se traga cualquier error.
        """
        try:
            from .services.connection_search import expire_stale_searches

            expire_stale_searches()
        except Exception:
            # La tabla aún no existe (primer arranque) o la DB no responde:
            # nada que expirar todavía, no es motivo para tirar abajo Django.
            from .services import connection_search as cs

            cs.logger.debug("Expiración de zombis de arranque no aplicable aún.", exc_info=True)