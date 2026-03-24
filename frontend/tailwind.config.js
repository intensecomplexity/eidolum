/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#05080f',
        surface: '#0b1120',
        'surface-2': '#111827',
        border: '#1e2d45',
        accent: '#00e5a0',
        'accent-dim': '#00b37e',
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
      },
    },
  },
  plugins: [],
}
