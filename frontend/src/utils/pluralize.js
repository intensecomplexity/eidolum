/**
 * English pluralize helper. Returns "1 call" / "2 calls" / "0 calls".
 *
 * Use this everywhere we render "{n} {noun}" so the singular form
 * never reads "1 calls" or "1 predictions". Keep the API tiny on
 * purpose — nouns we count are all regular and don't need lookup
 * tables.
 *
 * Examples:
 *   pluralize(1, 'call')            -> '1 call'
 *   pluralize(2, 'call')            -> '2 calls'
 *   pluralize(1, 'analyst')         -> '1 analyst'
 *   pluralize(1, 'sector', 'sectors') -> '1 sector'
 */
export function pluralize(n, singular, plural) {
  const count = Number.isFinite(n) ? n : 0;
  const word = count === 1 ? singular : (plural || `${singular}s`);
  return `${count} ${word}`;
}
