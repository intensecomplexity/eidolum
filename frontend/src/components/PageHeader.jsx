/**
 * PageHeader — consistent title alignment across all pages.
 * Uses max-w-7xl to match leaderboard positioning.
 * Gold serif titles stand alone — no icons.
 *
 * Usage:
 *   <PageHeader title="Consensus" subtitle="What Wall Street thinks." />
 */
export default function PageHeader({ title, subtitle, children }) {
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6 sm:pt-10">
      <h1 className="headline-serif mb-1" style={{ fontSize: 'clamp(28px, 5vw, 42px)', color: '#D4A843' }}>
        {title}
      </h1>
      {subtitle && <p className="text-text-secondary text-sm mb-6">{subtitle}</p>}
      {children}
    </div>
  );
}
