import { t } from '../i18n.js';

export default function RecommendationsList({ recommendations }) {
  return (
    <ul className="recommendations">
      {recommendations.map((rec) => (
        <li key={`${rec.artist}|${rec.album}`} className="recommendation">
          <div className="recommendation-title">
            <strong>{rec.artist}</strong> — {rec.album}
          </div>
          <div className="recommendation-score">
            {t('result.posibleTaste')} <strong>{rec.score}%</strong>
          </div>
          {rec.matched_seeds && rec.matched_seeds.length > 0 && (
            <div className="recommendation-links">
              {t('result.connects')}{' '}
              {rec.matched_seeds
                .map((m) => `${m.artist} — ${m.album} (${m.score}%)`)
                .join(t('result.separator'))}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}