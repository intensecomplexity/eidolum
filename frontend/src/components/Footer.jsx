import { BarChart3 } from 'lucide-react';

export default function Footer() {
  return (
    <footer className="border-t border-border bg-surface mt-12 sm:mt-20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-between sm:gap-4">
          <div className="flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-accent" />
            <span className="font-mono font-semibold">
              <span className="text-accent">eido</span>
              <span className="text-muted">lum</span>
            </span>
          </div>
          <p className="text-muted text-xs sm:text-sm text-center">
            Tracking predictions. Measuring accuracy. Building accountability.
          </p>
          <p className="text-muted text-xs">
            &copy; {new Date().getFullYear()} Eidolum. For informational purposes only.
          </p>
        </div>
      </div>
    </footer>
  );
}
