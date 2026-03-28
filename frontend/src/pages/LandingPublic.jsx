import { useEffect, useState, useRef } from 'react';
import { Link } from 'react-router-dom';
import { BarChart3, Crosshair, Check, Trophy, TrendingUp, TrendingDown, ArrowRight } from 'lucide-react';
import TypeBadge from '../components/TypeBadge';
import Footer from '../components/Footer';
import { getLeaderboard, getGlobalStats } from '../api';

// ── Animated counter ─────────────────────────────────────────────────────────
function AnimatedNumber({ target, duration = 1500 }) {
  const [value, setValue] = useState(0);
  const ref = useRef(null);
  const started = useRef(false);

  useEffect(() => {
    if (!target) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !started.current) {
        started.current = true;
        const start = Date.now();
        const tick = () => {
          const elapsed = Date.now() - start;
          const progress = Math.min(elapsed / duration, 1);
          const eased = 1 - Math.pow(1 - progress, 3);
          setValue(Math.floor(eased * target));
          if (progress < 1) requestAnimationFrame(tick);
        };
        tick();
      }
    }, { threshold: 0.3 });
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, [target, duration]);

  return <span ref={ref}>{value.toLocaleString()}</span>;
}

// ── Fade-in on scroll ────────────────────────────────────────────────────────
function FadeIn({ children, className = '' }) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) setVisible(true);
    }, { threshold: 0.15 });
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref} className={`transition-all duration-700 ${visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-6'} ${className}`}>
      {children}
    </div>
  );
}

export default function LandingPublic() {
  const [top5, setTop5] = useState([]);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    getLeaderboard().then(data => setTop5((data || []).slice(0, 5))).catch(() => {});
    getGlobalStats().then(setStats).catch(() => {});
  }, []);

  return (
    <div>
      {/* ── 1. HERO ────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden">
        {/* Background grid */}
        <div className="absolute inset-0 grid-bg opacity-50" />
        <div className="absolute inset-0" style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(0,168,120,0.08) 0%, transparent 60%)' }} />

        <div className="relative max-w-3xl mx-auto px-4 sm:px-6 pt-16 sm:pt-24 pb-12 sm:pb-20 text-center">
          <h1 className="headline-serif text-text-primary mb-5" style={{ fontSize: 'clamp(2.2rem, 6vw, 4rem)', lineHeight: 1.1 }}>
            Who should you actually listen to?
          </h1>
          <p className="text-text-secondary text-base sm:text-lg leading-relaxed max-w-xl mx-auto mb-8">
            We track analyst and investor predictions against real market data. No opinions. Just accuracy scores.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link to="/register" className="btn-primary px-8 w-full sm:w-auto">Start Predicting</Link>
            <Link to="/leaderboard" className="btn-secondary px-8 w-full sm:w-auto">See the Leaderboard</Link>
          </div>

          {/* Mini leaderboard preview */}
          {top5.length >= 3 && (
            <div className="mt-12 max-w-md mx-auto">
              <div className="card p-0 overflow-hidden border-accent/10">
                {top5.slice(0, 3).map((f, i) => (
                  <div key={f.id} className="flex items-center gap-3 px-4 py-3 border-b border-border/50 last:border-b-0">
                    <span className="font-mono font-bold text-warning text-sm w-6">{['🥇','🥈','🥉'][i]}</span>
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium">{f.name}</span>
                    </div>
                    <span className={`font-mono text-sm font-semibold ${(f.accuracy_rate || 0) >= 60 ? 'text-positive' : 'text-negative'}`}>
                      {(f.accuracy_rate || 0).toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>

      {/* ── 2. HOW IT WORKS ────────────────────────────────────────────── */}
      <section className="max-w-4xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <FadeIn>
          <h2 className="headline-serif text-center mb-3" style={{ fontSize: 'clamp(1.8rem, 4vw, 2.8rem)' }}>How it works</h2>
          <p className="text-text-secondary text-center mb-12">Three steps. No complexity.</p>
        </FadeIn>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
          {[
            { num: '01', icon: <Crosshair className="w-8 h-8 text-accent" />, title: 'Make a Call', desc: 'Pick a stock, go bullish or bearish, set your target and timeframe.' },
            { num: '02', icon: <Check className="w-8 h-8 text-positive" />, title: 'Get Scored', desc: 'We automatically compare your prediction to real market data when time\'s up.' },
            { num: '03', icon: <Trophy className="w-8 h-8 text-warning" />, title: 'Build Your Reputation', desc: 'Climb the ranks, earn badges, prove you\'re not just noise.' },
          ].map((step, i) => (
            <FadeIn key={step.num}>
              <div className="card text-center py-8" style={{ animationDelay: `${i * 150}ms` }}>
                <div className="text-[10px] text-accent font-mono font-bold tracking-widest mb-4">{step.num}</div>
                <div className="flex justify-center mb-4">{step.icon}</div>
                <h3 className="font-semibold mb-2">{step.title}</h3>
                <p className="text-sm text-text-secondary leading-relaxed">{step.desc}</p>
              </div>
            </FadeIn>
          ))}
        </div>
      </section>

      {/* ── 3. LIVE STATS ──────────────────────────────────────────────── */}
      {stats && (
        <section className="border-y border-border py-12 sm:py-16">
          <div className="max-w-4xl mx-auto px-4 sm:px-6">
            <FadeIn>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 text-center">
                <div>
                  <div className="font-mono text-2xl sm:text-3xl font-bold text-accent"><AnimatedNumber target={stats.total_predictions} /></div>
                  <div className="text-xs text-muted mt-1">Predictions Tracked</div>
                </div>
                <div>
                  <div className="font-mono text-2xl sm:text-3xl font-bold text-text-primary"><AnimatedNumber target={stats.total_forecasters + stats.total_users} /></div>
                  <div className="text-xs text-muted mt-1">Forecasters</div>
                </div>
                <div>
                  <div className="font-mono text-2xl sm:text-3xl font-bold text-positive"><AnimatedNumber target={Math.round(stats.average_accuracy)} />%</div>
                  <div className="text-xs text-muted mt-1">Avg Accuracy</div>
                </div>
                <div>
                  <div className="font-mono text-2xl sm:text-3xl font-bold text-warning"><AnimatedNumber target={stats.active_predictions} /></div>
                  <div className="text-xs text-muted mt-1">Active Right Now</div>
                </div>
              </div>
            </FadeIn>
          </div>
        </section>
      )}

      {/* ── 4. LEADERBOARD PREVIEW ─────────────────────────────────────── */}
      {top5.length > 0 && (
        <section className="max-w-4xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
          <FadeIn>
            <h2 className="headline-serif text-center mb-2" style={{ fontSize: 'clamp(1.8rem, 4vw, 2.8rem)' }}>
              The most accurate forecasters on the internet
            </h2>
            <p className="text-text-secondary text-center mb-10">Ranked by results, not followers.</p>
          </FadeIn>

          <FadeIn>
            <div className="card overflow-hidden p-0 border-accent/10">
              <table className="w-full">
                <thead>
                  <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                    <th className="px-5 py-3 w-12">#</th>
                    <th className="px-5 py-3">Name</th>
                    <th className="px-5 py-3 text-right">Accuracy</th>
                    <th className="px-5 py-3 text-right hidden sm:table-cell">Scored</th>
                  </tr>
                </thead>
                <tbody>
                  {top5.map(f => (
                    <tr key={f.id} className="border-b border-border/50">
                      <td className="px-5 py-3.5">
                        <span className={`font-mono font-bold ${f.rank <= 3 ? 'text-warning' : 'text-text-secondary'}`}>
                          {f.rank <= 3 ? [null, '🥇', '🥈', '🥉'][f.rank] : f.rank}
                        </span>
                      </td>
                      <td className="px-5 py-3.5">
                        <span className="font-medium">{f.name}</span>
                      </td>
                      <td className="px-5 py-3.5 text-right">
                        <span className={`font-mono font-semibold ${(f.accuracy_rate || 0) >= 60 ? 'text-positive' : 'text-negative'}`}>
                          {(f.accuracy_rate || 0).toFixed(1)}%
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-right hidden sm:table-cell">
                        <span className="font-mono text-text-secondary text-sm">{f.scored_count || f.evaluated_predictions || 0}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="text-center mt-6">
              <Link to="/leaderboard" className="text-accent text-sm font-medium inline-flex items-center gap-1">
                See full rankings <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
          </FadeIn>
        </section>
      )}

      {/* ── 5. DIFFERENTIATOR ──────────────────────────────────────────── */}
      <section className="max-w-4xl mx-auto px-4 sm:px-6 py-12 sm:py-20">
        <FadeIn>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="card text-center py-6 border-border/50">
              <div className="text-lg mb-2">𝕏</div>
              <h3 className="font-semibold text-sm mb-1 text-text-secondary">Twitter / X</h3>
              <p className="text-xs text-muted">Opinions with no accountability</p>
            </div>
            <div className="card text-center py-6 border-border/50">
              <div className="text-lg mb-2">🏦</div>
              <h3 className="font-semibold text-sm mb-1 text-text-secondary">Wall Street Research</h3>
              <p className="text-xs text-muted">Paywalled, no public track record</p>
            </div>
            <div className="card text-center py-6 border-accent/30 bg-accent/[0.03]">
              <div className="flex items-center justify-center gap-1.5 mb-2">
                <BarChart3 className="w-5 h-5 text-accent" />
                <span className="font-serif text-lg"><span className="text-accent">eido</span><span className="text-muted">lum</span></span>
              </div>
              <h3 className="font-semibold text-sm mb-1 text-accent">Eidolum</h3>
              <p className="text-xs text-text-secondary">Every call tracked, scored, and ranked. Free.</p>
            </div>
          </div>
        </FadeIn>
      </section>

      {/* ── 6. FINAL CTA ───────────────────────────────────────────────── */}
      <section className="border-t border-border py-16 sm:py-24 text-center">
        <FadeIn>
          <h2 className="headline-serif mb-4" style={{ fontSize: 'clamp(1.8rem, 4vw, 2.6rem)' }}>
            Ready to prove you're right?
          </h2>
          <p className="text-text-secondary mb-8 max-w-md mx-auto">
            No credit card. No paywall. Just predictions and results.
          </p>
          <Link to="/register" className="btn-primary px-10 py-4 text-base">Create your free account</Link>
        </FadeIn>
      </section>

      {/* ── FOOTER ─────────────────────────────────────────────────────── */}
      <footer className="border-t border-border py-8 text-center">
        <div className="max-w-4xl mx-auto px-4">
          <div className="flex items-center justify-center gap-2 mb-4">
            <BarChart3 className="w-5 h-5 text-accent" />
            <span className="font-serif text-lg"><span className="text-accent">eido</span><span className="text-muted">lum</span></span>
          </div>
          <div className="flex items-center justify-center gap-6 text-xs text-muted mb-4">
            <Link to="/leaderboard" className="hover:text-text-secondary">Leaderboard</Link>
            <Link to="/consensus" className="hover:text-text-secondary">Consensus</Link>
            <Link to="/activity" className="hover:text-text-secondary">Activity</Link>
          </div>
          <p className="text-[10px] text-muted/60">Built by Nimrod</p>
        </div>
      </footer>
    </div>
  );
}
