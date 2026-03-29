import { useState, useEffect, useRef } from 'react';

/**
 * Live P&L display with flash animation on price updates.
 * Props: direction, priceAtCall, currentPrice, compact
 */
export default function LivePnL({ direction, priceAtCall, currentPrice, compact }) {
  const [flash, setFlash] = useState(null); // 'up' | 'down' | null
  const prevPrice = useRef(currentPrice);

  useEffect(() => {
    if (prevPrice.current != null && currentPrice != null && currentPrice !== prevPrice.current) {
      setFlash(currentPrice > prevPrice.current ? 'up' : 'down');
      const timer = setTimeout(() => setFlash(null), 600);
      prevPrice.current = currentPrice;
      return () => clearTimeout(timer);
    }
    prevPrice.current = currentPrice;
  }, [currentPrice]);

  if (!priceAtCall || !currentPrice) return null;

  const rawPct = ((currentPrice - priceAtCall) / priceAtCall * 100);
  const pnl = direction === 'bearish' ? -rawPct : rawPct;
  const isWinning = pnl > 0;
  const arrow = direction === 'bullish'
    ? (currentPrice >= priceAtCall ? '▲' : '▼')
    : (currentPrice <= priceAtCall ? '▲' : '▼');

  const flashClass = flash === 'up' ? 'price-flash-up' : flash === 'down' ? 'price-flash-down' : '';

  if (compact) {
    return (
      <span
        title={`Current: $${currentPrice}, Entry: $${priceAtCall}`}
        className={`font-mono text-[11px] font-bold px-1.5 py-0.5 rounded ${flashClass} ${
          isWinning ? 'text-positive bg-positive/10' : 'text-negative bg-negative/10'
        }`}
      >
        {pnl >= 0 ? '+' : ''}{pnl.toFixed(1)}%
      </span>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <div className="text-right">
        <div className={`font-mono text-sm font-bold ${flashClass} ${isWinning ? 'text-positive' : 'text-negative'}`}>
          ${currentPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
        <div className="text-[10px] text-muted font-mono">
          Entry: ${priceAtCall.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
      </div>
      <span className={`font-mono text-xs font-bold ${isWinning ? 'text-positive' : 'text-negative'}`}>
        {arrow} {pnl >= 0 ? '+' : ''}{pnl.toFixed(1)}%
      </span>
    </div>
  );
}
