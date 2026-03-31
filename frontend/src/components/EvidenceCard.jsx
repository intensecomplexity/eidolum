import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Play, ExternalLink, X as XIcon, Search, Archive, MessageSquare, Newspaper, Link2 } from 'lucide-react';
import getSourceUrl from '../utils/getSourceUrl';
import { annotateContext, ExplainerLine } from '../utils/predictionExplainer';

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
  if (type === 'youtube') return <Play className="w-3 h-3" />;
  if (type === 'twitter') return <ExternalLink className="w-3 h-3" />;
  if (type === 'reddit') return <MessageSquare className="w-3 h-3" />;
  if (type === 'article') return <Newspaper className="w-3 h-3" />;
  return <Link2 className="w-3 h-3" />;
}

/** Check if a source_platform_id is a real YouTube video ID (11 alphanumeric chars, no underscores/spaces) */
function isRealYouTubeId(id) {
  if (!id || typeof id !== 'string') return false;
  if (id.length !== 11) return false;
  if (id.includes('_') || id.includes(' ')) return false;
  return /^[a-zA-Z0-9\-]+$/.test(id);
}

/** Build YouTube embed URL with optional timestamp */
function getEmbedUrl(videoId, timestampSec) {
  let url = `https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&rel=0`;
  if (timestampSec) url += `&start=${timestampSec}`;
  return url;
}

export default function EvidenceCard({ prediction: p, forecaster = null, expandable = true, compact = false }) {
  const [expanded, setExpanded] = useState(!expandable);
  const [showVideo, setShowVideo] = useState(false);

  if (!p) return null;

  const hasQuote = p.exact_quote && p.exact_quote.length > 0;
  const hasSource = p.source_url && p.source_url.length > 0;
  const hasRealVideo = isRealYouTubeId(p.source_platform_id);
  const badge = getSourceBadge(p.source_type, p.verified_by, !!p.video_timestamp_sec);

  // Wayback Machine archive link (external archive_url or computed from source_url)
  const archiveLink = p.archive_url && p.archive_url.startsWith('https://web.archive.org')
    ? p.archive_url
    : (hasSource && !p.source_url.includes('youtube.com') && !p.source_url.includes('x.com') && !p.source_url.includes('twitter.com') && !p.source_url.includes('reddit.com'))
      ? `https://web.archive.org/web/${p.source_url}`
      : null;

  // Build contextual search link as fallback
  const fc = forecaster || p.forecaster || null;
  const ctxSource = getSourceUrl(p, fc);

  // Compact mode: just the quote and source link inline
  if (compact) {
    return (
      <div className="mt-1.5">
        {hasQuote && (
          <>
            <p className="text-text-secondary text-xs italic leading-relaxed truncate">
              &ldquo;{annotateContext(p.exact_quote.slice(0, 100), p.ticker)}{p.exact_quote.length > 100 ? '...' : ''}&rdquo;
            </p>
            <ExplainerLine prediction={p} className="mt-0.5" />
          </>
        )}
        {hasRealVideo && p.source_type === 'youtube' && (
          <button
            onClick={(e) => { e.stopPropagation(); setShowVideo(!showVideo); }}
            className="inline-flex items-center gap-1 text-[11px] text-accent active:underline mt-0.5 min-h-[28px]"
          >
            <SourceIcon type="youtube" />
            {p.timestamp_display ? `Watch at ${p.timestamp_display}` : 'Watch'}
          </button>
        )}
        {hasSource && !hasRealVideo && p.source_type !== 'youtube' && (
          <a href={p.source_url} target="_blank" rel="noopener noreferrer"
             className="inline-flex items-center gap-1 text-[11px] text-accent active:underline mt-0.5">
            <SourceIcon type={p.source_type} />
            Source
          </a>
        )}
        {!hasSource && !hasRealVideo && ctxSource?.url && (
          <a href={ctxSource.url} target="_blank" rel="noopener noreferrer"
             title={ctxSource.tooltip}
             className="inline-flex items-center gap-1 text-[11px] text-accent active:underline mt-0.5">
            <Search className="w-2.5 h-2.5" />
            {ctxSource.label || 'Search source'}
          </a>
        )}
        {archiveLink && (
          <a href={archiveLink} target="_blank" rel="noopener noreferrer"
             className="inline-flex items-center gap-1 text-[11px] text-emerald-400 active:underline mt-0.5 ml-2">
            <Archive className="w-2.5 h-2.5" />
            Proof
          </a>
        )}
        {showVideo && hasRealVideo && (
          <InlinePlayer videoId={p.source_platform_id} timestamp={p.video_timestamp_sec} onClose={() => setShowVideo(false)} />
        )}
      </div>
    );
  }

  return (
    <div
      className={`${expandable ? 'cursor-pointer' : ''}`}
      onClick={expandable ? () => setExpanded(!expanded) : undefined}
    >
      {/* Quote with glossary tooltips */}
      {hasQuote && (
        <div className="mt-3 bg-warning/[0.06] border-l-[3px] border-warning/60 rounded-r-lg px-4 py-3 relative">
          <span className="absolute top-1 left-2 text-warning/30 text-3xl font-serif leading-none select-none">&ldquo;</span>
          <p className="text-text-primary text-sm italic leading-relaxed pl-4 font-serif">
            {expanded ? annotateContext(p.exact_quote, p.ticker) : (
              p.exact_quote.length > 140
                ? <>{annotateContext(p.exact_quote.slice(0, 140), p.ticker)}...</>
                : annotateContext(p.exact_quote, p.ticker)
            )}
          </p>
          {expanded && p.exact_quote.length > 10 && (
            <span className="absolute bottom-1 right-3 text-warning/30 text-3xl font-serif leading-none select-none">&rdquo;</span>
          )}
          <ExplainerLine prediction={p} className="mt-2 pl-4 not-italic" />
        </div>
      )}

      {/* Source line */}
      {(hasSource || p.source_title || ctxSource?.url) && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold ${badge.bg} ${badge.color} border ${badge.border}`}>
            <SourceIcon type={p.source_type} />
            {badge.label}
          </span>

          {p.source_title && (
            <span className="text-text-secondary text-xs truncate max-w-[200px] sm:max-w-xs">
              {p.source_title}
            </span>
          )}

          {/* YouTube Watch button — only if real video ID */}
          {hasRealVideo && p.source_type === 'youtube' && (
            <button
              onClick={(e) => { e.stopPropagation(); setShowVideo(!showVideo); }}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-positive/10 text-positive border border-positive/20 active:bg-positive/20 min-h-[28px]"
            >
              <Play className="w-3 h-3" fill="currentColor" />
              {p.timestamp_display ? `Watch at ${p.timestamp_display}` : 'Watch'}
            </button>
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

          {/* Contextual search link when no direct source */}
          {!hasSource && !hasRealVideo && ctxSource?.url && (
            <a
              href={ctxSource.url}
              target="_blank"
              rel="noopener noreferrer"
              title={ctxSource.tooltip}
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-accent/10 text-accent border border-accent/20 active:bg-accent/20 min-h-[28px]"
            >
              <Search className="w-3 h-3" />
              {ctxSource.label || 'Search source'}
            </a>
          )}

          {/* Wayback Machine archived proof link */}
          {archiveLink && (
            <a
              href={archiveLink}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-emerald-400/10 text-emerald-400 border border-emerald-400/20 active:bg-emerald-400/20 min-h-[28px]"
            >
              <Archive className="w-3 h-3" />
              Archived Proof
            </a>
          )}
        </div>
      )}

      {/* Inline video player */}
      {showVideo && hasRealVideo && (
        <div onClick={(e) => e.stopPropagation()}>
          <InlinePlayer videoId={p.source_platform_id} timestamp={p.video_timestamp_sec} onClose={() => setShowVideo(false)} />
        </div>
      )}

      {/* Expanded: full video link */}
      {expanded && hasRealVideo && p.source_type === 'youtube' && !showVideo && (
        <div className="mt-2 flex items-center gap-2 flex-wrap">
          <a
            href={`https://youtube.com/watch?v=${p.source_platform_id}`}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 text-xs text-muted active:text-text-primary min-h-[28px]"
          >
            <ExternalLink className="w-3 h-3" />
            Open on YouTube
          </a>
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

/** Inline YouTube player component */
function InlinePlayer({ videoId, timestamp, onClose }) {
  return (
    <div className="mt-3 rounded-lg overflow-hidden bg-bg border border-border">
      <div className="flex items-center justify-between px-3 py-1.5 bg-surface-2 border-b border-border">
        <span className="text-muted text-[10px] font-mono">YouTube Player</span>
        <button
          onClick={onClose}
          className="flex items-center gap-1 text-muted hover:text-text-secondary text-xs min-h-[28px]"
        >
          <XIcon className="w-3 h-3" /> Close video
        </button>
      </div>
      <div className="relative w-full" style={{ paddingBottom: '56.25%' }}>
        <iframe
          className="absolute inset-0 w-full h-full"
          src={getEmbedUrl(videoId, timestamp)}
          title="YouTube video player"
          frameBorder="0"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
        />
      </div>
    </div>
  );
}

// Mini version for activity feed
export function MiniQuote({ quote, sourceUrl, sourceType, timestampDisplay, sourcePlatformId }) {
  if (!quote) return null;
  const hasRealVideo = isRealYouTubeId(sourcePlatformId);
  return (
    <div className="mt-1">
      <p className="text-text-secondary text-xs italic truncate">
        &ldquo;{quote.slice(0, 80)}{quote.length > 80 ? '...' : ''}&rdquo;
      </p>
      {hasRealVideo && sourceType === 'youtube' && (
        <a href={`https://youtube.com/watch?v=${sourcePlatformId}`} target="_blank" rel="noopener noreferrer"
           className="inline-flex items-center gap-1 text-[10px] text-accent active:underline mt-0.5"
           onClick={(e) => e.stopPropagation()}>
          <Play className="w-2.5 h-2.5" fill="currentColor" />
          {timestampDisplay ? `${timestampDisplay}` : 'Watch'}
        </a>
      )}
      {sourceUrl && !hasRealVideo && sourceType !== 'youtube' && (
        <a href={sourceUrl} target="_blank" rel="noopener noreferrer"
           className="inline-flex items-center gap-1 text-[10px] text-accent active:underline mt-0.5"
           onClick={(e) => e.stopPropagation()}>
          Source
        </a>
      )}
    </div>
  );
}
