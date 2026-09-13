"""Bus de eventos en memoria para notificar cambios de estado de búsquedas.

Pensado para alimentar el endpoint SSE de ``/api/connections/{id}/events``: el
hilo de la búsqueda publica (``publish_search_event``) y el endpoint consume
(``subscribe_search_events``). El bus vive en el proceso Django, así que con
``runserver`` (un solo proceso) es exactamente el mismo proceso donde corre el
hilo real; para cualquier escenario multi-proceso el poll con ETag/304 sigue
siendo el respaldo.

Las colas son acotadas: si un suscriptor no consume, publicar no bloquea al
hilo de búsqueda (se descarta el evento viejo en lugar de frenar el BFS).
"""
import queue
import threading

_subs = {}
_lock = threading.Lock()


def publish_search_event(search_id, payload):
    """Encola ``payload`` a todos los suscriptores del ``search_id``.

    Nunca lanza: un suscriptor lento/muerto no debe tumbar al hilo de la
    búsqueda ni al request que publica.
    """
    with _lock:
        subscribers = list(_subs.get(str(search_id), ()))
    for subscriber in subscribers:
        try:
            subscriber.put_nowait(payload)
        except queue.Full:
            pass


def subscribe_search_events(search_id):
    """Crea una suscripción al ``search_id`` y devuelve su cola.

    Caller:
        El consumidor debe llamar ``unsubscribe_search_events`` cuando termine
        (idealmente en un ``finally``) para no quedar suscrito para siempre.

    Returns:
        ``queue.Queue`` de máxima ``maxsize`` con los eventos publicados.
    """
    subscriber = queue.Queue(maxsize=64)
    with _lock:
        _subs.setdefault(str(search_id), []).append(subscriber)
    return subscriber


def unsubscribe_search_events(search_id, subscriber):
    """Da de baja la suscripción; limpia el registro si queda vacío."""
    with _lock:
        subscribers = _subs.get(str(search_id))
        if subscribers is None:
            return
        try:
            subscribers.remove(subscriber)
        except ValueError:
            pass
        if not subscribers:
            _subs.pop(str(search_id), None)