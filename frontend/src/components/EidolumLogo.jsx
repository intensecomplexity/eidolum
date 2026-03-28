/**
 * Phantom Fade E logo — the letter E with dissolving particle edges.
 * Props: size (default 24)
 */
export default function EidolumLogo({ size = 24 }) {
  const scale = size / 24;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Vertical spine */}
      <line x1="4" y1="2" x2="4" y2="22" stroke="#D4A017" strokeWidth="2.5" strokeLinecap="round"/>
      {/* Top arm with fade */}
      <line x1="4" y1="3" x2="16" y2="3" stroke="#D4A017" strokeWidth="2" strokeLinecap="round"/>
      <line x1="16" y1="3" x2="19" y2="3" stroke="#D4A017" strokeWidth="1.5" strokeLinecap="round" opacity="0.5"/>
      <circle cx="20.5" cy="3" r="0.8" fill="#D4A017" opacity="0.35"/>
      <circle cx="22" cy="3" r="0.5" fill="#D4A017" opacity="0.15"/>
      {/* Middle arm with fade */}
      <line x1="4" y1="12" x2="13" y2="12" stroke="#D4A017" strokeWidth="2" strokeLinecap="round"/>
      <line x1="13" y1="12" x2="16" y2="12" stroke="#D4A017" strokeWidth="1.5" strokeLinecap="round" opacity="0.5"/>
      <circle cx="17.5" cy="12" r="0.8" fill="#D4A017" opacity="0.35"/>
      <circle cx="19" cy="12" r="0.5" fill="#D4A017" opacity="0.15"/>
      {/* Bottom arm with fade */}
      <line x1="4" y1="21" x2="16" y2="21" stroke="#D4A017" strokeWidth="2" strokeLinecap="round"/>
      <line x1="16" y1="21" x2="19" y2="21" stroke="#D4A017" strokeWidth="1.5" strokeLinecap="round" opacity="0.5"/>
      <circle cx="20.5" cy="21" r="0.8" fill="#D4A017" opacity="0.35"/>
      <circle cx="22" cy="21" r="0.5" fill="#D4A017" opacity="0.15"/>
    </svg>
  );
}
