import { useEffect, useRef, useState } from 'react';
import { searchArtists } from '../api/soundgraph.js';
import { t } from '../i18n.js';

const DEBOUNCE_MS = 300;

export default function ArtistCombobox({ artist, onChange, placeholder = t('artist.placeholder') }) {
  const [query, setQuery] = useState(artist);
  const [options, setOptions] = useState([]);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef(null);

  useEffect(() => {
    setQuery(artist);
  }, [artist]);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);

    const term = query.trim();
    if (!term || term === artist) {
      setOptions([]);
      setOpen(false);
      return;
    }

    timerRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await searchArtists(term);
        setOptions(data.results || []);
        setActiveIndex(-1);
        setOpen(true);
      } catch (err) {
        setOptions([]);
        setOpen(false);
      } finally {
        setLoading(false);
      }
    }, DEBOUNCE_MS);

    return () => clearTimeout(timerRef.current);
  }, [query, artist]);

  function selectOption(option) {
    onChange(option.name);
    setQuery(option.name);
    setOptions([]);
    setOpen(false);
  }

  function revertQuery() {
    setQuery(artist);
    setOpen(false);
  }

  function handleKeyDown(event) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (!open && options.length) setOpen(true);
      setActiveIndex((i) => Math.min(i + 1, options.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (open && activeIndex >= 0 && options[activeIndex]) {
        selectOption(options[activeIndex]);
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
        placeholder={placeholder}
        value={query}
        autoComplete="off"
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => options.length && setOpen(true)}
        onBlur={revertQuery}
        onKeyDown={handleKeyDown}
        aria-expanded={open}
        aria-autocomplete="list"
      />
      {loading && <span className="combobox-spinner">…</span>}
      {open && options.length > 0 && (
        <ul className="combobox-list" role="listbox">
          {options.map((option, index) => (
            <li
              key={`${option.name}-${index}`}
              role="option"
              aria-selected={index === activeIndex}
              className={index === activeIndex ? 'combobox-option active' : 'combobox-option'}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => selectOption(option)}
              onMouseEnter={() => setActiveIndex(index)}
            >
              <span className="combobox-name">{option.name}</span>
              {option.listeners > 0 && (
                <span className="combobox-meta">
                  {t('artist.listeners', { count: option.listeners.toLocaleString() })}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {open && !loading && options.length === 0 && (
        <div className="combobox-empty">{t('artist.empty')}</div>
      )}
    </div>
  );
}