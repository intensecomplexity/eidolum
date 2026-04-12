// Ship #13.5 — unifying section header with a 1px gold horizontal rule.
// Ships unconditionally: no feature flag, no hero dependency. Replaces
// the ad-hoc grey-uppercase-tracking-wider h2 pattern used everywhere.
//
// Color rationale: the gold <hr> uses the existing `border-accent`
// Tailwind token (resolves to #D4A843 on main, #b8922e in light mode
// per the [data-theme="light"] override in index.css), so the rule
// inherits the same gold as the H1 and CTA buttons without hard-
// coding a hex.
//
// Contrast rationale: the label is `text-text-primary` which flips
// to near-white in dark mode and near-black in light mode via the
// theme override — always the max-contrast column.
//
// Usage:
//   <SectionHeader subtitle="Recently graded — settled by reality.">
//     Receipts
//   </SectionHeader>
//   <SectionHeader as="h3">Top Forecasters</SectionHeader>

export default function SectionHeader({
  children,
  subtitle,
  as: Tag = 'h2',
  className = '',
}) {
  return (
    <header className={`mb-4 ${className}`}>
      <Tag
        className="text-sm sm:text-base font-bold uppercase text-text-primary"
        style={{ letterSpacing: '0.08em' }}
      >
        {children}
      </Tag>
      <hr className="border-0 border-t border-accent mt-2" aria-hidden="true" />
      {subtitle && (
        <p className="text-sm text-text-secondary mt-3 mb-6">{subtitle}</p>
      )}
    </header>
  );
}
