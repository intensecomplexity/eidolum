// Single source of truth for rendering a prediction's % return in the UI.
//
// The backend bounds a prediction's actual_return to [-100, +200]: a position
// can never lose more than 100% of its capital, and gains are capped at the
// per-window ceiling (max +200% for a >180d call). Any value outside that legal
// band is a data error and must NEVER reach the user as an impossible
// percentage (e.g. "-230.4%" or "+8037.2%") — we render an em dash instead.
//
// Values at the +200 cap are labeled ">+200%" so a capped gain reads as a
// floor on an even larger move rather than a precise figure.

export const RETURN_MAX_GAIN = 200;
export const RETURN_MAX_LOSS = -100;

// Returns { text, positive } for a renderable return, or null when the value
// is missing / non-finite / outside the legal band (caller should show "—").
// opts.decimals controls precision (default 1). opts.capLabel (default true)
// emits ">+200%" at the cap; pass false for aggregates (e.g. Avg Return) where
// a ">" label would misrepresent an average.
export function formatReturn(value, opts = {}) {
  const { decimals = 1, capLabel = true } = opts;
  if (value === null || value === undefined) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  if (n < RETURN_MAX_LOSS || n > RETURN_MAX_GAIN) return null; // impossible — guard
  if (capLabel && n >= RETURN_MAX_GAIN) return { text: '>+200%', positive: true };
  const positive = n >= 0;
  return { text: `${positive ? '+' : ''}${n.toFixed(decimals)}%`, positive };
}
