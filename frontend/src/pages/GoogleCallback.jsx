import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { API_BASE } from '../api';

export default function GoogleCallback() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { loginWithToken } = useAuth();
  const [error, setError] = useState('');

  useEffect(() => {
    // Check for token first (backend redirected here after code exchange)
    const token = searchParams.get('token');
    if (token) {
      const userId = searchParams.get('user_id');
      const username = searchParams.get('username');
      loginWithToken({ token, user_id: parseInt(userId), username });
      navigate('/');
      return;
    }

    // Check for error from login page redirect
    const errorParam = searchParams.get('error');
    if (errorParam) {
      setError('Google sign-in failed. Please try again.');
      return;
    }

    // Google redirected here with a code — redirect browser to backend to exchange it
    const code = searchParams.get('code');
    if (code) {
      // Redirect the browser (not an API call) to the backend callback
      // The backend will exchange the code, create/find the user, and redirect back
      // to /auth/callback?token=...
      window.location.href = `${API_BASE}/api/auth/google/callback?code=${encodeURIComponent(code)}`;
      return;
    }

    setError('No authorization code received from Google.');
  }, []);

  if (error) {
    return (
      <div className="max-w-md mx-auto px-4 py-20 text-center">
        <div className="bg-negative/10 border border-negative/20 rounded-lg px-4 py-3 mb-4 text-sm text-negative">{error}</div>
        <button onClick={() => navigate('/login')} className="btn-primary">Back to Login</button>
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
