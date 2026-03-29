import { useEffect, useState, useRef } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, ChevronDown, TrendingUp, TrendingDown } from 'lucide-react';
import EidolumLogo from '../components/EidolumLogo';
import Footer from '../components/Footer';
import { getLeaderboard, getHomepageStats, getTrendingTickers, getPendingPredictions } from '../api';

// ── Animated counter ─────────────────────────────────────────────────────────
function AnimatedNumber({ target, duration = 1500, suffix = '' }) {
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

  return <span ref={ref}>{value.toLocaleString()}{suffix}</span>;
}

// ── Fade-in on scroll ────────────────────────────────────────────────────────
function FadeIn({ children, className = '', delay = 0 }) {
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
    <div ref={ref} className={`transition-all duration-700 ${visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-6'} ${className}`}
      style={{ transitionDelay: `${delay}ms` }}>
      {children}
    </div>
  );
}

// ── Time ago helper ──────────────────────────────────────────────────────────
function timeAgo(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const hours = Math.floor(diff / 3600000);
  if (hours < 1) return 'just now';
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function LandingPublic() {
  const [top5, setTop5] = useState([]);
  const [stats, setStats] = useState(null);
  const [trending, setTrending] = useState([]);
  const [recentCalls, setRecentCalls] = useState([]);

  useEffect(() => {
    getLeaderboard().then(data => setTop5((data || []).slice(0, 5))).catch(() => {});
    getHomepageStats().then(setStats).catch(() => {});
    getTrendingTickers().then(data => setTrending((data || []).slice(0, 8))).catch(() => {});
    getPendingPredictions().then(data => setRecentCalls((data || []).slice(0, 5))).catch(() => {});
  }, []);

  return (
    <div>
      {/* ── 1. HERO ────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 grid-bg opacity-50" />
        <div className="absolute inset-0" style={{ background: 'radial-gradient(ellipse at 50% 0%, rgba(212,160,23,0.08) 0%, transparent 60%)' }} />

        <div className="relative max-w-3xl mx-auto px-4 sm:px-6 pt-16 sm:pt-24 pb-10 sm:pb-16 text-center">
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

          {/* Trust stat bar */}
          {stats && (
            <div className="mt-6 text-muted text-xs sm:text-sm font-mono">
              Tracking <span className="text-accent font-semibold">{(stats.total_predictions || 0).toLocaleString()}+</span> predictions
              {' '}from <span className="text-accent font-semibold">{(stats.forecasters_tracked || 0).toLocaleString()}+</span> analysts since 2024
            </div>
          )}

          {/* Mini leaderboard preview */}
          {top5.length >= 3 && (
            <div className="mt-8 max-w-md mx-auto">
              <div className="card p-0 overflow-hidden border-accent/10">
                {top5.slice(0, 3).map((f, i) => (
                  <div key={f.id} className="flex items-center gap-3 px-4 py-3 border-b border-border/50 last:border-b-0">
                    <span className="font-mono font-bold text-warning text-sm w-6">{['\uD83E\uDD47','\uD83E\uDD48','\uD83E\uDD49'][i]}</span>
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

      {/* ── 2. TRENDING TICKERS ────────────────────────────────────────── */}
      {trending.length > 0 && (
        <section className="border-y border-border py-8 sm:py-10">
          <div className="max-w-5xl mx-auto px-4 sm:px-6">
            <FadeIn>
              <h2 className="text-center font-semibold text-lg sm:text-xl mb-6">Trending Now</h2>
              <div className="flex gap-3 overflow-x-auto pills-scroll pb-2">
                {trending.map(t => {
                  const bullPct = t.bull_pct || 50;
                  return (
                    <Link key={t.ticker} to={`/asset/${t.ticker}`}
                      className="shrink-0 w-36 sm:w-40 card py-3 px-4 hover:border-accent/30 transition-colors">
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-mono font-bold text-accent text-sm">{t.ticker}</span>
                        <span className="text-muted text-[10px] font-mono">{t.total} calls</span>
                      </div>
                      {/* Bull/bear bar */}
                      <div className="flex h-1.5 rounded-full overflow-hidden bg-surface-2">
                        <div className="bg-positive rounded-l-full" style={{ width: `${bullPct}%` }} />
                        <div className="bg-negative rounded-r-full" style={{ width: `${100 - bullPct}%` }} />
                      </div>
                      <div className="flex justify-between text-[10px] mt-1">
                        <span className="text-positive font-mono">{bullPct}% bull</span>
                        <span className="text-negative font-mono">{100 - bullPct}% bear</span>
                      </div>
                    </Link>
                  );
                })}
              </div>
            </FadeIn>
          </div>
        </section>
      )}

      {/* ── 3. HOW SCORING WORKS ──────────────────────────────────────── */}
      <section className="max-w-4xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <FadeIn>
          <h2 className="font-bold text-center mb-3" style={{ fontSize: 'clamp(1.8rem, 4vw, 2.8rem)' }}>How Scoring Works</h2>
          <p className="text-text-secondary text-center mb-10">Four steps. Full transparency.</p>
        </FadeIn>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mb-8">
          {[
            { num: '01', icon: '\uD83D\uDCE1', title: 'We Collect Predictions', desc: 'Analyst upgrades, downgrades, and price targets are collected from verified financial sources with timestamps and archived proof.' },
            { num: '02', icon: '\u23F3', title: 'We Wait for the Deadline', desc: 'Each prediction has a clear evaluation window. Every prediction is tracked — not just the ones that worked out.' },
            { num: '03', icon: '\uD83D\uDCCA', title: 'We Check the Math', desc: 'When the window closes, we compare the prediction against actual market data. Right or wrong — no gray area.' },
            { num: '04', icon: '\uD83C\uDFC6', title: 'We Rank by Results', desc: 'Forecasters are ranked by verified accuracy, not followers or reputation.' },
          ].map((step, i) => (
            <FadeIn key={step.num} delay={i * 80}>
              <div className="card py-6">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-lg">{step.icon}</span>
                  <span className="text-[10px] text-accent font-mono font-bold tracking-widest">{step.num}</span>
                </div>
                <h3 className="font-semibold mb-1.5">{step.title}</h3>
                <p className="text-sm text-text-secondary leading-relaxed">{step.desc}</p>
              </div>
            </FadeIn>
          ))}
        </div>

        {/* Real example */}
        <FadeIn>
          <div className="card border-accent/20 py-5">
            <div className="text-[10px] text-accent font-mono font-bold tracking-widest mb-2">REAL EXAMPLE</div>
            <p className="text-sm text-text-primary leading-relaxed">
              Goldman Sachs said <span className="font-mono text-accent font-semibold">AAPL</span> would hit $250.
              It reached $237. Score: <span className="text-positive font-semibold">Correct (+14.7%)</span>
            </p>
            <p className="text-xs text-muted mt-2 italic">Before Eidolum: trust reputation. After Eidolum: trust data.</p>
          </div>
        </FadeIn>
      </section>

      {/* ── 4. TOP ANALYSTS THIS MONTH ─────────────────────────────────── */}
      {top5.length > 0 && (
        <section className="max-w-4xl mx-auto px-4 sm:px-6 py-12 sm:py-20">
          <FadeIn>
            <h2 className="headline-serif text-center mb-2" style={{ fontSize: 'clamp(1.8rem, 4vw, 2.8rem)' }}>
              Top Analysts Right Now
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
                    <th className="px-5 py-3 text-right hidden sm:table-cell">Avg Return</th>
                    <th className="px-5 py-3 text-right hidden sm:table-cell">Scored</th>
                  </tr>
                </thead>
                <tbody>
                  {top5.map(f => (
                    <tr key={f.id} className="border-b border-border/50 hover:bg-surface-2/30 transition-colors">
                      <td className="px-5 py-3.5">
                        <span className={`font-mono font-bold ${f.rank <= 3 ? 'text-warning' : 'text-text-secondary'}`}>
                          {f.rank <= 3 ? [null, '\uD83E\uDD47', '\uD83E\uDD48', '\uD83E\uDD49'][f.rank] : f.rank}
                        </span>
                      </td>
                      <td className="px-5 py-3.5">
                        <Link to={`/forecaster/${f.id}`} className="font-medium hover:text-accent transition-colors">{f.name}</Link>
                        {f.sector_strengths?.[0] && (
                          <span className="text-muted text-[10px] ml-1.5 font-mono">{f.sector_strengths[0].sector}</span>
                        )}
                      </td>
                      <td className="px-5 py-3.5 text-right">
                        <span className={`font-mono font-semibold ${(f.accuracy_rate || 0) >= 60 ? 'text-positive' : 'text-negative'}`}>
                          {(f.accuracy_rate || 0).toFixed(1)}%
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-right hidden sm:table-cell">
                        <span className={`font-mono text-sm ${(f.avg_return || 0) >= 0 ? 'text-positive' : 'text-negative'}`}>
                          {(f.avg_return || 0) >= 0 ? '+' : ''}{(f.avg_return || 0).toFixed(1)}%
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

      {/* ── 5. RECENT CALLS (live activity) ────────────────────────────── */}
      {recentCalls.length > 0 && (
        <section className="border-y border-border py-12 sm:py-16">
          <div className="max-w-4xl mx-auto px-4 sm:px-6">
            <FadeIn>
              <h2 className="font-semibold text-lg sm:text-xl mb-6 text-center">Recent Analyst Calls</h2>
              <div className="space-y-2">
                {recentCalls.map(p => (
                  <Link key={p.id} to={`/asset/${p.ticker}`}
                    className="flex items-center gap-3 card py-3 hover:border-accent/20 transition-colors">
                    <span className={`shrink-0 ${p.direction === 'bullish' ? 'text-positive' : 'text-negative'}`}>
                      {p.direction === 'bullish' ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                    </span>
                    <div className="flex-1 min-w-0 text-sm">
                      <span className="text-text-secondary">{p.forecaster?.name}</span>
                      <span className="text-muted"> — </span>
                      <span className={p.direction === 'bullish' ? 'text-positive font-medium' : 'text-negative font-medium'}>
                        {p.direction === 'bullish' ? 'Bullish' : 'Bearish'}
                      </span>
                      <span className="text-muted"> on </span>
                      <span className="font-mono text-accent font-semibold">{p.ticker}</span>
                      {p.target_price && <span className="text-muted">, target ${p.target_price.toFixed(0)}</span>}
                    </div>
                    <span className="text-muted text-xs font-mono shrink-0">{timeAgo(p.prediction_date)}</span>
                  </Link>
                ))}
              </div>
              <div className="text-center mt-4">
                <Link to="/expiring" className="text-accent text-sm font-medium inline-flex items-center gap-1">
                  See all predictions <ArrowRight className="w-3.5 h-3.5" />
                </Link>
              </div>
            </FadeIn>
          </div>
        </section>
      )}

      {/* ── 6. WHO IS EIDOLUM FOR? ─────────────────────────────────────── */}
      <section className="max-w-4xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <FadeIn>
          <h2 className="font-bold text-center mb-10" style={{ fontSize: 'clamp(1.6rem, 4vw, 2.4rem)' }}>Who Is Eidolum For?</h2>
        </FadeIn>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <FadeIn delay={0}>
            <div className="card py-6 text-center h-full">
              <div className="text-2xl mb-3">{'\uD83D\uDCB0'}</div>
              <h3 className="font-semibold mb-2">For Investors</h3>
              <p className="text-sm text-text-secondary leading-relaxed">Stop guessing which analyst to trust. See who's actually right before following their calls.</p>
            </div>
          </FadeIn>
          <FadeIn delay={100}>
            <div className="card py-6 text-center h-full">
              <div className="text-2xl mb-3">{'\uD83D\uDCCA'}</div>
              <h3 className="font-semibold mb-2">For Analysts</h3>
              <p className="text-sm text-text-secondary leading-relaxed">Prove your track record. Let your accuracy speak for itself — not your follower count.</p>
            </div>
          </FadeIn>
          <FadeIn delay={200}>
            <div className="card py-6 text-center h-full">
              <div className="text-2xl mb-3">{'\u26BD'}</div>
              <h3 className="font-semibold mb-2">For Everyone</h3>
              <p className="text-sm text-text-secondary leading-relaxed">Like sports stats, but for Wall Street. See who's winning, who's slumping, and who's on fire.</p>
            </div>
          </FadeIn>
        </div>
      </section>

      {/* ── 7. THE NUMBERS (social proof) ──────────────────────────────── */}
      {stats && (
        <section className="border-y border-border py-12 sm:py-16">
          <div className="max-w-4xl mx-auto px-4 sm:px-6">
            <FadeIn>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 text-center">
                <div>
                  <div className="font-mono text-2xl sm:text-3xl font-bold text-accent"><AnimatedNumber target={stats.total_predictions} suffix="+" /></div>
                  <div className="text-xs text-muted mt-1">Predictions Tracked</div>
                </div>
                <div>
                  <div className="font-mono text-2xl sm:text-3xl font-bold text-text-primary"><AnimatedNumber target={stats.forecasters_tracked} suffix="+" /></div>
                  <div className="text-xs text-muted mt-1">Analysts Monitored</div>
                </div>
                <div>
                  <div className="font-mono text-2xl sm:text-3xl font-bold text-positive">2+</div>
                  <div className="text-xs text-muted mt-1">Years of Data</div>
                </div>
                <div>
                  <div className="font-mono text-2xl sm:text-3xl font-bold text-warning">2h</div>
                  <div className="text-xs text-muted mt-1">Update Frequency</div>
                </div>
              </div>
            </FadeIn>
          </div>
        </section>
      )}

      {/* ── 8. FAQ ─────────────────────────────────────────────────────── */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 py-16 sm:py-24">
        <FadeIn>
          <h2 className="font-bold text-center mb-10" style={{ fontSize: 'clamp(1.6rem, 4vw, 2.4rem)' }}>Frequently Asked Questions</h2>
        </FadeIn>
        <div className="space-y-2">
          <FaqItem q="How do you define a prediction?" a="A prediction is a specific, measurable financial forecast — like 'TSLA will reach $300 by June 2026' or 'UBS downgrades NKE to Sell with a $50 target.' Vague commentary doesn't count. Every prediction needs a ticker, a direction, and a timeframe." />
          <FaqItem q="How do you score correctness?" a="When a prediction's timeframe expires, we compare it against actual market data. For price targets, did the stock hit the target? For directional calls, did it move the right way? It's binary — correct or incorrect." />
          <FaqItem q="Can users see the raw source?" a="Yes. Every scraped prediction links back to its original source with an archived proof link. You can verify every data point yourself." />
          <FaqItem q="How do you avoid cherry-picking?" a="We track ALL predictions from each forecaster, not just their wins. Every prediction is timestamped and archived the moment we find it." />
          <FaqItem q="Are you rating conviction or popularity?" a="Pure accuracy. We don't care how many followers an analyst has. The only thing that matters is: were they right?" />
        </div>
      </section>

      {/* ── 9. CTA — STOP GUESSING ────────────────────────────────────── */}
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

      {/* ── 10. FOOTER ────────────────────────────────────────────────── */}
      <footer className="border-t border-border py-8">
        <div className="max-w-4xl mx-auto px-4 sm:px-6">
          <div className="flex flex-col items-center gap-4 sm:flex-row sm:justify-between">
            <div className="flex items-center gap-2">
              <EidolumLogo size={20} />
              <span className="font-serif text-lg text-accent">Eidolum</span>
            </div>
            <div className="flex items-center gap-4 text-xs text-muted">
              <Link to="/leaderboard" className="hover:text-accent transition-colors">Leaderboard</Link>
              <Link to="/consensus" className="hover:text-accent transition-colors">Consensus</Link>
              <Link to="/compete" className="hover:text-accent transition-colors">Compete</Link>
              <a href="https://eidolum.com" className="hover:text-accent transition-colors">eidolum.com</a>
            </div>
            <div className="text-center sm:text-right">
              <p className="text-muted text-xs">Built by Nimrod</p>
              <p className="text-muted/50 text-[10px] mt-0.5 italic">Truth is the only currency that matters.</p>
            </div>
          </div>
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
