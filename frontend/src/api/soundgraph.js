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

export function fetchRecommendations({ seeds, nResults }) {
  return request('/recommendations/', {
    method: 'POST',
    body: JSON.stringify({
      seeds,
      n_results: nResults,
    }),
  });
}

export function searchArtists(query) {
  return request(`/search/artists/?q=${encodeURIComponent(query)}`);
}

export function fetchArtistAlbums(artist) {
  return request(`/search/albums/?artist=${encodeURIComponent(artist)}`);
}

export function fetchAtypicalAlbums(artistId) {
  return request(`/artists/${artistId}/atypical-albums/`);
}