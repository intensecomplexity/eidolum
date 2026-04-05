/**
 * CompanyLogo -- thin wrapper that delegates to TickerLogo.
 * Keeps backward compatibility for existing imports.
 */
import TickerLogo, { clearLogoCache } from './TickerLogo';

export { clearLogoCache };

export default function CompanyLogo({ domain, logoUrl, ticker, size = 24, ...rest }) {
  return <TickerLogo ticker={ticker} logoUrl={logoUrl} size={size} {...rest} />;
}
