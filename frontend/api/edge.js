// Vercel Edge Function — proxies a STRICT ALLOWLIST of public, anonymous
// GET API endpoints from the Railway backend and serves them through
// Vercel's edge CDN, so repeat visits worldwide skip the ~200-400ms
// Railway round-trip (same mechanism as the logo function in
// frontend/api/logo/[ticker].js: Vercel edge-caches Edge Function
// responses that carry s-maxage; it does NOT edge-cache external
// rewrites).
//
// ROUTING — why a single file + rewrite instead of api/edge/[...path].js:
// the bare /api directory only supports single [param] segments, not
// catch-alls; a [...path].js file deploys but Vercel returns its own
// NOT_FOUND for the route (caused the 2026-06-11 ~12min incident, rolled
// back in f5577ff). vercel.json rewrites /api/edge/:path* to
// /api/edge?path=:path* (the same :path* syntax the og-image rule uses),
// and Vercel merges the original query params into the rewritten URL.
//
// SECURITY MODEL — read before editing:
// - The allowlist below is the boundary. Every entry was verified
//   byte-identical for anonymous vs authenticated requests (perf ship 2,
//   2026-06-11) — these responses contain NO per-user data.
// - Anything not matching the allowlist returns 404. Never widen a
//   pattern beyond the verified endpoint shape; never add an endpoint
//   without re-running the anon-vs-auth byte-diff.
// - GET only. Incoming Authorization/Cookie headers are NEVER forwarded
//   (we build the upstream fetch with no client headers at all), so a
//   personalized variant can never be cached even if the upstream grows
//   auth-dependent behavior later.
//
// Cache strategy (s-maxage only — browser caching unchanged so the SPA's
// own in-memory caches keep their existing semantics):
// - homepage-data / stats/global: 5 min (matches the worker cron cadence)
// - leaderboard / consensus / predictions / asset consensus / platforms: 2 min
// - sectors / themes / timeframes / flags: 10 min
// - non-2xx upstream: 30s — never pin errors for minutes (logo-function rule).

export const config = { runtime: 'edge' };

const ORIGIN = 'https://api.eidolum.com';

// path (the ?path= rewrite param) → must match one of these EXACTLY.
const ALLOWLIST = [
  /^homepage-data$/,
  /^stats\/global$/,
  /^leaderboard$/,
  /^leaderboard\/available-timeframes$/,
  /^sectors$/,
  /^themes$/,
  /^themes\/[a-z0-9-]{1,60}$/,
  /^consensus$/,
  /^predictions\/recent$/,
  /^predictions\/today$/,
  /^platforms\/[a-z]{1,20}$/,
  /^asset\/[A-Za-z0-9.^-]{1,12}\/consensus$/,
  /^public\/flags$/,
  /^features$/,
  // Perf ship 3 (2026-06-12) — verified anon/auth byte-identical (the two
  // activity feeds differ only in row ORDER, identically for anon-vs-anon —
  // unstable sort, not personalization). /activity/friends is personalized
  // and stays direct; /analysts excluded until its backend 504 is fixed.
  /^smart-money$/,
  /^activity\/recent-predictions$/,
  /^activity\/recently-scored$/,
  /^activity\/expiring$/,
  /^activity\/disclosures$/,
  /^trending-tickers$/,
  /^predictions\/expiring$/,
  /^firms$/,
  /^firm\/[a-z0-9-]{1,100}$/,
  /^earnings\/upcoming$/,
  // Perf ship 4 — eligible after the e832e3e backend rewrite (was a
  // guaranteed 504). Exact match only: /analysts/subscriptions and the
  // other personalized sub-paths stay direct.
  /^analysts$/,
];

const LONG = 'public, s-maxage=600, stale-while-revalidate=1200';
const MED = 'public, s-maxage=120, stale-while-revalidate=300';
// List feeds: generous SWR so quiet-traffic visitors get instant-stale +
// background revalidate instead of paying a full MISS.
const FEED = 'public, s-maxage=120, stale-while-revalidate=600';
const SHORT_FAIL = 'public, s-maxage=30';
const CRON = 'public, s-maxage=300, stale-while-revalidate=600';

function cacheControlFor(path, ok) {
  if (!ok) return SHORT_FAIL;
  if (path === 'homepage-data' || path === 'stats/global') return CRON;
  if (
    path === 'sectors' ||
    path === 'themes' || path.startsWith('themes/') ||
    path === 'leaderboard/available-timeframes' ||
    path === 'public/flags' ||
    path === 'features'
  ) return LONG;
  if (
    path === 'smart-money' ||
    path.startsWith('activity/') ||
    path === 'trending-tickers' ||
    path === 'predictions/expiring' ||
    path === 'firms' || path.startsWith('firm/') ||
    path === 'earnings/upcoming' ||
    path === 'analysts'
  ) return FEED;
  return MED;
}

export default async function handler(request) {
  if (request.method !== 'GET') {
    return new Response('Method not allowed', { status: 405 });
  }

  const url = new URL(request.url);
  const path = (url.searchParams.get('path') || '').replace(/^\/+|\/+$/g, '');

  if (!ALLOWLIST.some((re) => re.test(path))) {
    return new Response('Not found', { status: 404 });
  }

  // Original query params (minus the rewrite's own ?path=) pass through.
  const qs = new URLSearchParams(url.searchParams);
  qs.delete('path');
  const search = qs.toString() ? `?${qs.toString()}` : '';

  // Fresh fetch with NO client headers — Authorization/Cookie are stripped
  // by construction, not by deletion.
  let upstream;
  try {
    upstream = await fetch(`${ORIGIN}/api/${path}${search}`, {
      headers: { accept: 'application/json' },
    });
  } catch (_err) {
    return new Response(JSON.stringify({ detail: 'upstream error' }), {
      status: 502,
      headers: { 'content-type': 'application/json', 'cache-control': SHORT_FAIL },
    });
  }

  const headers = {
    'content-type': upstream.headers.get('content-type') || 'application/json',
    'cache-control': cacheControlFor(path, upstream.ok),
    'x-edge-proxy': 'eidolum-public-get',
  };
  // Pagination totals (e.g. /analysts) ride in this header — forward it,
  // since we build the response with explicit headers only.
  const totalCount = upstream.headers.get('x-total-count');
  if (totalCount) headers['x-total-count'] = totalCount;

  return new Response(upstream.body, {
    status: upstream.status,
    headers,
  });
}
