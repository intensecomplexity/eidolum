/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#07090a',
        surface: '#0e1212',
        'surface-2': '#161a19',
        border: 'rgba(255,255,255,0.08)',
        accent: '#00a878',
        'accent-dim': '#008f66',
        blue: '#0ea5e9',
        'blue-dim': '#0284c7',
        muted: '#6b7280',
        'text-primary': '#e8e8e6',
        'text-secondary': '#94a3b8',
        positive: '#22c55e',
        negative: '#ef4444',
        warning: '#f59e0b',
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
