export default function EidolumLogo({ size = 24, className = "" }) {
  return (
    <svg viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" width={size} height={size} className={className}>
      {/* Vertical spine — thinner */}
      <line x1="12" y1="8" x2="12" y2="92" stroke="#D4A017" strokeWidth="5" strokeLinecap="round"/>

      {/* Top arm — solid then gradual fade */}
      <line x1="12" y1="12" x2="55" y2="12" stroke="#D4A017" strokeWidth="4.5" strokeLinecap="round"/>
      <line x1="55" y1="12" x2="68" y2="12" stroke="#D4A017" strokeWidth="3.5" strokeLinecap="round" opacity="0.5"/>
      <line x1="68" y1="12" x2="76" y2="12" stroke="#D4A017" strokeWidth="2.5" strokeLinecap="round" opacity="0.3"/>
      <circle cx="81" cy="12" r="2.5" fill="#D4A017" opacity="0.25"/>
      <circle cx="87" cy="12" r="1.8" fill="#D4A017" opacity="0.15"/>
      <circle cx="92" cy="12" r="1.2" fill="#D4A017" opacity="0.08"/>

      {/* Middle arm — shorter, same fade pattern */}
      <line x1="12" y1="50" x2="45" y2="50" stroke="#D4A017" strokeWidth="4.5" strokeLinecap="round"/>
      <line x1="45" y1="50" x2="56" y2="50" stroke="#D4A017" strokeWidth="3.5" strokeLinecap="round" opacity="0.5"/>
      <line x1="56" y1="50" x2="64" y2="50" stroke="#D4A017" strokeWidth="2.5" strokeLinecap="round" opacity="0.3"/>
      <circle cx="69" cy="50" r="2.5" fill="#D4A017" opacity="0.25"/>
      <circle cx="75" cy="50" r="1.8" fill="#D4A017" opacity="0.15"/>
      <circle cx="80" cy="50" r="1.2" fill="#D4A017" opacity="0.08"/>

      {/* Bottom arm — same as top */}
      <line x1="12" y1="88" x2="55" y2="88" stroke="#D4A017" strokeWidth="4.5" strokeLinecap="round"/>
      <line x1="55" y1="88" x2="68" y2="88" stroke="#D4A017" strokeWidth="3.5" strokeLinecap="round" opacity="0.5"/>
      <line x1="68" y1="88" x2="76" y2="88" stroke="#D4A017" strokeWidth="2.5" strokeLinecap="round" opacity="0.3"/>
      <circle cx="81" cy="88" r="2.5" fill="#D4A017" opacity="0.25"/>
      <circle cx="87" cy="88" r="1.8" fill="#D4A017" opacity="0.15"/>
      <circle cx="92" cy="88" r="1.2" fill="#D4A017" opacity="0.08"/>
    </svg>
  );
}
