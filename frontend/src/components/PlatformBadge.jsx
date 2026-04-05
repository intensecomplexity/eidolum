import { FaYoutube, FaReddit } from 'react-icons/fa';
import { FaXTwitter } from 'react-icons/fa6';

const PLATFORM_CONFIG = {
  youtube:       { Icon: FaYoutube, iconColor: '#FF0000', label: 'YouTube', bg: '#FF0000', text: '#ffffff' },
  twitter:       { Icon: FaXTwitter, iconColor: '#ffffff', label: 'X', bg: '#000000', text: '#ffffff' },
  x:             { Icon: FaXTwitter, iconColor: '#ffffff', label: 'X', bg: '#000000', text: '#ffffff' },
  reddit:        { Icon: FaReddit, iconColor: '#FF4500', label: 'Reddit', bg: '#FF4500', text: '#ffffff' },
  congress:      { Icon: null, label: 'Gov', bg: '#3b82f6', text: '#ffffff' },
  institutional: { Icon: null, label: 'Wall St', bg: '#D4A843', text: '#0d0f13' },
  player:        { Icon: null, label: 'Community', bg: '#34d399', text: '#0d0f13' },
  user:          { Icon: null, label: 'Community', bg: '#34d399', text: '#0d0f13' },
  article:       { Icon: null, label: 'Wall St', bg: '#D4A843', text: '#0d0f13' },
};

export default function PlatformBadge({ platform, size = 16, showLabel = false }) {
  if (!platform) return null;
  const config = PLATFORM_CONFIG[platform.toLowerCase()];
  if (!config) return null;
  const { Icon, iconColor, label, bg, text } = config;

  // Icon-only mode (default, small)
  if (!showLabel && Icon) {
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        background: bg, borderRadius: '4px', padding: '2px 5px',
        lineHeight: 1, verticalAlign: 'middle',
      }}>
        <Icon size={size} color={iconColor || text} style={{ display: 'block' }} />
      </span>
    );
  }

  // Pill badge mode
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: '3px',
      background: bg, color: text, borderRadius: '4px',
      padding: '1px 6px', fontSize: '10px', fontWeight: 700,
      lineHeight: 1.5, verticalAlign: 'middle', whiteSpace: 'nowrap',
    }}>
      {Icon && <Icon size={Math.max(size * 0.7, 10)} color={iconColor || text} style={{ display: 'block' }} />}
      {label}
    </span>
  );
}
