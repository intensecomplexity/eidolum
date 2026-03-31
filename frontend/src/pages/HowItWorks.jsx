import { Link } from 'react-router-dom';
import { Check, Crosshair, BarChart3, Trophy, Users, Clock, TrendingUp, TrendingDown } from 'lucide-react';
import Footer from '../components/Footer';

export default function HowItWorks() {
  return (
    <div>
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-10 sm:py-16">

        {/* ── 1. What is Eidolum? ──────────────────────────────────── */}
        <section className="mb-12">
          <h1 className="font-bold text-2xl sm:text-3xl mb-4">What is Eidolum?</h1>
          <p className="text-text-secondary text-base leading-relaxed">
            Eidolum tracks analyst predictions and scores them against real market data. When a Wall Street analyst says a stock will hit $200, we check if it actually did. Every prediction is timestamped, every score is verified.
          </p>
        </section>

        {/* ── 2. How Scoring Works ─────────────────────────────────── */}
        <section className="mb-12">
          <h2 className="font-bold text-xl sm:text-2xl mb-4">How Scoring Works</h2>
          <p className="text-text-secondary text-sm mb-6">Every prediction gets one of three scores:</p>

          <div className="grid gap-4 sm:grid-cols-3 mb-8">
            <div className="card py-5 text-center">
              <div className="w-12 h-12 rounded-full mx-auto mb-3 flex items-center justify-center text-sm font-bold" style={{ backgroundColor: '#34d399', color: '#000' }}>HIT</div>
              <h3 className="font-semibold mb-1">Hit</h3>
              <p className="text-xs text-text-secondary">Target reached within tolerance. The analyst nailed it.</p>
            </div>
            <div className="card py-5 text-center">
              <div className="w-12 h-12 rounded-full mx-auto mb-3 flex items-center justify-center text-sm font-bold" style={{ backgroundColor: '#fbbf24', color: '#000' }}>NEAR</div>
              <h3 className="font-semibold mb-1">Near</h3>
              <p className="text-xs text-text-secondary">Right direction, meaningful movement, but missed the target.</p>
            </div>
            <div className="card py-5 text-center">
              <div className="w-12 h-12 rounded-full mx-auto mb-3 flex items-center justify-center text-sm font-bold" style={{ backgroundColor: '#f87171', color: '#fff' }}>MISS</div>
              <h3 className="font-semibold mb-1">Miss</h3>
              <p className="text-xs text-text-secondary">Wrong direction or barely moved. The analyst got it wrong.</p>
            </div>
          </div>

          <div className="card">
            <div className="text-[10px] text-accent font-mono font-bold tracking-widest mb-2">REAL EXAMPLE</div>
            <p className="text-sm text-text-primary leading-relaxed">
              Goldman Sachs said <span className="font-mono text-accent font-semibold">AAPL</span> would hit $195.
              It reached $198. Score: <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-mono font-bold" style={{ backgroundColor: '#34d399', color: '#000' }}>HIT</span>
            </p>
          </div>
        </section>

        {/* ── 3. Tolerance by Timeframe ────────────────────────────── */}
        <section className="mb-12">
          <h2 className="font-bold text-xl sm:text-2xl mb-4">Tolerance by Timeframe</h2>
          <p className="text-text-secondary text-sm mb-4">Longer predictions get more room. A 1-year call doesn't need to be as precise as a 1-day call.</p>
          <div className="card overflow-hidden p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted text-xs uppercase tracking-wider border-b border-border">
                  <th className="px-4 py-3">Timeframe</th>
                  <th className="px-4 py-3 text-right">HIT tolerance</th>
                  <th className="px-4 py-3 text-right">NEAR minimum</th>
                </tr>
              </thead>
              <tbody className="font-mono text-text-secondary">
                {[
                  ['1 day', '2%', '0.5%'], ['1 week', '3%', '1%'], ['2 weeks', '4%', '1.5%'],
                  ['1 month', '5%', '2%'], ['3 months', '5%', '2%'], ['6 months', '7%', '3%'],
                  ['1 year', '10%', '4%'],
                ].map(([tf, tol, min]) => (
                  <tr key={tf} className="border-b border-border/50 last:border-0">
                    <td className="px-4 py-2.5 text-text-primary">{tf}</td>
                    <td className="px-4 py-2.5 text-right text-positive">{tol}</td>
                    <td className="px-4 py-2.5 text-right text-warning">{min}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* ── 4. What is a Prediction? ─────────────────────────────── */}
        <section className="mb-12">
          <h2 className="font-bold text-xl sm:text-2xl mb-4">What Counts as a Prediction?</h2>
          <div className="space-y-2">
            {[
              { icon: TrendingUp, text: 'A specific ticker (AAPL, TSLA, BTC, etc.)' },
              { icon: Crosshair, text: 'A direction: bullish (going up), bearish (going down), or hold' },
              { icon: Clock, text: 'A timeframe: when will the target be reached' },
              { icon: BarChart3, text: 'Optional: a price target ($250, $50, etc.)' },
            ].map(({ icon: Icon, text }) => (
              <div key={text} className="flex items-center gap-3 card py-3">
                <Icon className="w-4 h-4 text-accent shrink-0" />
                <span className="text-sm text-text-secondary">{text}</span>
              </div>
            ))}
          </div>
        </section>

        {/* ── 5. Analysts vs Players ───────────────────────────────── */}
        <section className="mb-12">
          <h2 className="font-bold text-xl sm:text-2xl mb-4">Analysts vs Players</h2>
          <div className="grid sm:grid-cols-2 gap-4">
            <div className="card py-5">
              <h3 className="font-semibold mb-2 flex items-center gap-2"><Trophy className="w-4 h-4 text-accent" /> Analysts</h3>
              <p className="text-sm text-text-secondary leading-relaxed">Auto-tracked from published reports. Goldman Sachs, UBS, Morgan Stanley — their predictions are collected and scored automatically.</p>
            </div>
            <div className="card py-5">
              <h3 className="font-semibold mb-2 flex items-center gap-2"><Users className="w-4 h-4 text-accent" /> Players</h3>
              <p className="text-sm text-text-secondary leading-relaxed">That's you. Sign up, submit your own predictions, and compete on the same leaderboard. Prove your accuracy against Wall Street.</p>
            </div>
          </div>
        </section>

        {/* ── 6. Get Started ───────────────────────────────────────── */}
        <section className="mb-8">
          <h2 className="font-bold text-xl sm:text-2xl mb-4">How to Get Started</h2>
          <div className="space-y-3">
            {[
              { step: '01', title: 'Browse', desc: 'Explore the leaderboard, check analyst accuracy, see the consensus on any stock.' },
              { step: '02', title: 'Sign Up', desc: 'Create a free account in 30 seconds. Google sign-in available.' },
              { step: '03', title: 'Predict', desc: 'Submit your first call. Pick a stock, set a direction, choose a timeframe. We handle the rest.' },
            ].map(({ step, title, desc }) => (
              <div key={step} className="card py-4 flex items-start gap-4">
                <span className="text-accent font-mono text-xs font-bold mt-0.5">{step}</span>
                <div>
                  <h3 className="font-semibold text-sm">{title}</h3>
                  <p className="text-xs text-text-secondary mt-0.5">{desc}</p>
                </div>
              </div>
            ))}
          </div>
          <div className="flex gap-3 mt-6 justify-center">
            <Link to="/register" className="btn-primary px-8">Sign Up Free</Link>
            <Link to="/leaderboard" className="btn-secondary px-8">See the Leaderboard</Link>
          </div>
        </section>
      </div>
      <Footer />
    </div>
  );
}
