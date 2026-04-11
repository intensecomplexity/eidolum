import { useState, useEffect } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { Link } from 'react-router-dom';
import { ArrowLeft, ChevronDown, ArrowUp, ArrowDown, Minus } from 'lucide-react';
import PlatformBadge from '../components/PlatformBadge';
import Footer from '../components/Footer';
import { getReportCards } from '../api';
import { pluralize } from '../utils/pluralize';

const GRADE_COLORS = {
  'A+': 'text-positive', A: 'text-positive', 'A-': 'text-positive',
  'B+': 'text-blue', B: 'text-blue', 'B-': 'text-blue',
  'C+': 'text-warning', C: 'text-warning',
  D: 'text-negative', F: 'text-negative',
};

const GRADE_BG = {
  'A+': 'bg-positive/10', A: 'bg-positive/10', 'A-': 'bg-positive/10',
  'B+': 'bg-blue/10', B: 'bg-blue/10', 'B-': 'bg-blue/10',
  'C+': 'bg-warning/10', C: 'bg-warning/10',
  D: 'bg-negative/10', F: 'bg-negative/10',
};

export default function ReportCards() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    setLoading(true);
    getReportCards()
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <Link
          to="/leaderboard"
          className="inline-flex items-center gap-1 text-muted text-sm active:text-text-primary transition-colors mb-4 sm:mb-6 min-h-[44px]"
        >
          <ArrowLeft className="w-4 h-4" /> Back to leaderboard
        </Link>

        <div className="mb-5 sm:mb-8">
          <h1 className="font-bold mb-1 sm:mb-2" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>
            Monthly Report Cards
          </h1>
          <p className="text-text-secondary text-sm sm:text-base">
            {data ? data.month : 'Loading...'} &mdash; How did each forecaster perform?
          </p>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16"><LoadingSpinner size="lg" /></div>
        ) : !data || data.report_cards.length === 0 ? (
          <div className="card text-center py-12">
            <p className="text-text-secondary">No report cards available for this month yet.</p>
          </div>
        ) : (
          <>
            {/* Mobile cards */}
            <div className="sm:hidden space-y-3">
              {data.report_cards.map(rc => (
                <div
                  key={rc.forecaster_id}
                  className="bg-surface border border-border rounded-xl p-4 active:bg-surface-2"
                  onClick={() => setExpanded(expanded === rc.forecaster_id ? null : rc.forecaster_id)}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-muted text-xs font-mono">#{rc.rank}</span>
                        <Link to={`/forecaster/${rc.forecaster_id}`} className="font-medium text-text-primary" onClick={e => e.stopPropagation()}>
                          {rc.name}
                        </Link>
                        <PlatformBadge platform={rc.platform} />
                      </div>
                    </div>
                    <div className={`text-2xl font-serif font-bold ${GRADE_COLORS[rc.grade] || 'text-muted'}`}>
                      {rc.grade}
                    </div>
                  </div>

                  <div className="flex items-center gap-3 text-xs">
                    <span className={`font-mono ${rc.accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
                      {rc.accuracy.toFixed(1)}%
                    </span>
                    {rc.accuracy_change !== null && (
                      <span className={`flex items-center gap-0.5 ${rc.accuracy_change > 0 ? 'text-positive' : rc.accuracy_change < 0 ? 'text-negative' : 'text-muted'}`}>
                        {rc.accuracy_change > 0 ? <ArrowUp className="w-3 h-3" /> : rc.accuracy_change < 0 ? <ArrowDown className="w-3 h-3" /> : <Minus className="w-3 h-3" />}
                        {rc.accuracy_change > 0 ? '+' : ''}{rc.accuracy_change.toFixed(1)}%
                      </span>
                    )}
                    <span className="text-muted">{pluralize(rc.predictions_count, 'call')}</span>
                  </div>

                  {expanded === rc.forecaster_id && (
                    <div className="mt-3 pt-3 border-t border-border space-y-2 text-xs">
                      {rc.best_call && (
                        <div className="flex justify-between">
                          <span className="text-muted">Best call</span>
                          <span className="text-positive font-mono">{rc.best_call.ticker} {rc.best_call.return >= 0 ? '+' : ''}{rc.best_call.return.toFixed(1)}%</span>
                        </div>
                      )}
                      {rc.worst_call && (
                        <div className="flex justify-between">
                          <span className="text-muted">Worst call</span>
                          <span className="text-negative font-mono">{rc.worst_call.ticker} {rc.worst_call.return >= 0 ? '+' : ''}{rc.worst_call.return.toFixed(1)}%</span>
                        </div>
                      )}
                      {rc.alpha !== 0 && (
                        <div className="flex justify-between">
                          <span className="text-muted">Alpha</span>
                          <span className={`font-mono ${rc.alpha >= 0 ? 'text-positive' : 'text-negative'}`}>{rc.alpha >= 0 ? '+' : ''}{rc.alpha.toFixed(2)}%</span>
                        </div>
                      )}
                      {rc.better_sectors.length > 0 && (
                        <div><span className="text-muted">Better in: </span><span className="text-positive">{rc.better_sectors.join(', ')}</span></div>
                      )}
                      {rc.worse_sectors.length > 0 && (
                        <div><span className="text-muted">Worse in: </span><span className="text-negative">{rc.worse_sectors.join(', ')}</span></div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Desktop table */}
            <div className="hidden sm:block card overflow-hidden p-0">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                      <th className="px-6 py-3 w-16">Rank</th>
                      <th className="px-6 py-3">Forecaster</th>
                      <th className="px-6 py-3 text-center">Grade</th>
                      <th className="px-6 py-3 text-right">This Month</th>
                      <th className="px-6 py-3 text-right">vs Last Month</th>
                      <th className="px-6 py-3 text-right">Alpha</th>
                      <th className="px-6 py-3 text-right hidden lg:table-cell">Best Call</th>
                      <th className="px-6 py-3 text-right hidden lg:table-cell">Worst Call</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.report_cards.map(rc => (
                      <tr key={rc.forecaster_id} className="border-b border-border/50 hover:bg-surface-2/50 transition-colors">
                        <td className="px-6 py-4 font-mono text-muted">#{rc.rank}</td>
                        <td className="px-6 py-4">
                          <Link to={`/forecaster/${rc.forecaster_id}`} className="hover:text-accent transition-colors">
                            <div className="flex items-center gap-2">
                              <span className="font-medium">{rc.name}</span>
                              <PlatformBadge platform={rc.platform} />
                            </div>
                            <div className="text-muted text-xs">{rc.predictions_count} predictions</div>
                          </Link>
                        </td>
                        <td className="px-6 py-4 text-center">
                          <span className={`inline-flex items-center justify-center w-10 h-10 rounded-lg text-lg font-serif font-bold ${GRADE_COLORS[rc.grade] || 'text-muted'} ${GRADE_BG[rc.grade] || 'bg-surface-2'}`}>
                            {rc.grade}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-right">
                          <span className={`font-mono font-semibold ${rc.accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>
                            {rc.accuracy.toFixed(1)}%
                          </span>
                        </td>
                        <td className="px-6 py-4 text-right">
                          {rc.accuracy_change !== null ? (
                            <span className={`inline-flex items-center gap-0.5 font-mono text-sm ${
                              rc.accuracy_change > 0 ? 'text-positive' : rc.accuracy_change < 0 ? 'text-negative' : 'text-muted'
                            }`}>
                              {rc.accuracy_change > 0 ? <ArrowUp className="w-3 h-3" /> : rc.accuracy_change < 0 ? <ArrowDown className="w-3 h-3" /> : <Minus className="w-3 h-3" />}
                              {rc.accuracy_change > 0 ? '+' : ''}{rc.accuracy_change.toFixed(1)}%
                            </span>
                          ) : <span className="text-muted text-xs">&mdash;</span>}
                        </td>
                        <td className="px-6 py-4 text-right">
                          <span className={`font-mono text-sm ${rc.alpha >= 0 ? 'text-positive' : 'text-negative'}`}>
                            {rc.alpha >= 0 ? '+' : ''}{rc.alpha.toFixed(2)}%
                          </span>
                        </td>
                        <td className="px-6 py-4 text-right hidden lg:table-cell">
                          {rc.best_call ? (
                            <span className="text-positive text-xs font-mono">{rc.best_call.ticker} +{rc.best_call.return.toFixed(1)}%</span>
                          ) : <span className="text-muted text-xs">&mdash;</span>}
                        </td>
                        <td className="px-6 py-4 text-right hidden lg:table-cell">
                          {rc.worst_call ? (
                            <span className="text-negative text-xs font-mono">{rc.worst_call.ticker} {rc.worst_call.return.toFixed(1)}%</span>
                          ) : <span className="text-muted text-xs">&mdash;</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>
      <Footer />
    </div>
  );
}
