import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { loginUser, registerUser, getMe, getUserProfile } from '../api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(() => localStorage.getItem('eidolum_token'));
  const [loading, setLoading] = useState(!!localStorage.getItem('eidolum_token'));

  // On mount, if we have a token, hydrate from /auth/me
  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    getMe()
      .then(userData => {
        setUser(userData);
        localStorage.setItem('eidolum_user', JSON.stringify(userData));
      })
      .catch(() => {
        // Token expired or invalid — clear everything
        localStorage.removeItem('eidolum_token');
        localStorage.removeItem('eidolum_user');
        setToken(null);
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email, password) => {
    const data = await loginUser(email, password);
    localStorage.setItem('eidolum_token', data.token);
    // data has {user_id, username, display_name, token} — store as user obj
    const userObj = { id: data.user_id, username: data.username, display_name: data.display_name };
    localStorage.setItem('eidolum_user', JSON.stringify(userObj));
    setToken(data.token);
    setUser(userObj);
    // Fetch full profile in background to populate all fields
    getMe().then(full => {
      setUser(full);
      localStorage.setItem('eidolum_user', JSON.stringify(full));
    }).catch(() => {});
    return data;
  }, []);

  const register = useCallback(async (username, email, password) => {
    const data = await registerUser(username, email, password);
    localStorage.setItem('eidolum_token', data.token);
    const userObj = { id: data.user_id, username: data.username };
    localStorage.setItem('eidolum_user', JSON.stringify(userObj));
    setToken(data.token);
    setUser(userObj);
    // Fetch full profile in background
    getMe().then(full => {
      setUser(full);
      localStorage.setItem('eidolum_user', JSON.stringify(full));
    }).catch(() => {});
    return data;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('eidolum_token');
    localStorage.removeItem('eidolum_user');
    setToken(null);
    setUser(null);
  }, []);

  const refreshProfile = useCallback(async () => {
    if (!user) return;
    try {
      const profile = await getUserProfile(user.user_id || user.id);
      const updated = { ...user, ...profile };
      setUser(updated);
      localStorage.setItem('eidolum_user', JSON.stringify(updated));
    } catch {}
  }, [user]);

  const isAuthenticated = !!token && !!user;

  return (
    <AuthContext.Provider value={{ user, token, loading, isAuthenticated, login, register, logout, refreshProfile }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
