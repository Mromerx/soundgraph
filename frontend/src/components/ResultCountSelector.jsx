const MIN_RESULTS = 1;
const MAX_RESULTS = 5;

export default function ResultCountSelector({ nResults, onChange }) {
  return (
    <label className="result-count">
      <span>Resultados: {nResults}</span>
      <input
        type="range"
        min={MIN_RESULTS}
        max={MAX_RESULTS}
        step={1}
        value={nResults}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <span className="range-labels">
        <small>{MIN_RESULTS}</small>
        <small>{MAX_RESULTS}</small>
      </span>
    </label>
  );
}