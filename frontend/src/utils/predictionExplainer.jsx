/**
 * Translates analyst jargon into plain English and adds glossary tooltips.
 * Used by PredictionCard, EvidenceCard, and PredictionRow.
 */
import React from 'react';
import { Link } from 'react-router-dom';

// ── Glossary: analyst terms → plain-English tooltips ────────────────────────
const GLOSSARY = [
  { pattern: /\bunderweight\b/gi, label: 'Underweight', tip: 'Means the analyst thinks this stock will underperform. Similar to a Sell rating.' },
  { pattern: /\boverweight\b/gi, label: 'Overweight', tip: 'Means the analyst thinks this stock will outperform. Similar to a Buy rating.' },
  { pattern: /\boutperform\b/gi, label: 'Outperform', tip: 'The analyst expects this stock to beat the market.' },
  { pattern: /\bunderperform\b/gi, label: 'Underperform', tip: 'The analyst expects this stock to lag behind the market. Similar to Sell.' },
  { pattern: /\bequal[\s-]?weight\b/gi, label: 'Equal-Weight', tip: 'The analyst thinks the stock will perform in line with the market. Similar to Hold.' },
  { pattern: /\bmarket[\s-]?perform\b/gi, label: 'Market Perform', tip: 'Expected to match overall market returns. Similar to Hold.' },
  { pattern: /\bsector[\s-]?perform\b/gi, label: 'Sector Perform', tip: 'Expected to match its sector average. Similar to Hold.' },
  { pattern: /\bstrong buy\b/gi, label: 'Strong Buy', tip: 'The analyst is very bullish and expects the stock to significantly beat the market.' },
  { pattern: /\bstrong sell\b/gi, label: 'Strong Sell', tip: 'The analyst is very bearish and expects the stock to significantly underperform.' },
  { pattern: /\binitiates?[\s_]coverage[\s_]?on\b/gi, label: 'Initiates Coverage', tip: 'The analyst is covering this stock for the first time.' },
  { pattern: /\binitiates?[\s_]coverage\b/gi, label: 'Initiates Coverage', tip: 'The analyst is covering this stock for the first time.' },
  { pattern: /\bstarted coverage\b/gi, label: 'Started Coverage', tip: 'The analyst is covering this stock for the first time.' },
  { pattern: /\bmaintains\b/gi, label: 'Maintains', tip: 'The analyst is keeping their previous rating unchanged.' },
  { pattern: /\breiterates?\b/gi, label: 'Reiterates', tip: 'The analyst is reaffirming their existing rating. Nothing changed.' },
  { pattern: /\breaffirms?\b/gi, label: 'Reaffirms', tip: 'The analyst is reaffirming their existing rating. Nothing changed.' },
  { pattern: /\bdowngrades?\b/gi, label: 'Downgrades', tip: 'The analyst lowered their rating. They became more negative.' },
  { pattern: /\bupgrades?\b/gi, label: 'Upgrades', tip: 'The analyst raised their rating. They became more positive.' },
  { pattern: /\bPT\b/g, label: 'PT', tip: 'Price Target: the price the analyst thinks the stock will reach.' },
  { pattern: /\bprice target\b/gi, label: 'Price Target', tip: 'The price the analyst thinks the stock will reach.' },
  { pattern: /\btarget:\s?\$/gi, label: 'Target: $', tip: 'The price the analyst thinks the stock will reach.' },
];

/**
 * Wrap glossary terms in the text with tooltip spans.
 * Returns an array of React elements.
 */
export function annotateContext(text, ticker = null) {
  if (!text) return null;

  // Find all glossary matches with their positions
  const matches = [];
  for (const entry of GLOSSARY) {
    let m;
    const regex = new RegExp(entry.pattern.source, entry.pattern.flags);
    while ((m = regex.exec(text)) !== null) {
      const overlaps = matches.some(
        (existing) => m.index < existing.end && m.index + m[0].length > existing.start
      );
      if (!overlaps) {
        matches.push({ start: m.index, end: m.index + m[0].length, original: m[0], type: 'glossary', tip: entry.tip });
      }
    }
  }

  // Also match the ticker symbol as a link
  if (ticker) {
    const tickerRegex = new RegExp(`\\b${ticker}\\b`, 'g');
    let m;
    while ((m = tickerRegex.exec(text)) !== null) {
      const overlaps = matches.some(
        (existing) => m.index < existing.end && m.index + m[0].length > existing.start
      );
      if (!overlaps) {
        matches.push({ start: m.index, end: m.index + m[0].length, original: m[0], type: 'ticker' });
      }
    }
  }

  if (matches.length === 0) return text;

  matches.sort((a, b) => a.start - b.start);

  const parts = [];
  let cursor = 0;
  for (const match of matches) {
    if (match.start > cursor) {
      parts.push(text.slice(cursor, match.start));
    }
    if (match.type === 'ticker') {
      parts.push(
        <Link key={`t${match.start}`} to={`/ticker/${match.original}`}
          className="font-semibold hover:underline" style={{ color: '#D4A843' }}>
          {match.original}
        </Link>
      );
    } else {
      parts.push(
        <span key={match.start} className="glossary-term" data-tip={match.tip}>
          {match.original}
        </span>
      );
    }
    cursor = match.end;
  }
  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }

  return parts;
}

/**
 * Generate a simple one-line explanation of what the prediction means.
 * Handles the nuance of rating action vs price target direction.
 */
export function simpleExplainer(prediction) {
  const p = prediction;
  const ticker = p.ticker || '';
  const entry = p.entry_price;
  const target = p.target_price;
  const context = (p.exact_quote || p.context || '').toLowerCase();
  const callType = (p.call_type || '').toLowerCase();

  const isUpgrade = callType === 'upgrade' || /upgrade/i.test(context);
  const isDowngrade = callType === 'downgrade' || /downgrade/i.test(context);
  const isInitiate = callType === 'new_coverage' || /initiat|started coverage/i.test(context);
  const isMaintain = /maintain|reiterat|reaffirm/i.test(context);

  // Extract rating from context (e.g. "downgrades neutral" → "Neutral")
  const ratingMatch = context.match(/(?:to|with)\s+(buy|sell|hold|neutral|outperform|underperform|overweight|underweight|equal[\s-]?weight|market[\s-]?perform|strong buy|strong sell)/i);
  const rating = ratingMatch ? ratingMatch[1].replace(/[\s-]+/g, ' ').trim() : '';
  const ratingCap = rating ? rating.charAt(0).toUpperCase() + rating.slice(1) : '';

  if (target && entry && entry > 0) {
    const pctChange = ((target - entry) / entry * 100).toFixed(1);
    const sign = target >= entry ? '+' : '';
    const priceInfo = `Target $${target.toFixed(0)} (currently $${entry.toFixed(0)}, ${sign}${pctChange}%)`;
    const targetAbove = target > entry;

    // CASE 1: Downgrade but target ABOVE current (less optimistic, still sees upside)
    if (isDowngrade && targetAbove) {
      return `In simple terms: Less optimistic on ${ticker}, but still sees upside. ${ratingCap ? `Lowered rating to ${ratingCap}. ` : ''}${priceInfo}`;
    }
    // CASE 2: Upgrade but target BELOW current (more positive, but target still below)
    if (isUpgrade && !targetAbove) {
      return `In simple terms: More positive on ${ticker}, but target is still below current price. ${ratingCap ? `Raised rating to ${ratingCap}. ` : ''}${priceInfo}`;
    }
    // CASE 3: Downgrade and target BELOW current (straightforward bearish)
    if (isDowngrade && !targetAbove) {
      return `In simple terms: Bearish on ${ticker}. Downgraded and expects a drop. ${priceInfo}`;
    }
    // CASE 4: Upgrade and target ABOVE current (straightforward bullish)
    if (isUpgrade && targetAbove) {
      return `In simple terms: Bullish on ${ticker}. Upgraded and expects a rise. ${priceInfo}`;
    }
    // CASE 5: Maintains with target
    if (isMaintain) {
      return `In simple terms: Still ${targetAbove ? 'positive' : 'cautious'} on ${ticker}. Maintains rating. ${priceInfo}`;
    }
    // CASE 6: Initiates coverage
    if (isInitiate) {
      return `In simple terms: Started covering ${ticker}${ratingCap ? ` with a ${ratingCap} rating` : ''}. ${priceInfo}`;
    }
    // Default with target
    return `In simple terms: ${targetAbove ? 'Sees upside' : 'Sees downside'} on ${ticker}. ${priceInfo}`;
  }

  // No price target — directional only
  const direction = (p.direction || '').toLowerCase();
  if (direction === 'bullish') {
    if (isUpgrade) return `In simple terms: Turned more positive on ${ticker}, expects it to go up`;
    if (isInitiate) return `In simple terms: Started tracking ${ticker} with a positive outlook`;
    if (isMaintain) return `In simple terms: Still positive on ${ticker}, expects it to go up`;
    return `In simple terms: Positive on ${ticker}, expects it to go up`;
  }
  if (direction === 'bearish') {
    if (isDowngrade) return `In simple terms: Turned more negative on ${ticker}, expects it to go down`;
    if (isInitiate) return `In simple terms: Started tracking ${ticker} with a negative outlook`;
    if (isMaintain) return `In simple terms: Still negative on ${ticker}, expects it to go down`;
    return `In simple terms: Negative on ${ticker}, expects it to go down`;
  }

  return null;
}

/**
 * Extract a short rating change description from the context.
 * e.g. "Downgraded to Neutral" or "Upgraded to Buy"
 */
export function ratingChangeLabel(prediction) {
  const ctx = (prediction.exact_quote || prediction.context || '');
  const callType = (prediction.call_type || '').toLowerCase();

  if (callType === 'upgrade' || /upgrade/i.test(ctx)) {
    const m = ctx.match(/upgrade[sd]?\s+(?:to\s+)?(\w[\w\s-]*?)(?:\s+on\s|\s*,|\s*\.|\s+rating)/i);
    return m ? `Upgraded to ${m[1].trim()}` : 'Upgraded';
  }
  if (callType === 'downgrade' || /downgrade/i.test(ctx)) {
    const m = ctx.match(/downgrade[sd]?\s+(?:to\s+)?(\w[\w\s-]*?)(?:\s+on\s|\s*,|\s*\.|\s+rating)/i);
    return m ? `Downgraded to ${m[1].trim()}` : 'Downgraded';
  }
  if (callType === 'new_coverage' || /initiat|started coverage/i.test(ctx)) {
    const m = ctx.match(/(?:with|at)\s+(?:a\s+)?(\w[\w\s-]*?)\s+rating/i);
    return m ? `Initiated: ${m[1].trim()}` : 'New coverage';
  }
  if (/maintain|reiterat|reaffirm/i.test(ctx)) {
    const m = ctx.match(/(?:maintains?|reiterates?|reaffirms?)\s+(\w[\w\s-]*?)(?:\s+on\s|\s*,|\s*\.|\s+rating)/i);
    return m ? `Maintains ${m[1].trim()}` : 'Maintains rating';
  }
  return null;
}

/**
 * Render the explainer with styled "In simple terms:" prefix.
 * Ticker symbols in the body become clickable links to /ticker/{TICKER}.
 */
export function ExplainerLine({ prediction, className = '' }) {
  const text = simpleExplainer(prediction);
  if (!text) return null;
  const ticker = prediction.ticker || '';
  const prefix = 'In simple terms:';
  const body = text.startsWith(prefix) ? text.slice(prefix.length).trim() : text;

  // Split body around the ticker to make it a link
  let bodyEl = body;
  if (ticker && body.includes(ticker)) {
    const idx = body.indexOf(ticker);
    const before = body.slice(0, idx);
    const after = body.slice(idx + ticker.length);
    bodyEl = <>{before}<Link to={`/ticker/${ticker}`} className="font-semibold hover:underline" style={{ color: '#D4A843' }}>{ticker}</Link>{after}</>;
  }

  return (
    <p className={`text-sm leading-relaxed ${className}`} style={{ color: '#D4A843' }}>
      <span className="font-medium">In simple terms:</span>{' '}{bodyEl}
    </p>
  );
}
