import { useState, useEffect } from 'react';

function getInitialTheme() {
  const stored = localStorage.getItem('eidolum_theme');
  if (stored) return stored;
  if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light';
}

export default function useTheme() {
  const [theme, setTheme] = useState(getInitialTheme);

  useEffect(() => {
    const html = document.documentElement;
    html.setAttribute('data-theme', theme);
    html.classList.remove('theme-light', 'theme-dark');
    html.classList.add(theme === 'light' ? 'theme-light' : 'theme-dark');
    localStorage.setItem('eidolum_theme', theme);
  }, [theme]);

  const toggleTheme = () => setTheme(t => (t === 'dark' ? 'light' : 'dark'));

  return { theme, toggleTheme, setTheme };
}
