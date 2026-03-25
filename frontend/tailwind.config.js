/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#080c08',
        surface: '#0d1208',
        'surface-2': '#141a10',
        border: 'rgba(255,255,255,0.07)',
        accent: '#00b37d',
        'accent-dim': '#009968',
        blue: '#0ea5e9',
        'blue-dim': '#0284c7',
        muted: '#64748b',
        'text-primary': '#e2e8f0',
        'text-secondary': '#94a3b8',
        positive: '#22c55e',
        negative: '#ef4444',
        warning: '#f59e0b',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
        serif: ['Instrument Serif', 'Georgia', 'serif'],
      },
    },
  },
  plugins: [],
}
