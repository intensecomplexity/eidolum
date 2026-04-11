// Ship #13. Thin three-step strip that sits below HeroBand on `/`.
// Stays above the fold on a 1080p screen; stacks vertically on mobile.

const STEPS = [
  { n: 1, text: 'A forecaster makes a public call' },
  { n: 2, text: 'Eidolum locks it — timestamp, ticker, target' },
  { n: 3, text: 'The market grades it — HIT, NEAR, or MISS' },
];

export default function HowItWorks() {
  return (
    <section className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 sm:gap-8">
        {STEPS.map(s => (
          <div
            key={s.n}
            className="flex items-center gap-3 sm:flex-col sm:text-center sm:items-center"
          >
            <div
              className="shrink-0 w-8 h-8 rounded-full border border-accent/40 flex items-center justify-center font-mono text-sm font-bold text-accent bg-accent/5"
              aria-hidden
            >
              {s.n}
            </div>
            <div className="text-sm text-text-primary font-medium">
              {s.text}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
