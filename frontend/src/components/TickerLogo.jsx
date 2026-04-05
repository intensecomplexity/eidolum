import { useState, useEffect } from 'react';

// -- Logo cache with TTL (shared with CompanyLogo) --
const CACHE_PREFIX = 'eidolum_logo:';
const SUCCESS_TTL = 7 * 24 * 60 * 60 * 1000; // 7 days
const FAIL_TTL = 4 * 60 * 60 * 1000;          // 4 hours

function getCachedLogoUrl(ticker) {
  if (!ticker) return null;
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + ticker);
    if (!raw) return null;
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
      if (raw === 'no_logo') { localStorage.removeItem(CACHE_PREFIX + ticker); return null; }
      return raw;
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
  } catch {}
}

/** Clear all cached logos */
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

// -- FMP logo URL sources (static CDN, no API key needed) --
function fmpUrls(ticker) {
  if (!ticker || ticker === '?') return [];
  return [
    `https://financialmodelingprep.com/image-stock/${ticker.toUpperCase()}.png`,
    `https://images.financialmodelingprep.com/symbol/${ticker.toUpperCase()}.png`,
  ];
}

/**
 * TickerLogo -- renders a stock/company logo with fallback.
 *
 * Props:
 *   ticker   - ticker symbol (e.g. "AAPL")
 *   logoUrl  - optional explicit logo URL from API
 *   size     - pixel dimensions (default 32)
 *   className - optional extra class names on the outer wrapper
 *
 * Behavior:
 *   1. If logoUrl is provided, try it first.
 *   2. Then try FMP CDN URLs.
 *   3. Uses localStorage caching (shared with CompanyLogo).
 *   4. On all failures, render letter-in-circle fallback.
 */
export default function TickerLogo({ ticker, logoUrl, size = 32, className = '' }) {
  const symbol = (ticker || '?').toUpperCase();
  const letter = symbol[0] || '?';

  // Build ordered list of URLs to try: prop -> FMP primary -> FMP fallback
  const fallbacks = fmpUrls(symbol);
  const allUrls = [logoUrl, ...fallbacks].filter(Boolean);

  const cached = getCachedLogoUrl(symbol);
  const [urlIndex, setUrlIndex] = useState(0);
  const [effectiveUrl, setEffectiveUrl] = useState(() => {
    if (cached && cached !== 'no_logo') return cached;
    return allUrls[0] || null;
  });
  const [loaded, setLoaded] = useState(!!cached && cached !== 'no_logo');
  const [failed, setFailed] = useState(cached === 'no_logo');

  // If logoUrl prop arrives after mount, reset to try it
  useEffect(() => {
    if (logoUrl && !effectiveUrl && !failed) {
      setEffectiveUrl(logoUrl);
      setUrlIndex(0);
    }
  }, [logoUrl]);

  const container = {
    width: size,
    height: size,
    minWidth: size,
    minHeight: size,
  };

  function handleLoad(e) {
    // Guard against blank/tiny placeholder images returned by CDNs
    const img = e.target;
    if (img.naturalWidth <= 1 || img.naturalHeight <= 1) {
      handleError();
      return;
    }
    setLoaded(true);
    if (effectiveUrl) setCachedLogoUrl(symbol, effectiveUrl);
  }

  function handleError() {
    // Try next URL in the list
    const nextIdx = urlIndex + 1;
    const nextUrl = allUrls[nextIdx];
    if (nextUrl && nextUrl !== effectiveUrl) {
      setUrlIndex(nextIdx);
      setEffectiveUrl(nextUrl);
      setLoaded(false);
      return;
    }
    setFailed(true);
    setCachedLogoUrl(symbol, null);
  }

  const pad = Math.max(Math.round(size * 0.12), 2);
  const innerSize = size - pad * 2;
  const fontSize = size * 0.42;

  // Fallback: dark circle with gold letter
  if (failed || !effectiveUrl) {
    return (
      <div
        className={`flex items-center justify-center shrink-0 ${className}`}
        style={{
          ...container,
          backgroundColor: '#1e2028',
          borderRadius: '50%',
          color: '#D4A843',
          fontSize,
          fontWeight: 700,
          lineHeight: 1,
        }}
      >
        {letter}
      </div>
    );
  }

  // White rounded container for loaded logos
  const boxStyle = {
    ...container,
    backgroundColor: '#ffffff',
    border: '1px solid rgba(0,0,0,0.08)',
    borderRadius: 8,
    padding: pad,
  };

  return (
    <div
      className={`flex items-center justify-center shrink-0 overflow-hidden relative ${className}`}
      style={boxStyle}
    >
      <img
        src={effectiveUrl}
        alt=""
        width={innerSize}
        height={innerSize}
        loading="lazy"
        className="object-contain"
        onLoad={handleLoad}
        onError={handleError}
        style={{ opacity: loaded ? 1 : 0, transition: 'opacity 200ms ease-in' }}
      />
      {!loaded && (
        <span
          className="absolute"
          style={{
            color: '#D4A843',
            fontSize: size * 0.32,
            fontWeight: 700,
            fontFamily: 'monospace',
          }}
        >
          {symbol.slice(0, 3)}
        </span>
      )}
    </div>
  );
}
