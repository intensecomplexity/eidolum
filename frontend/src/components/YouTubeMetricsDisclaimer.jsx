// Shared one-line caption for surfaces that show accuracy/return metrics
// next to YouTube-sourced forecasters. Required wording — the metrics are
// Eidolum's own computation, not YouTube data.
export default function YouTubeMetricsDisclaimer({ className = '' }) {
  return (
    <p className={`text-[11px] text-muted/80 leading-relaxed ${className}`}>
      Accuracy and return metrics are calculated by Eidolum from licensed market
      data and the forecaster's public statements. They are not provided by or
      derived from YouTube.
    </p>
  );
}
