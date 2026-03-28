import { useEffect, useState } from 'react';
import { Zap, Check, X, Trophy, Flame } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import DailyChallengeCard from '../components/DailyChallengeCard';
import TickerLink from '../components/TickerLink';
import Footer from '../components/Footer';
import { getChallengeHistory, getChallengeLeaderboard } from '../api';

export default function DailyChallenge() {
  const { isAuthenticated } = useAuth();
  const [tab, setTab] = useState('history');
  const [history, setHistory] = useState([]);
  const [leaderboard, setLeaderboard] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    if (tab === 'history') {
      getChallengeHistory().then(setHistory).catch(() => {}).finally(() => setLoading(false));
    } else {
      getChallengeLeaderboard().then(setLeaderboard).catch(() => {}).finally(() => setLoading(false));
    }
  }, [tab]);

  return (
    <div>
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-1">
          <Zap className="w-6 h-6 text-warning" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Daily Challenge</h1>
        </div>
        <p className="text-text-secondary text-sm mb-6">One stock. Bull or bear. Every day.</p>

        {/* Today's challenge */}
        <DailyChallengeCard />

        {/* Tabs */}
        <div className="flex gap-2 mb-6">
          <button onClick={() => setTab('history')} className={`px-4 py-2 rounded-lg text-xs font-semibold transition-colors ${tab === 'history' ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface text-text-secondary border border-border'}`}>History</button>
          <button onClick={() => setTab('leaderboard')} className={`px-4 py-2 rounded-lg text-xs font-semibold transition-colors ${tab === 'leaderboard' ? 'bg-accent/15 text-accent border border-accent/30' : 'bg-surface text-text-secondary border border-border'}`}>Leaderboard</button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>
        ) : tab === 'history' ? (
          /* History */
          history.length === 0 ? (
            <div className="text-center py-12"><p className="text-text-secondary">No completed challenges yet.</p></div>
          ) : (
            <div className="space-y-2">
              {history.map(c => (
                <div key={c.id} className="card py-3 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <TickerLink ticker={c.ticker} className="text-sm" />
                    <span className={c.correct_direction === 'bullish' ? 'badge-bull' : 'badge-bear'}>{c.correct_direction}</span>
                    <span className="text-xs text-muted">{c.challenge_date}</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs">
                    <span className="text-muted font-mono">{c.community_accuracy}% correct</span>
                    {c.user_entry ? (
                      c.user_entry.outcome === 'correct'
                        ? <Check className="w-4 h-4 text-positive" />
                        : <X className="w-4 h-4 text-negative" />
                    ) : (
                      <span className="text-muted">-</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )
        ) : (
          /* Leaderboard */
          leaderboard.length === 0 ? (
            <div className="text-center py-12"><Trophy className="w-10 h-10 text-muted/30 mx-auto mb-3" /><p className="text-text-secondary">Need 10 entries to rank.</p></div>
          ) : (
            <div className="space-y-2">
              {leaderboard.map(u => (
                <div key={u.user_id} className="card py-3 flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <span className={`font-mono font-bold text-sm ${u.rank <= 3 ? 'text-warning' : 'text-text-secondary'}`}>
                      {u.rank <= 3 ? [null, '\uD83E\uDD47', '\uD83E\uDD48', '\uD83E\uDD49'][u.rank] : `#${u.rank}`}
                    </span>
                    <div>
                      <span className="font-medium text-sm">{u.display_name || u.username}</span>
                      <span className="text-xs text-muted block font-mono">{u.total_entries} played</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <span className={`font-mono font-semibold ${u.accuracy >= 60 ? 'text-positive' : 'text-negative'}`}>{u.accuracy}%</span>
                    {u.daily_streak_current >= 3 && <span className="text-orange-400 text-xs font-mono flex items-center gap-0.5 justify-end mt-0.5"><Flame className="w-3 h-3" />{u.daily_streak_current}</span>}
                  </div>
                </div>
              ))}
            </div>
          )
        )}
      </div>
      <Footer />
    </div>
  );
}
