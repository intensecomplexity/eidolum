import { useState, useEffect } from 'react';
import { getTickerPrice } from '../api';

/**
 * Live stock price display.
 * Props:
 *  - ticker: string (required)
 *  - size: 'large' | 'medium' | 'small' (default 'medium')
 *  - showChange: boolean (default true)
 *  - autoRefresh: boolean (default false) — refresh every 30s
 *  - inline: boolean (default false) — render as inline span
 */
export default function StockPrice({ ticker, size = 'medium', showChange = true, autoRefresh = false, inline = false }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ticker) return;
    let mounted = true;

    function fetch() {
      getTickerPrice(ticker)
        .then(d => { if (mounted) setData(d); })
        .catch(() => {})
        .finally(() => { if (mounted) setLoading(false); });
    }

    fetch();

    let interval;
    if (autoRefresh) {
      interval = setInterval(fetch, 30000);
    }

    return () => { mounted = false; if (interval) clearInterval(interval); };
  }, [ticker, autoRefresh]);

  if (loading || !data?.current_price) {
    const placeholder = size === 'large' ? 'text-2xl' : size === 'small' ? 'text-[11px]' : 'text-sm';
    return <span className={`${placeholder} text-muted font-mono`}>--</span>;
  }

  const price = data.current_price;
  const changePct = data.price_change_percent || 0;
  const changeAbs = data.price_change_24h || 0;
  const isUp = changePct >= 0;

  const sizeClasses = {
    large: { price: 'text-2xl sm:text-3xl font-bold', change: 'text-base font-semibold ml-2' },
    medium: { price: 'text-sm font-bold', change: 'text-xs font-semibold ml-1' },
    small: { price: 'text-[11px] font-bold', change: 'text-[10px] font-semibold ml-0.5' },
  };
  const cls = sizeClasses[size] || sizeClasses.medium;

  const Tag = inline ? 'span' : 'div';

  return (
    <Tag className={inline ? 'inline-flex items-baseline gap-0.5' : 'flex items-baseline gap-0.5'}>
      <span className={`font-mono text-accent ${cls.price}`}>${price.toFixed(2)}</span>
      {showChange && changePct !== 0 && (
        <span className={`font-mono ${cls.change} ${isUp ? 'text-positive' : 'text-negative'}`}>
          {isUp ? '+' : ''}{changePct.toFixed(2)}%
        </span>
      )}
    </Tag>
  );
}
