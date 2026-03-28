/**
 * Phantom Fade E logo — the letter E with arms that dissolve into tiny particles.
 * Uses currentColor so it inherits text color from parent (set color: #D4A017).
 * Props: size (default 24), className (optional)
 */
export default function EidolumLogo({ size = 24, className }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      style={{ color: '#D4A017' }}
    >
      {/* Vertical spine */}
      <line x1="15" y1="8" x2="15" y2="92" stroke="currentColor" strokeWidth="8" strokeLinecap="round"/>

      {/* Top arm — solid to fade */}
      <line x1="15" y1="12" x2="62" y2="12" stroke="currentColor" strokeWidth="6" strokeLinecap="round"/>
      <line x1="62" y1="12" x2="74" y2="12" stroke="currentColor" strokeWidth="4" strokeLinecap="round" opacity="0.45"/>
      <circle cx="79" cy="12" r="2.2" fill="currentColor" opacity="0.25"/>
      <circle cx="84" cy="12" r="1.5" fill="currentColor" opacity="0.12"/>
      <circle cx="88" cy="12" r="0.9" fill="currentColor" opacity="0.06"/>

      {/* Middle arm — slightly shorter, solid to fade */}
      <line x1="15" y1="50" x2="52" y2="50" stroke="currentColor" strokeWidth="6" strokeLinecap="round"/>
      <line x1="52" y1="50" x2="62" y2="50" stroke="currentColor" strokeWidth="4" strokeLinecap="round" opacity="0.45"/>
      <circle cx="67" cy="50" r="2.2" fill="currentColor" opacity="0.25"/>
      <circle cx="72" cy="50" r="1.5" fill="currentColor" opacity="0.12"/>
      <circle cx="76" cy="50" r="0.9" fill="currentColor" opacity="0.06"/>

      {/* Bottom arm — solid to fade */}
      <line x1="15" y1="88" x2="62" y2="88" stroke="currentColor" strokeWidth="6" strokeLinecap="round"/>
      <line x1="62" y1="88" x2="74" y2="88" stroke="currentColor" strokeWidth="4" strokeLinecap="round" opacity="0.45"/>
      <circle cx="79" cy="88" r="2.2" fill="currentColor" opacity="0.25"/>
      <circle cx="84" cy="88" r="1.5" fill="currentColor" opacity="0.12"/>
      <circle cx="88" cy="88" r="0.9" fill="currentColor" opacity="0.06"/>
    </svg>
  );
}
