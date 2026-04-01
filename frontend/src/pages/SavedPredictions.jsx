import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Bookmark, ArrowRight, Clock, Pencil, ExternalLink, X, ChevronDown, Trophy, Search, CircleDot, BarChart3, Bell, CheckCircle, XCircle, AlertTriangle } from 'lucide-react';
import Footer from '../components/Footer';
import PredictionBadge from '../components/PredictionBadge';
import PlatformBadge from '../components/PlatformBadge';
import BookmarkButton from '../components/BookmarkButton';
import { useSavedPredictions } from '../context/SavedPredictionsContext';
import { getSavedPredictions, updateSavedNote } from '../api';
import { formatTimeRemaining } from '../utils/timeRemaining';

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'pending', label: 'Pending' },
  { key: 'correct', label: 'Resolved \u2713' },
  { key: 'incorrect', label: 'Resolved \u2717' },
];

const SORTS = [
  { key: 'recent', label: 'Recently saved' },
  { key: 'resolves', label: 'Resolves soonest' },
  { key: 'gain', label: 'Biggest gain' },
  { key: 'loss', label: 'Biggest loss' },
];

export default function SavedPredictions() {
  const { savedIds, count, userId } = useSavedPredictions();
  const [predictions, setPredictions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState('recent');
  const [alerts, setAlerts] = useState([]);

  const fetchSaved = useCallback(() => {
    setLoading(true);
    getSavedPredictions(userId)
      .then((data) => {
        setPredictions(data);
        // Check for smart notifications
        checkAlerts(data);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [userId]);

  useEffect(() => {
    fetchSaved();
  }, [fetchSaved, savedIds.size]);

  function checkAlerts(data) {
    const lastVisit = localStorage.getItem('qa_last_visited_saved');
    const dismissed = JSON.parse(localStorage.getItem('qa_dismissed_alerts') || '[]');
    const now = new Date();
    localStorage.setItem('qa_last_visited_saved', now.toISOString());

    const newAlerts = [];

    // Resolving soon
    const resolvingSoon = data.filter(p => p.outcome === 'pending' && p.days_remaining !== null && p.days_remaining <= 7);
    if (resolvingSoon.length > 0 && !dismissed.includes('resolving_soon')) {
      newAlerts.push({
        id: 'resolving_soon',
        type: 'warning',
        icon: 'warning',
        message: `${resolvingSoon.length} of your saved prediction${resolvingSoon.length > 1 ? 's' : ''} resolve${resolvingSoon.length === 1 ? 's' : ''} in the next 7 days.`,
      });
    }

    // New resolutions since last visit
    if (lastVisit) {
      const lastDate = new Date(lastVisit);
      const newlyResolved = data.filter(
        p => p.outcome !== 'pending' && p.evaluation_date && new Date(p.evaluation_date) > lastDate
      );
      newlyResolved.forEach(p => {
        const alertId = `resolved_${p.id}`;
        if (!dismissed.includes(alertId)) {
          const isCorrect = p.outcome === 'correct';
          newAlerts.push({
            id: alertId,
            type: isCorrect ? 'positive' : 'negative',
            icon: isCorrect ? 'correct' : 'incorrect',
            message: `${p.forecaster.name}'s ${p.ticker} call resolved ${p.outcome.toUpperCase()}${p.actual_return !== null ? ` \u2014 ${p.actual_return >= 0 ? '+' : ''}${p.actual_return.toFixed(1)}%` : ''}!`,
          });
        }
      });
    }

    setAlerts(newAlerts);
  }

  function dismissAlert(alertId) {
    const dismissed = JSON.parse(localStorage.getItem('qa_dismissed_alerts') || '[]');
    dismissed.push(alertId);
    localStorage.setItem('qa_dismissed_alerts', JSON.stringify(dismissed));
    setAlerts(prev => prev.filter(a => a.id !== alertId));
  }

  // Filter + sort
  let filtered = predictions;
  if (filter === 'pending') filtered = predictions.filter(p => p.outcome === 'pending');
  else if (filter === 'correct') filtered = predictions.filter(p => p.outcome === 'correct');
  else if (filter === 'incorrect') filtered = predictions.filter(p => p.outcome === 'incorrect');

  if (sort === 'resolves') {
    filtered = [...filtered].sort((a, b) => (a.days_remaining ?? 9999) - (b.days_remaining ?? 9999));
  } else if (sort === 'gain') {
    filtered = [...filtered].sort((a, b) => {
      const aRet = a.actual_return ?? a.current_return ?? -9999;
      const bRet = b.actual_return ?? b.current_return ?? -9999;
      return bRet - aRet;
    });
  } else if (sort === 'loss') {
    filtered = [...filtered].sort((a, b) => {
      const aRet = a.actual_return ?? a.current_return ?? 9999;
      const bRet = b.actual_return ?? b.current_return ?? 9999;
      return aRet - bRet;
    });
  }
  // 'recent' is the default order from API

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Header */}
        <div className="mb-5 sm:mb-8">
          <div className="flex items-center gap-2 mb-1 sm:mb-2">
            <Bookmark className="w-6 h-6 text-accent fill-accent" />
            <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>
              My Saved Predictions
            </h1>
          </div>
          <p className="text-text-secondary text-sm sm:text-base">
            Track the calls you care about &mdash; all in one place.
          </p>
          {count > 0 && (
            <p className="text-muted text-sm mt-1 font-mono">{count} saved prediction{count !== 1 ? 's' : ''}</p>
          )}
        </div>

        {/* Smart alerts */}
        {alerts.length > 0 && (
          <div className="space-y-2 mb-6">
            {alerts.map(alert => (
              <div
                key={alert.id}
                className={`flex items-start gap-3 p-3 rounded-lg border ${
                  alert.type === 'positive' ? 'bg-positive/5 border-positive/20' :
                  alert.type === 'negative' ? 'bg-negative/5 border-negative/20' :
                  'bg-warning/5 border-warning/20'
                }`}
              >
                <span className="shrink-0">{alert.icon === 'correct' ? <CheckCircle className="w-4 h-4 text-positive" /> : alert.icon === 'warning' ? <AlertTriangle className="w-4 h-4 text-warning" /> : <XCircle className="w-4 h-4 text-negative" />}</span>
                <p className="text-sm text-text-primary flex-1">{alert.message}</p>
                <button
                  onClick={() => dismissAlert(alert.id)}
                  className="text-muted hover:text-text-secondary shrink-0 min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 flex items-center justify-center"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Empty state */}
        {count === 0 ? (
          <EmptyState />
        ) : (
          <>
            {/* Filter + Sort bar */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 mb-6">
              <div className="flex gap-1.5 overflow-x-auto pills-scroll pb-1 w-full sm:w-auto">
                {FILTERS.map(f => (
                  <button
                    key={f.key}
                    onClick={() => setFilter(f.key)}
                    className={`px-3 py-2 rounded-lg text-xs font-medium whitespace-nowrap min-h-[36px] transition-colors shrink-0 ${
                      filter === f.key
                        ? 'bg-accent/10 text-accent border border-accent/20'
                        : 'bg-surface border border-border text-text-secondary active:text-text-primary'
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <div className="relative ml-auto">
                <select
                  value={sort}
                  onChange={(e) => setSort(e.target.value)}
                  className="appearance-none bg-surface border border-border rounded-lg px-3 py-2 pr-8 text-xs text-text-primary focus:outline-none focus:border-accent/50 cursor-pointer min-h-[36px]"
                >
                  {SORTS.map(s => (
                    <option key={s.key} value={s.key}>{s.label}</option>
                  ))}
                </select>
                <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted pointer-events-none" />
              </div>
            </div>

            {/* Prediction cards */}
            <div className="space-y-4">
              {filtered.map(p => (
                <SavedCard key={p.id} prediction={p} userId={userId} onUpdate={fetchSaved} />
              ))}
              {filtered.length === 0 && (
                <div className="text-center py-12 text-muted text-sm">
                  No predictions match this filter.
                </div>
              )}
            </div>
          </>
        )}
      </div>

      <Footer />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="text-center py-16 sm:py-24">
      <Bookmark className="w-12 h-12 text-muted/30 mx-auto mb-4" />
      <h2 className="text-lg font-semibold text-text-primary mb-2">No saved predictions yet</h2>
      <p className="text-text-secondary text-sm mb-8 max-w-md mx-auto">
        Browse predictions and click the bookmark icon to save them here and track them live.
      </p>

      {/* Onboarding cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-2xl mx-auto mb-8">
        {[
          { Icon: Bookmark, title: 'Save predictions you want to track', desc: 'Tap the bookmark icon on any prediction to save it here and watch it live.' },
          { Icon: BarChart3, title: 'Watch them move in real time', desc: 'See if the prediction is tracking toward its target \u2014 before it resolves.' },
          { Icon: Bell, title: 'Get notified when they resolve', desc: 'Enter your email to get an alert when any saved prediction gets its final verdict.' },
        ].map((step, i) => (
          <div key={i} className="card text-left">
            <step.Icon className="w-6 h-6 text-accent mb-2" />
            <h3 className="text-sm font-semibold mb-1">{step.title}</h3>
            <p className="text-text-secondary text-xs leading-relaxed">{step.desc}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-center gap-3">
        <Link to="/leaderboard" className="btn-primary text-sm">
          <Trophy className="w-4 h-4" /> Browse Leaderboard
        </Link>
        <Link to="/" className="btn-secondary text-sm">
          <Search className="w-4 h-4" /> Explore Assets
        </Link>
      </div>
    </div>
  );
}

function SavedCard({ prediction: p, userId, onUpdate }) {
  const [editingNote, setEditingNote] = useState(false);
  const [noteText, setNoteText] = useState(p.personal_note || '');
  const [showTracking, setShowTracking] = useState(false);
  const [saving, setSaving] = useState(false);

  const isPending = p.outcome === 'pending';
  const isCorrect = p.outcome === 'correct';
  const isIncorrect = p.outcome === 'incorrect';

  // Determine if current direction aligns with the call
  const currentReturn = p.actual_return ?? p.current_return;
  const isTracking = currentReturn !== null && (
    (p.direction === 'bullish' && currentReturn > 0) ||
    (p.direction === 'bearish' && currentReturn < 0)
  );
  const displayReturn = currentReturn !== null ? Math.abs(currentReturn) : null;
  const returnSign = currentReturn !== null ? (currentReturn >= 0 ? '+' : '') : '';

  // Progress toward target
  let targetProgress = null;
  if (isPending && p.entry_price && p.target_price && currentReturn !== null) {
    const targetReturn = ((p.target_price - p.entry_price) / p.entry_price) * 100;
    if (targetReturn !== 0) {
      targetProgress = Math.min(100, Math.max(0, (currentReturn / targetReturn) * 100));
    }
  }

  // Resolution urgency — use precise time remaining
  const _tr = formatTimeRemaining(p.expires_at || p.evaluation_date, p.days_remaining);
  const isUrgent = isPending && _tr.isUrgent;
  const isCritical = isPending && _tr.isCritical;

  const borderColor = isPending ? 'border-l-warning' : isCorrect ? 'border-l-positive' : 'border-l-negative';
  const bgTint = isCorrect ? 'bg-positive/[0.02]' : isIncorrect ? 'bg-negative/[0.02]' : '';

  async function handleSaveNote() {
    setSaving(true);
    try {
      await updateSavedNote(userId, p.id, noteText);
      setEditingNote(false);
      onUpdate();
    } catch {}
    setSaving(false);
  }

  const savedDate = p.saved_at ? new Date(p.saved_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '';

  return (
    <div className={`card p-0 overflow-hidden border-l-[3px] ${borderColor} ${bgTint}`}>
      {/* Resolution banner */}
      {isCorrect && (
        <div className="bg-positive/10 px-4 py-2 text-positive text-sm font-semibold flex items-center gap-1.5">
          <span>&#10003;</span> CORRECT{p.actual_return !== null ? ` \u2014 resolved ${p.actual_return >= 0 ? '+' : ''}${p.actual_return.toFixed(1)}%` : ''}
        </div>
      )}
      {isIncorrect && (
        <div className="bg-negative/10 px-4 py-2 text-negative text-sm font-semibold flex items-center gap-1.5">
          <span>&#10007;</span> WRONG{p.actual_return !== null ? ` \u2014 resolved ${p.actual_return >= 0 ? '+' : ''}${p.actual_return.toFixed(1)}%` : ''}
        </div>
      )}

      <div className="p-4 sm:p-5">
        {/* Top row: forecaster + unsave */}
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2 flex-wrap">
            <Link to={`/forecaster/${p.forecaster.id}`} className="font-medium text-sm hover:text-accent transition-colors">
              {p.forecaster.name}
            </Link>
            <PlatformBadge platform={p.forecaster.platform} />
          </div>
          <BookmarkButton predictionId={p.id} />
        </div>

        {/* Ticker + direction + date */}
        <div className="flex items-center gap-2 flex-wrap mb-3">
          <Link to={`/asset/${p.ticker}`} className="font-mono text-accent text-lg font-bold hover:underline">
            {p.ticker}
          </Link>
          <PredictionBadge direction={p.direction} windowDays={p.window_days || p.evaluation_window_days} />
          {savedDate && <span className="text-muted text-xs">Saved {savedDate}</span>}
        </div>

        {/* Quote */}
        {p.exact_quote && (
          <p className="text-text-secondary text-sm italic leading-relaxed mb-3 border-l-2 border-border pl-3">
            &ldquo;{p.exact_quote.length > 200 ? p.exact_quote.slice(0, 200) + '...' : p.exact_quote}&rdquo;
          </p>
        )}

        {/* Live tracking section */}
        {isPending && (
          <>
            {/* Mobile: collapsible */}
            <button
              className="sm:hidden flex items-center gap-1.5 text-xs text-muted mb-2 min-h-[44px]"
              onClick={() => setShowTracking(!showTracking)}
            >
              <Clock className="w-3 h-3" />
              {showTracking ? 'Hide tracking' : 'Show tracking'}
              <ChevronDown className={`w-3 h-3 transition-transform ${showTracking ? 'rotate-180' : ''}`} />
            </button>

            <div className={`${showTracking ? 'block' : 'hidden'} sm:block`}>
              <TrackingSection
                p={p}
                currentReturn={currentReturn}
                returnSign={returnSign}
                isTracking={isTracking}
                targetProgress={targetProgress}
                isUrgent={isUrgent}
                isCritical={isCritical}
              />
            </div>
          </>
        )}

        {/* Personal note */}
        {p.personal_note && !editingNote && (
          <div className="flex items-start gap-2 mt-3 p-2 bg-surface-2 rounded-lg">
            <Pencil className="w-3 h-3 text-muted shrink-0 mt-0.5" />
            <p className="text-text-secondary text-xs leading-relaxed flex-1">{p.personal_note}</p>
          </div>
        )}

        {/* Note editor */}
        {editingNote && (
          <div className="mt-3 p-3 bg-surface-2 border border-border rounded-lg">
            <textarea
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder="Add a personal note..."
              className="w-full bg-transparent text-text-primary text-sm placeholder:text-muted focus:outline-none resize-none min-h-[60px]"
              autoFocus
            />
            <div className="flex justify-end gap-2 mt-2">
              <button
                onClick={() => { setEditingNote(false); setNoteText(p.personal_note || ''); }}
                className="px-3 py-1.5 text-xs text-muted hover:text-text-secondary min-h-[36px]"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveNote}
                disabled={saving}
                className="px-3 py-1.5 text-xs bg-accent/10 text-accent border border-accent/20 rounded-lg font-medium min-h-[36px] hover:bg-accent/20 transition-colors disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save note'}
              </button>
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-3 mt-3 flex-wrap">
          {!editingNote && (
            <button
              onClick={() => setEditingNote(true)}
              className="flex items-center gap-1 text-xs text-muted hover:text-text-secondary transition-colors min-h-[44px] sm:min-h-0"
            >
              <Pencil className="w-3 h-3" /> {p.personal_note ? 'Edit note' : 'Add note'}
            </button>
          )}
          <Link
            to={`/forecaster/${p.forecaster.id}`}
            className="flex items-center gap-1 text-xs text-muted hover:text-text-secondary transition-colors min-h-[44px] sm:min-h-0"
          >
            <span>&#128100;</span> View forecaster
          </Link>
          {p.source_url && (
            <a
              href={p.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-muted hover:text-text-secondary transition-colors min-h-[44px] sm:min-h-0"
            >
              <ExternalLink className="w-3 h-3" /> Source
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

function TrackingSection({ p, currentReturn, returnSign, isTracking, targetProgress, isUrgent, isCritical }) {
  return (
    <div className="bg-surface-2 border border-border rounded-lg p-3 mb-3">
      <div className="text-[10px] text-muted uppercase tracking-wider font-semibold mb-2">
        Live Tracking
      </div>

      <div className="space-y-1.5 text-sm">
        {p.entry_price && (
          <div className="flex justify-between">
            <span className="text-muted text-xs">Price when called</span>
            <span className="font-mono text-xs text-text-secondary">${p.entry_price.toFixed(2)}</span>
          </div>
        )}

        {currentReturn !== null && (
          <div className="flex justify-between items-center">
            <span className="text-muted text-xs">Current movement</span>
            <span className={`font-mono text-sm font-bold ${isTracking ? 'text-positive' : 'text-negative'}`}>
              {returnSign}{currentReturn.toFixed(1)}%
            </span>
          </div>
        )}

        {p.target_price && (
          <div className="flex justify-between">
            <span className="text-muted text-xs">Target price</span>
            <span className="font-mono text-xs text-text-secondary">${p.target_price.toFixed(2)}</span>
          </div>
        )}

        {targetProgress !== null && (
          <div>
            <div className="flex justify-between mb-1">
              <span className="text-muted text-xs">Progress to target</span>
              <span className="font-mono text-xs text-text-secondary">{targetProgress.toFixed(0)}%</span>
            </div>
            <div className="w-full h-2 bg-surface rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${isTracking ? 'bg-positive' : 'bg-negative'}`}
                style={{ width: `${targetProgress}%` }}
              />
            </div>
          </div>
        )}

        {/* Resolution countdown */}
        {p.days_remaining !== null && (
          <div className="pt-1.5 mt-1.5 border-t border-border/50">
            <div className="flex justify-between items-center mb-1">
              <span className="text-muted text-xs">Resolution</span>
              <span className={`text-xs font-mono font-medium ${
                _tr.isEvaluating ? 'text-accent' :
                isCritical ? 'text-negative pulse-live' :
                isUrgent ? 'text-warning' :
                'text-text-secondary'
              }`}>
                {_tr.label || `${p.days_remaining}d left`}
              </span>
            </div>
            <div className="w-full h-1.5 bg-surface rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  isCritical ? 'bg-negative' : isUrgent ? 'bg-warning' : 'bg-accent'
                }`}
                style={{ width: `${p.progress_pct || 0}%` }}
              />
            </div>
            <div className="flex justify-between text-[10px] text-muted mt-0.5">
              <span>{p.days_elapsed}d elapsed</span>
              <span>{_tr.label || `${p.days_remaining}d left`}</span>
            </div>
          </div>
        )}
      </div>

      {currentReturn !== null && (
        <div className={`text-xs mt-2 ${isTracking ? 'text-positive' : 'text-negative'}`}>
          {isTracking
            ? `Currently ${returnSign}${currentReturn.toFixed(1)}% \u2014 tracking toward target`
            : `Currently ${returnSign}${currentReturn.toFixed(1)}% \u2014 moving against the call`
          }
        </div>
      )}
    </div>
  );
}
