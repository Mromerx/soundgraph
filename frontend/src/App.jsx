import { useState } from 'react';
import { fetchRecommendations } from './api/soundgraph.js';
import { t, translateError } from './i18n.js';
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

  const canRecommend =
    seedArtists.length > 0 &&
    seeds.filter((s) => s.artist.trim()).every((s) => s.album.trim());

  async function handleSubmit(event) {
    event.preventDefault();
    setError('');

    const nonEmpty = seeds.filter((s) => s.artist.trim() && s.album.trim());
    if (nonEmpty.length === 0) {
      setError(t('recommend.noSeedError'));
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
      setError(translateError(err.message));
      setResults(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>SoundGraph</h1>
        <p>{t('app.tagline')}</p>
      </header>

      <main className="app-main">
        <form className="controls" onSubmit={handleSubmit}>
          <SeedSelector seeds={seeds} onChange={setSeeds} />
          <section className="recommend-controls">
            <h2>{t('recommend.title')}</h2>
            <p className="section-desc">{t('recommend.desc')}</p>
            <ResultCountSelector nResults={nResults} onChange={setNResults} />
            <button type="submit" className="submit" disabled={loading || !canRecommend}>
              {loading ? t('recommend.loading') : t('recommend.submit')}
            </button>
            {!canRecommend && <p className="button-hint">{t('recommend.hint')}</p>}
          </section>
        </form>

        {error && <p className="error">{error}</p>}

        {results !== null && !loading && (
          <section className="results">
            <h2>{t('results.title')}</h2>
            <p className="section-desc">{t('results.desc')}</p>
            <RecommendationsList recommendations={results} />
          </section>
        )}

        <ConnectionSearchPanel
          seedArtists={seedArtists}
          onStart={() => setConnection(null)}
          onStatus={setConnection}
        />

        {connection !== null && (
          <section className="results">
            <h2>{t('graph.title')}</h2>
            <p className="section-desc">{t('graph.desc')}</p>
            <GraphView connection={connection} />
          </section>
        )}
      </main>
    </div>
  );
}