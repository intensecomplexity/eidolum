/**
 * The Breathing Seal — Eidolum loading indicator.
 * E mark inside a circle with 3 orbiting dots at different speeds.
 * The dots create an ever-changing, non-repeating pattern.
 *
 * Pure CSS animations — zero JS overhead.
 *
 * Props:
 *  - size: "sm" (24px) | "md" (40px) | "lg" (64px) | number
 *  - text: optional muted text below
 */
const SIZES = { sm: 24, md: 40, lg: 64 };

export default function LoadingSpinner({ size = 'md', text }) {
  const px = typeof size === 'number' ? size : (SIZES[size] || 40);
  const showDots = px >= 32;

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative" style={{ width: px, height: px }}>
        {/* Static SVG: circle ring + E mark */}
        <svg
          width={px}
          height={px}
          viewBox="0 0 60 60"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          className="eidolum-breath"
        >
          {/* Circle ring */}
          <circle cx="30" cy="30" r="27" stroke="#D4A843" strokeWidth="1" fill="none" />

          {/* E mark */}
          <g transform="translate(20, 16) scale(0.6)">
            <line x1="5" y1="6" x2="5" y2="42" stroke="#D4A843" strokeWidth="2.5" strokeLinecap="round" />
            <line x1="5" y1="6" x2="26" y2="6" stroke="#D4A843" strokeWidth="2.5" strokeLinecap="round" />
            <line x1="5" y1="24" x2="20" y2="24" stroke="#D4A843" strokeWidth="2.5" strokeLinecap="round" />
            <line x1="5" y1="42" x2="26" y2="42" stroke="#D4A843" strokeWidth="2.5" strokeLinecap="round" />
            <circle cx="29" cy="6" r="1.2" fill="#D4A843" />
            <circle cx="23" cy="24" r="1.2" fill="#D4A843" />
            <circle cx="29" cy="42" r="1.2" fill="#D4A843" />
          </g>
        </svg>

        {/* 3 orbiting dots — each wrapper rotates at a different speed */}
        {showDots && (
          <>
            <div className="seal-orbit" style={{ animationDuration: '3s' }}>
              <div className="seal-dot" style={{ animationDuration: '3s' }} />
            </div>
            <div className="seal-orbit" style={{ animationDuration: '5s' }}>
              <div className="seal-dot" style={{ animationDuration: '5s' }} />
            </div>
            <div className="seal-orbit" style={{ animationDuration: '7s' }}>
              <div className="seal-dot" style={{ animationDuration: '7s' }} />
            </div>
          </>
        )}
      </div>
      {text && <span className="text-muted text-[13px]">{text}</span>}
    </div>
  );
}
