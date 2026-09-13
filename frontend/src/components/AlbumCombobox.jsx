import { useEffect, useMemo, useState } from 'react';
import { fetchArtistAlbums } from '../api/soundgraph.js';

export default function AlbumCombobox({ artist, album, onChange }) {
  const [query, setQuery] = useState(album);
  const [albums, setAlbums] = useState([]);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const disabled = !artist;

  useEffect(() => {
    setQuery(album);
  }, [album]);

  useEffect(() => {
    if (!artist) {
      setAlbums([]);
      setQuery('');
      setError('');
      setOpen(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError('');
    fetchArtistAlbums(artist)
      .then((data) => {
        if (cancelled) return;
        setAlbums(data.results || []);
        setActiveIndex(-1);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message);
        setAlbums([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [artist]);

  const filtered = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return albums;
    return albums.filter((a) => a.title.toLowerCase().includes(term));
  }, [albums, query]);

  function selectOption(option) {
    onChange(option.title);
    setQuery(option.title);
    setOpen(false);
  }

  function revertQuery() {
    setQuery(album);
    setOpen(false);
  }

  function handleKeyDown(event) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (!open && filtered.length) setOpen(true);
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (open && activeIndex >= 0 && filtered[activeIndex]) {
        selectOption(filtered[activeIndex]);
      } else {
        revertQuery();
      }
    } else if (event.key === 'Escape') {
      revertQuery();
    }
  }

  return (
    <div className="combobox">
      <input
        type="text"
        className="combobox-input"
        placeholder={disabled ? 'Primero elige un artista' : 'Álbum'}
        value={disabled ? '' : query}
        autoComplete="off"
        disabled={disabled}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => filtered.length && setOpen(true)}
        onBlur={revertQuery}
        onKeyDown={handleKeyDown}
        aria-expanded={open}
        aria-autocomplete="list"
      />
      {loading && <span className="combobox-spinner">…</span>}
      {error && <span className="combobox-error">{error}</span>}
      {open && !loading && filtered.length > 0 && (
        <ul className="combobox-list" role="listbox">
          {filtered.map((option, index) => (
            <li
              key={`${option.title}-${index}`}
              role="option"
              aria-selected={index === activeIndex}
              className={index === activeIndex ? 'combobox-option active' : 'combobox-option'}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => selectOption(option)}
              onMouseEnter={() => setActiveIndex(index)}
            >
              <span className="combobox-name">{option.title}</span>
            </li>
          ))}
        </ul>
      )}
      {open && !loading && filtered.length === 0 && (
        <div className="combobox-empty">Sin álbumes para «{query.trim()}»</div>
      )}
    </div>
  );
}