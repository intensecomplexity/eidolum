/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#07090a',
        surface: '#0f1115',
        'surface-2': '#16181d',
        border: 'rgba(212,160,23,0.1)',
        accent: '#D4A017',
        'accent-dim': '#92710A',
        'accent-light': '#FDE68A',
        blue: '#4A9EFF',
        'blue-dim': '#2563eb',
        muted: '#52525b',
        'text-primary': '#e4e4e7',
        'text-secondary': '#a1a1aa',
        positive: '#22c55e',
        negative: '#ef4444',
        warning: '#F59E0B',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
        sans: ['Sora', 'sans-serif'],
        serif: ['Instrument Serif', 'Georgia', 'serif'],
      },
    },
  },
  plugins: [],
}
