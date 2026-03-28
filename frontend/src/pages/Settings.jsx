import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Settings as SettingsIcon, Bell, BellOff, Mail, User, Shield, AlertTriangle } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Footer from '../components/Footer';
import { setPriceAlerts, setEmailPreferences, getNotificationPrefs, setNotificationPrefs } from '../api';

export default function Settings() {
  const navigate = useNavigate();
  const { isAuthenticated, user, logout } = useAuth();
  const [priceAlerts, setPriceAlertsState] = useState(true);
  const [weeklyDigest, setWeeklyDigestState] = useState(true);
  const [saving, setSaving] = useState('');
  const [notifPrefs, setNotifPrefsState] = useState(null);

  useEffect(() => {
    if (user) {
      setPriceAlertsState(user.price_alerts_enabled !== false);
      setWeeklyDigestState(user.weekly_digest_enabled !== false);
      getNotificationPrefs().then(setNotifPrefsState).catch(() => {});
    }
  }, [user]);

  async function togglePriceAlerts() {
    setSaving('price');
    try { await setPriceAlerts(!priceAlerts); setPriceAlertsState(!priceAlerts); }
    catch {} finally { setSaving(''); }
  }

  async function toggleDigest() {
    setSaving('digest');
    try { await setEmailPreferences(!weeklyDigest); setWeeklyDigestState(!weeklyDigest); }
    catch {} finally { setSaving(''); }
  }

  if (!isAuthenticated) {
    return (
      <div className="max-w-lg mx-auto px-4 py-20 text-center">
        <SettingsIcon className="w-10 h-10 text-muted/30 mx-auto mb-3" />
        <p className="text-text-secondary mb-4">Log in to manage settings.</p>
        <button onClick={() => navigate('/login')} className="btn-primary">Log In</button>
      </div>
    );
  }

  return (
    <div>
      <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <div className="flex items-center gap-2 mb-6">
          <SettingsIcon className="w-6 h-6 text-accent" />
          <h1 className="font-bold" style={{ fontSize: 'clamp(24px, 5vw, 36px)' }}>Settings</h1>
        </div>

        {/* Email Preferences */}
        <div className="card mb-4">
          <h2 className="text-xs text-muted uppercase tracking-wider mb-4 flex items-center gap-1.5"><Mail className="w-3.5 h-3.5" /> Email Preferences</h2>

          <ToggleRow
            icon={<Mail className="w-5 h-5" />}
            title="Weekly digest email"
            desc="Sent every Sunday at 10 AM. Includes your weekly stats, badge progress, and leaderboard updates."
            enabled={weeklyDigest}
            onToggle={toggleDigest}
            loading={saving === 'digest'}
          />
        </div>

        {/* Notifications */}
        <div className="card mb-4">
          <h2 className="text-xs text-muted uppercase tracking-wider mb-4 flex items-center gap-1.5"><Bell className="w-3.5 h-3.5" /> Notifications</h2>

          <ToggleRow
            icon={priceAlerts ? <Bell className="w-5 h-5 text-accent" /> : <BellOff className="w-5 h-5 text-muted" />}
            title="Price alerts for my predictions"
            desc="Get notified when stocks move significantly for or against your open predictions"
            enabled={priceAlerts}
            onToggle={togglePriceAlerts}
            loading={saving === 'price'}
          />
        </div>

        {/* Account */}
        <div className="card mb-4">
          <h2 className="text-xs text-muted uppercase tracking-wider mb-4 flex items-center gap-1.5"><User className="w-3.5 h-3.5" /> Account</h2>

          <div className="space-y-3 text-sm">
            <div className="flex items-center justify-between py-2">
              <span className="text-text-secondary">Username</span>
              <span className="font-mono text-text-primary">@{user?.username}</span>
            </div>
            <div className="flex items-center justify-between py-2">
              <span className="text-text-secondary">Email</span>
              <span className="text-text-primary">{user?.email || 'Not set'}</span>
            </div>
            <div className="flex items-center justify-between py-2">
              <span className="text-text-secondary">Display Name</span>
              <span className="text-text-primary">{user?.display_name || user?.username}</span>
            </div>
            <div className="flex items-center justify-between py-2">
              <span className="text-text-secondary">Sign-in method</span>
              <span className="text-text-primary flex items-center gap-1.5">
                {user?.auth_provider === 'google' ? (
                  <><GoogleIcon /> Google</>
                ) : (
                  'Email & password'
                )}
              </span>
            </div>
          </div>
        </div>

        {/* Notification Preferences */}
        {notifPrefs && (
          <div className="card mb-4">
            <h2 className="text-xs text-muted uppercase tracking-wider mb-4 flex items-center gap-1.5"><Bell className="w-3.5 h-3.5" /> Notification Preferences</h2>
            {[
              { key: 'friends', label: 'Friend requests' },
              { key: 'prediction_results', label: 'Prediction results' },
              { key: 'comments', label: 'Comments on my predictions' },
              { key: 'reactions', label: 'Reaction milestones' },
              { key: 'duels', label: 'Duel updates' },
              { key: 'badges', label: 'Badge unlocks' },
              { key: 'daily_challenge', label: 'Daily Challenge' },
              { key: 'seasons', label: 'Season updates' },
              { key: 'watchlist', label: 'Watchlist alerts' },
              { key: 'price_alerts', label: 'Price alerts' },
              { key: 'leaderboard', label: 'Leaderboard changes' },
            ].map(cat => (
              <ToggleRow
                key={cat.key}
                icon={notifPrefs[cat.key] ? <Bell className="w-4 h-4 text-accent" /> : <BellOff className="w-4 h-4 text-muted" />}
                title={cat.label}
                desc=""
                enabled={notifPrefs[cat.key] !== false}
                onToggle={async () => {
                  const updated = { ...notifPrefs, [cat.key]: !notifPrefs[cat.key] };
                  setNotifPrefsState(updated);
                  await setNotificationPrefs(updated).catch(() => {});
                }}
                loading={false}
              />
            ))}
          </div>
        )}

        {/* Danger Zone */}
        <div className="card border-negative/20">
          <h2 className="text-xs text-negative uppercase tracking-wider mb-4 flex items-center gap-1.5"><AlertTriangle className="w-3.5 h-3.5" /> Danger Zone</h2>
          <p className="text-xs text-muted mb-3">Account deletion is permanent and cannot be undone.</p>
          <button className="text-xs text-negative font-medium px-3 py-2 rounded-lg border border-negative/20 hover:bg-negative/10 transition-colors">
            Contact support to delete account
          </button>
        </div>
      </div>
      <Footer />
    </div>
  );
}

function ToggleRow({ icon, title, desc, enabled, onToggle, loading }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-border last:border-b-0">
      <div className="flex items-center gap-3">
        {icon}
        <div>
          <div className="text-sm font-medium">{title}</div>
          <div className="text-xs text-muted mt-0.5">{desc}</div>
        </div>
      </div>
      <button onClick={onToggle} disabled={loading}
        className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${enabled ? 'bg-accent' : 'bg-surface-2'}`}>
        <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-transform ${enabled ? 'left-[22px]' : 'left-0.5'}`} />
      </button>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 48 48" className="flex-shrink-0">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
    </svg>
  );
}
