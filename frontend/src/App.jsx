import { useState } from 'react';
import { fetchRecommendations } from './api/soundgraph.js';
import ConnectionSearchPanel from './components/ConnectionSearchPanel.jsx';
import GraphView from './components/GraphView.jsx';
import RecommendationsList from './components/RecommendationsList.jsx';
import ResultCountSelector from './components/ResultCountSelector.jsx';
import SeedSelector from './components/SeedSelector.jsx';

const INITIAL_SEEDS = [{ artist: '', album: '', key: 1 }];

export default function App() {
  const [seeds, setSeeds] = useState(INITIAL_SEEDS);
  const [nResults, setNResults] = useState(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [results, setResults] = useState(null);
  const [connection, setConnection] = useState(null);

  const seedArtists = seeds
    .map((s) => s.artist.trim())
    .filter(Boolean);

  async function handleSubmit(event) {
    event.preventDefault();
    setError('');

    const nonEmpty = seeds.filter((s) => s.artist.trim() && s.album.trim());
    if (nonEmpty.length === 0) {
      setError('Elige al menos un artista y uno de sus álbumes de la lista.');
      return;
    }

    setLoading(true);
    try {
      const data = await fetchRecommendations({
        seeds: nonEmpty.map(({ artist, album }) => ({
          artist: artist.trim(),
          album: album.trim(),
        })),
        nResults,
      });
      setResults(data);
    } catch (err) {
      setError(err.message);
      setResults(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>SoundGraph</h1>
        <p>Descubre álbumes por similitud musical.</p>
      </header>

      <main className="app-main">
        <form className="controls" onSubmit={handleSubmit}>
          <SeedSelector seeds={seeds} onChange={setSeeds} />
          <ResultCountSelector nResults={nResults} onChange={setNResults} />
          <button type="submit" className="submit" disabled={loading}>
            {loading ? 'Recomendando…' : 'Recomendar'}
          </button>
        </form>

        <ConnectionSearchPanel
          seedArtists={seedArtists}
          onStart={() => setConnection(null)}
          onStatus={setConnection}
        />

        {error && <p className="error">{error}</p>}

        {results !== null && !loading && (
          <section className="results">
            <h2>Recomendaciones</h2>
            <RecommendationsList recommendations={results} />
          </section>
        )}

        {connection !== null && (
          <section className="results">
            <h2>Grafo de la conexión</h2>
            <GraphView connection={connection} />
          </section>
        )}
      </main>
    </div>
  );
}