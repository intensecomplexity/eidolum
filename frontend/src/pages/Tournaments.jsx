import { useEffect, useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { Link } from 'react-router-dom';
import { Trophy, Clock, Users, Lock, Check } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import TickerSearch from '../components/TickerSearch';
import Footer from '../components/Footer';
import api from '../api';

function authHeaders() {
  const token = localStorage.getItem('eidolum_token') || '';
  return { Authorization: `Bearer ${token}` };
}

export default function Tournaments() {
  const { isAuthenticated, user } = useAuth();
  const [tournaments, setTournaments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [myEntry, setMyEntry] = useState(null);
  const [picks, setPicks] = useState([{ ticker: '', direction: 'bullish', target_price: '' }, { ticker: '', direction: 'bullish', target_price: '' }, { ticker: '', direction: 'bullish', target_price: '' }, { ticker: '', direction: 'bullish', target_price: '' }, { ticker: '', direction: 'bullish', target_price: '' }]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get('/tournaments').then(r => {
      setTournaments(r.data);
      if (r.data.length > 0) setSelected(r.data[0]);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selected || !isAuthenticated) return;
    api.get(`/tournaments/${selected.id}/my-entry`, { headers: authHeaders() })
      .then(r => setMyEntry(r.data))
      .catch(() => setMyEntry(null));
  }, [selected, isAuthenticated]);

  async function handleSubmit() {
    if (!selected) return;
    const valid = picks.every(p => p.ticker.trim());
    if (!valid) { setError('All 5 picks are required'); return; }
    setSubmitting(true); setError('');
    try {
      await api.post(`/tournaments/${selected.id}/enter`, { picks }, { headers: authHeaders() });
      setMyEntry({ entered: true, picks });
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to enter');
    } finally { setSubmitting(false); }
  }

  function updatePick(i, field, value) {
    const next = [...picks];
    next[i] = { ...next[i], [field]: value };
    setPicks(next);
  }

  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><LoadingSpinner size="lg" /></div>;

  if (tournaments.length === 0) return (
    <div className="max-w-3xl mx-auto px-4 py-20 text-center">
      <Trophy className="w-10 h-10 text-muted/30 mx-auto mb-3" />
      <p className="text-text-secondary text-lg">No tournaments yet.</p>
      <p className="text-muted text-sm mt-1">Check back soon.</p>
    </div>
  );

  const t = selected;
  const isUpcoming = t?.status === 'upcoming';
  const isActive = t?.status === 'active';
  const isCompleted = t?.status === 'completed';

  return (
    <div>
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-10">
        <h1 className="font-bold text-2xl sm:text-3xl mb-2 flex items-center gap-2">
          <Trophy className="w-7 h-7 text-accent" /> Tournaments
        </h1>
        <p className="text-text-secondary text-sm mb-6">Pick 5 stocks. Get scored. Win badges.</p>

        {/* Tournament selector */}
        {tournaments.length > 1 && (
          <div className="flex gap-2 mb-6 overflow-x-auto pills-scroll">
            {tournaments.map(tr => (
              <button key={tr.id} onClick={() => setSelected(tr)}
                className={`px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
                  selected?.id === tr.id ? 'bg-accent/10 text-accent border border-accent/20' : 'text-text-secondary border border-border'
                }`}>
                {tr.name}
              </button>
            ))}
          </div>
        )}

        {t && (
          <>
            {/* Tournament header */}
            <div className="card mb-6">
              <div className="flex items-center justify-between mb-2">
                <h2 className="text-lg font-bold">{t.name}</h2>
                <span className={`text-xs font-mono px-2 py-1 rounded ${
                  isUpcoming ? 'bg-warning/10 text-warning' : isActive ? 'bg-positive/10 text-positive' : 'bg-muted/10 text-muted'
                }`}>
                  {t.status.toUpperCase()}
                </span>
              </div>
              <div className="flex gap-4 text-xs text-muted">
                <span><Clock className="w-3 h-3 inline mr-1" />{t.start_date?.slice(0, 10)} — {t.end_date?.slice(0, 10)}</span>
                <span><Users className="w-3 h-3 inline mr-1" />{t.entries}/{t.max_participants} entered</span>
                {isUpcoming && <span><Lock className="w-3 h-3 inline mr-1" />Deadline: {t.entry_deadline?.slice(0, 10)}</span>}
              </div>
            </div>

            {/* Entry form (upcoming only, not already entered) */}
            {isUpcoming && isAuthenticated && !myEntry?.entered && (
              <div className="card mb-6">
                <h3 className="font-semibold mb-3">Your 5 Picks</h3>
                {error && <div className="text-negative text-sm mb-3">{error}</div>}
                <div className="space-y-3">
                  {picks.map((pick, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <span className="text-xs text-muted w-4">{i + 1}.</span>
                      <input type="text" value={pick.ticker} onChange={e => updatePick(i, 'ticker', e.target.value.toUpperCase())}
                        placeholder="AAPL" className="w-24 px-3 py-2 bg-surface-2 border border-border rounded-lg font-mono text-sm" />
                      <select value={pick.direction} onChange={e => updatePick(i, 'direction', e.target.value)}
                        className="px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm">
                        <option value="bullish">Bull</option>
                        <option value="bearish">Bear</option>
                        <option value="neutral">Hold</option>
                      </select>
                      <input type="text" value={pick.target_price} onChange={e => updatePick(i, 'target_price', e.target.value)}
                        placeholder="Target $" className="w-24 px-3 py-2 bg-surface-2 border border-border rounded-lg font-mono text-sm" />
                    </div>
                  ))}
                </div>
                <button onClick={handleSubmit} disabled={submitting} className="btn-primary mt-4 w-full">
                  {submitting ? 'Submitting...' : 'Lock In My Picks'}
                </button>
              </div>
            )}

            {/* My entry */}
            {myEntry?.entered && (
              <div className="card mb-6 border-accent/20">
                <div className="flex items-center gap-2 mb-3">
                  <Check className="w-4 h-4 text-positive" />
                  <span className="text-sm font-medium">Your picks are locked</span>
                  {myEntry.score != null && <span className="font-mono text-accent ml-auto">{myEntry.score} pts (#{myEntry.rank})</span>}
                </div>
                <div className="space-y-1">
                  {(myEntry.picks || []).map((p, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span className="font-mono text-accent w-14">{p.ticker}</span>
                      <span className={p.direction === 'bullish' ? 'text-positive' : p.direction === 'bearish' ? 'text-negative' : 'text-warning'}>
                        {p.direction === 'bullish' ? 'BULL' : p.direction === 'bearish' ? 'BEAR' : 'HOLD'}
                      </span>
                      {p.target_price && <span className="text-muted">${p.target_price}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Not logged in */}
            {isUpcoming && !isAuthenticated && (
              <div className="card mb-6 text-center py-8">
                <p className="text-text-secondary mb-3">Log in to enter this tournament</p>
                <Link to="/login" className="btn-primary px-6">Log In</Link>
              </div>
            )}

            {/* Leaderboard */}
            {(isActive || isCompleted) && selected && (
              <TournamentLeaderboard tournamentId={selected.id} />
            )}
          </>
        )}
      </div>
      <Footer />
    </div>
  );
}

function TournamentLeaderboard({ tournamentId }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    api.get(`/tournaments/${tournamentId}`).then(r => setData(r.data)).catch(() => {});
  }, [tournamentId]);

  if (!data?.leaderboard?.length) return null;

  return (
    <div>
      <h3 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Leaderboard</h3>
      <div className="card p-0 overflow-hidden">
        {data.leaderboard.map((r, i) => (
          <div key={r.user_id} className={`flex items-center justify-between px-4 py-3 ${i > 0 ? 'border-t border-border/50' : ''}`}>
            <div className="flex items-center gap-3">
              <span className={`font-mono text-sm font-bold w-6 ${i < 3 ? 'text-accent' : 'text-muted'}`}>
                {r.rank || i + 1}
              </span>
              <Link to={`/profile/${r.user_id}`} className="text-sm font-medium hover:text-accent">
                {r.display_name || r.username}
              </Link>
              {r.prize_badge && (
                <span className="text-xs">
                  {r.prize_badge === 'tournament_gold' ? '🥇' : r.prize_badge === 'tournament_silver' ? '🥈' : '🥉'}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 text-xs font-mono">
              <span className="text-positive">{r.hits}H</span>
              <span className="text-warning">{r.nears}N</span>
              <span className="text-negative">{r.misses}M</span>
              <span className="text-accent font-bold">{r.score} pts</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
