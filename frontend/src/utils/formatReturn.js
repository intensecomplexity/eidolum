// Single source of truth for rendering a prediction's % return in the UI.
//
// The backend now sends a prediction's actual_return as its TRUE, price_bars-
// verified value: a genuine +450% winner arrives as 450, not a "+200%" cap.
// Two jobs are split cleanly:
//   - DATA VALIDITY is decided on the backend (entry within tolerance of the
//     price_bars close + valid direction math). Untrustworthy/unverifiable rows
//     arrive as null here and render "—" — we never invent a number.
//   - DISPLAY keeps only the two real-world guards: a P&L return can never sit
//     below -100% (no position loses more than its capital), and an ABSOLUTE
//     backstop at +2000% catches anything corrupt that slips validation. There
//     is NO upper "+200%" clamp anymore — verified big winners show their true %.

export const RETURN_MAX_LOSS = -100;
export const RETURN_EXTREME = 2000; // absolute backstop — above this = corrupt → "—"

// Returns { text, positive } for a renderable return, or null when the value is
// missing / non-finite / outside the legal band (caller should show "—").
// opts.decimals controls precision (default 1). opts.capLabel is accepted for
// backward compatibility but ignored — there is no upper cap to label anymore.
export function formatReturn(value, opts = {}) {
  const { decimals = 1 } = opts;
  if (value === null || value === undefined) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  if (n < RETURN_MAX_LOSS || n > RETURN_EXTREME) return null; // impossible/corrupt — guard → "—"
  const positive = n >= 0;
  return { text: `${positive ? '+' : ''}${n.toFixed(decimals)}%`, positive };
}
