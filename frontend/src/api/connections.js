const BASE_URL = '/api';

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

export function getConnectionStatus(searchId) {
  return request(`/connections/${encodeURIComponent(searchId)}/`);
}
