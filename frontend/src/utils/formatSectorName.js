/**
 * Normalize the SIC/Morningstar sector strings we render in cards.
 *
 * Backend ships a mix of:
 *   - Title-case Morningstar names ("Financial Services", "Life Sciences Tools & Services")
 *   - ALL-CAPS SIC labels ("MOTOR VEHICLES & PASSENGER CAR BODIES", "INVESTMENT ADVICE")
 *   - SIC labels with a "<PARENT>-<SUBCAT>" parent prefix
 *     ("SERVICES-VIDEO TAPE RENTAL", "SERVICES-BUSINESS SERVICES, NEC")
 *
 * The all-caps strings render visually larger than the title-case ones
 * even at the same font-size and look out of place next to clean
 * Morningstar names. We:
 *   1. Strip the redundant ALL-CAPS parent prefix (e.g. "SERVICES-")
 *   2. Title-case the rest
 *   3. Preserve the "NEC" SIC catch-all acronym since "Nec" looks broken
 *
 * Inputs that are already title-case pass through untouched, so we
 * never lowercase a deliberate cap in something like
 * "B of A Securities".
 *
 * IMPORTANT: this is a *display* transform only. Click-through routes
 * (/consensus?sector=...) must keep using the raw backend string so
 * the server-side filter still matches the row's stored sector value.
 */

const PRESERVED_ACRONYMS = new Set(['NEC']);

export function formatSectorName(raw) {
  if (!raw || typeof raw !== 'string') return raw;
  let s = raw.trim();
  if (!s) return s;

  // Pass-through for already-mixed-case strings — leave intentional
  // capitalization (e.g. "B of A", "& Services") alone.
  const hasLower = /[a-z]/.test(s);
  if (hasLower) return s;

  // Strip an ALL-CAPS parent prefix like "SERVICES-..." → "...".
  // Only fires for "<CAPS><dash>" patterns at the start so we don't
  // mangle hyphenated single-segment names.
  const prefixMatch = s.match(/^[A-Z]+-/);
  if (prefixMatch) {
    s = s.slice(prefixMatch[0].length).trim();
    if (!s) return raw; // fall back if the strip emptied the string
  }

  return s
    .split(' ')
    .map((word) => {
      if (!word) return word;
      const bare = word.replace(/[^A-Za-z]/g, '');
      if (PRESERVED_ACRONYMS.has(bare.toUpperCase())) return word.toUpperCase();
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    })
    .join(' ');
}
