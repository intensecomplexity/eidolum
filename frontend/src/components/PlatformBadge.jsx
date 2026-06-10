import { FaReddit } from 'react-icons/fa';
import { FaXTwitter } from 'react-icons/fa6';
import ytIconUrl from '../assets/youtube-icon.svg';

// Official YouTube icon asset (full-color red rounded rect + white play
// triangle, downloaded unmodified from YouTube's brand resources).
// YouTube branding rules: never recolor, crop, or redraw it; render at
// >= 20px height; no colored wrapper behind it — the icon sits directly
// on the card/row background. This intentionally overrides the internal
// "2-color inline SVG" badge convention for YouTube specifically.
const YT_MIN_HEIGHT = 20;
const YT_ASPECT = 158 / 110; // official asset viewBox ratio

function YouTubeIcon({ size = 16 }) {
  const h = Math.max(size, YT_MIN_HEIGHT);
  const w = Math.round(h * YT_ASPECT);
  return (
    <img
      src={ytIconUrl}
      alt="YouTube"
      height={h}
      width={w}
      style={{ display: 'block', height: `${h}px`, width: `${w}px` }}
    />
  );
}

const PLATFORM_CONFIG = {
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
  const key = platform.toLowerCase();

  if (key === 'youtube') {
    if (!showLabel) return <YouTubeIcon size={size} />;
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: '5px',
        color: 'inherit', fontSize: '10px', fontWeight: 700,
        lineHeight: 1.5, verticalAlign: 'middle', whiteSpace: 'nowrap',
      }}>
        <YouTubeIcon size={size} />
        YouTube
      </span>
    );
  }

  const config = PLATFORM_CONFIG[key];
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
