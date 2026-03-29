/**
 * Translates analyst jargon into plain English and adds glossary tooltips.
 * Used by PredictionCard, EvidenceCard, and PredictionRow.
 */
import React from 'react';

// ── Glossary: analyst terms → plain-English tooltips ────────────────────────
const GLOSSARY = [
  { pattern: /\bunderweight\b/gi, label: 'Underweight', tip: 'Means the analyst thinks this stock will underperform. Similar to a Sell rating.' },
  { pattern: /\boverweight\b/gi, label: 'Overweight', tip: 'Means the analyst thinks this stock will outperform. Similar to a Buy rating.' },
  { pattern: /\boutperform\b/gi, label: 'Outperform', tip: 'The analyst expects this stock to beat the market.' },
  { pattern: /\bunderperform\b/gi, label: 'Underperform', tip: 'The analyst expects this stock to lag behind the market. Similar to Sell.' },
  { pattern: /\bequal[\s-]?weight\b/gi, label: 'Equal-Weight', tip: 'The analyst thinks the stock will perform in line with the market. Similar to Hold.' },
  { pattern: /\bmarket[\s-]?perform\b/gi, label: 'Market Perform', tip: 'Expected to match overall market returns. Similar to Hold.' },
  { pattern: /\bsector[\s-]?perform\b/gi, label: 'Sector Perform', tip: 'Expected to match its sector average. Similar to Hold.' },
  { pattern: /\bstrong buy\b/gi, label: 'Strong Buy', tip: 'The analyst is very bullish — expects the stock to significantly beat the market.' },
  { pattern: /\bstrong sell\b/gi, label: 'Strong Sell', tip: 'The analyst is very bearish — expects the stock to significantly underperform.' },
  { pattern: /\binitiates?[\s_]coverage[\s_]?on\b/gi, label: 'Initiates Coverage', tip: 'The analyst is covering this stock for the first time.' },
  { pattern: /\binitiates?[\s_]coverage\b/gi, label: 'Initiates Coverage', tip: 'The analyst is covering this stock for the first time.' },
  { pattern: /\bstarted coverage\b/gi, label: 'Started Coverage', tip: 'The analyst is covering this stock for the first time.' },
  { pattern: /\bmaintains\b/gi, label: 'Maintains', tip: 'The analyst is keeping their previous rating unchanged.' },
  { pattern: /\breiterates?\b/gi, label: 'Reiterates', tip: 'The analyst is reaffirming their existing rating — nothing changed.' },
  { pattern: /\breaffirms?\b/gi, label: 'Reaffirms', tip: 'The analyst is reaffirming their existing rating — nothing changed.' },
  { pattern: /\bdowngrades?\b/gi, label: 'Downgrades', tip: 'The analyst lowered their rating — they became more negative.' },
  { pattern: /\bupgrades?\b/gi, label: 'Upgrades', tip: 'The analyst raised their rating — they became more positive.' },
  { pattern: /\bPT\b/g, label: 'PT', tip: 'Price Target — the price the analyst thinks the stock will reach.' },
  { pattern: /\bprice target\b/gi, label: 'Price Target', tip: 'The price the analyst thinks the stock will reach.' },
  { pattern: /\btarget:\s?\$/gi, label: 'Target: $', tip: 'The price the analyst thinks the stock will reach.' },
];

/**
 * Wrap glossary terms in the text with tooltip spans.
 * Returns an array of React elements.
 */
export function annotateContext(text) {
  if (!text) return null;

  // Find all glossary matches with their positions
  const matches = [];
  for (const entry of GLOSSARY) {
    let m;
    const regex = new RegExp(entry.pattern.source, entry.pattern.flags);
    while ((m = regex.exec(text)) !== null) {
      // Avoid overlapping matches
      const overlaps = matches.some(
        (existing) => m.index < existing.end && m.index + m[0].length > existing.start
      );
      if (!overlaps) {
        matches.push({ start: m.index, end: m.index + m[0].length, original: m[0], tip: entry.tip });
      }
    }
  }

  if (matches.length === 0) return text;

  // Sort by position
  matches.sort((a, b) => a.start - b.start);

  // Build React elements
  const parts = [];
  let cursor = 0;
  for (const match of matches) {
    if (match.start > cursor) {
      parts.push(text.slice(cursor, match.start));
    }
    parts.push(
      <span key={match.start} className="glossary-term" data-tip={match.tip}>
        {match.original}
      </span>
    );
    cursor = match.end;
  }
  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }

  return parts;
}

/**
 * Generate a simple one-line explanation of what the prediction means.
 * Returns a plain string or null if we can't generate one.
 */
export function simpleExplainer(prediction) {
  const p = prediction;
  const ticker = p.ticker || '';
  const direction = (p.direction || '').toLowerCase();
  const entry = p.entry_price;
  const target = p.target_price;
  const context = (p.exact_quote || p.context || '').toLowerCase();

  // Determine the action type from context
  const isUpgrade = /upgrade/i.test(context);
  const isDowngrade = /downgrade/i.test(context);
  const isInitiate = /initiat|started coverage/i.test(context);
  const isMaintain = /maintain|reiterat|reaffirm/i.test(context);

  if (target && entry && entry > 0) {
    const pctChange = ((target - entry) / entry * 100).toFixed(1);
    const sign = target >= entry ? '+' : '';

    if (direction === 'bullish') {
      if (isMaintain) {
        return `In simple terms: Still expects ${ticker} to rise to $${target.toFixed(0)} from $${entry.toFixed(0)} (${sign}${pctChange}%)`;
      }
      return `In simple terms: Expects ${ticker} to rise from $${entry.toFixed(0)} to $${target.toFixed(0)} (${sign}${pctChange}%)`;
    } else if (direction === 'bearish') {
      if (isMaintain) {
        return `In simple terms: Still expects ${ticker} to fall to $${target.toFixed(0)} from $${entry.toFixed(0)} (${sign}${pctChange}%)`;
      }
      return `In simple terms: Expects ${ticker} to drop from $${entry.toFixed(0)} to $${target.toFixed(0)} (${sign}${pctChange}%)`;
    }
  }

  // No price target — directional only
  if (direction === 'bullish') {
    if (isUpgrade) return `In simple terms: Turned more positive on ${ticker} — expects it to go up`;
    if (isInitiate) return `In simple terms: Started tracking ${ticker} with a positive outlook`;
    if (isMaintain) return `In simple terms: Still positive on ${ticker} — expects it to go up`;
    return `In simple terms: Positive on ${ticker} — expects it to go up`;
  }
  if (direction === 'bearish') {
    if (isDowngrade) return `In simple terms: Turned more negative on ${ticker} — expects it to go down`;
    if (isInitiate) return `In simple terms: Started tracking ${ticker} with a negative outlook`;
    if (isMaintain) return `In simple terms: Still negative on ${ticker} — expects it to go down`;
    return `In simple terms: Negative on ${ticker} — expects it to go down`;
  }

  return null;
}
