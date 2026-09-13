const BASE_URL = '/api';
const SSE_URL = '/api';

async function request(path, options = {}) {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const message =
      (data && data.detail) ||
      (data && Object.values(data).flat().join(', ')) ||
      `Error ${response.status}`;
    throw new Error(message);
  }

  return data;
}

export function startConnectionSearch(seedArtists) {
  return request('/connections/', {
    method: 'POST',
    body: JSON.stringify({ seed_artists: seedArtists }),
  });
}

/**
 * Trae el estado de una búsqueda soportando revalidación por ETag.
 *
 * Devuelve `{ data, etag }`: `data` es el payload de estado, o `null` si el
 * servidor respondió 304 (nada cambió desde el `etag` enviado). El SSE cubre
 * los cambios al instante; este GET queda como respaldo barato (304) para
 * cuando el stream se cae.
 */
export async function getConnectionStatus(searchId, { full = false, etag = null } = {}) {
  const query = full ? '?graph=full' : '';
  const headers = {};
  if (etag) headers['If-None-Match'] = etag;

  const response = await fetch(`${BASE_URL}/connections/${encodeURIComponent(searchId)}/${query}`, {
    headers,
  });

  if (response.status === 304) {
    return { data: null, etag };
  }

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const message =
      (data && data.detail) ||
      (data && Object.values(data).flat().join(', ')) ||
      `Error ${response.status}`;
    throw new Error(message);
  }

  return { data, etag: response.headers.get('ETag') || null };
}

export function controlConnectionSearch(searchId, action) {
  return request(`/connections/${encodeURIComponent(searchId)}/`, {
    method: 'PATCH',
    body: JSON.stringify({ action }),
  });
}

/**
 * Abre un stream SSE de estado para una búsqueda.
 *
 * @returns {EventSource} Con `close()` para cortarlo. Llamá `onEvent(payload)`
 *   en cada evento de estado y `onError()` si el stream se cae.
 */
export function streamConnectionStatus(searchId, { onEvent, onError } = {}) {
  const source = new EventSource(
    `${SSE_URL}/connections/${encodeURIComponent(searchId)}/events`
  );
  source.onmessage = (event) => {
    try {
      onEvent?.(JSON.parse(event.data));
    } catch {
      // ignorar frames malformados o keep-alive
    }
  };
  source.onerror = () => {
    onError?.();
    source.close();
  };
  return source;
}