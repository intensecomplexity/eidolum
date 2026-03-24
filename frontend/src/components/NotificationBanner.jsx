import { Bell, X } from 'lucide-react';
import { useState } from 'react';

export default function NotificationBanner({ text, onDismiss }) {
  const [email, setEmail] = useState('');
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  function handleDismiss() {
    setDismissed(true);
    onDismiss?.();
  }

  return (
    <div className="bg-surface-2 border border-accent/20 rounded-lg p-3 flex flex-col sm:flex-row items-start sm:items-center gap-2 sm:gap-3 mt-4">
      <div className="flex items-center gap-2 flex-1 min-w-0">
        <Bell className="w-4 h-4 text-accent shrink-0" />
        <span className="text-text-secondary text-sm">{text}</span>
      </div>
      <div className="flex items-center gap-2 w-full sm:w-auto">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="your@email.com"
          className="flex-1 sm:w-40 px-3 py-2 sm:py-1 bg-surface border border-border rounded text-sm text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 min-h-[44px] sm:min-h-0"
        />
        <button className="text-sm text-accent font-medium active:underline whitespace-nowrap min-h-[44px] sm:min-h-0 px-2">
          Subscribe
        </button>
        <button onClick={handleDismiss} className="text-muted active:text-text-primary min-h-[44px] sm:min-h-0 px-1">
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
