import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Swords } from 'lucide-react';
import { getMyRival } from '../api';

export default function RivalCard() {
  const [data, setData] = useState(null);

  useEffect(() => {
    getMyRival().then(d => { if (d?.rival) setData(d); }).catch(() => {});
  }, []);

  if (!data?.rival) return null;

  const { rival, head_to_head, shared_tickers } = data;
  const gap = rival.accuracy_gap;
  const userAhead = gap < 0;

  return (
    <div className="card mb-4 relative overflow-hidden" style={{ borderColor: '#f59e0b30' }}>
      <div className="absolute inset-0 opacity-[0.03]" style={{ background: 'linear-gradient(135deg, #f59e0b, transparent 70%)' }} />
      <div className="relative">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Swords className="w-4 h-4 text-warning" />
            <span className="text-[10px] font-bold uppercase tracking-widest text-warning">Your Rival</span>
          </div>
          <span className="text-[10px] text-muted">#{rival.user_rank} vs #{rival.rival_rank}</span>
        </div>

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {rival.rival_avatar_url ? (
              <img src={rival.rival_avatar_url} alt="" className="w-10 h-10 rounded-full border border-warning/20 object-cover" referrerPolicy="no-referrer" />
            ) : (
              <div className="w-10 h-10 rounded-full bg-warning/10 border border-warning/20 flex items-center justify-center">
                <span className="font-mono text-sm text-warning font-bold">{(rival.rival_username || '?')[0].toUpperCase()}</span>
              </div>
            )}
            <div>
              <Link to={`/profile/${rival.rival_user_id}`} className="font-medium text-sm hover:text-accent transition-colors">
                {rival.rival_display_name || rival.rival_username}
              </Link>
              <div className="text-xs text-muted font-mono">@{rival.rival_username} · {rival.rival_accuracy}%</div>
            </div>
          </div>

          <div className="text-right">
            <div className={`font-mono text-sm font-bold ${userAhead ? 'text-positive' : 'text-negative'}`}>
              {userAhead ? `You're ${Math.abs(gap).toFixed(1)}% ahead` : `${Math.abs(gap).toFixed(1)}% ahead of you`}
            </div>
            {shared_tickers > 0 && (
              <div className="text-[10px] text-muted">{shared_tickers} shared tickers</div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 mt-3">
          <Link to={`/profile/${rival.rival_user_id}`} className="text-[10px] text-muted hover:text-accent transition-colors">View profile</Link>
          <span className="text-border">·</span>
          <Link to={`/compare/${rival.user_rank > rival.rival_rank ? '' : ''}${rival.rival_user_id}`} className="text-[10px] text-muted hover:text-accent transition-colors">Compare</Link>
        </div>
      </div>
    </div>
  );
}
