export default function TickerBar({ forecasters }) {
  if (!forecasters || forecasters.length === 0) return null;

  const items = [...forecasters, ...forecasters];

  return (
    <div className="w-full overflow-hidden ticker-tape py-2 sm:py-3">
      <div className="ticker-scroll flex gap-5 sm:gap-8 whitespace-nowrap">
        {items.map((f, i) => (
          <div key={i} className="flex items-center gap-2 sm:gap-3 text-xs sm:text-sm">
            <span className="text-text-primary font-medium">{f.name}</span>
            <span
              className={`font-mono font-semibold ${
                f.accuracy_rate >= 60 ? 'text-positive' : 'text-negative'
              }`}
            >
              {f.accuracy_rate.toFixed(1)}%
            </span>
            <span className="text-border">|</span>
          </div>
        ))}
      </div>
    </div>
  );
}
