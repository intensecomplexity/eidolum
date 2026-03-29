/**
 * Round a number DOWN to a clean display value.
 *
 *   < 1,000     → nearest 100   (847 → "800+")
 *   1,000–9,999 → nearest 500   (1,487 → "1,000+")
 *   10k–99,999  → nearest 5,000 (53,129 → "50,000+")
 *   100,000+    → nearest 50,000
 */
export default function formatRoundNumber(n) {
  if (!n || n <= 0) return '0';

  let step;
  if (n < 1000) step = 100;
  else if (n < 10000) step = 500;
  else if (n < 100000) step = 5000;
  else step = 50000;

  const rounded = Math.floor(n / step) * step;
  return rounded.toLocaleString() + '+';
}
