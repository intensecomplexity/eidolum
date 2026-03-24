import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Play, ExternalLink, Share2, Copy, Download } from 'lucide-react';
import PredictionBadge from './PredictionBadge';

const SOURCE_BADGES = {
  youtube: { label: 'VIDEO', extra: null, color: 'text-positive', bg: 'bg-positive/10', border: 'border-positive/20' },
  youtube_ts: { label: 'VIDEO + TIMESTAMP', extra: null, color: 'text-positive', bg: 'bg-positive/10', border: 'border-positive/20' },
  twitter: { label: 'TWEET', extra: null, color: 'text-sky-400', bg: 'bg-sky-400/10', border: 'border-sky-400/20' },
  reddit: { label: 'POST', extra: null, color: 'text-orange-400', bg: 'bg-orange-400/10', border: 'border-orange-400/20' },
  article: { label: 'ARTICLE', extra: null, color: 'text-sky-400', bg: 'bg-sky-400/10', border: 'border-sky-400/20' },
  ai_parsed: { label: 'AI PARSED', extra: 'Extracted from video description', color: 'text-warning', bg: 'bg-warning/10', border: 'border-warning/20' },
  auto_title: { label: 'TITLE INFERRED', extra: 'Inferred from video title', color: 'text-muted', bg: 'bg-surface-2', border: 'border-border' },
};

function getSourceBadge(sourceType, verifiedBy, hasTimestamp) {
  if (verifiedBy === 'ai_parsed') return SOURCE_BADGES.ai_parsed;
  if (verifiedBy === 'auto_title' && sourceType !== 'twitter') return SOURCE_BADGES.auto_title;
  if (sourceType === 'youtube' && hasTimestamp) return SOURCE_BADGES.youtube_ts;
  return SOURCE_BADGES[sourceType] || SOURCE_BADGES.auto_title;
}

function SourceIcon({ type }) {
  if (type === 'youtube') return <span className="text-sm">&#x25B6;</span>;
  if (type === 'twitter') return <span className="text-sm">&#x1D54F;</span>;
  if (type === 'reddit') return <span className="text-sm">&#x1F4DD;</span>;
  if (type === 'article') return <span className="text-sm">&#x1F4F0;</span>;
  return <span className="text-sm">&#x1F517;</span>;
}

export default function EvidenceCard({ prediction: p, expandable = true, compact = false }) {
  const [expanded, setExpanded] = useState(!expandable);

  if (!p) return null;

  const hasQuote = p.exact_quote && p.exact_quote.length > 0;
  const hasSource = p.source_url && p.source_url.length > 0;
  const badge = getSourceBadge(p.source_type, p.verified_by, !!p.video_timestamp_sec);

  // Compact mode: just the quote and source link inline
  if (compact) {
    return (
      <div className="mt-1.5">
        {hasQuote && (
          <p className="text-text-secondary text-xs italic leading-relaxed truncate">
            &ldquo;{p.exact_quote.slice(0, 100)}{p.exact_quote.length > 100 ? '...' : ''}&rdquo;
          </p>
        )}
        {hasSource && (
          <a href={p.source_url} target="_blank" rel="noopener noreferrer"
             className="inline-flex items-center gap-1 text-[11px] text-accent active:underline mt-0.5">
            <SourceIcon type={p.source_type} />
            {p.timestamp_display ? `Watch at ${p.timestamp_display}` : 'Source'}
          </a>
        )}
      </div>
    );
  }

  return (
    <div
      className={`${expandable ? 'cursor-pointer' : ''}`}
      onClick={expandable ? () => setExpanded(!expanded) : undefined}
    >
      {/* Collapsed: quote preview + source */}
      {hasQuote && (
        <div className="mt-3 bg-warning/[0.06] border-l-[3px] border-warning/60 rounded-r-lg px-4 py-3 relative">
          <span className="absolute top-1 left-2 text-warning/30 text-3xl font-serif leading-none select-none">&ldquo;</span>
          <p className="text-text-primary text-sm italic leading-relaxed pl-4 font-serif">
            {expanded ? p.exact_quote : (
              p.exact_quote.length > 140
                ? p.exact_quote.slice(0, 140) + '...'
                : p.exact_quote
            )}
          </p>
          {expanded && p.exact_quote.length > 10 && (
            <span className="absolute bottom-1 right-3 text-warning/30 text-3xl font-serif leading-none select-none">&rdquo;</span>
          )}
        </div>
      )}

      {/* Source line */}
      {(hasSource || p.source_title) && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {/* Source badge */}
          <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold ${badge.bg} ${badge.color} border ${badge.border}`}>
            <SourceIcon type={p.source_type} />
            {badge.label}
          </span>

          {p.source_title && (
            <span className="text-text-secondary text-xs truncate max-w-[200px] sm:max-w-xs">
              {p.source_title}
            </span>
          )}

          {/* Watch button */}
          {hasSource && p.source_type === 'youtube' && (
            <a
              href={p.timestamp_url || p.source_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-positive/10 text-positive border border-positive/20 active:bg-positive/20 min-h-[28px]"
            >
              <Play className="w-3 h-3" fill="currentColor" />
              {p.timestamp_display ? `Watch at ${p.timestamp_display}` : 'Watch'}
            </a>
          )}

          {/* Non-YouTube source link */}
          {hasSource && p.source_type !== 'youtube' && (
            <a
              href={p.source_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-sky-400/10 text-sky-400 border border-sky-400/20 active:bg-sky-400/20 min-h-[28px]"
            >
              <ExternalLink className="w-3 h-3" />
              Source
            </a>
          )}
        </div>
      )}

      {/* Expanded: full details */}
      {expanded && hasSource && p.source_type === 'youtube' && (
        <div className="mt-2 flex items-center gap-2 flex-wrap">
          {p.source_url && p.timestamp_url !== p.source_url && (
            <a
              href={p.source_url.split('&t=')[0]}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 text-xs text-muted active:text-text-primary min-h-[28px]"
            >
              <ExternalLink className="w-3 h-3" />
              Full Video
            </a>
          )}
        </div>
      )}

      {/* Resolution info when expanded */}
      {expanded && p.outcome && p.outcome !== 'pending' && (
        <div className="mt-3 bg-surface-2 rounded-lg px-3 py-2 text-xs text-text-secondary">
          Resolution: {p.ticker} was{' '}
          <span className={`font-mono font-semibold ${p.actual_return >= 0 ? 'text-positive' : 'text-negative'}`}>
            {p.actual_return >= 0 ? '+' : ''}{p.actual_return?.toFixed(1)}%
          </span>
          {' '}at {p.window_days}-day mark{' '}
          <span className={p.outcome === 'correct' ? 'text-positive' : 'text-negative'}>
            {p.outcome === 'correct' ? '&#10003;' : '&#10007;'}
          </span>
          {p.entry_price && (
            <span className="ml-2 text-muted">
              Entry: ${p.entry_price.toFixed(0)}
            </span>
          )}
        </div>
      )}

      {/* Disclaimer */}
      {expanded && (
        <p className="text-[10px] text-muted italic mt-2">
          Quote sourced from public statement. Eidolum does not provide investment advice.
        </p>
      )}
    </div>
  );
}

// Mini version for activity feed
export function MiniQuote({ quote, sourceUrl, sourceType, timestampDisplay }) {
  if (!quote) return null;
  return (
    <div className="mt-1">
      <p className="text-text-secondary text-xs italic truncate">
        &ldquo;{quote.slice(0, 80)}{quote.length > 80 ? '...' : ''}&rdquo;
      </p>
      {sourceUrl && (
        <a href={sourceUrl} target="_blank" rel="noopener noreferrer"
           className="inline-flex items-center gap-1 text-[10px] text-accent active:underline mt-0.5"
           onClick={(e) => e.stopPropagation()}>
          <Play className="w-2.5 h-2.5" fill="currentColor" />
          {timestampDisplay ? `${timestampDisplay}` : 'Source'}
        </a>
      )}
    </div>
  );
}
