import { useState, useRef, useEffect } from 'react';
import { X, Crosshair, Check, Trophy, ChevronLeft, ChevronRight, ChevronDown } from 'lucide-react';

// ── How It Works carousel cards ──────────────────────────────────────────────

const HOW_CARDS = [
  { icon: <Crosshair className="w-10 h-10 text-accent" />, title: 'Make a Call', desc: 'Pick a stock, choose bullish or bearish, set your price target and timeframe.' },
  { icon: <Check className="w-10 h-10 text-positive" />, title: 'Get Scored', desc: 'When your timeframe expires, we compare your prediction to the real market price. No faking it.' },
  { icon: <Trophy className="w-10 h-10 text-warning" />, title: 'Climb the Ranks', desc: 'Earn badges, build streaks, compete on the leaderboard. Your accuracy is your reputation.' },
];

// ── Features guide accordion items ───────────────────────────────────────────

const FEATURES = [
  { title: 'Submit a Call', body: 'Pick any stock or crypto, choose bullish or bearish, set your price target and evaluation window. Your prediction gets locked and timestamped — no edits, no deletes after 5 minutes.' },
  { title: 'Leaderboard', body: 'All forecasters ranked by prediction accuracy. Minimum 10 scored predictions to appear. See who\'s actually right, not just who\'s loudest.' },
  { title: 'Badges & Achievements', body: 'Earn badges across 7 categories: Accuracy, Streaks, Volume, Timing, Sectors, Conviction, and Prestige. Track your progress and collect them all.' },
  { title: 'Daily Challenge', body: 'Every trading day, one stock is picked. Everyone calls bullish or bearish. Results at market close. Separate daily challenge streak and leaderboard.' },
  { title: 'Duels', body: 'Challenge another player on the same stock. You pick opposite directions. Winner is whoever\'s prediction was closer to reality.' },
  { title: 'Seasons', body: 'Quarterly competitive seasons with themed names. Fresh leaderboard each quarter. Top 5 earn a permanent season badge on their profile.' },
  { title: 'Consensus Meter', body: 'See what the community thinks about any ticker. Bull/bear percentage across all active predictions.' },
  { title: 'Watchlist', body: 'Save tickers you care about. See all predictions on your watched stocks in one feed. Get notified when someone makes a new call.' },
  { title: 'Prediction Reactions', body: 'React to other people\'s predictions: Agree, Disagree, Bold Call, or No Way. See if the crowd was right after scoring.' },
  { title: 'Analyst Tracker', body: 'Every Wall Street analyst tracked with a verified accuracy score. See how Goldman Sachs, Morgan Stanley, and others actually perform.' },
  { title: 'Levels & XP', body: 'Earn XP from predictions, challenges, duels, and social actions. Progress through 10 levels from Newcomer to Eidolon, unlocking perks along the way.' },
  { title: 'Streaks', body: 'Two types: Prediction Streak (consecutive correct calls) and Return Streak (consecutive days visiting Eidolum). Both tracked on your profile.' },
  { title: 'Templates', body: 'Structured prediction types: Earnings Play, Momentum Trade, Macro Thesis, Technical Breakout, Contrarian Bet, Sector Rotation. Each has suggested timeframes.' },
  { title: 'Sharing', body: 'Share any prediction on Twitter/X with timestamped proof. When you\'re right, use the \'I Told You So\' button for maximum bragging rights.' },
  { title: 'Heatmap', body: 'Visual overview of community sentiment across all sectors and tickers. See where the crowd is most bullish, bearish, or divided.' },
];

const SCORING_RULES = [
  'Bullish predictions are correct if the price is higher than your entry when the timeframe expires.',
  'Bearish predictions are correct if the price is lower than your entry when the timeframe expires.',
  'Predictions are scored automatically — no manual judging.',
  'You cannot edit or delete predictions after 5 minutes.',
];

// ── Component ────────────────────────────────────────────────────────────────

export default function HelpModal({ onClose }) {
  const [carouselIdx, setCarouselIdx] = useState(0);
  const [openAccordion, setOpenAccordion] = useState(null);
  const touchStartX = useRef(0);

  return (
    <div className="fixed inset-0 z-[85] bg-bg/90 backdrop-blur-sm flex items-start justify-center overflow-y-auto" onClick={onClose}>
      <div className="w-full max-w-2xl mx-4 my-8 bg-surface border border-border rounded-xl overflow-hidden" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border sticky top-0 bg-surface z-10">
          <h2 className="font-bold text-lg">How Eidolum Works</h2>
          <button onClick={onClose} className="text-muted hover:text-text-primary"><X className="w-5 h-5" /></button>
        </div>

        <div className="px-5 py-6 space-y-8">
          {/* ── Section 1: Carousel ──────────────────────────────────── */}
          <div>
            <div className="relative">
              {/* Arrow buttons */}
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

              {/* Sliding container */}
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

              {/* Dot indicators */}
              <div className="flex items-center justify-center gap-2 mt-4">
                {HOW_CARDS.map((_, i) => (
                  <button key={i} onClick={() => setCarouselIdx(i)}
                    className={`w-2.5 h-2.5 rounded-full transition-all ${i === carouselIdx ? 'bg-accent scale-110' : 'bg-surface-2 hover:bg-muted/30'}`} />
                ))}
              </div>
            </div>
          </div>

          {/* ── Section 2: Features Guide ────────────────────────────── */}
          <div>
            <h3 className="text-xs text-muted uppercase tracking-wider font-bold mb-3">Features Guide</h3>
            <div className="space-y-1">
              {FEATURES.map((f, i) => (
                <div key={i} className="border border-border rounded-lg overflow-hidden">
                  <button onClick={() => setOpenAccordion(openAccordion === i ? null : i)}
                    className="w-full flex items-center justify-between px-4 py-3 text-left text-sm font-medium hover:bg-surface-2 transition-colors min-h-[44px]">
                    {f.title}
                    <ChevronDown className={`w-4 h-4 text-muted transition-transform ${openAccordion === i ? 'rotate-180' : ''}`} />
                  </button>
                  {openAccordion === i && (
                    <div className="px-4 pb-3 text-xs text-text-secondary leading-relaxed border-t border-border pt-2">
                      {f.body}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* ── Section 3: Scoring Rules ─────────────────────────────── */}
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
