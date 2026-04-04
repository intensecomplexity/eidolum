import { useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { Link } from 'react-router-dom';
import { ArrowLeft, Mail } from 'lucide-react';
import { forgotPassword } from '../api';
import Footer from '../components/Footer';

export default function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    if (!email.includes('@')) { setError('Please enter a valid email address'); return; }

    setLoading(true);
    try {
      await forgotPassword(email.trim());
      setSent(true);
    } catch (err) {
      setError(err.response?.data?.detail || 'Something went wrong. Please try again.');
    } finally { setLoading(false); }
  }

  return (
    <div>
      <div className="max-w-md mx-auto px-4 py-10 sm:py-16">
        <Link to="/login" className="inline-flex items-center gap-1 text-sm text-muted hover:text-accent transition-colors mb-8">
          <ArrowLeft className="w-4 h-4" /> Back to login
        </Link>

        {sent ? (
          <div className="text-center">
            <div className="w-14 h-14 rounded-full bg-accent/10 flex items-center justify-center mx-auto mb-6">
              <Mail className="w-7 h-7 text-accent" />
            </div>
            <h1 className="headline-serif text-2xl sm:text-3xl mb-3">Check your email</h1>
            <p className="text-text-secondary text-sm mb-2">
              If <span className="font-mono text-text-primary">{email}</span> is registered,
              you'll receive a password reset link shortly.
            </p>
            <p className="text-muted text-xs mt-4">
              Didn't get it? Check your spam folder, or{' '}
              <button onClick={() => setSent(false)} className="text-accent hover:underline">try again</button>.
            </p>
          </div>
        ) : (
          <>
            <div className="text-center mb-8">
              <h1 className="headline-serif text-3xl sm:text-4xl mb-2">Reset password</h1>
              <p className="text-text-secondary text-sm">Enter your email and we'll send you a reset link.</p>
            </div>

            {error && (
              <div className="bg-negative/10 border border-negative/20 rounded-lg px-4 py-3 mb-4 text-sm text-negative">{error}</div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-xs text-muted uppercase tracking-wider mb-1.5">Email</label>
                <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" autoFocus
                  className="w-full px-4 py-3 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50" />
              </div>
              <button type="submit" disabled={loading} className="btn-primary w-full disabled:opacity-50">
                {loading ? <div className="w-5 h-5 border-2 border-bg border-t-transparent rounded-full animate-spin" /> : 'Send Reset Link'}
              </button>
            </form>
          </>
        )}
      </div>
      <Footer />
    </div>
  );
}
