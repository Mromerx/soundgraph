import { useState } from 'react';
import ArtistCombobox from './ArtistCombobox.jsx';
import AlbumCombobox from './AlbumCombobox.jsx';

const MAX_SEEDS = 5;

function emptySeed(i = 0) {
  return { artist: '', album: '', key: i };
}

export default function SeedSelector({ seeds, onChange }) {
  const [error, setError] = useState('');

  function updateArtist(key, name) {
    updateSeed(key, 'artist', name, 'album', '');
  }

  function updateAlbum(key, title) {
    updateSeed(key, 'album', title);
  }

  function updateSeed(key, ...updates) {
    const next = seeds.map((seed) => {
      if (seed.key !== key) return seed;
      const patch = {};
      for (let i = 0; i < updates.length; i += 2) {
        patch[updates[i]] = updates[i + 1];
      }
      return { ...seed, ...patch };
    });
    setError('');
    onChange(next);
  }

  function addSeed() {
    if (seeds.length >= MAX_SEEDS) return;
    onChange([...seeds, emptySeed(Date.now())]);
  }

  function removeSeed(key) {
    if (seeds.length === 1) {
      setError('Debes dejar al menos una semilla.');
      return;
    }
    onChange(seeds.filter((seed) => seed.key !== key));
  }

  return (
    <section>
      <h2>Álbumes semilla</h2>
      {seeds.map((seed, index) => (
        <div key={seed.key} className="seed-row">
          <span className="seed-index">{index + 1}.</span>
          <ArtistCombobox
            artist={seed.artist}
            onChange={(name) => updateArtist(seed.key, name)}
          />
          <AlbumCombobox
            artist={seed.artist}
            album={seed.album}
            onChange={(title) => updateAlbum(seed.key, title)}
          />
          <button
            type="button"
            className="remove"
            title="Quitar semilla"
            disabled={seeds.length === 1}
            onClick={() => removeSeed(seed.key)}
          >
            &times;
          </button>
        </div>
      ))}
      <button
        type="button"
        className="add"
        onClick={addSeed}
        disabled={seeds.length >= MAX_SEEDS}
      >
        +
      </button>
      {seeds.length >= MAX_SEEDS && (
        <span className="hint">Máximo {MAX_SEEDS} semillas.</span>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  );
}