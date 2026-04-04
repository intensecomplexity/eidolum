import EidolumLogo from './EidolumLogo';

/**
 * Branded loading spinner — Eidolum "E" with pulse animation.
 * Replace generic spinning circles with this.
 */
export default function EidolumSpinner({ size = 36, className = '' }) {
  return (
    <div className={`flex items-center justify-center ${className}`}>
      <div style={{ animation: 'eidolumPulse 1.5s ease-in-out infinite' }}>
        <EidolumLogo size={size} />
      </div>
      <style>{`@keyframes eidolumPulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }`}</style>
    </div>
  );
}
