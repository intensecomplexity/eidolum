// formatDate(input, { relative = false, includeYear = true, compact = false } = {})
// - input: ISO string "2026-05-14" OR Date object OR null/undefined
// - relative=true → "just now", "Nm ago", "Nh ago", "yesterday", "Nd ago", "Nw ago", "Nmo ago" for <1y, else absolute
// - relative=false → "May 14, 2026" (or "May 14" if includeYear=false and same calendar year)
// - compact=true (relative only) → drops the " ago" suffix: "5m", "2h", "3d", "2w", "1mo".
//   "just now" and "yesterday" stay unchanged.
// - null/undefined/invalid → "" (never "Invalid Date")
//
// Naive ISO strings (no trailing Z or +HH:MM offset) are coerced to UTC. Backend
// frequently returns naive UTC; treating them as local would mis-display by the
// viewer's offset. Strings with explicit timezone info are parsed as written.

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

export function formatDate(input, { relative = false, includeYear = true, compact = false } = {}) {
  if (!input) return '';

  let d;
  if (input instanceof Date) {
    d = input;
  } else if (typeof input === 'string') {
    const hasTimezone = /([Zz]|[+-]\d{2}:?\d{2})$/.test(input);
    const isDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(input);
    const isNaiveISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(input) && !hasTimezone;
    if (isDateOnly || isNaiveISO) {
      d = new Date(input + (isDateOnly ? 'T00:00:00Z' : 'Z'));
    } else {
      d = new Date(input);
    }
  } else {
    d = new Date(input);
  }
  if (Number.isNaN(d.getTime())) return '';

  if (relative) {
    const diffMs = Date.now() - d.getTime();
    if (diffMs >= 0) {
      const diffSec = Math.floor(diffMs / 1000);
      const diffMin = Math.floor(diffSec / 60);
      const diffHr = Math.floor(diffMin / 60);
      const diffDays = Math.floor(diffHr / 24);
      const suffix = compact ? '' : ' ago';

      if (diffSec < 45) return 'just now';
      if (diffMin < 60) return `${diffMin}m${suffix}`;
      if (diffHr < 24) return `${diffHr}h${suffix}`;
      if (diffDays === 1) return 'yesterday';
      if (diffDays < 7) return `${diffDays}d${suffix}`;
      if (diffDays < 30) return `${Math.floor(diffDays / 7)}w${suffix}`;
      if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo${suffix}`;
    }
  }

  const month = MONTHS[d.getMonth()];
  const day = d.getDate();
  const year = d.getFullYear();
  const now = new Date();

  if (!includeYear && year === now.getFullYear()) {
    return `${month} ${day}`;
  }
  return `${month} ${day}, ${year}`;
}

export default formatDate;
