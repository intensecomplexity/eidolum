import EidolumLogo from './EidolumLogo';

/**
 * Branded empty state — large watermark "E" with message.
 */
export default function EmptyState({ message = 'No data yet', subtitle }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 relative">
      <div style={{ opacity: 0.06 }}>
        <EidolumLogo size={120} />
      </div>
      <p className="text-text-secondary text-sm mt-4">{message}</p>
      {subtitle && <p className="text-muted text-xs mt-1">{subtitle}</p>}
    </div>
  );
}
