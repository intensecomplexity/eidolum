import { useState, useEffect, useRef } from 'react';

/**
 * TickerLogo — simple, reliable stock logo component.
 *
 * Every logo sits in a dark rounded container (#1e2028).
 * No CSS filters. No blend modes. No special-case lists.
 * If the image fails, show a gold letter.
 */

const FAIL_PREFIX = 'logo_fail:';
const FAIL_TTL = 4 * 60 * 60 * 1000;

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

function buildUrls(symbol, logoUrl) {
  if (!symbol || symbol === '?') return [];
  const urls = [];
  if (logoUrl) urls.push(logoUrl);
  urls.push(`/api/logo/${symbol}.png`);
  urls.push(`https://financialmodelingprep.com/image-stock/${symbol}.png`);
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

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current); }, []);

  useEffect(() => {
    if (loaded || failed || !currentUrl) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => { markFailed(currentUrl); tryNext(); }, 4000);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [idx, loaded, failed]);

  function tryNext() {
    const next = idx + 1;
    if (next < allUrls.length) { setIdx(next); setLoaded(false); }
    else setFailed(true);
  }

  function handleLoad(e) {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (e.target.naturalWidth <= 1 || e.target.naturalHeight <= 1) { markFailed(currentUrl); tryNext(); return; }
    setLoaded(true);
  }

  function handleError() {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (currentUrl) markFailed(currentUrl);
    tryNext();
  }

  const box = { width: size, height: size, minWidth: size, minHeight: size };
  const pad = Math.max(Math.round(size * 0.1), 2);
  const imgSize = size - pad * 2;

  // Gold letter fallback
  if (failed || !currentUrl) {
    return (
      <div className={`flex items-center justify-center shrink-0 ${className}`}
        style={{ ...box, borderRadius: '50%', backgroundColor: '#1e2028', color: '#D4A843',
          fontSize: size * 0.45, fontWeight: 700, lineHeight: 1 }}>
        {letter}
      </div>
    );
  }

  // Dark container with logo image
  return (
    <div className={`flex items-center justify-center shrink-0 overflow-hidden ${className}`}
      style={{ ...box, borderRadius: 8, backgroundColor: '#1e2028', padding: pad }}>
      <img
        src={currentUrl}
        alt=""
        width={imgSize}
        height={imgSize}
        loading="lazy"
        onLoad={handleLoad}
        onError={handleError}
        style={{ objectFit: 'contain', width: imgSize, height: imgSize,
          opacity: loaded ? 1 : 0, transition: 'opacity 150ms ease-in' }}
      />
      {!loaded && (
        <span className="absolute" style={{ color: '#D4A843', fontSize: size * 0.32,
          fontWeight: 700, fontFamily: 'monospace' }}>
          {symbol.slice(0, 3)}
        </span>
      )}
    </div>
  );
}
