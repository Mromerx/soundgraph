import { Fragment, useEffect, useRef, useState } from 'react';
import {
  controlConnectionSearch,
  getConnectionStatus,
  startConnectionSearch,
  streamConnectionStatus,
} from '../api/connections.js';

const POLL_INTERVAL_RUNNING_MS = 2000;
const POLL_INTERVAL_PAUSED_MS = 5000;
// Goteo de eventos SSE: una pelotita de artista por tick. Las respuestas de la
// API traen hasta 10 artistas "de golpe" y sus eventos llegan en la misma
// ráfaga (el navegador los pintaría juntos en un frame); dosificándolos, cada
// artista aparece de a uno. Como la API genera ~3.8 descubiertos/s (>150ms
// entre eventos), el goteo drena más rápido de lo que se llena en el caso real.
const STATUS_DRIP_INTERVAL_MS = 150;
const FINAL_STATUSES = ['found', 'exhausted', 'failed', 'stopped'];

function isFinal(s) {
  return s && FINAL_STATUSES.includes(s.status);
}

function pollDelayFor(status) {
  return status && status.status === 'paused' ? POLL_INTERVAL_PAUSED_MS : POLL_INTERVAL_RUNNING_MS;
}

export default function ConnectionSearchPanel({ seedArtists, onStart, onStatus }) {
  const [searchId, setSearchId] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const [controlling, setControlling] = useState(false);
  const timerRef = useRef(null);
  const sourceRef = useRef(null);
  const etagRef = useRef(null);
  const statusRef = useRef(null);
  const pollingRef = useRef(false);
  const pendingRef = useRef([]);
  const dripTimerRef = useRef(null);
  const drippingRef = useRef(false);

  const canSearch = seedArtists.length >= 2;

  function stopPolling() {
    pollingRef.current = false;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }

  function closeStream() {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
    }
  }

  function reset() {
    stopPolling();
    closeStream();
    stopDrip();
    setSearchId(null);
    setStatus(null);
    statusRef.current = null;
    etagRef.current = null;
    setError('');
  }

  function applyStatus(next, { fromStream = false } = {}) {
    if (!next) return;
    setStatus(next);
    statusRef.current = next;
    onStatus?.(next);
    if (isFinal(next)) {
      stopPolling();
      if (fromStream) closeStream();
    }
  }

  function stopDrip() {
    drippingRef.current = false;
    pendingRef.current = [];
    if (dripTimerRef.current) {
      clearTimeout(dripTimerRef.current);
      dripTimerRef.current = null;
    }
  }

  function dripNext() {
    const next = pendingRef.current.shift();
    if (!next) {
      drippingRef.current = false;
      return;
    }
    dripTimerRef.current = null;
    applyStatus(next, { fromStream: true });
    if (isFinal(next)) {
      drippingRef.current = false;
      pendingRef.current = [];
      return;
    }
    dripTimerRef.current = setTimeout(dripNext, STATUS_DRIP_INTERVAL_MS);
  }

  function enqueueStatus(next) {
    // Goteo: los eventos SSE se aplican de a uno, una pelotita por tick, en
    // vez de pintarse juntos cuando una respuesta de la API trae varios.
    pendingRef.current.push(next);
    // Tope de seguridad: si una ráfaga patológica encola decenas de snapshots,
    // descartar los intermedios. Cada snapshot es acumulativo (trae todo lo
    // anterior), así nunca se pierde el estado más nuevo; los descartados solo
    // se ven "juntos" en el siguiente tick.
    if (pendingRef.current.length > 200) {
      pendingRef.current = pendingRef.current.slice(-50);
    }
    if (!drippingRef.current) {
      drippingRef.current = true;
      dripNext();
    }
  }

  function scheduleNextPoll() {
    if (!pollingRef.current || isFinal(statusRef.current)) return;
    timerRef.current = setTimeout(pollStatus, pollDelayFor(statusRef.current));
  }

  async function pollStatus() {
    if (!searchId || isFinal(statusRef.current)) return;
    timerRef.current = null;
    try {
      const { data, etag } = await getConnectionStatus(searchId, { etag: etagRef.current });
      if (data === null) return; // 304: nada cambió, no re-renderizar
      if (etag) etagRef.current = etag;
      // Por el mismo goteo que el SSE: su estado (fin de nivel) no debe
      // pintarse por delante de eventos más viejos en cola.
      enqueueStatus(data);
    } catch (err) {
      setError(err.message);
      stopPolling();
      closeStream();
      return;
    } finally {
      // El poll queda como respaldo barato: el SSE ya cubrió los cambios al
      // instante. Donde no llegue (stream caído) este reintento sigue vivo.
      scheduleNextPoll();
    }
  }

  async function handleSearch() {
    setError('');
    setStatus(null);
    statusRef.current = null;
    etagRef.current = null;
    setStarting(true);
    onStart?.(seedArtists);
    try {
      const { search_id } = await startConnectionSearch(seedArtists);
      setSearchId(search_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setStarting(false);
    }
  }

  async function sendControl(action) {
    if (!searchId) return;
    setError('');
    setControlling(true);
    try {
      const next = await controlConnectionSearch(searchId, action);
      applyStatus(next);
    } catch (err) {
      setError(err.message);
    } finally {
      setControlling(false);
    }
  }

  useEffect(() => {
    if (!searchId) return;

    pollingRef.current = true;
    etagRef.current = null;
    stopDrip();
    pollStatus();

    const source = streamConnectionStatus(searchId, {
      onEvent: (payload) => {
        // Cada evento trae las muestras del grafo con una pelotita más; el
        // goteo las aplica de a una. El poll con ETag queda como respaldo si
        // el stream se cae o en multi-proceso.
        enqueueStatus(payload);
      },
      onError: () => {
        // El stream murió: el poll (2-5s, con 304) sigue como respaldo. Lo
        // pendiente del goteo se aplica igual (no se pierde).
        sourceRef.current = null;
      },
    });
    sourceRef.current = source;

    return () => {
      stopPolling();
      closeStream();
      stopDrip();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchId]);

  useEffect(() => {
    if (!canSearch) reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canSearch]);

  if (error) {
    return (
      <section className="connection-panel">
        <p className="error">{error}</p>
      </section>
    );
  }

  if (!canSearch) return null;

  if (status && status.status === 'found') {
    return (
      <section className="connection-panel">
        <h2>Conexión encontrada</h2>
        <p>
          Artista puente: <strong className="bridge-artist">{status.bridge_artist}</strong>
        </p>
        <div className="connection-paths">
          {Object.entries(status.path || {}).map(([seed, chain]) => (
            <ol key={seed} className="connection-path">
              {chain.map((step, i) => (
                <Fragment key={`${seed}-${i}`}>
                  <li>
                    {step === status.bridge_artist && step === seed ? (
                      <strong>{step}</strong>
                    ) : (
                      step
                    )}
                  </li>
                  {i < chain.length - 1 && (
                    <li className="path-arrow" aria-hidden="true">
                      →
                    </li>
                  )}
                </Fragment>
              ))}
            </ol>
          ))}
        </div>
      </section>
    );
  }

  if (status && status.status === 'exhausted') {
    const hitNodeLimit = status.stopped_reason === 'node_limit';
    return (
      <section className="connection-panel">
        <h2>Búsqueda agotada</h2>
        <p>
          {hitNodeLimit
            ? `Se exploraron ${status.total_discovered ?? 0} artistas sin encontrar una conexión dentro del límite de seguridad. Prueba con artistas más cercanos entre sí.`
            : 'No se encontró una conexión directa entre estos artistas dentro del límite de búsqueda'}
        </p>
      </section>
    );
  }

  if (status && status.status === 'failed') {
    return (
      <section className="connection-panel">
        <h2>Error en la búsqueda</h2>
        <p className="error">{status.error_message || 'Error desconocido'}</p>
      </section>
    );
  }

  const running = starting || (status && !isFinal(status));

  const live =
    status &&
    (status.status === 'pending' ||
      status.status === 'running' ||
      status.status === 'paused');

  return (
    <section className="connection-panel">
      <button
        type="button"
        className="connection-button"
        onClick={handleSearch}
        disabled={running}
      >
        {starting
          ? 'Iniciando búsqueda…'
          : status && status.status === 'stopped'
            ? 'Buscar otra conexión entre estos artistas'
            : 'Buscar conexión entre estos artistas'}
      </button>

      {status && status.status === 'stopped' && (
        <p className="connection-progress">Búsqueda detenida por el usuario.</p>
      )}

      {live && (
        <p className="connection-progress">
          {status.status === 'paused'
            ? 'Búsqueda pausada. Reanudala o detenela cuando quieras.'
            : `Explorando nivel ${status.current_depth ?? 0} de ${status.max_depth ?? 0}${status.total_discovered ? ` · ${status.total_discovered} artistas` : ''}...`}
        </p>
      )}

      {live && (
        <div className="connection-controls">
          <button
            type="button"
            className="connection-control"
            onClick={() => sendControl(status.status === 'paused' ? 'resume' : 'pause')}
            disabled={controlling}
          >
            {status.status === 'paused' ? 'Reanudar' : 'Pausar'}
          </button>
          <button
            type="button"
            className="connection-control connection-control-stop"
            onClick={() => sendControl('stop')}
            disabled={controlling}
          >
            Detener
          </button>
        </div>
      )}
    </section>
  );
}