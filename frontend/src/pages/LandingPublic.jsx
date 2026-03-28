import { useEffect, useState, useRef } from 'react';
import { Link } from 'react-router-dom';
import { Crosshair, Check, Trophy, TrendingUp, TrendingDown, ArrowRight, ChevronDown } from 'lucide-react';
import EidolumLogo from '../components/EidolumLogo';
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
        <div className="absolute inset-0" style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(212,160,23,0.08) 0%, transparent 60%)' }} />

        <div className="relative max-w-3xl mx-auto px-4 sm:px-6 pt-16 sm:pt-24 pb-12 sm:pb-20 text-center">
          <h1 className="headline-serif text-text-primary mb-5" style={{ fontSize: 'clamp(2.2rem, 6vw, 4rem)', lineHeight: 1.1 }}>
            Who should you <span className="font-serif italic text-accent">actually</span> listen to?
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

      {/* ── 2. HOW SCORING WORKS ──────────────────────────────────────── */}
      <section className="max-w-4xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <FadeIn>
          <h2 className="font-bold text-center mb-3" style={{ fontSize: 'clamp(1.8rem, 4vw, 2.8rem)' }}>How Scoring Works</h2>
          <p className="text-text-secondary text-center mb-12">Four steps. Full transparency.</p>
        </FadeIn>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          {[
            { num: '01', title: 'We Collect Predictions', desc: 'Analyst upgrades, downgrades, and price targets are collected from verified financial sources with timestamps and archived proof.' },
            { num: '02', title: 'We Wait for the Deadline', desc: 'Each prediction has a clear evaluation window. Every prediction is tracked — not just the ones that worked out.' },
            { num: '03', title: 'We Check the Math', desc: 'When the window closes, we compare the prediction against actual market data. Right or wrong — no gray area.' },
            { num: '04', title: 'We Rank by Results', desc: 'Forecasters are ranked by verified accuracy, not followers or reputation.' },
          ].map((step, i) => (
            <FadeIn key={step.num}>
              <div className="card py-6" style={{ animationDelay: `${i * 100}ms` }}>
                <div className="text-[10px] text-accent font-mono font-bold tracking-widest mb-2">{step.num}</div>
                <h3 className="font-semibold mb-1.5">{step.title}</h3>
                <p className="text-sm text-text-secondary leading-relaxed">{step.desc}</p>
              </div>
            </FadeIn>
          ))}
        </div>
      </section>

      {/* ── 2b. SEASONS EXPLAINER ────────────────────────────────────── */}
      <section className="border-y border-border py-10 sm:py-14">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 text-center">
          <FadeIn>
            <span className="text-[10px] text-accent font-mono font-bold uppercase tracking-widest">Quarterly Competition</span>
            <p className="text-text-secondary text-sm sm:text-base leading-relaxed mt-3 max-w-2xl mx-auto">
              Compete in quarterly Seasons — each with a unique theme — where accuracy resets and everyone gets a fresh shot at the top. Climb the seasonal leaderboard and earn exclusive badges.
            </p>
          </FadeIn>
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
            <div className="card text-center py-6 border-negative/20 bg-negative/[0.02]">
              <div className="text-lg mb-2">𝕏</div>
              <h3 className="font-semibold text-sm mb-1 text-text-secondary">Twitter / X</h3>
              <p className="text-xs text-muted">Opinions with no accountability</p>
            </div>
            <div className="card text-center py-6 border-negative/20 bg-negative/[0.02]">
              <div className="text-lg mb-2">🏦</div>
              <h3 className="font-semibold text-sm mb-1 text-text-secondary">Wall Street Research</h3>
              <p className="text-xs text-muted">Paywalled, no public track record</p>
            </div>
            <div className="card text-center py-6" style={{ borderColor: 'rgba(212,160,23,0.3)', background: 'rgba(212,160,23,0.03)' }}>
              <div className="flex items-center justify-center gap-1.5 mb-2">
                <EidolumLogo size={20} />
                <span className="font-serif text-lg text-accent">Eidolum</span>
                <span className="text-accent text-sm">✓</span>
              </div>
              <p className="text-sm text-text-primary font-medium">Every call tracked, scored, and ranked. Free.</p>
            </div>
          </div>
        </FadeIn>
      </section>

      {/* ── 6. FAQ ─────────────────────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <FadeIn>
          <h2 className="font-bold text-center mb-10" style={{ fontSize: 'clamp(1.6rem, 4vw, 2.4rem)' }}>Frequently Asked Questions</h2>
        </FadeIn>
        <div className="space-y-2">
          <FaqItem q="How do you define a prediction?" a="A prediction is a specific, measurable financial forecast — like 'TSLA will reach $300 by June 2026' or 'UBS downgrades NKE to Sell with a $50 target.' Vague commentary like 'I'm bullish on tech' doesn't count. Every prediction needs a ticker, a direction, and a timeframe." />
          <FaqItem q="How do you score correctness?" a="When a prediction's timeframe expires, we compare it against actual market data. For price targets, did the stock hit the target? For directional calls, did it move the right way? It's binary — correct or incorrect." />
          <FaqItem q="Can users see the raw source?" a="Yes. Every scraped prediction links back to its original source with an archived proof link. You can verify every data point yourself." />
          <FaqItem q="How do you avoid cherry-picking?" a="We track ALL predictions from each forecaster, not just their wins. Every prediction is timestamped and archived the moment we find it. There's no way to hide bad calls — your full track record is public." />
          <FaqItem q="Are you rating conviction or popularity?" a="Pure accuracy. We don't care how many followers an analyst has. The only thing that matters is: were they right?" />
        </div>
      </section>

      {/* ── 7. CTA — STOP GUESSING ────────────────────────────────────── */}
      <section className="border-t border-border py-16 sm:py-24 text-center">
        <FadeIn>
          <h2 className="font-bold mb-4" style={{ fontSize: 'clamp(1.8rem, 4vw, 2.6rem)' }}>
            Stop guessing who to trust
          </h2>
          <p className="text-text-secondary mb-8 max-w-lg mx-auto">
            Track predictions. Verify accuracy. Follow the forecasters who actually get it right.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link to="/leaderboard" className="btn-primary px-8 w-full sm:w-auto">See the Leaderboard</Link>
            <Link to="/register" className="btn-secondary px-8 w-full sm:w-auto">Start Tracking</Link>
          </div>
        </FadeIn>
      </section>

      {/* ── 8. FOOTER ────────────────────────────────────────────────── */}
      <footer className="border-t border-border py-8 text-center">
        <div className="max-w-4xl mx-auto px-4">
          <div className="flex items-center justify-center gap-2 mb-4">
            <EidolumLogo size={20} />
            <span className="font-serif text-lg text-accent">Eidolum</span>
          </div>
          <div className="flex items-center justify-center gap-6 text-xs text-muted mb-4">
            <Link to="/leaderboard" className="hover:text-accent">Leaderboard</Link>
            <Link to="/consensus" className="hover:text-accent">Consensus</Link>
            <Link to="/activity" className="hover:text-accent">Activity</Link>
          </div>
          <p className="text-[10px] text-muted/50">&copy; 2026 Eidolum. All data, scoring methodologies, and platform content are proprietary.</p>
        </div>
      </footer>
    </div>
  );
}

function FaqItem({ q, a }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card py-0 overflow-hidden">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between px-5 py-4 text-left">
        <span className="text-sm font-medium text-text-primary pr-4">{q}</span>
        <ChevronDown className={`w-4 h-4 text-muted flex-shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="px-5 pb-4 text-sm text-text-secondary leading-relaxed border-t border-border/50 pt-3">
          {a}
        </div>
      )}
    </div>
  );
}
