import { useState, useEffect } from 'react';

// ── Logo cache in localStorage ──────────────────────────────────────────────
const CACHE_PREFIX = 'eidolum_logo:';

function getCachedLogoUrl(ticker) {
  if (!ticker) return null;
  try {
    const val = localStorage.getItem(CACHE_PREFIX + ticker);
    if (val === 'no_logo') return 'no_logo';
    return val || null;
  } catch { return null; }
}

function setCachedLogoUrl(ticker, url) {
  if (!ticker) return;
  try {
    localStorage.setItem(CACHE_PREFIX + ticker, url || 'no_logo');
  } catch { /* localStorage full — continue without caching */ }
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

// ── Preload queue for top tickers ───────────────────────────────────────────
let _preloaded = false;

export function preloadLogos(tickers) {
  if (_preloaded || !tickers?.length) return;
  _preloaded = true;

  // Only preload tickers not already cached
  const uncached = tickers.filter(t => !getCachedLogoUrl(t));
  if (!uncached.length) return;

  // Batch preload 5 at a time via hidden Image objects
  let idx = 0;
  function loadBatch() {
    const batch = uncached.slice(idx, idx + 5);
    if (!batch.length) return;
    batch.forEach(ticker => {
      // Try Clearbit as a lightweight preload (just validates the URL)
      const img = new Image();
      img.onload = () => {
        // We don't know the exact URL to cache without domain info
        // The real caching happens in CompanyLogo on first render
      };
      img.onerror = () => {};
      // Can't preload FMP logos without the URL — skip
    });
    idx += 5;
    if (idx < uncached.length) {
      setTimeout(loadBatch, 500);
    }
  }
  setTimeout(loadBatch, 2000); // Start 2s after app load
}


// ── Component ───────��──────────────────────────────────���────────────────────
export default function CompanyLogo({ domain, logoUrl, ticker, size = 24 }) {
  const symbol = ticker || '?';
  const imgSize = Math.round(size * 0.75);
  const fontSize = symbol.length <= 2 ? size * 0.4 : symbol.length <= 3 ? size * 0.32 : size * 0.25;

  // Check cache first
  const cached = getCachedLogoUrl(symbol);
  const [effectiveUrl, setEffectiveUrl] = useState(() => {
    if (cached && cached !== 'no_logo') return cached;
    return logoUrl || null;
  });
  const [loaded, setLoaded] = useState(!!cached && cached !== 'no_logo');
  const [failed, setFailed] = useState(cached === 'no_logo');
  const [triedClearbit, setTriedClearbit] = useState(false);

  // If logoUrl prop changes (e.g. data loaded after mount), try it
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
    // Cache the working URL
    if (effectiveUrl) {
      setCachedLogoUrl(symbol, effectiveUrl);
    }
  }

  function handleError() {
    // If FMP URL failed, try Clearbit
    if (!triedClearbit && domain) {
      setTriedClearbit(true);
      const clearbitUrl = `https://logo.clearbit.com/${domain}`;
      setEffectiveUrl(clearbitUrl);
      setLoaded(false);
      return;
    }
    // All sources failed — mark as no_logo
    setFailed(true);
    setCachedLogoUrl(symbol, 'no_logo');
  }

  // Fallback: ticker letter on dark background
  if (failed || !effectiveUrl) {
    return (
      <div className="flex items-center justify-center rounded-lg shrink-0"
        style={{ ...container, backgroundColor: '#1e2028', color: '#ffffff',
          fontSize, fontWeight: 700, fontFamily: 'monospace', letterSpacing: '-0.02em' }}>
        {symbol}
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center rounded-lg shrink-0 overflow-hidden relative"
      style={{ ...container, backgroundColor: loaded ? '#ffffff' : '#1e2028' }}>
      <img
        src={effectiveUrl}
        alt=""
        width={imgSize}
        height={imgSize}
        loading="lazy"
        className="object-contain"
        onLoad={handleLoad}
        onError={handleError}
        style={{ opacity: loaded ? 1 : 0, transition: 'opacity 200ms ease-in' }}
      />
      {!loaded && (
        <span className="absolute" style={{ color: '#fff', fontSize, fontWeight: 700, fontFamily: 'monospace' }}>
          {symbol}
        </span>
      )}
    </div>
  );
}
