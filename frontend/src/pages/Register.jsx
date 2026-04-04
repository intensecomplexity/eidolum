import { useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { useNavigate, Link, useSearchParams } from 'react-router-dom';
import { Eye, EyeOff } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import GoogleSignInButton from '../components/GoogleSignInButton';
import Footer from '../components/Footer';

export default function Register() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const ref = searchParams.get('ref') || '';
  const { register } = useAuth();
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [hp, setHp] = useState('');

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    if (!username.trim() || username.trim().length < 3 || username.trim().length > 30) {
      setError('Username must be 3-30 characters'); return;
    }
    if (!/^[a-zA-Z0-9_]+$/.test(username.trim())) {
      setError('Username: letters, numbers, underscores only'); return;
    }
    if (!email.includes('@')) { setError('Valid email required'); return; }
    if (password.length < 8) { setError('Password must be 8+ characters'); return; }

    setLoading(true);
    try {
      await register(username.trim(), email.trim(), password, ref, hp ? { website: hp } : {});
      navigate('/');
    } catch (err) {
      setError(err.response?.data?.detail || 'Registration failed');
    } finally { setLoading(false); }
  }

  return (
    <div>
      <div className="max-w-md mx-auto px-4 py-10 sm:py-16">
        <div className="text-center mb-8">
          <h1 className="headline-serif text-3xl sm:text-4xl mb-2">Create Account</h1>
          <p className="text-text-secondary text-sm">Start tracking your predictions</p>
        </div>

        {ref && (
          <div className="bg-accent/5 border border-accent/20 rounded-lg px-4 py-3 mb-4 text-sm text-accent">
            Invited by <span className="font-mono font-bold">@{ref}</span>. You'll both get 25 XP!
          </div>
        )}

        {error && (
          <div className="bg-negative/10 border border-negative/20 rounded-lg px-4 py-3 mb-4 text-sm text-negative">{error}</div>
        )}

        <GoogleSignInButton label="Sign up with Google" />

        <div className="flex items-center gap-3 my-6">
          <div className="flex-1 h-px bg-border" />
          <span className="text-xs text-muted">or</span>
          <div className="flex-1 h-px bg-border" />
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs text-muted uppercase tracking-wider mb-1.5">Username</label>
            <input type="text" value={username} onChange={e => setUsername(e.target.value)} placeholder="your_handle"
              className="w-full px-4 py-3 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50 font-mono" />
          </div>
          <div>
            <label className="block text-xs text-muted uppercase tracking-wider mb-1.5">Display Name <span className="text-muted/50">(optional)</span></label>
            <input type="text" value={displayName} onChange={e => setDisplayName(e.target.value)} placeholder="Your Name"
              className="w-full px-4 py-3 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50" />
          </div>
          <div>
            <label className="block text-xs text-muted uppercase tracking-wider mb-1.5">Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com"
              className="w-full px-4 py-3 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50" />
          </div>
          <div>
            <label className="block text-xs text-muted uppercase tracking-wider mb-1.5">Password</label>
            <div className="relative">
              <input type={showPw ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)} placeholder="Min 8 characters"
                className="w-full px-4 py-3 pr-12 bg-surface border border-border rounded-lg text-text-primary placeholder:text-muted focus:outline-none focus:border-accent/50" />
              <button type="button" onClick={() => setShowPw(!showPw)} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted">
                {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
          {/* Honeypot — hidden from real users */}
          <div aria-hidden="true" style={{ position: 'absolute', left: '-9999px', height: 0, overflow: 'hidden' }}>
            <input type="text" name="website" tabIndex={-1} autoComplete="off" value={hp} onChange={e => setHp(e.target.value)} />
          </div>
          <button type="submit" disabled={loading} className="btn-primary w-full disabled:opacity-50">
            {loading ? <div className="w-5 h-5 border-2 border-bg border-t-transparent rounded-full animate-spin" /> : 'Create Account'}
          </button>
        </form>

        <p className="text-center text-muted text-xs mt-6">
          Already have an account? <Link to="/login" className="text-accent">Log in</Link>
        </p>
      </div>
      <Footer />
    </div>
  );
}
