import { Fragment, useEffect, useRef, useState } from 'react';
import {
  controlConnectionSearch,
  getConnectionStatus,
  startConnectionSearch,
} from '../api/connections.js';

const POLL_INTERVAL_MS = 1000;
const FINAL_STATUSES = ['found', 'exhausted', 'failed', 'stopped'];

function isFinal(s) {
  return s && FINAL_STATUSES.includes(s.status);
}

export default function ConnectionSearchPanel({ seedArtists, onStart, onStatus }) {
  const [searchId, setSearchId] = useState(null);
  const [status, setStatus] = useState(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const [controlling, setControlling] = useState(false);
  const timerRef = useRef(null);

  const canSearch = seedArtists.length >= 2;

  function stopPolling() {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }

  function reset() {
    stopPolling();
    setSearchId(null);
    setStatus(null);
    setError('');
  }

  async function pollStatus() {
    if (!searchId) return;
    try {
      const next = await getConnectionStatus(searchId);
      setStatus(next);
      onStatus?.(next);
      if (isFinal(next)) stopPolling();
    } catch (err) {
      setError(err.message);
      stopPolling();
    }
  }

  async function handleSearch() {
    setError('');
    setStatus(null);
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
      setStatus(next);
      onStatus?.(next);
      if (isFinal(next)) stopPolling();
    } catch (err) {
      setError(err.message);
    } finally {
      setControlling(false);
    }
  }

  useEffect(() => {
    if (!searchId) return;
    pollStatus();
    timerRef.current = setInterval(pollStatus, POLL_INTERVAL_MS);
    return stopPolling;
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