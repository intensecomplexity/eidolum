export default function EidolumLogo({ size = 24, className = "" }) {
  return (
    <svg viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" width={size} height={size} className={className}>
      <line x1="15" y1="8" x2="15" y2="92" stroke="#D4A017" strokeWidth="8" strokeLinecap="round"/>
      <line x1="15" y1="12" x2="62" y2="12" stroke="#D4A017" strokeWidth="6" strokeLinecap="round"/>
      <line x1="62" y1="12" x2="74" y2="12" stroke="#D4A017" strokeWidth="4" strokeLinecap="round" opacity="0.45"/>
      <circle cx="79" cy="12" r="2.2" fill="#D4A017" opacity="0.25"/>
      <circle cx="84" cy="12" r="1.5" fill="#D4A017" opacity="0.12"/>
      <circle cx="88" cy="12" r="0.9" fill="#D4A017" opacity="0.06"/>
      <line x1="15" y1="50" x2="52" y2="50" stroke="#D4A017" strokeWidth="6" strokeLinecap="round"/>
      <line x1="52" y1="50" x2="62" y2="50" stroke="#D4A017" strokeWidth="4" strokeLinecap="round" opacity="0.45"/>
      <circle cx="67" cy="50" r="2.2" fill="#D4A017" opacity="0.25"/>
      <circle cx="72" cy="50" r="1.5" fill="#D4A017" opacity="0.12"/>
      <circle cx="76" cy="50" r="0.9" fill="#D4A017" opacity="0.06"/>
      <line x1="15" y1="88" x2="62" y2="88" stroke="#D4A017" strokeWidth="6" strokeLinecap="round"/>
      <line x1="62" y1="88" x2="74" y2="88" stroke="#D4A017" strokeWidth="4" strokeLinecap="round" opacity="0.45"/>
      <circle cx="79" cy="88" r="2.2" fill="#D4A017" opacity="0.25"/>
      <circle cx="84" cy="88" r="1.5" fill="#D4A017" opacity="0.12"/>
      <circle cx="88" cy="88" r="0.9" fill="#D4A017" opacity="0.06"/>
    </svg>
  );
}
