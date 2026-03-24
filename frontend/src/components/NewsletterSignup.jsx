import { useState } from 'react';
import { Mail, CheckCircle } from 'lucide-react';
import { subscribeNewsletter } from '../api';

export default function NewsletterSignup({ inline = false }) {
  const [email, setEmail] = useState('');
  const [status, setStatus] = useState(null); // null | 'loading' | 'success' | 'error'

  async function handleSubmit(e) {
    e.preventDefault();
    if (!email.trim()) return;
    setStatus('loading');
    try {
      await subscribeNewsletter(email.trim());
      setStatus('success');
      localStorage.setItem('qa_newsletter', email.trim());
    } catch {
      setStatus('error');
    }
  }

  if (status === 'success') {
    return (
      <div className={`flex items-center gap-2 ${inline ? '' : 'py-2'}`}>
        <CheckCircle className="w-4 h-4 text-accent" />
        <span className="text-accent text-sm font-medium">Subscribed! See you Monday.</span>
      </div>
    );
  }

  if (inline) {
    return (
      <form onSubmit={handleSubmit} className="flex items-center gap-2">
        <Mail className="w-4 h-4 text-muted shrink-0" />
        <input
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="your@email.com"
          className="flex-1 px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 font-mono min-h-[44px] sm:min-h-0"
        />
        <button type="submit" disabled={status === 'loading'} className="text-accent text-sm font-medium active:underline whitespace-nowrap min-h-[44px] sm:min-h-0 px-2">
          {status === 'loading' ? 'Saving...' : 'Subscribe'}
        </button>
      </form>
    );
  }

  return (
    <div className="card glow-accent text-center">
      <Mail className="w-6 h-6 text-accent mx-auto mb-2" />
      <h3 className="text-text-primary font-semibold mb-1">Get the Weekly Roundup</h3>
      <p className="text-muted text-sm mb-3">Top calls, leaderboard changes, and rare signals &mdash; every Monday.</p>
      <form onSubmit={handleSubmit} className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 max-w-md mx-auto">
        <input
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="your@email.com"
          className="flex-1 px-4 py-3 bg-surface-2 border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 min-h-[48px]"
        />
        <button type="submit" disabled={status === 'loading'} className="btn-primary whitespace-nowrap">
          {status === 'loading' ? 'Subscribing...' : 'Subscribe'}
        </button>
      </form>
      {status === 'error' && <p className="text-negative text-xs mt-2">Something went wrong. Try again.</p>}
    </div>
  );
}
