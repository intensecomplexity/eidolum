export default function StatCard({ label, value, sub }) {
  return (
    <div className="card sm:text-center">
      {/* Mobile: horizontal | Desktop: stacked */}
      <div className="flex items-center justify-between sm:block">
        <div>
          <div className="text-text-primary font-medium text-sm sm:order-2">{label}</div>
          {sub && <div className="text-muted text-xs mt-0.5 sm:mt-1">{sub}</div>}
        </div>
        <div className="stat-number text-2xl sm:text-3xl font-bold sm:mb-1">{value}</div>
      </div>
    </div>
  );
}
