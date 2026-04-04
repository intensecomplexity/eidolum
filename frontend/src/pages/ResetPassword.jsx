import { useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { Eye, EyeOff, ArrowLeft } from 'lucide-react';
import { resetPassword } from '../api';
import Footer from '../components/Footer';

export default function ResetPassword() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  if (!token) {
    return (
      <div>
        <div className="max-w-md mx-auto px-4 py-20 text-center">
          <h1 className="headline-serif text-2xl mb-4">Invalid Reset Link</h1>
          <p className="text-text-secondary text-sm mb-6">This password reset link is missing or invalid.</p>
          <Link to="/forgot-password" className="btn-primary inline-block">Request a new link</Link>
        </div>
        <Footer />
      </div>
    );
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    if (password.length < 8) { setError('Password must be at least 8 characters'); return; }
    if (password !== confirm) { setError('Passwords do not match'); return; }

    setLoading(true);
    try {
      await resetPassword(token, password);
      navigate('/login?reset=success');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to reset password. The link may have expired.');
    } finally { setLoading(false); }
  }

  return (
    <div>
      <div className="max-w-md mx-auto px-4 py-10 sm:py-16">
        <Link to="/login" className="inline-flex items-center gap-1 text-sm text-muted hover:text-accent transition-colors mb-8">
          <ArrowLeft className="w-4 h-4" /> Back to login
        </Link>

        <div className="text-center mb-8">
          <h1 className="headline-serif text-3xl sm:text-4xl mb-2">New password</h1>
          <p className="text-text-secondary text-sm">Choose a new password for your account.</p>
        </div>

        {error && (
          <div className="bg-negative/10 border border-negative/20 rounded-lg px-4 py-3 mb-4 text-sm text-negative">{error}</div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs text-muted uppercase tracking-wider mb-1.5">New Password</label>
            <div className="relative">
              <input type={showPw ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)} placeholder="Min 8 characters" autoFocus
                className="w-full px-4 py-3 pr-12 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50" />
              <button type="button" onClick={() => setShowPw(!showPw)} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted">
                {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <div>
            <label className="block text-xs text-muted uppercase tracking-wider mb-1.5">Confirm Password</label>
            <input type={showPw ? 'text' : 'password'} value={confirm} onChange={e => setConfirm(e.target.value)} placeholder="Re-enter password"
              className="w-full px-4 py-3 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50" />
          </div>
          <button type="submit" disabled={loading} className="btn-primary w-full disabled:opacity-50">
            {loading ? <div className="w-5 h-5 border-2 border-bg border-t-transparent rounded-full animate-spin" /> : 'Reset Password'}
          </button>
        </form>
      </div>
      <Footer />
    </div>
  );
}
