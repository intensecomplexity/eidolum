import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Search, BarChart3, CheckCircle } from 'lucide-react';
import TickerBar from '../components/TickerBar';
import StatCard from '../components/StatCard';
import ActivityFeed from '../components/ActivityFeed';
import Footer from '../components/Footer';
import RareSignalBanner from '../components/RareSignalBanner';
import NewsletterSignup from '../components/NewsletterSignup';
import { getLeaderboard, getHomepageStats } from '../api';

export default function Landing() {
  const [forecasters, setForecasters] = useState([]);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    getLeaderboard().then(setForecasters).catch(() => {});
    getHomepageStats().then(setStats).catch(() => {});
  }, []);

  return (
    <div>
      {/* 1. TICKER TAPE */}
      <TickerBar forecasters={forecasters} />

      {/* 2. HERO */}
      <div style={{
        textAlign: 'center',
        padding: '56px 24px 40px',
        maxWidth: '680px',
        margin: '0 auto',
      }}>
        <h1 style={{
          fontFamily: "'Instrument Serif', serif",
          fontWeight: 400,
          fontSize: 'clamp(2rem, 5vw, 3.6rem)',
          letterSpacing: '-0.02em',
          lineHeight: 1.15,
          color: '#ffffff',
          margin: '0 0 14px',
        }}>
          Who should you actually listen to?
        </h1>
        <p style={{
          fontSize: '1rem',
          color: '#7a8a7a',
          lineHeight: 1.7,
          fontWeight: 400,
          margin: 0,
        }}>
          We verify predictions from 50+ finance influencers against real market data.
          No hype, no guesswork — just accountability.
        </p>
      </div>

      {/* 3. LIVE ACTIVITY — prominent hero content */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 pb-12 sm:pb-16">
        <div className="flex items-center gap-2 mb-4">
          <span style={{
            width: 8, height: 8, borderRadius: '50%',
            background: '#22c55e',
            display: 'inline-block',
            animation: 'pulse 2s ease-in-out infinite',
          }} />
          <span style={{ fontSize: '0.8rem', color: '#6b7280', fontWeight: 500, letterSpacing: '0.04em' }}>
            Live
          </span>
        </div>
        <ActivityFeed />
      </section>

      {/* 4. RARE SIGNAL */}
      <section className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 pb-10 sm:pb-16">
        <RareSignalBanner />
      </section>

      {/* 5. HOW IT WORKS */}
      <section id="how-it-works" style={{ padding: '72px 24px', maxWidth: '900px', margin: '0 auto' }}>
        <h2 style={{ textAlign: 'center', fontFamily: "'Instrument Serif', serif", fontWeight: 400, fontSize: 'clamp(1.8rem, 4vw, 2.8rem)', marginBottom: '12px' }}>
          How It Works
        </h2>
        <p style={{ textAlign: 'center', color: '#7a8a7a', marginBottom: '48px' }}>
          Three simple steps to separate signal from noise.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '32px' }}>
          {[
            { num: '01', icon: Search, title: 'Collect', desc: 'We pull predictions from 50+ tracked YouTube channels, Reddit posts, and X accounts.' },
            { num: '02', icon: BarChart3, title: 'Parse', desc: 'NLP and keyword matching extract structured predictions: ticker, direction, and price targets.' },
            { num: '03', icon: CheckCircle, title: 'Verify', desc: 'After 30/60/90 days we compare predictions to actual market data and score each forecaster.' },
          ].map(step => (
            <div key={step.num} style={{ padding: '28px', background: '#0e1212', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '12px' }}>
              <div style={{ fontSize: '0.75rem', color: '#00a878', fontWeight: 700, letterSpacing: '0.1em', marginBottom: '12px' }}>{step.num}</div>
              <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '10px' }}>{step.title}</h3>
              <p style={{ color: '#7a8a7a', fontSize: '0.9rem', lineHeight: 1.6, margin: 0 }}>{step.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* 6. STATS */}
      <section className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12">
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 sm:gap-4">
          <StatCard
            label="Tracked Forecasters"
            value={stats ? stats.forecasters_tracked : '—'}
            sub="YouTube, Reddit, X"
          />
          <StatCard
            label="Verified Predictions"
            value={stats ? stats.verified_predictions.toLocaleString() : '—'}
            sub="Scored against market data"
          />
          <StatCard
            label="Months of Data"
            value={stats ? stats.months_of_data : '—'}
            sub="Historical tracking"
          />
          <StatCard
            label="Avg Accuracy"
            value={stats ? `${stats.avg_accuracy}%` : '—'}
            sub="Across all forecasters"
          />
          <StatCard
            label="Conflict Flags"
            value={stats ? stats.conflict_flags?.toLocaleString() || '0' : '—'}
            sub={`Across ${stats?.transparency_tracked || 0} investors`}
          />
        </div>
      </section>

      {/* 7. NEWSLETTER */}
      <section style={{ padding: '72px 24px', textAlign: 'center', borderTop: '1px solid rgba(255,255,255,0.07)' }}>
        <h2 style={{ fontFamily: "'Instrument Serif', serif", fontWeight: 400, fontSize: 'clamp(1.6rem, 3vw, 2.4rem)', marginBottom: '12px' }}>
          Stay ahead of the market
        </h2>
        <p style={{ color: '#7a8a7a', marginBottom: '24px' }}>
          Get the daily predictions digest — who called what, and whether they were right.
        </p>
        <div className="max-w-md mx-auto">
          <NewsletterSignup />
        </div>
      </section>

      <Footer />
    </div>
  );
}
