import { Link } from 'react-router-dom';

/**
 * Clickable ticker symbol that navigates to /ticker/{symbol}.
 * Props: ticker (string), className (optional extra classes)
 */
export default function TickerLink({ ticker, className = '' }) {
  return (
    <Link
      to={`/ticker/${ticker}`}
      className={`font-mono font-bold tracking-wider hover:text-accent transition-colors ${className}`}
    >
      {ticker}
    </Link>
  );
}
