import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { googleCallback } from '../api';

export default function GoogleCallback() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { loginWithToken } = useAuth();
  const [error, setError] = useState('');
  const [processing, setProcessing] = useState(false);

  useEffect(() => {
    // Flow 1: Arrived with token already (e.g. from a backend redirect)
    const token = searchParams.get('token');
    if (token) {
      const userId = searchParams.get('user_id');
      const username = searchParams.get('username');
      loginWithToken({ token, user_id: parseInt(userId), username });
      navigate('/');
      return;
    }

    // Flow 2: Arrived with error param
    const errorParam = searchParams.get('error');
    if (errorParam) {
      setError('Google sign-in failed. Please try again.');
      return;
    }

    // Flow 3: Google redirected here with a code — call backend API to exchange it
    const code = searchParams.get('code');
    if (!code) {
      setError('No authorization code received from Google.');
      return;
    }

    if (processing) return;
    setProcessing(true);

    googleCallback(code)
      .then(data => {
        loginWithToken(data);
        navigate('/');
      })
      .catch(err => {
        const detail = err?.response?.data?.detail || '';
        console.error('[GoogleCallback] Error:', detail || err);
        setError(detail || 'Google sign-in failed. Please try again.');
      });
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
