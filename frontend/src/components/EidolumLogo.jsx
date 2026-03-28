export default function EidolumLogo({ size = 24, className = "" }) {
  const sw = Math.max(size * 0.12, 1.5); // stroke width scales with size
  const c = "#D4A843";
  return (
    <svg viewBox="0 0 40 48" fill="none" xmlns="http://www.w3.org/2000/svg" width={size} height={size * 1.2} className={className}>
      {/* Vertical spine */}
      <line x1="5" y1="6" x2="5" y2="42" stroke={c} strokeWidth={sw} strokeLinecap="round"/>

      {/* Top arm + dissolving dots */}
      <line x1="5" y1="6" x2="26" y2="6" stroke={c} strokeWidth={sw} strokeLinecap="round"/>
      <circle cx="30" cy="6" r={sw * 0.55} fill={c}/>
      <circle cx="34" cy="6" r={sw * 0.4} fill={c} opacity="0.6"/>
      <circle cx="37.5" cy="6" r={sw * 0.28} fill={c} opacity="0.3"/>

      {/* Middle arm (shorter) + dissolving dots */}
      <line x1="5" y1="24" x2="20" y2="24" stroke={c} strokeWidth={sw} strokeLinecap="round"/>
      <circle cx="24" cy="24" r={sw * 0.55} fill={c}/>
      <circle cx="27.5" cy="24" r={sw * 0.4} fill={c} opacity="0.6"/>
      <circle cx="30.5" cy="24" r={sw * 0.28} fill={c} opacity="0.3"/>

      {/* Bottom arm + dissolving dots */}
      <line x1="5" y1="42" x2="26" y2="42" stroke={c} strokeWidth={sw} strokeLinecap="round"/>
      <circle cx="30" cy="42" r={sw * 0.55} fill={c}/>
      <circle cx="34" cy="42" r={sw * 0.4} fill={c} opacity="0.6"/>
      <circle cx="37.5" cy="42" r={sw * 0.28} fill={c} opacity="0.3"/>
    </svg>
  );
}
