/**
 * Calculate and format time remaining until a prediction expires.
 * Uses 4:00 PM ET (20:00 UTC during EDT, 21:00 UTC during EST) as expiry moment.
 *
 * @param {string|Date} expiresAt - The expiration date
 * @param {number|null} daysRemaining - Pre-calculated days remaining (fallback)
 * @returns {{ label: string, isExpired: boolean, isEvaluating: boolean, isUrgent: boolean, isCritical: boolean }}
 */
export function formatTimeRemaining(expiresAt, daysRemaining = null) {
  if (!expiresAt && daysRemaining == null) {
    return { label: '', isExpired: false, isEvaluating: false, isUrgent: false, isCritical: false };
  }

  const now = new Date();

  // If we have an actual expiry date, calculate precisely
  if (expiresAt) {
    const expiry = new Date(expiresAt);

    // Set expiry to 4:00 PM ET (approx 20:00 UTC during EDT)
    // This is approximate — exact offset depends on DST
    const expiryWithMarketClose = new Date(expiry);
    expiryWithMarketClose.setUTCHours(20, 0, 0, 0);

    const diffMs = expiryWithMarketClose.getTime() - now.getTime();

    // Already expired
    if (diffMs <= 0) {
      return { label: 'Evaluating', isExpired: true, isEvaluating: true, isUrgent: true, isCritical: true };
    }

    const diffHours = diffMs / 3600000;
    const diffDays = Math.floor(diffHours / 24);

    // More than 1 day
    if (diffDays >= 1) {
      return {
        label: `${diffDays}d left`,
        isExpired: false,
        isEvaluating: false,
        isUrgent: diffDays <= 7,
        isCritical: diffDays <= 1,
      };
    }

    // Less than 24 hours — show hours
    const hours = Math.floor(diffHours);
    const minutes = Math.floor((diffMs % 3600000) / 60000);

    if (hours >= 1) {
      return {
        label: minutes > 0 ? `${hours}h ${minutes}m left` : `${hours}h left`,
        isExpired: false,
        isEvaluating: false,
        isUrgent: true,
        isCritical: true,
      };
    }

    // Less than 1 hour — show minutes
    return {
      label: `${Math.max(1, minutes)}m left`,
      isExpired: false,
      isEvaluating: false,
      isUrgent: true,
      isCritical: true,
    };
  }

  // Fallback: use days_remaining integer
  if (daysRemaining != null) {
    if (daysRemaining <= 0) {
      return { label: 'Evaluating', isExpired: true, isEvaluating: true, isUrgent: true, isCritical: true };
    }
    return {
      label: `${daysRemaining}d left`,
      isExpired: false,
      isEvaluating: false,
      isUrgent: daysRemaining <= 7,
      isCritical: daysRemaining <= 1,
    };
  }

  return { label: '', isExpired: false, isEvaluating: false, isUrgent: false, isCritical: false };
}
