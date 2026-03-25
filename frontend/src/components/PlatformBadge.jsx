import { FaYoutube, FaReddit } from 'react-icons/fa'
import { FaXTwitter } from 'react-icons/fa6'

const PLATFORM_CONFIG = {
  youtube:       { Icon: FaYoutube,  color: '#FF0000', bg: null },
  twitter:       { Icon: FaXTwitter, color: '#ffffff', bg: '#000000' },
  x:             { Icon: FaXTwitter, color: '#ffffff', bg: '#000000' },
  reddit:        { Icon: FaReddit,   color: '#FF4500', bg: null },
  congress:      { Icon: null, label: 'GOV',  color: '#3b82f6', bg: null },
  institutional: { Icon: null, label: 'INST', color: '#a78bfa', bg: null },
}

export default function PlatformBadge({ platform, size = 16 }) {
  if (!platform) return null
  const config = PLATFORM_CONFIG[platform.toLowerCase()]
  if (!config) return null
  const { Icon, color, bg, label } = config

  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: bg || 'transparent',
      borderRadius: bg ? '4px' : '0',
      padding: bg ? '2px 5px' : '0',
      marginLeft: '6px',
      verticalAlign: 'middle',
      lineHeight: 1,
    }}>
      {Icon
        ? <Icon size={size} color={color} style={{ display: 'block' }} />
        : <span style={{
            fontSize: Math.max(size * 0.7, 9) + 'px',
            color,
            fontWeight: 700,
            border: `1px solid ${color}`,
            borderRadius: '3px',
            padding: '0 3px',
            lineHeight: 1.4,
          }}>
            {label}
          </span>
      }
    </span>
  )
}
