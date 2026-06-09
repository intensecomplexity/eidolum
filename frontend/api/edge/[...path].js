// Vercel Edge Function — proxies a STRICT ALLOWLIST of public, anonymous
// GET API endpoints from the Railway backend and serves them through
// Vercel's edge CDN, so repeat visits worldwide skip the ~200-400ms
// Railway round-trip (same mechanism as the logo function in
// frontend/api/logo/[ticker].js: Vercel edge-caches Edge Function
// responses that carry s-maxage; it does NOT edge-cache external
// rewrites).
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

// path (after /api/edge/) → must match one of these EXACTLY.
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
];

const LONG = 'public, s-maxage=600, stale-while-revalidate=1200';
const MED = 'public, s-maxage=120, stale-while-revalidate=300';
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
  return MED;
}

export default async function handler(request) {
  if (request.method !== 'GET') {
    return new Response('Method not allowed', { status: 405 });
  }

  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api\/edge\//, '').replace(/\/+$/, '');

  if (!ALLOWLIST.some((re) => re.test(path))) {
    return new Response('Not found', { status: 404 });
  }

  // Fresh fetch with NO client headers — Authorization/Cookie are stripped
  // by construction, not by deletion.
  let upstream;
  try {
    upstream = await fetch(`${ORIGIN}/api/${path}${url.search}`, {
      headers: { accept: 'application/json' },
    });
  } catch (_err) {
    return new Response(JSON.stringify({ detail: 'upstream error' }), {
      status: 502,
      headers: { 'content-type': 'application/json', 'cache-control': SHORT_FAIL },
    });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      'content-type': upstream.headers.get('content-type') || 'application/json',
      'cache-control': cacheControlFor(path, upstream.ok),
      'x-edge-proxy': 'eidolum-public-get',
    },
  });
}
