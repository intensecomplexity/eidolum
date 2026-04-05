import EidolumLogo from './EidolumLogo';

/**
 * The Breathing Seal — premium Eidolum loading indicator.
 * Uses the real EidolumLogo SVG (same E mark as Vault Door splash and navbar).
 * Gold circle ring + 3 orbiting dots + pulsing E. All CSS animations.
 *
 * size="sm" (24px): just the E pulsing, no ring/dots
 * size="md" (40px): E + ring + dots
 * size="lg" (64px): E + ring + dots, primary between-page usage
 */
const SIZES = { sm: 24, md: 40, lg: 64 };

export default function LoadingSpinner({ size = 'md', text }) {
  const px = typeof size === 'number' ? size : (SIZES[size] || 40);
  const showRing = px >= 36;
  // E logo size: ~55% of container for proper padding inside the ring
  const logoSize = Math.round(px * 0.5);
  // Ring radius and orbit radius
  const ringR = px / 2 - 2;

  return (
    <div className="flex flex-col items-center justify-center" style={{ gap: 16 }}>
      <div className="relative flex items-center justify-center eidolum-breath" style={{ width: px, height: px }}>
        {/* Circle ring */}
        {showRing && (
          <svg
            className="absolute inset-0"
            width={px} height={px}
            viewBox={`0 0 ${px} ${px}`}
            fill="none"
          >
            <circle
              cx={px / 2} cy={px / 2} r={ringR}
              stroke="#D4A843" strokeWidth="1.5" fill="none" opacity="0.3"
            />
          </svg>
        )}

        {/* The real E mark — centered */}
        <EidolumLogo size={logoSize} />

        {/* 3 orbiting dots — clean CSS rotation at different speeds */}
        {showRing && (
          <>
            <div className="absolute inset-0" style={{ animation: 'sealOrbit 3s linear infinite' }}>
              <svg width={px} height={px} viewBox={`0 0 ${px} ${px}`} className="absolute inset-0">
                <circle cx={px / 2} cy={2} r="2.5" fill="#D4A843" opacity="0.7" />
              </svg>
            </div>
            <div className="absolute inset-0" style={{ animation: 'sealOrbit 5s linear infinite', animationDelay: '-1.5s' }}>
              <svg width={px} height={px} viewBox={`0 0 ${px} ${px}`} className="absolute inset-0">
                <circle cx={px / 2} cy={2} r="2" fill="#D4A843" opacity="0.5" />
              </svg>
            </div>
            <div className="absolute inset-0" style={{ animation: 'sealOrbit 7s linear infinite', animationDelay: '-3s' }}>
              <svg width={px} height={px} viewBox={`0 0 ${px} ${px}`} className="absolute inset-0">
                <circle cx={px / 2} cy={2} r="1.5" fill="#D4A843" opacity="0.35" />
              </svg>
            </div>
          </>
        )}
      </div>
      {text && <span className="text-muted text-[13px]">{text}</span>}
    </div>
  );
}
