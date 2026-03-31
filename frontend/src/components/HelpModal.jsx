import { useState, useRef } from 'react';
import {
  X, Crosshair, Check, Trophy, ChevronLeft, ChevronRight,
  BarChart3, Users, TrendingUp, Swords, Calendar, Flame,
  Award, Star, Share2, Eye, ThumbsUp, LayoutGrid,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import useLockBodyScroll from '../hooks/useLockBodyScroll';

// ── How It Works carousel cards ──────────────────────────────────────────────

const HOW_CARDS = [
  { icon: <Crosshair className="w-10 h-10 text-accent" />, title: 'Make a Call', desc: 'Pick a stock, choose bullish or bearish, set your price target and timeframe.' },
  { icon: <Check className="w-10 h-10 text-positive" />, title: 'Get Scored', desc: 'When your timeframe expires, we compare your prediction to real market data. No faking it.' },
  { icon: <Trophy className="w-10 h-10 text-warning" />, title: 'Climb the Ranks', desc: 'Earn badges, build streaks, compete on the leaderboard. Your accuracy is your reputation.' },
];

// ── Feature sections ────────────────────────────────────────────────────────

const SECTIONS = [
  {
    title: 'Core Features',
    items: [
      { icon: TrendingUp, label: 'Analyst Tracker', desc: 'See which Wall Street analysts are actually right, with verified accuracy scores.', link: '/analysts' },
      { icon: BarChart3, label: 'Leaderboard', desc: 'Top 100 forecasters ranked by real accuracy. Minimum 10 scored predictions.', link: '/leaderboard' },
      { icon: Users, label: 'Consensus Meter', desc: 'See what the crowd thinks about any stock. Bull/bear split across all active predictions.', link: '/consensus' },
      { icon: Crosshair, label: 'Submit a Call', desc: 'Make your own prediction and prove yourself. Locked and timestamped.', link: '/submit' },
    ],
  },
  {
    title: 'Competition',
    items: [
      { icon: Calendar, label: 'Daily Challenge', desc: 'One stock, one call, results at market close. Separate streak and leaderboard.', link: '/daily-challenge' },
      { icon: Swords, label: 'Duels', desc: 'Challenge another player on the same stock, opposite sides. Closer to reality wins.', link: '/duels' },
      { icon: Trophy, label: 'Seasons', desc: 'Quarterly competition with fresh leaderboards. Top 5 earn permanent season badges.', link: '/compete' },
      { icon: Flame, label: 'Streaks', desc: 'Track your consecutive correct predictions and daily visit streaks.', link: '/profile' },
    ],
  },
  {
    title: 'Progression',
    items: [
      { icon: Star, label: 'Levels & XP', desc: 'Earn XP from every action. Progress through 10 levels from Newcomer to Eidolon.', link: '/profile' },
      { icon: Award, label: 'Badges & Achievements', desc: '49 badges across 7 categories: Accuracy, Streaks, Volume, Timing, and more.', link: '/badges' },
      { icon: Share2, label: 'Sharing', desc: 'Share your wins on X with timestamped proof. Use the "I Told You So" button.', link: null },
    ],
  },
  {
    title: 'Tools',
    items: [
      { icon: Eye, label: 'Watchlist', desc: 'Track your favorite tickers. See all predictions on watched stocks in one feed.', link: '/watchlist' },
      { icon: ThumbsUp, label: 'Prediction Reactions', desc: 'React to predictions: Agree, Disagree, Bold Call, or No Way.', link: null },
      { icon: LayoutGrid, label: 'Heatmap', desc: 'Sector sentiment at a glance. See where the crowd is bullish or bearish.', link: '/heatmap' },
    ],
  },
];

const SCORING_RULES = [
  'Bullish predictions are correct if the price is higher than your entry when the timeframe expires.',
  'Bearish predictions are correct if the price is lower than your entry when the timeframe expires.',
  'Predictions are scored automatically. No manual judging.',
  'You cannot edit or delete predictions after 5 minutes.',
];

// ── Component ────────────────────────────────────────────────────────────────

export default function HelpModal({ onClose }) {
  useLockBodyScroll();
  const navigate = useNavigate();
  const [carouselIdx, setCarouselIdx] = useState(0);
  const touchStartX = useRef(0);

  function goTo(link) {
    if (link) {
      onClose();
      navigate(link);
    }
  }

  return (
    <div className="fixed inset-0 z-[85] bg-bg/90 backdrop-blur-sm flex items-start justify-center overflow-y-auto" onClick={onClose}>
      <div className="w-full max-w-2xl mx-4 my-8 bg-surface border border-border rounded-xl overflow-hidden" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border sticky top-0 bg-surface z-10">
          <h2 className="font-bold text-lg">How Eidolum Works</h2>
          <button onClick={onClose} className="text-muted hover:text-text-primary"><X className="w-5 h-5" /></button>
        </div>

        <div className="px-5 py-6 space-y-8">
          {/* ── Section 1: How It Works Carousel ───────────────────────── */}
          <div>
            <div className="relative">
              {carouselIdx > 0 && (
                <button onClick={() => setCarouselIdx(i => Math.max(i - 1, 0))}
                  className="absolute left-0 top-1/2 -translate-y-1/2 z-10 w-9 h-9 rounded-full bg-surface-2 border border-border flex items-center justify-center text-text-secondary hover:text-text-primary -ml-2 shadow-lg">
                  <ChevronLeft className="w-5 h-5" />
                </button>
              )}
              {carouselIdx < HOW_CARDS.length - 1 && (
                <button onClick={() => setCarouselIdx(i => Math.min(i + 1, HOW_CARDS.length - 1))}
                  className="absolute right-0 top-1/2 -translate-y-1/2 z-10 w-9 h-9 rounded-full bg-surface-2 border border-border flex items-center justify-center text-text-secondary hover:text-text-primary -mr-2 shadow-lg">
                  <ChevronRight className="w-5 h-5" />
                </button>
              )}

              <div className="overflow-hidden rounded-xl"
                onTouchStart={e => { touchStartX.current = e.touches[0].clientX; }}
                onTouchEnd={e => {
                  const diff = touchStartX.current - e.changedTouches[0].clientX;
                  if (diff > 50) setCarouselIdx(i => Math.min(i + 1, HOW_CARDS.length - 1));
                  else if (diff < -50) setCarouselIdx(i => Math.max(i - 1, 0));
                }}>
                <div className="flex" style={{ transform: `translateX(-${carouselIdx * 100}%)`, transition: 'transform 0.3s ease' }}>
                  {HOW_CARDS.map((card, i) => (
                    <div key={i} className="flex-shrink-0 w-full px-4">
                      <div className="card text-center py-8">
                        <div className="flex justify-center mb-4">{card.icon}</div>
                        <h3 className="font-semibold text-base mb-2">{card.title}</h3>
                        <p className="text-sm text-text-secondary leading-relaxed max-w-xs mx-auto">{card.desc}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-center gap-2 mt-4">
                {HOW_CARDS.map((_, i) => (
                  <button key={i} onClick={() => setCarouselIdx(i)}
                    className={`w-2.5 h-2.5 rounded-full transition-all ${i === carouselIdx ? 'bg-accent scale-110' : 'bg-surface-2 hover:bg-muted/30'}`} />
                ))}
              </div>
            </div>
          </div>

          {/* ── Sections 2-5: Feature cards ─────────────────────────────── */}
          {SECTIONS.map((section) => (
            <div key={section.title}>
              <h3 className="text-xs text-muted uppercase tracking-wider font-bold mb-3">{section.title}</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {section.items.map((item) => {
                  const Icon = item.icon;
                  const isClickable = !!item.link;
                  return (
                    <button
                      key={item.label}
                      onClick={() => goTo(item.link)}
                      disabled={!isClickable}
                      className={`text-left card py-3 px-4 flex items-start gap-3 transition-colors ${
                        isClickable ? 'hover:border-accent/30 cursor-pointer' : 'cursor-default'
                      }`}
                    >
                      <Icon className="w-5 h-5 text-accent flex-shrink-0 mt-0.5" />
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-text-primary">{item.label}</div>
                        <div className="text-xs text-text-secondary leading-relaxed mt-0.5">{item.desc}</div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}

          {/* ── Section 6: Scoring Rules ────────────────────────────────── */}
          <div>
            <h3 className="text-xs text-muted uppercase tracking-wider font-bold mb-3">Scoring Rules</h3>
            <div className="card space-y-2">
              {SCORING_RULES.map((rule, i) => (
                <div key={i} className="flex items-start gap-2 text-xs text-text-secondary">
                  <Check className="w-3 h-3 text-accent mt-0.5 flex-shrink-0" />
                  <span>{rule}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
