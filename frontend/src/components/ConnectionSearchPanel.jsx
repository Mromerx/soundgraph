import { Fragment, useEffect, useRef, useState } from 'react';
import { t, translateError } from '../i18n.js';
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
      setError(translateError(err.message));
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
      setError(translateError(err.message));
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
      setError(translateError(err.message));
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

  const running = starting || (status && !isFinal(status));

  const live =
    status &&
    (status.status === 'pending' ||
      status.status === 'running' ||
      status.status === 'paused');

  const hitNodeLimit = status?.status === 'exhausted' && status.stopped_reason === 'node_limit';
  const hasPreviousSearch = !!status && (isFinal(status) || status.status === 'stopped');

  return (
    <Fragment>
      <section className="connection-panel">
        <h2>{t('connection.title')}</h2>
        <p className="section-desc">{t('connection.desc')}</p>

        <button
          type="button"
          className="connection-button"
          onClick={handleSearch}
          disabled={!canSearch || running}
        >
          {starting
            ? t('connection.starting')
            : running
              ? t('connection.searching')
              : hasPreviousSearch
                ? t('connection.searchAgain')
                : t('connection.search')}
        </button>
        {!canSearch && <p className="button-hint">{t('connection.hint')}</p>}

        {error && <p className="error">{error}</p>}

        {status && status.status === 'exhausted' && (
          <>
            <h2>{t('connection.exhausted')}</h2>
            <p>
              {hitNodeLimit
                ? t('connection.exhaustedLimit', { count: status.total_discovered ?? 0 })
                : t('connection.exhaustedNone')}
            </p>
          </>
        )}

        {status && status.status === 'failed' && (
          <>
            <h2>{t('connection.failed')}</h2>
            <p className="error">{status.error_message || t('connection.unknownError')}</p>
          </>
        )}

        {status && status.status === 'stopped' && (
          <p className="connection-progress">{t('connection.stopped')}</p>
        )}

        {live && (
          <p className="connection-progress">
            {status.status === 'paused'
              ? t('connection.paused')
              : `${t('connection.exploring', {
                  depth: status.current_depth ?? 0,
                  max: status.max_depth ?? 0,
                })}${status.total_discovered ? ` ${t('connection.artists', { count: status.total_discovered })}` : ''}...`}
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
              {status.status === 'paused' ? t('connection.resume') : t('connection.pause')}
            </button>
            <button
              type="button"
              className="connection-control connection-control-stop"
              onClick={() => sendControl('stop')}
              disabled={controlling}
            >
              {t('connection.stop')}
            </button>
          </div>
        )}
      </section>

      {status && status.status === 'found' && (
        <section className="results">
          <h2>{t('connection.found')}</h2>
          <p className="section-desc">
            {t('connection.bridgePrefix', { name: status.bridge_artist })}
          </p>
          <div className="connection-paths">
            {Object.entries(status.path || {}).map(([seed, chain]) => (
              <div key={seed} className="connection-path">
                {chain.map((step, i) => (
                  <Fragment key={`${seed}-${i}`}>
                    <span className="path-step">
                      {step}
                    </span>
                    {i < chain.length - 1 && (
                      <span className="path-arrow" aria-hidden="true">
                        →
                      </span>
                    )}
                  </Fragment>
                ))}
              </div>
            ))}
          </div>
        </section>
      )}
    </Fragment>
  );
}