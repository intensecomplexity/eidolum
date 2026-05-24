import { FaReddit } from 'react-icons/fa';
import { FaXTwitter } from 'react-icons/fa6';

// FaYoutube is a single-color glyph; rendered red on the red badge bg the
// play triangle disappeared and the badge read as a featureless red blob.
// Inline 2-color SVG keeps the rect red AND draws the play triangle white.
function YouTubeGlyph({ size = 16 }) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="YouTube" role="img"
      style={{ display: 'block' }}
    >
      <path d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.6 12 3.6 12 3.6s-7.5 0-9.4.5A3 3 0 0 0 .5 6.2 31 31 0 0 0 0 12a31 31 0 0 0 .5 5.8 3 3 0 0 0 2.1 2.1C4.5 20.4 12 20.4 12 20.4s7.5 0 9.4-.5a3 3 0 0 0 2.1-2.1A31 31 0 0 0 24 12a31 31 0 0 0-.5-5.8z" fill="#FF0000"/>
      <path d="M9.6 15.6 15.8 12 9.6 8.4z" fill="#fff"/>
    </svg>
  );
}

const PLATFORM_CONFIG = {
  youtube:       { Icon: YouTubeGlyph, iconColor: '#FF0000', label: 'YouTube', bg: '#FF0000', text: '#ffffff' },
  twitter:       { Icon: FaXTwitter, iconColor: '#ffffff', label: 'X', bg: '#000000', text: '#ffffff' },
  x:             { Icon: FaXTwitter, iconColor: '#ffffff', label: 'X', bg: '#000000', text: '#ffffff' },
  reddit:        { Icon: FaReddit, iconColor: '#FF4500', label: 'Reddit', bg: '#FF4500', text: '#ffffff' },
  congress:      { Icon: null, label: 'Gov', bg: '#3b82f6', text: '#ffffff' },
  institutional: { Icon: null, label: 'Wall St', bg: '#3b82f6', text: '#ffffff' },
  player:        { Icon: null, label: 'Community', bg: '#34d399', text: '#0d0f13' },
  user:          { Icon: null, label: 'Community', bg: '#34d399', text: '#0d0f13' },
  article:       { Icon: null, label: 'Wall St', bg: '#3b82f6', text: '#ffffff' },
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
