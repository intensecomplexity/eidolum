// Vercel Edge Function — proxies ticker logos from the Railway backend
// and serves them through Vercel's edge CDN so cross-user first-visit
// latency drops from ~500ms (Railway europe-west4 round-trip) to
// ~20-50ms globally (Vercel POP HIT).
//
// Why an Edge Function instead of a plain rewrite in vercel.json:
// Vercel does NOT edge-cache external rewrites — `s-maxage` on the
// origin response is ignored for that route shape, even when set via
// vercel.json's `headers` override. Edge Functions, by contrast, ARE
// edge-cached when their responses include `s-maxage`. The 4a77551
// backend ship made the origin send `s-maxage` correctly; this ship
// wraps the call in an Edge Function so Vercel actually honors it.
//
// Routing: file-based via [ticker]. A request to /api/logo/AAPL.png
// arrives here with the path's last segment as "AAPL.png" — we strip
// the .png and forward to the Railway endpoint.
//
// Cache strategy: 30 days at the edge for 2xx, 60s for non-2xx. Short
// TTL on failures prevents a transient Railway 5xx or a 404 for a
// newly-processed ticker from sticking for a month.

export const config = { runtime: 'edge' };

const ORIGIN = 'https://api.eidolum.com';

export default async function handler(request) {
  const { pathname } = new URL(request.url);
  // pathname is "/api/logo/<segment>" — last segment may be "AAPL.png"
  // or just "AAPL"; either way strip a trailing .png so we always
  // forward the canonical "<TICKER>.png" upstream URL.
  const lastSegment = pathname.split('/').filter(Boolean).pop() || '';
  const ticker = lastSegment.replace(/\.png$/i, '').toUpperCase();

  if (!ticker) {
    return new Response('Missing ticker', { status: 400 });
  }

  let upstream;
  try {
    upstream = await fetch(`${ORIGIN}/api/logo/${encodeURIComponent(ticker)}.png`);
  } catch (_err) {
    // Upstream unreachable — short-cache the failure so a flapping
    // Railway doesn't permanently shadow the real logo at the edge.
    return new Response('upstream error', {
      status: 502,
      headers: { 'cache-control': 'public, max-age=60, s-maxage=60' },
    });
  }

  const cacheControl = upstream.ok
    ? 'public, max-age=604800, s-maxage=2592000, immutable'
    : 'public, max-age=60, s-maxage=60';

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      'content-type': upstream.headers.get('content-type') || 'image/png',
      'cache-control': cacheControl,
      'x-logo-source': upstream.headers.get('x-logo-source') || 'edge-proxy',
    },
  });
}
