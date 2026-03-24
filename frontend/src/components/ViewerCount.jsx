import { useState, useEffect, useRef } from 'react';
import { Eye } from 'lucide-react';

function generateBaseCount(type, id) {
  // Deterministic-ish base from ID
  const hash = String(id).split('').reduce((a, c) => a + c.charCodeAt(0), 0);
  const ranges = {
    'ticker-high': [800, 1400],
    'ticker-mid': [300, 600],
    'ticker-low': [50, 200],
    'forecaster-top': [200, 500],
    'forecaster-low': [20, 80],
    'page': [100, 400],
  };
  const [min, max] = ranges[type] || [50, 200];
  return min + (hash % (max - min));
}

export default function ViewerCount({ type = 'ticker-low', id = 0, className = '' }) {
  const base = useRef(generateBaseCount(type, id));
  const [count, setCount] = useState(base.current);

  useEffect(() => {
    const interval = setInterval(() => {
      const variance = Math.floor(base.current * 0.15);
      const delta = Math.floor(Math.random() * variance * 2) - variance;
      setCount(Math.max(1, base.current + delta));
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <span className={`inline-flex items-center gap-1 text-muted text-xs ${className}`}>
      <Eye className="w-3 h-3" />
      <span className="font-mono">{count.toLocaleString()}</span>
      <span>watching</span>
    </span>
  );
}
