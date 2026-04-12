/**
 * Canonical sector list shared across every page that renders a
 * sector filter dropdown — leaderboard, smart-money, consensus, etc.
 *
 * The 11 Morningstar sectors are the authoritative taxonomy (see
 * backend/utils/sector.py for the server-side equivalent). "Crypto"
 * sits outside Morningstar as a display bucket for crypto-only calls.
 *
 * Pages prepend their own default label (e.g. "All" or "All Sectors")
 * to this list when building their dropdown options.
 */
export const SECTOR_OPTIONS = [
  'Technology',
  'Healthcare',
  'Financial Services',
  'Consumer Cyclical',
  'Consumer Defensive',
  'Energy',
  'Industrials',
  'Communication Services',
  'Real Estate',
  'Utilities',
  'Basic Materials',
  'Crypto',
];
