/**
 * Format time remaining until a date.
 * - >1 day: "5d left"
 * - 1-24 hours: "5h left"
 * - <1 hour: "45m left"
 * - Expired: "Evaluating"
 *
 * @param {string|Date|number} evalDate - evaluation date (ISO string, Date, or days_remaining number)
 * @returns {{ text: string, urgent: boolean, expired: boolean }}
 */
export default function timeLeft(evalDate) {
  if (evalDate == null) return { text: '?', urgent: false, expired: false };

  // If it's already a number (days_remaining from API), convert
  if (typeof evalDate === 'number') {
    if (evalDate <= 0) return { text: 'Evaluating', urgent: false, expired: true };
    if (evalDate === 1) return { text: '1d left', urgent: true, expired: false };
    return { text: `${evalDate}d left`, urgent: evalDate <= 3, expired: false };
  }

  // Parse date string
  const target = typeof evalDate === 'string' ? new Date(evalDate) : evalDate;
  if (isNaN(target.getTime())) return { text: '?', urgent: false, expired: false };

  const diffMs = target.getTime() - Date.now();

  if (diffMs <= 0) return { text: 'Evaluating', urgent: false, expired: true };

  const hours = Math.floor(diffMs / 3600000);
  const days = Math.floor(hours / 24);

  if (days > 0) return { text: `${days}d left`, urgent: days <= 3, expired: false };
  if (hours > 0) return { text: `${hours}h left`, urgent: true, expired: false };

  const minutes = Math.max(1, Math.floor(diffMs / 60000));
  return { text: `${minutes}m left`, urgent: true, expired: false };
}
