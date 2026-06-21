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

// Two-color inline SVG marks for the alt-source axes (insider Form-4 trades,
// congressional PTR trades). Like the YouTube asset they render directly on
// the card/row background (no colored wrapper pill) so the two tones read as
// the badge. Distinct hues keep them separable from Wall St (#3b82f6 blue):
// Congress = indigo capitol dome, Insider = violet office tower.
function CongressIcon({ size = 16 }) {
  const h = Math.max(size, 18);
  return (
    <svg width={h} height={h} viewBox="0 0 24 24" fill="none"
         xmlns="http://www.w3.org/2000/svg" style={{ display: 'block' }} aria-label="Congress">
      <rect x="11.4" y="1" width="1.2" height="1.9" rx="0.6" fill="#a5b4fc" />
      <path d="M12 2.5c-2.6 0-4 2.6-4 5h8c0-2.4-1.4-5-4-5z" fill="#6366f1" />
      <rect x="6.5" y="7.5" width="11" height="1.8" rx="0.4" fill="#6366f1" />
      <rect x="7" y="9.3" width="10" height="8.2" fill="#a5b4fc" />
      <rect x="8" y="9.3" width="1.4" height="8.2" fill="#6366f1" />
      <rect x="11.3" y="9.3" width="1.4" height="8.2" fill="#6366f1" />
      <rect x="14.6" y="9.3" width="1.4" height="8.2" fill="#6366f1" />
      <rect x="5" y="17.5" width="14" height="1.7" rx="0.4" fill="#6366f1" />
      <rect x="4" y="19.2" width="16" height="1.8" rx="0.5" fill="#a5b4fc" />
    </svg>
  );
}

function InsiderIcon({ size = 16 }) {
  const h = Math.max(size, 18);
  return (
    <svg width={h} height={h} viewBox="0 0 24 24" fill="none"
         xmlns="http://www.w3.org/2000/svg" style={{ display: 'block' }} aria-label="Insider">
      <rect x="5" y="3" width="14" height="18" rx="1.2" fill="#7c3aed" />
      <rect x="7.6" y="5.6" width="2.6" height="2.6" rx="0.4" fill="#ddd6fe" />
      <rect x="13.8" y="5.6" width="2.6" height="2.6" rx="0.4" fill="#ddd6fe" />
      <rect x="7.6" y="9.8" width="2.6" height="2.6" rx="0.4" fill="#ddd6fe" />
      <rect x="13.8" y="9.8" width="2.6" height="2.6" rx="0.4" fill="#ddd6fe" />
      <rect x="7.6" y="14" width="2.6" height="2.6" rx="0.4" fill="#ddd6fe" />
      <rect x="13.8" y="14" width="2.6" height="2.6" rx="0.4" fill="#ddd6fe" />
      <rect x="10.5" y="17.4" width="3" height="3.6" rx="0.3" fill="#ddd6fe" />
    </svg>
  );
}

const PLATFORM_CONFIG = {
  twitter:       { Icon: FaXTwitter, iconColor: '#ffffff', label: 'X', bg: '#000000', text: '#ffffff' },
  x:             { Icon: FaXTwitter, iconColor: '#ffffff', label: 'X', bg: '#000000', text: '#ffffff' },
  reddit:        { Icon: FaReddit, iconColor: '#FF4500', label: 'Reddit', bg: '#FF4500', text: '#ffffff' },
  congress:      { Icon: null, label: 'Congress', bg: '#6366f1', text: '#ffffff' },
  insider:       { Icon: null, label: 'Insider', bg: '#7c3aed', text: '#ffffff' },
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

  // Insider / Congress 2-color marks render directly on the background (no
  // colored wrapper pill), mirroring the YouTube treatment above.
  if (key === 'insider' || key === 'congress') {
    const Mark = key === 'insider' ? InsiderIcon : CongressIcon;
    const markLabel = key === 'insider' ? 'Insider' : 'Congress';
    if (!showLabel) return <Mark size={size} />;
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: '5px',
        color: 'inherit', fontSize: '10px', fontWeight: 700,
        lineHeight: 1.5, verticalAlign: 'middle', whiteSpace: 'nowrap',
      }}>
        <Mark size={size} />
        {markLabel}
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
