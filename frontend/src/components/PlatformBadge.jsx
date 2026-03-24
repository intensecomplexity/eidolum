const PLATFORM_STYLES = {
  youtube: { label: 'YouTube', bg: 'bg-red-500/10', text: 'text-red-400', border: 'border-red-500/20' },
  reddit: { label: 'Reddit', bg: 'bg-orange-500/10', text: 'text-orange-400', border: 'border-orange-500/20' },
  x: { label: 'X', bg: 'bg-sky-500/10', text: 'text-sky-400', border: 'border-sky-500/20' },
  congress: { label: 'Congress', bg: 'bg-yellow-500/10', text: 'text-yellow-400', border: 'border-yellow-500/20' },
  institutional: { label: 'Wall St', bg: 'bg-blue-500/10', text: 'text-blue-400', border: 'border-blue-500/20' },
};

export default function PlatformBadge({ platform }) {
  const style = PLATFORM_STYLES[platform] || PLATFORM_STYLES.youtube;
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold uppercase ${style.bg} ${style.text} border ${style.border}`}>
      {style.label}
    </span>
  );
}
