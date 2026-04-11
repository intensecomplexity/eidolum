import { useEffect, useState } from 'react';
import EidolumLogo from './EidolumLogo';

/**
 * Editorial splash. First visit only. 1.2s hard cap.
 * Skips entirely on return visits (localStorage flag) or reduced motion.
 */

const FADE_OUT_AT = 1000;
const HARD_CAP = 1200;

function getThemeBG() {
  const theme =
    localStorage.getItem('eidolum_theme') ||
    document.documentElement.getAttribute('data-theme') ||
    'dark';
  return theme === 'light' ? '#f5f5f7' : '#0d0f13';
}

export default function VaultDoorSplash({ onComplete }) {
  const [phase, setPhase] = useState('in'); // 'in' | 'out' | 'gone'

  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) {
      setPhase('gone');
      sessionStorage.setItem('eidolum_splash_seen', '1');
      localStorage.setItem('eidolum_visited', '1');
      onComplete?.();
      return;
    }

    const fade = setTimeout(() => setPhase('out'), FADE_OUT_AT);
    const done = setTimeout(() => {
      setPhase('gone');
      sessionStorage.setItem('eidolum_splash_seen', '1');
      localStorage.setItem('eidolum_visited', '1');
      onComplete?.();
    }, HARD_CAP);

    return () => {
      clearTimeout(fade);
      clearTimeout(done);
    };
  }, [onComplete]);

  if (phase === 'gone') return null;

  const bg = getThemeBG();
  const isLight = bg === '#f5f5f7';

  return (
    <div
      onClick={() => {
        setPhase('gone');
        sessionStorage.setItem('eidolum_splash_seen', '1');
        localStorage.setItem('eidolum_visited', '1');
        onComplete?.();
      }}
      aria-hidden="true"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        backgroundColor: bg,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'column',
        gap: 18,
        cursor: 'pointer',
        opacity: phase === 'out' ? 0 : 1,
        transition: 'opacity 200ms ease-out',
        pointerEvents: phase === 'out' ? 'none' : 'auto',
      }}
    >
      <div
        style={{
          opacity: 0,
          animation: 'eidolumSplashLogoIn 320ms ease-out forwards',
        }}
      >
        <EidolumLogo size={64} />
      </div>
      <div
        style={{
          opacity: 0,
          animation: 'eidolumSplashTextIn 360ms ease-out 200ms forwards',
          textAlign: 'center',
          maxWidth: '90vw',
        }}
      >
        <div
          style={{
            fontFamily: "'Sora', sans-serif",
            fontSize: 11,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            color: '#D4A843',
            fontWeight: 600,
          }}
        >
          Truth is the only currency.
        </div>
        <div
          style={{
            fontFamily: "'Instrument Serif', serif",
            fontSize: 18,
            marginTop: 6,
            color: isLight ? '#52525b' : '#a8a59f',
            fontStyle: 'italic',
          }}
        >
          Every analyst call. Scored against reality.
        </div>
      </div>
      <style>{`
        @keyframes eidolumSplashLogoIn {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes eidolumSplashTextIn {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
