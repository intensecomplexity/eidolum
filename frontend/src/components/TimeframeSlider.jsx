import { useState } from 'react';

const PRESETS = [
  { label: '1D', days: 1 },
  { label: '1W', days: 7 },
  { label: '2W', days: 14 },
  { label: '1M', days: 30 },
  { label: '3M', days: 90 },
  { label: '6M', days: 180 },
  { label: '1Y', days: 365 },
];

export default function TimeframeSlider({ value, onChange, min = 1, max = 365 }) {
  const [showCustom, setShowCustom] = useState(
    !PRESETS.some(p => p.days === value)
  );

  function handlePreset(days) {
    setShowCustom(false);
    onChange(days);
  }

  function handleCustomToggle() {
    setShowCustom(true);
  }

  return (
    <div>
      {/* Preset pills */}
      <div className="flex flex-wrap gap-2 mb-3">
        {PRESETS.map(p => (
          <button
            key={p.days}
            type="button"
            onClick={() => handlePreset(p.days)}
            className={`px-3 py-1.5 rounded-lg text-xs font-mono font-semibold transition-colors ${
              value === p.days && !showCustom
                ? 'bg-accent/15 text-accent border border-accent/30'
                : 'bg-surface-2 text-text-secondary border border-border hover:border-accent/20'
            }`}
          >
            {p.label}
          </button>
        ))}
        <button
          type="button"
          onClick={handleCustomToggle}
          className={`px-3 py-1.5 rounded-lg text-xs font-mono font-semibold transition-colors ${
            showCustom
              ? 'bg-accent/15 text-accent border border-accent/30'
              : 'bg-surface-2 text-text-secondary border border-border hover:border-accent/20'
          }`}
        >
          Custom
        </button>
      </div>

      {/* Custom slider */}
      {showCustom && (
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={min}
            max={max}
            value={value}
            onChange={(e) => onChange(parseInt(e.target.value))}
            className="flex-1 h-1.5 bg-surface-2 rounded-full appearance-none cursor-pointer accent-accent"
          />
          <span className="font-mono text-sm text-accent min-w-[48px] text-right">
            {value}d
          </span>
        </div>
      )}

      {/* Display label */}
      {!showCustom && (
        <p className="text-xs text-muted">
          Evaluate after <span className="text-accent font-mono">{value}</span> days
        </p>
      )}
    </div>
  );
}
