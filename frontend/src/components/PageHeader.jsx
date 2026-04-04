/**
 * PageHeader — consistent title alignment across all pages.
 * Uses max-w-7xl to match leaderboard positioning.
 *
 * Usage:
 *   <PageHeader title="Consensus" subtitle="What Wall Street thinks." icon={TrendingUp} />
 */
export default function PageHeader({ title, subtitle, icon: Icon, children }) {
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6 sm:pt-10">
      <div className="flex items-center gap-2 mb-1">
        {Icon && <Icon className="w-6 h-6 text-accent" />}
        <h1 className="headline-serif" style={{ fontSize: 'clamp(28px, 5vw, 42px)', color: '#D4A843' }}>
          {title}
        </h1>
      </div>
      {subtitle && <p className="text-text-secondary text-sm mb-6">{subtitle}</p>}
      {children}
    </div>
  );
}
