import { useState, useEffect, useRef } from 'react';

/**
 * TickerLogo -- bulletproof stock logo component.
 *
 * Fallback chain:
 *   1. /api/logo/{TICKER}.png  (processed, bg-stripped — best quality)
 *   2. FMP CDN primary          (raw — may need CSS treatment)
 *   3. FMP CDN alternate         (raw — may need CSS treatment)
 *   4. Gold letter on circle     (always works)
 *
 * Each level has a 4-second timeout. Failed URLs are cached in
 * localStorage so re-renders skip them instantly.
 */

// -- Failure cache (localStorage) --
const FAIL_PREFIX = 'logo_fail:';
const FAIL_TTL = 4 * 60 * 60 * 1000; // 4 hours

function isKnownFail(url) {
  try {
    const ts = localStorage.getItem(FAIL_PREFIX + url);
    if (!ts) return false;
    if (Date.now() - Number(ts) > FAIL_TTL) {
      localStorage.removeItem(FAIL_PREFIX + url);
      return false;
    }
    return true;
  } catch { return false; }
}

function markFailed(url) {
  try { localStorage.setItem(FAIL_PREFIX + url, String(Date.now())); } catch {}
}

// -- White/light logos that are invisible on light backgrounds --
const WHITE_LOGOS = new Set([
  'NKE', 'AMZN', 'LLY', 'UBER', 'SQ', 'BLOCK',
  'ABNB', 'SNAP', 'HOOD', 'COIN', 'RBLX', 'U', 'ZM',
  'SHOP', 'SPOT', 'NET', 'CRWD', 'DDOG', 'MDB', 'SNOW', 'DASH',
]);

/** Clear all cached logo failures from localStorage */
export function clearLogoCache() {
  try {
    const keys = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && (key.startsWith(FAIL_PREFIX) || key.startsWith('eidolum_logo:') || key.startsWith('logo_dark_'))) {
        keys.push(key);
      }
    }
    keys.forEach(k => localStorage.removeItem(k));
    return keys.length;
  } catch { return 0; }
}

// -- Build URL list for a ticker --
function buildUrls(symbol, logoUrl) {
  if (!symbol || symbol === '?') return [];
  const urls = [];
  if (logoUrl) urls.push(logoUrl);
  urls.push(`/api/logo/${symbol}.png`);
  urls.push(`https://financialmodelingprep.com/image-stock/${symbol}.png`);
  urls.push(`https://images.financialmodelingprep.com/symbol/${symbol}.png`);
  return urls.filter(u => !isKnownFail(u));
}

export default function TickerLogo({ ticker, logoUrl, size = 32, className = '' }) {
  const symbol = (ticker || '?').toUpperCase();
  const letter = symbol[0] || '?';

  const allUrls = buildUrls(symbol, logoUrl);
  const [idx, setIdx] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(allUrls.length === 0);
  const timerRef = useRef(null);
  const currentUrl = allUrls[idx] || null;

  // Clear timeout on unmount
  useEffect(() => {
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, []);

  // 4-second timeout per URL — move to next if too slow
  useEffect(() => {
    if (loaded || failed || !currentUrl) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      markFailed(currentUrl);
      tryNext();
    }, 4000);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [idx, loaded, failed]);

  function tryNext() {
    const next = idx + 1;
    if (next < allUrls.length) {
      setIdx(next);
      setLoaded(false);
    } else {
      setFailed(true);
    }
  }

  function handleLoad(e) {
    if (timerRef.current) clearTimeout(timerRef.current);
    const img = e.target;
    if (img.naturalWidth <= 1 || img.naturalHeight <= 1) {
      markFailed(currentUrl);
      tryNext();
      return;
    }
    setLoaded(true);
  }

  function handleError() {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (currentUrl) markFailed(currentUrl);
    tryNext();
  }

  const isDark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
  const container = { width: size, height: size, minWidth: size, minHeight: size };
  const fontSize = size * 0.42;

  // Fallback: gold letter on subtle circle
  if (failed || !currentUrl) {
    return (
      <div
        className={`flex items-center justify-center shrink-0 ${className}`}
        style={{
          ...container,
          backgroundColor: isDark ? '#1e2028' : '#e8e8e8',
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

  // Determine if current URL is a processed logo (no CSS needed) or raw CDN
  const isProcessed = currentUrl.startsWith('/api/logo/');
  const isWhiteLogo = WHITE_LOGOS.has(symbol);

  // CSS treatment for raw CDN logos
  let imgFilter = 'none';
  let imgBlend = 'normal';
  if (!isProcessed && loaded) {
    if (isWhiteLogo) {
      // White logos: slightly dim on dark, invert on light
      imgFilter = isDark ? 'brightness(0.85)' : 'brightness(0.15)';
    } else {
      // Default: blend mode drops baked-in backgrounds
      imgBlend = isDark ? 'screen' : 'multiply';
    }
  }

  return (
    <div
      className={`flex items-center justify-center shrink-0 overflow-hidden relative ${className}`}
      style={{ ...container, borderRadius: 6 }}
    >
      <img
        src={currentUrl}
        alt=""
        width={size}
        height={size}
        loading="lazy"
        crossOrigin="anonymous"
        onLoad={handleLoad}
        onError={handleError}
        style={{
          objectFit: 'contain',
          width: size,
          height: size,
          opacity: loaded ? 1 : 0,
          transition: 'opacity 200ms ease-in',
          filter: imgFilter,
          mixBlendMode: imgBlend,
        }}
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
