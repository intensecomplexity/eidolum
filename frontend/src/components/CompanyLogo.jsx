import { useState, useEffect } from 'react';

// ── Logo cache with TTL ───────────────────────────────────────────────────────
const CACHE_PREFIX = 'eidolum_logo:';
const SUCCESS_TTL = 7 * 24 * 60 * 60 * 1000; // 7 days
const FAIL_TTL = 4 * 60 * 60 * 1000;          // 4 hours

function getCachedLogoUrl(ticker) {
  if (!ticker) return null;
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + ticker);
    if (!raw) return null;

    // New JSON format: { url, ts } or { failed, ts }
    try {
      const entry = JSON.parse(raw);
      const age = Date.now() - (entry.ts || 0);
      if (entry.failed) {
        if (age > FAIL_TTL) { localStorage.removeItem(CACHE_PREFIX + ticker); return null; }
        return 'no_logo';
      }
      if (entry.url) {
        if (age > SUCCESS_TTL) { localStorage.removeItem(CACHE_PREFIX + ticker); return null; }
        return entry.url;
      }
      return null;
    } catch {
      // Old plain-string format — clear poisoned 'no_logo' entries
      if (raw === 'no_logo') { localStorage.removeItem(CACHE_PREFIX + ticker); return null; }
      return raw; // old cached URL string, still usable
    }
  } catch { return null; }
}

function setCachedLogoUrl(ticker, url) {
  if (!ticker) return;
  try {
    if (!url) {
      localStorage.setItem(CACHE_PREFIX + ticker, JSON.stringify({ failed: true, ts: Date.now() }));
    } else {
      localStorage.setItem(CACHE_PREFIX + ticker, JSON.stringify({ url, ts: Date.now() }));
    }
  } catch { /* localStorage full */ }
}

/** Clear all cached logos (for admin/debug use) */
export function clearLogoCache() {
  try {
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(CACHE_PREFIX)) keys.push(key);
    }
    keys.forEach(k => localStorage.removeItem(k));
    return keys.length;
  } catch { return 0; }
}


// ── Component ─────────────────────────────────────────────────────────────────
export default function CompanyLogo({ domain, logoUrl, ticker, size = 24 }) {
  const symbol = ticker || '?';
  const imgSize = Math.round(size * 0.75);
  const fontSize = symbol.length <= 2 ? size * 0.4 : symbol.length <= 3 ? size * 0.32 : size * 0.25;

  // Built-in FMP CDN fallback — works for most US tickers without API key
  const fmpFallback = symbol !== '?' ? `https://images.financialmodelingprep.com/symbol/${symbol}.png` : null;

  // Resolve initial URL: cache → prop → FMP CDN
  const cached = getCachedLogoUrl(symbol);
  const [effectiveUrl, setEffectiveUrl] = useState(() => {
    if (cached && cached !== 'no_logo') return cached;
    return logoUrl || fmpFallback;
  });
  const [loaded, setLoaded] = useState(!!cached && cached !== 'no_logo');
  const [failed, setFailed] = useState(cached === 'no_logo');
  const [triedFmp, setTriedFmp] = useState(false);

  // If logoUrl prop arrives after mount (async data), try it
  useEffect(() => {
    if (logoUrl && !effectiveUrl && !failed) {
      setEffectiveUrl(logoUrl);
    }
  }, [logoUrl]);

  const container = {
    width: size, height: size, minWidth: size, minHeight: size,
  };

  function handleLoad() {
    setLoaded(true);
    if (effectiveUrl) setCachedLogoUrl(symbol, effectiveUrl);
  }

  function handleError() {
    // If the explicit logoUrl failed, try FMP CDN
    if (!triedFmp && fmpFallback && effectiveUrl !== fmpFallback) {
      setTriedFmp(true);
      setEffectiveUrl(fmpFallback);
      setLoaded(false);
      return;
    }
    // All sources exhausted — mark as failed (with TTL, will retry later)
    setFailed(true);
    setCachedLogoUrl(symbol, null);
  }

  // Fallback: ticker letter
  if (failed || !effectiveUrl) {
    return (
      <div className="flex items-center justify-center rounded-lg shrink-0 bg-surface-2 text-text-primary"
        style={{ ...container, fontSize, fontWeight: 700, fontFamily: 'monospace', letterSpacing: '-0.02em' }}>
        {symbol}
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center rounded-lg shrink-0 overflow-hidden relative bg-surface-2"
      style={container}>
      <img
        src={effectiveUrl}
        alt=""
        width={imgSize}
        height={imgSize}
        loading="lazy"
        className="object-contain"
        onLoad={handleLoad}
        onError={handleError}
        style={{ opacity: loaded ? 1 : 0, transition: 'opacity 200ms ease-in',
          backgroundColor: loaded ? '#ffffff' : 'transparent', borderRadius: loaded ? 2 : 0 }}
      />
      {!loaded && (
        <span className="absolute text-text-primary" style={{ fontSize, fontWeight: 700, fontFamily: 'monospace' }}>
          {symbol}
        </span>
      )}
    </div>
  );
}
