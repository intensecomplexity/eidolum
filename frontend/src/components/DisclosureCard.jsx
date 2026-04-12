import { Link } from 'react-router-dom';
import TickerLogo from './TickerLogo';

/**
 * DisclosureCard — renders a single forecaster disclosure (what they
 * actually bought, sold, added, trimmed, etc). Visually distinct from
 * prediction cards: amber left border, past-tense verb framing, and
 * a follow-through metric instead of HIT/NEAR/MISS.
 *
 * Props:
 *   disclosure: API row from /api/forecasters/:id/disclosures (or
 *               /api/activity/disclosures with name/handle/slug joined)
 *   compact:    smaller variant for lists (no reasoning_text)
 *   showForecaster: render forecaster name+handle as a Link (activity
 *                   feed only — on the profile page it would be
 *                   redundant)
 */
export default function DisclosureCard({ disclosure, compact = false, showForecaster = false }) {
  if (!disclosure) return null;
  const {
    ticker, action, size_shares, size_pct, size_qualitative,
    entry_price, reasoning_text, disclosed_at,
    follow_through_3m, follow_through_1m, follow_through_12m,
    forecaster_name, forecaster_handle, forecaster_slug,
  } = disclosure;

  const { color, bg, verb } = _actionStyle(action);
  const sizeLabel = _formatSize(size_shares, size_pct, size_qualitative);
  const ftDisplay = _formatFollowThrough(follow_through_3m, follow_through_1m, follow_through_12m);
  const dateLabel = disclosed_at ? new Date(disclosed_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '';

  return (
    <div
      className="border-l-4 bg-surface-1 rounded-r-md px-3 py-2 flex flex-col gap-1"
      style={{ borderLeftColor: '#f59e0b' }}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <TickerLogo ticker={ticker} size={18} />
        <Link to={`/asset/${ticker}`} className="ticker-mono text-accent hover:underline" onClick={e => e.stopPropagation()}>
          {ticker}
        </Link>
        <span
          className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[9px] font-semibold uppercase tracking-wide whitespace-nowrap"
          style={{ backgroundColor: bg, color }}
        >
          {verb}
        </span>
        {sizeLabel && (
          <span className="text-[10px] font-mono text-text-secondary whitespace-nowrap">{sizeLabel}</span>
        )}
        {entry_price !== null && entry_price !== undefined && (
          <span className="text-[10px] font-mono text-text-secondary whitespace-nowrap">@ ${entry_price.toFixed(2)}</span>
        )}
        <span className="text-[10px] text-muted ml-auto whitespace-nowrap">{dateLabel}</span>
      </div>
      {showForecaster && forecaster_name && (
        <div className="text-[11px] text-text-secondary">
          by{' '}
          <Link
            to={forecaster_slug ? `/analyst/${forecaster_slug}` : '#'}
            className="font-medium text-accent hover:underline"
          >
            {forecaster_name}
          </Link>
          {forecaster_handle && <span className="text-muted"> · @{forecaster_handle}</span>}
        </div>
      )}
      {!compact && reasoning_text && (
        <div className="text-[11px] text-text-secondary italic line-clamp-2">
          “{reasoning_text}”
        </div>
      )}
      {ftDisplay && (
        <div className="flex items-center gap-1 text-[10px]">
          <span className="text-muted">follow-through {ftDisplay.window}:</span>
          <span className={ftDisplay.value >= 0 ? 'text-positive font-mono font-semibold' : 'text-negative font-mono font-semibold'}>
            {ftDisplay.value >= 0 ? '+' : ''}{(ftDisplay.value * 100).toFixed(1)}%
          </span>
        </div>
      )}
    </div>
  );
}

function _actionStyle(action) {
  switch (action) {
    case 'buy':
      return { color: '#34d399', bg: 'rgba(52,211,153,0.14)', verb: 'Bought' };
    case 'add':
      return { color: '#34d399', bg: 'rgba(52,211,153,0.12)', verb: 'Added' };
    case 'starter':
      return { color: '#60a5fa', bg: 'rgba(96,165,250,0.14)', verb: 'Started' };
    case 'hold':
      return { color: '#a78bfa', bg: 'rgba(167,139,250,0.14)', verb: 'Holding' };
    case 'trim':
      return { color: '#fb923c', bg: 'rgba(251,146,60,0.14)', verb: 'Trimmed' };
    case 'sell':
      return { color: '#f87171', bg: 'rgba(248,113,113,0.14)', verb: 'Sold' };
    case 'exit':
      return { color: '#f87171', bg: 'rgba(248,113,113,0.18)', verb: 'Exited' };
    default:
      return { color: '#94a3b8', bg: 'rgba(148,163,184,0.14)', verb: action };
  }
}

function _formatSize(shares, pct, qual) {
  if (shares !== null && shares !== undefined) {
    if (shares >= 1000) return `${(shares / 1000).toFixed(1)}k sh`;
    return `${shares.toFixed(0)} sh`;
  }
  if (pct !== null && pct !== undefined) {
    return `${(pct * 100).toFixed(1)}%`;
  }
  if (qual) {
    return qual;
  }
  return null;
}

function _formatFollowThrough(ft3m, ft1m, ft12m) {
  // Prefer 3-month follow-through (the canonical window).
  // Fall back to 1-month then 12-month if 3m isn't available.
  if (ft3m !== null && ft3m !== undefined) return { window: '3m', value: ft3m };
  if (ft1m !== null && ft1m !== undefined) return { window: '1m', value: ft1m };
  if (ft12m !== null && ft12m !== undefined) return { window: '12m', value: ft12m };
  return null;
}
