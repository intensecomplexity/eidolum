import { useState, useEffect } from 'react';

/**
 * Live countdown from an ISO timestamp.
 * Props: expiresAt (ISO string), className (optional)
 */
export default function Countdown({ expiresAt, className = '' }) {
  const [now, setNow] = useState(Date.now());

  const diffMs = expiresAt ? new Date(expiresAt).getTime() - now : 0;
  const isExpired = diffMs <= 0;
  const totalSec = Math.max(0, Math.floor(diffMs / 1000));
  const days = Math.floor(totalSec / 86400);
  const hours = Math.floor((totalSec % 86400) / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  const seconds = totalSec % 60;

  // Determine tick interval based on urgency
  const tickMs = totalSec < 3600 ? 1000 : 60000;

  useEffect(() => {
    if (isExpired) return;
    const id = setInterval(() => setNow(Date.now()), tickMs);
    return () => clearInterval(id);
  }, [isExpired, tickMs]);

  // Format
  let text;
  if (isExpired) {
    text = 'Scoring...';
  } else if (days > 30) {
    const months = Math.floor(days / 30);
    const remDays = days % 30;
    text = `${months}mo ${remDays}d`;
  } else if (days >= 1) {
    text = `${days}d ${hours}h`;
  } else if (hours >= 1) {
    text = `${hours}h ${minutes}m`;
  } else if (minutes >= 1) {
    text = `${minutes}m ${seconds}s`;
  } else {
    text = `${seconds}s`;
  }

  // Color
  let colorClass = 'text-muted';
  if (isExpired) {
    colorClass = 'text-warning animate-pulse';
  } else if (totalSec < 3600) {
    colorClass = 'text-negative font-bold animate-pulse';
  } else if (days < 1) {
    colorClass = 'text-negative font-bold';
  } else if (days <= 3) {
    colorClass = 'text-warning font-bold';
  }

  return (
    <span className={`font-mono ${colorClass} ${className}`}>
      {text}
    </span>
  );
}
