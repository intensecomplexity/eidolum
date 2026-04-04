import { useEffect, useState } from 'react';
import LoadingSpinner from '../components/LoadingSpinner';
import { useSearchParams } from 'react-router-dom';
import { API_BASE } from '../api';

export default function GoogleCallback() {
  const [searchParams] = useSearchParams();
  const [error, setError] = useState(null);

  useEffect(() => {
    // Flow 1: Already have a token (backend redirect flow)
    const token = searchParams.get('token');
    if (token) {
      const userId = searchParams.get('user_id');
      const username = searchParams.get('username');
      localStorage.setItem('eidolum_token', token);
      localStorage.setItem('eidolum_user', JSON.stringify({
        id: parseInt(userId), user_id: parseInt(userId), username,
      }));
      window.location.href = '/';
      return;
    }

    // Flow 2: Error from previous attempt
    const errorParam = searchParams.get('error');
    if (errorParam) {
      setError('Google sign-in failed. Please try again.');
      return;
    }

    // Flow 3: Google redirected here with a code — exchange it
    const code = searchParams.get('code');
    if (!code) {
      setError('No authorization code received from Google.');
      return;
    }

    // Use fetch directly (not axios) to avoid any interceptor/redirect issues
    fetch(`${API_BASE}/api/auth/google/callback?code=${encodeURIComponent(code)}`)
      .then(res => {
        if (!res.ok) return res.json().then(d => { throw new Error(d.detail || 'Login failed'); });
        return res.json();
      })
      .then(data => {
        if (data.token) {
          localStorage.setItem('eidolum_token', data.token);
          localStorage.setItem('eidolum_user', JSON.stringify({
            id: data.user_id, user_id: data.user_id,
            username: data.username, display_name: data.display_name,
          }));
          // Use window.location to force full page reload with fresh auth state
          window.location.href = '/';
        } else {
          setError(data.detail || 'Login failed. No token received.');
        }
      })
      .catch(err => {
        console.error('[GoogleCallback]', err);
        setError(err.message || 'Failed to complete Google sign-in.');
      });
  }, []);

  if (error) {
    return (
      <div className="max-w-md mx-auto px-4 py-20 text-center">
        <div className="bg-negative/10 border border-negative/20 rounded-lg px-4 py-3 mb-4 text-sm text-negative">{error}</div>
        <a href="/login" className="btn-primary inline-block">Back to Login</a>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-3">
      <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      <p className="text-muted text-sm">Signing in with Google...</p>
    </div>
  );
}
