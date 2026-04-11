import { useEffect, useState } from 'react';
import { getGlobalStats } from '../../api';

// Ship #13. Hero band at the top of `/` when ENABLE_HOMEPAGE_HERO is on.
// Stat numbers come from /api/stats/global (NOT hardcoded). Until the
// fetch resolves we show subtle placeholders — render is never blocked.

function StatTile({ value, label }) {
  return (
    <div className="flex flex-col items-center gap-1 min-w-[7rem]">
      <div className="font-mono text-2xl sm:text-3xl font-bold text-accent">
        {value}
      </div>
      <div className="text-[10px] sm:text-xs uppercase tracking-wider text-muted text-center">
        {label}
      </div>
    </div>
  );
}

function formatPlus(n) {
  if (n == null || Number.isNaN(n)) return '—';
  if (n >= 1000) {
    // 274013 -> 274K+, 6012 -> 6K+, 31421 -> 31K+
    const rounded = Math.floor(n / 1000);
    return `${rounded.toLocaleString()}K+`;
  }
  return `${n.toLocaleString()}+`;
}

export default function HeroBand() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    let active = true;
    getGlobalStats()
      .then(s => { if (active) setStats(s); })
      .catch(() => {});
    return () => { active = false; };
  }, []);

  const predictions = stats?.total_predictions;
  const forecasters = stats?.total_forecasters;
  const scored = stats?.total_scored;

  return (
    <section className="relative overflow-hidden border-b border-border/40">
      <div className="absolute inset-0 grid-bg opacity-40" aria-hidden />
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse at 50% 0%, rgba(212,160,23,0.10) 0%, transparent 60%)',
        }}
        aria-hidden
      />

      <div className="relative max-w-4xl mx-auto px-4 sm:px-6 py-10 sm:py-16 text-center">
        <h1
          className="headline-serif text-accent mb-4 sm:mb-5"
          style={{ fontSize: 'clamp(2.2rem, 5.5vw, 3.8rem)', lineHeight: 1.08 }}
        >
          Who should you actually listen to?
        </h1>

        <p className="text-text-secondary text-base sm:text-xl leading-relaxed max-w-xl mx-auto mb-3">
          Every Wall Street analyst and fintwit forecaster on one leaderboard,
          scored against reality.
        </p>

        <p className="italic font-serif text-accent text-sm sm:text-base mb-8 sm:mb-10">
          Truth is the only currency.
        </p>

        <div className="flex flex-row items-center justify-center flex-wrap gap-6 sm:gap-10 mb-6 sm:mb-8">
          <StatTile value={formatPlus(predictions)} label="Predictions Tracked" />
          <StatTile value={formatPlus(forecasters)} label="Forecasters Watched" />
          <StatTile value={formatPlus(scored)} label="Calls Graded" />
        </div>

        <div className="inline-flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-xs sm:text-[13px] text-text-secondary">
          <LegendPill color="#34d399" label="HIT" />
          <Dot />
          <LegendPill color="#fbbf24" label="NEAR" />
          <Dot />
          <LegendPill color="#f87171" label="MISS" />
          <span className="text-muted hidden sm:inline">—</span>
          <span className="text-muted">
            locked at submission, graded automatically by the market
          </span>
        </div>
      </div>
    </section>
  );
}

function LegendPill({ color, label }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="inline-block w-2 h-2 rounded-full"
        style={{ backgroundColor: color, boxShadow: `0 0 8px ${color}66` }}
      />
      <span className="font-mono font-bold" style={{ color }}>{label}</span>
    </span>
  );
}

function Dot() {
  return <span className="text-muted opacity-40">·</span>;
}
