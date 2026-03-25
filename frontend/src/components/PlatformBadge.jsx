import { FaYoutube, FaReddit } from 'react-icons/fa';
import { FaXTwitter } from 'react-icons/fa6';

const PLATFORM_CONFIG = {
  youtube:       { icon: FaYoutube,  color: '#FF0000', label: 'YouTube' },
  twitter:       { icon: FaXTwitter, color: '#fff',    label: 'X', bg: '#000' },
  x:             { icon: FaXTwitter, color: '#fff',    label: 'X', bg: '#000' },
  reddit:        { icon: FaReddit,   color: '#FF4500', label: 'Reddit' },
  congress:      { icon: null,       color: '#3b82f6', label: 'Congress' },
  institutional: { icon: null,       color: '#a78bfa', label: 'Institution' },
};

export default function PlatformBadge({ platform, size = 16, showLabel = false }) {
  const config = PLATFORM_CONFIG[platform?.toLowerCase()] || null;
  if (!config) return null;

  const Icon = config.icon;

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '4px',
      background: config.bg || 'transparent',
      borderRadius: '4px',
      padding: config.bg ? '2px 5px' : '0',
    }}>
      {Icon
        ? <Icon size={size} color={config.color} title={config.label} />
        : <span style={{
            fontSize: size * 0.7 + 'px',
            color: config.color,
            fontWeight: 700,
            border: `1px solid ${config.color}`,
            borderRadius: '3px',
            padding: '0 3px',
            lineHeight: 1.4,
          }}>{config.label}</span>
      }
      {showLabel && (
        <span style={{ color: config.color, fontSize: size * 0.85 + 'px', fontWeight: 500 }}>
          {config.label}
        </span>
      )}
    </span>
  );
}
