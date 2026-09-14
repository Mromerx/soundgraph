import { t } from '../i18n.js';

const MIN_RESULTS = 1;
const MAX_RESULTS = 15;

export default function ResultCountSelector({ nResults, onChange }) {
  const decrement = () => onChange(Math.max(MIN_RESULTS, nResults - 1));
  const increment = () => onChange(Math.min(MAX_RESULTS, nResults + 1));

  return (
    <div className="result-count">
      <span>{t('recommend.results', { n: nResults })}</span>
      <div className="stepper">
        <button
          type="button"
          onClick={decrement}
          disabled={nResults <= MIN_RESULTS}
          aria-label={t('recommend.fewer')}
        >
          <span>&minus;</span>
        </button>
        <span aria-live="polite">{nResults}</span>
        <button
          type="button"
          onClick={increment}
          disabled={nResults >= MAX_RESULTS}
          aria-label={t('recommend.more')}
        >
          <span>+</span>
        </button>
      </div>
    </div>
  );
}