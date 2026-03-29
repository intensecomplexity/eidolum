import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Shield, TrendingUp, TrendingDown, Check, X, ExternalLink, Bell, BellOff } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import TypeBadge from '../components/TypeBadge';
import TickerLink from '../components/TickerLink';
import AccuracyChart from '../components/AccuracyChart';
import Footer from '../components/Footer';
import { getAnalystProfile, getAnalystAccuracyHistory, getAnalystSubscriptionStatus, subscribeAnalyst, unsubscribeAnalyst } from '../api';

export default function AnalystProfile() {
  const { name } = useParams();
  const { isAuthenticated, user } = useAuth();
  const [profile, setProfile] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [subscribed, setSubscribed] = useState(false);
  const [subLoading, setSubLoading] = useState(false);
  const [emailInput, setEmailInput] = useState('');
  const [emailSubmitted, setEmailSubmitted] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    if (!name) return;
    setLoading(true);
    const fetches = [
      getAnalystProfile(name),
      getAnalystAccuracyHistory(name).catch(() => []),
    ];
    if (isAuthenticated) {
      fetches.push(getAnalystSubscriptionStatus(name).catch(() => ({ subscribed: false })));
    }
    Promise.all(fetches).then(([p, h, sub]) => {
      setProfile(p);
      setHistory(h);
      if (sub) setSubscribed(sub.subscribed);
    }).catch(() => {}).finally(() => setLoading(false));
  }, [name, isAuthenticated]);

  function showToast(message) {
    setToast(message);
    setTimeout(() => setToast(null), 3500);
  }

  async function handleSubscribe() {
    setSubLoading(true);
    try {
      await subscribeAnalyst(name);
      setSubscribed(true);
      showToast(`You'll be notified when ${profile?.name || name} makes a new prediction`);
    } catch {
      showToast('Failed to subscribe');
    } finally { setSubLoading(false); }
  }

  async function handleUnsubscribe() {
    setSubLoading(true);
    try {
      await unsubscribeAnalyst(name);
      setSubscribed(false);
      showToast(`Unsubscribed from ${profile?.name || name}`);
    } catch {
      showToast('Failed to unsubscribe');
    } finally { setSubLoading(false); }
  }

  async function handleEmailSubscribe(e) {
    e.preventDefault();
    const email = emailInput.trim();
    if (!email) return;
    setSubLoading(true);
    try {
      await subscribeAnalyst(name, email);
      setEmailSubmitted(true);
      showToast(`You'll be notified when ${profile?.name || name} makes a new prediction`);
    } catch {
      showToast('Failed to subscribe');
    } finally { setSubLoading(false); }
  }

  async function handleEmailUnsubscribe() {
    const email = emailInput.trim();
    if (!email) return;
    setSubLoading(true);
    try {
      await unsubscribeAnalyst(name, email);
      setEmailSubmitted(false);
      setEmailInput('');
      showToast(`Unsubscribed from ${profile?.name || name}`);
    } catch {
      showToast('Failed to unsubscribe');
    } finally { setSubLoading(false); }
  }

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;
  if (!profile) return <div className="max-w-lg mx-auto px-4 py-20 text-center"><p className="text-text-secondary">Analyst not found.</p></div>;

  return (
    <div>
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        {/* Header */}
        <div className="card mb-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-14 h-14 rounded-full bg-warning/10 border border-warning/20 flex items-center justify-center flex-shrink-0">
                <Shield className="w-7 h-7 text-warning" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="font-bold text-xl">{profile.name}</h1>
                  <TypeBadge type="analyst" showLabel size={14} />
                </div>
                <p className="text-xs text-muted">Verified Analyst: predictions sourced from published research</p>
                {profile.channel_url && (
                  <a href={profile.channel_url} target="_blank" rel="noopener noreferrer" className="text-xs text-accent flex items-center gap-1 mt-1">
                    Source <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
            </div>
            <div className="flex-shrink-0">
              {isAuthenticated ? (
                <SubscribeButton subscribed={subscribed} loading={subLoading} onSubscribe={handleSubscribe} onUnsubscribe={handleUnsubscribe} />
              ) : (
                <EmailSubscribe
                  email={emailInput}
                  setEmail={setEmailInput}
                  submitted={emailSubmitted}
                  loading={subLoading}
                  onSubmit={handleEmailSubscribe}
                  onUnsubscribe={handleEmailUnsubscribe}
                />
              )}
            </div>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-6">
          <Stat label="Accuracy" value={`${profile.accuracy}%`} accent={profile.accuracy >= 50} />
          <Stat label="Total" value={profile.total_predictions} />
          <Stat label="Scored" value={profile.scored_predictions} />
          <Stat label="Correct" value={profile.correct_predictions} />
          <Stat label="Active" value={profile.active_predictions} />
        </div>

        {/* Accuracy Trend */}
        {history.length > 0 && (
          <div className="card mb-6">
            <h2 className="text-xs text-muted uppercase tracking-wider mb-3">Accuracy Trend</h2>
            <AccuracyChart data={history} />
          </div>
        )}

        {/* Sector Breakdown */}
        {profile.sector_breakdown?.length > 0 && (
          <div className="card mb-6">
            <h2 className="text-xs text-muted uppercase tracking-wider mb-3">Sector Accuracy</h2>
            <div className="space-y-2">
              {profile.sector_breakdown.map(s => (
                <div key={s.sector} className="flex items-center gap-3">
                  <span className="text-sm w-24 truncate">{s.sector}</span>
                  <div className="flex-1 h-2 bg-surface-2 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${s.accuracy >= 50 ? 'bg-positive' : 'bg-negative'}`} style={{ width: `${s.accuracy}%` }} />
                  </div>
                  <span className={`font-mono text-xs min-w-[40px] text-right ${s.accuracy >= 50 ? 'text-positive' : 'text-negative'}`}>{s.accuracy}%</span>
                  <span className="text-[10px] text-muted">{s.total}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Ticker Breakdown */}
        {profile.ticker_breakdown?.length > 0 && (
          <div className="card mb-6">
            <h2 className="text-xs text-muted uppercase tracking-wider mb-3">Top Tickers</h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {profile.ticker_breakdown.slice(0, 9).map(t => (
                <div key={t.ticker} className="flex items-center justify-between p-2 bg-surface-2 rounded-lg">
                  <TickerLink ticker={t.ticker} className="text-sm" />
                  <div className="text-right">
                    <span className={`font-mono text-xs ${t.accuracy >= 50 ? 'text-positive' : 'text-negative'}`}>{t.accuracy}%</span>
                    <span className="text-[10px] text-muted ml-1">({t.total})</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Recent Predictions */}
        {profile.recent_predictions?.length > 0 && (
          <div className="mb-6">
            <h2 className="text-xs text-muted uppercase tracking-wider mb-3">Recent Predictions</h2>
            {/* Mobile cards */}
            <div className="sm:hidden space-y-2">
              {profile.recent_predictions.map(p => (
                <div key={p.id} className="card py-3">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <TickerLink ticker={p.ticker} className="text-sm" />
                      <span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span>
                    </div>
                    {p.outcome === 'correct' && <span className="text-positive text-xs font-mono flex items-center gap-0.5"><Check className="w-3 h-3" /> Correct</span>}
                    {p.outcome === 'incorrect' && <span className="text-negative text-xs font-mono flex items-center gap-0.5"><X className="w-3 h-3" /> Incorrect</span>}
                    {p.outcome === 'pending' && <span className="text-muted text-xs">Pending</span>}
                  </div>
                  <div className="text-xs text-muted">
                    {p.target_price && <span>Target: ${p.target_price} </span>}
                    {p.prediction_date && <span>{new Date(p.prediction_date).toLocaleDateString()}</span>}
                  </div>
                </div>
              ))}
            </div>
            {/* Desktop table */}
            <div className="hidden sm:block card overflow-hidden p-0">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                    <th className="px-4 py-2.5">Ticker</th>
                    <th className="px-4 py-2.5">Direction</th>
                    <th className="px-4 py-2.5">Target</th>
                    <th className="px-4 py-2.5 text-center">Outcome</th>
                    <th className="px-4 py-2.5 text-right">Return</th>
                    <th className="px-4 py-2.5 text-right">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {profile.recent_predictions.map(p => (
                    <tr key={p.id} className="border-b border-border/50 hover:bg-surface-2/50">
                      <td className="px-4 py-3"><TickerLink ticker={p.ticker} className="text-sm" /></td>
                      <td className="px-4 py-3"><span className={p.direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{p.direction}</span></td>
                      <td className="px-4 py-3 font-mono text-sm">{p.target_price ? `$${p.target_price}` : '-'}</td>
                      <td className="px-4 py-3 text-center">
                        {p.outcome === 'correct' && <span className="text-positive text-xs font-mono"><Check className="w-3 h-3 inline" /> Correct</span>}
                        {p.outcome === 'incorrect' && <span className="text-negative text-xs font-mono"><X className="w-3 h-3 inline" /> Incorrect</span>}
                        {p.outcome === 'pending' && <span className="text-muted text-xs">Pending</span>}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs">
                        {p.actual_return != null ? (
                          <span className={p.actual_return >= 0 ? 'text-positive' : 'text-negative'}>
                            {p.actual_return >= 0 ? '+' : ''}{p.actual_return.toFixed(1)}%
                          </span>
                        ) : '-'}
                      </td>
                      <td className="px-4 py-3 text-right text-xs text-muted">{p.prediction_date ? new Date(p.prediction_date).toLocaleDateString() : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
      <Footer />
      {toast && (
        <div className="fixed bottom-[80px] sm:bottom-6 left-1/2 -translate-x-1/2 z-[70] px-4 py-2.5 rounded-xl text-xs font-medium shadow-lg border bg-surface border-border text-text-primary backdrop-blur-sm toast-slide-up">
          {toast}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, accent }) {
  return (
    <div className="card text-center py-3">
      <div className={`font-mono text-lg font-bold ${accent ? 'text-accent' : 'text-text-primary'}`}>{value}</div>
      <div className="text-[10px] text-muted">{label}</div>
    </div>
  );
}

function SubscribeButton({ subscribed, loading, onSubscribe, onUnsubscribe }) {
  if (subscribed) {
    return (
      <div className="relative group">
        <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-positive bg-positive/10 border border-positive/20">
          <Bell className="w-3.5 h-3.5" /> Subscribed
        </span>
        <button onClick={onUnsubscribe} disabled={loading}
          className="absolute inset-0 opacity-0 group-hover:opacity-100 flex items-center justify-center rounded-lg text-xs font-medium text-negative bg-negative/10 border border-negative/20 transition-opacity">
          <BellOff className="w-3.5 h-3.5 mr-1" /> Unsubscribe
        </button>
      </div>
    );
  }
  return (
    <button onClick={onSubscribe} disabled={loading}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-accent bg-accent/10 border border-accent/30 hover:bg-accent/20 transition-colors">
      <Bell className="w-3.5 h-3.5" /> Get notified
    </button>
  );
}

function EmailSubscribe({ email, setEmail, submitted, loading, onSubmit, onUnsubscribe }) {
  if (submitted) {
    return (
      <div className="flex items-center gap-2">
        <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-positive bg-positive/10 border border-positive/20">
          <Bell className="w-3.5 h-3.5" /> Subscribed
        </span>
        <button onClick={onUnsubscribe} className="text-[10px] text-muted hover:text-negative transition-colors">
          Unsubscribe
        </button>
      </div>
    );
  }
  return (
    <form onSubmit={onSubmit} className="flex items-center gap-2">
      <input
        type="email"
        value={email}
        onChange={e => setEmail(e.target.value)}
        placeholder="your@email.com"
        required
        className="w-40 sm:w-48 px-3 py-1.5 bg-surface-2 border border-border rounded-lg text-xs text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50"
      />
      <button type="submit" disabled={loading}
        className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-accent bg-accent/10 border border-accent/30 hover:bg-accent/20 transition-colors whitespace-nowrap">
        <Bell className="w-3.5 h-3.5" /> Notify me
      </button>
    </form>
  );
}
