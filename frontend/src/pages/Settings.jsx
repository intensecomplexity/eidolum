import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Settings as SettingsIcon, Bell, BellOff, Mail, User, Shield, AlertTriangle, Globe, ExternalLink, Play } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import Footer from '../components/Footer';
import { setPriceAlerts, setEmailPreferences, getNotificationPrefs, setNotificationPrefs, updateSocialLinks, getEmailNotificationSettings, setEmailNotificationSettings } from '../api';

export default function Settings() {
  const navigate = useNavigate();
  const { isAuthenticated, user, logout } = useAuth();
  const [priceAlerts, setPriceAlertsState] = useState(true);
  const [weeklyDigest, setWeeklyDigestState] = useState(true);
  const [saving, setSaving] = useState('');
  const [notifPrefs, setNotifPrefsState] = useState(null);
  const [social, setSocial] = useState({ twitter_url: '', linkedin_url: '', youtube_url: '', website_url: '' });
  const [socialSaving, setSocialSaving] = useState(false);
  const [socialMsg, setSocialMsg] = useState('');
  const [emailNotif, setEmailNotif] = useState(true);
  const [notifFreq, setNotifFreq] = useState('daily');

  useEffect(() => {
    if (user) {
      setPriceAlertsState(user.price_alerts_enabled !== false);
      setWeeklyDigestState(user.weekly_digest_enabled !== false);
      getNotificationPrefs().then(setNotifPrefsState).catch(() => {});
      getEmailNotificationSettings().then(d => {
        setEmailNotif(d.email_notifications !== false);
        setNotifFreq(d.notification_frequency || 'daily');
      }).catch(() => {});
      setSocial({
        twitter_url: user.twitter_url || '',
        linkedin_url: user.linkedin_url || '',
        youtube_url: user.youtube_url || '',
        website_url: user.website_url || '',
      });
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

        {/* Watchlist Email Notifications */}
        <div className="card mb-4">
          <h2 className="text-xs text-muted uppercase tracking-wider mb-4 flex items-center gap-1.5"><Mail className="w-3.5 h-3.5" /> Watchlist Email Notifications</h2>

          <ToggleRow
            icon={emailNotif ? <Bell className="w-5 h-5 text-accent" /> : <BellOff className="w-5 h-5 text-muted" />}
            title="Email me about new analyst calls"
            desc="Get notified when analysts make new predictions on stocks in your watchlist."
            enabled={emailNotif}
            onToggle={async () => {
              const next = !emailNotif;
              setEmailNotif(next);
              await setEmailNotificationSettings(next, notifFreq).catch(() => {});
            }}
            loading={false}
          />

          {emailNotif && (
            <div className="mt-4 pl-8">
              <div className="text-xs text-muted mb-2">Frequency</div>
              <div className="flex gap-2">
                {['instant', 'daily', 'weekly'].map(freq => (
                  <button key={freq} onClick={async () => {
                    setNotifFreq(freq);
                    await setEmailNotificationSettings(emailNotif, freq).catch(() => {});
                  }}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                      notifFreq === freq
                        ? 'bg-accent/15 text-accent border border-accent/30'
                        : 'bg-surface-2 text-text-secondary border border-border'
                    }`}>
                    {freq === 'instant' ? 'Instant' : freq === 'daily' ? 'Daily Digest' : 'Weekly Digest'}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-muted mt-2">
                {notifFreq === 'instant' ? 'You\'ll get an email for each new analyst call.' :
                 notifFreq === 'daily' ? 'One email each weekday at 8 AM EST with all new calls.' :
                 'One email each Monday with the week\'s calls.'}
              </p>
            </div>
          )}
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

        {/* Social Links */}
        <div className="card mb-4">
          <h2 className="text-xs text-muted uppercase tracking-wider mb-4 flex items-center gap-1.5"><Globe className="w-3.5 h-3.5" /> Social Links</h2>
          <div className="space-y-3">
            <SocialInput label="Twitter / X" placeholder="https://x.com/yourusername" value={social.twitter_url}
              onChange={v => setSocial(s => ({ ...s, twitter_url: v }))} icon={<ExternalLink className="w-4 h-4" />} />
            <SocialInput label="LinkedIn" placeholder="https://linkedin.com/in/yourusername" value={social.linkedin_url}
              onChange={v => setSocial(s => ({ ...s, linkedin_url: v }))} icon={<span className="text-sm font-bold text-blue-400">in</span>} />
            <SocialInput label="YouTube" placeholder="https://youtube.com/@yourchannel" value={social.youtube_url}
              onChange={v => setSocial(s => ({ ...s, youtube_url: v }))} icon={<Play className="w-4 h-4" />} />
            <SocialInput label="Website" placeholder="https://yoursite.com" value={social.website_url}
              onChange={v => setSocial(s => ({ ...s, website_url: v }))} icon={<Globe className="w-4 h-4" />} />
          </div>
          <div className="flex items-center gap-3 mt-4">
            <button
              onClick={async () => {
                setSocialSaving(true); setSocialMsg('');
                try {
                  await updateSocialLinks(social);
                  setSocialMsg('Saved');
                  setTimeout(() => setSocialMsg(''), 3000);
                } catch (e) {
                  setSocialMsg(e.response?.data?.detail ? JSON.stringify(e.response.data.detail) : 'Error saving');
                } finally { setSocialSaving(false); }
              }}
              disabled={socialSaving}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-accent text-bg hover:bg-accent/90 transition-colors disabled:opacity-50"
            >
              {socialSaving ? 'Saving...' : 'Save Links'}
            </button>
            {socialMsg && (
              <span className={`text-xs font-medium ${socialMsg === 'Saved' ? 'text-positive' : 'text-negative'}`}>{socialMsg}</span>
            )}
          </div>
        </div>

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

function SocialInput({ label, placeholder, value, onChange, icon }) {
  return (
    <div>
      <label className="text-xs text-muted mb-1 block">{label}</label>
      <div className="flex items-center gap-2">
        <span className="w-8 h-8 flex items-center justify-center rounded bg-surface-2 border border-border shrink-0 text-muted">
          {icon}
        </span>
        <input
          type="url"
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          className="flex-1 bg-surface border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-muted/50 focus:outline-none focus:border-accent/50 font-mono"
        />
      </div>
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
