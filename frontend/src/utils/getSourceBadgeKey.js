/**
 * Determine the correct PlatformBadge key from a prediction or forecaster's source data.
 * Priority: verified_by > source_type > primary_verified_by > primary_source > platform.
 *
 * Works for:
 * - Predictions (have source_type, verified_by)
 * - Leaderboard forecasters (have primary_source, primary_verified_by, platform)
 */
export function getSourceBadgeKey(item, forecaster) {
  // Check verified_by (prediction-level or forecaster primary)
  const vb = item.verified_by || item.primary_verified_by;
  if (vb === 'x_scraper') return 'x';
  if (vb === 'benzinga_api' || vb === 'fmp_ratings' || vb === 'alphavantage' || vb === 'benzinga_rss' || vb === 'marketbeat_rss' || vb === 'yfinance') return 'institutional';
  if (vb === 'youtube_scraper') return 'youtube';
  if (vb === 'user' || vb === 'manual') return 'user';

  // Check source_type (prediction-level or forecaster primary)
  const st = item.source_type || item.primary_source;
  if (st === 'x' || st === 'twitter') return 'x';
  if (st === 'youtube') return 'youtube';
  if (st === 'reddit') return 'reddit';
  if (st === 'article') return 'institutional';

  return forecaster?.platform || item.platform || null;
}
