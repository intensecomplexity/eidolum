// formatDate(input, { relative = false, includeYear = true } = {})
// - input: ISO string "2026-05-14" OR Date object OR null/undefined
// - relative=true → "today", "yesterday", "Nd ago", "Nw ago", "Nmo ago" for <1y, else absolute
// - relative=false → "May 14, 2026" (or "May 14" if includeYear=false and same calendar year)
// - null/undefined/invalid → "" (never "Invalid Date")

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

export function formatDate(input, { relative = false, includeYear = true } = {}) {
  if (!input) return '';
  const d = input instanceof Date ? input : new Date(input);
  if (Number.isNaN(d.getTime())) return '';

  if (relative) {
    const diffMs = Date.now() - d.getTime();
    const diffDays = Math.floor(diffMs / 86400000);
    if (diffDays >= 0) {
      if (diffDays === 0) return 'today';
      if (diffDays === 1) return 'yesterday';
      if (diffDays < 7) return `${diffDays}d ago`;
      if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
      if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo ago`;
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
