import { useEffect, useState, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Trash2, Shield, ShieldOff, UserX, ChevronLeft, ChevronRight, Search, RefreshCw } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import {
  getAdminDashboard, getAdminUsers, getAdminForecasters, getAdminAuditLog,
  banUser, unbanUser, deleteUserAccount, promoteAdmin, demoteAdmin,
  deleteForecasterAdmin, deletePredictionAdmin, getAdminPredictions,
  getSchedulerStatus,
} from '../api';

const TABS = ['Overview', 'Users', 'Forecasters', 'Predictions', 'Audit Log'];

export default function AdminDashboard() {
  const navigate = useNavigate();
  const { user, isAuthenticated } = useAuth();
  const [tab, setTab] = useState('Overview');
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);

  // Redirect non-admins
  useEffect(() => {
    if (!isAuthenticated) { navigate('/'); return; }
    if (user && !user.is_admin) { navigate('/'); return; }
  }, [isAuthenticated, user]);

  useEffect(() => {
    if (!user?.is_admin) return;
    setLoading(true);
    getAdminDashboard().then(setDashboard).catch(() => navigate('/')).finally(() => setLoading(false));
  }, [user]);

  function showToast(msg) { setToast(msg); setTimeout(() => setToast(null), 3000); }

  if (!user?.is_admin) return null;
  if (loading) return <div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" /></div>;

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-accent">Admin Panel</h1>
        <span className="text-muted text-xs font-mono">{user.email}</span>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 overflow-x-auto pills-scroll">
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
              tab === t ? 'bg-accent/10 text-accent border border-accent/20' : 'text-text-secondary border border-border'
            }`}>{t}</button>
        ))}
      </div>

      {tab === 'Overview' && <OverviewTab dashboard={dashboard} />}
      {tab === 'Users' && <UsersTab showToast={showToast} isSuperAdmin={user.email === 'nimrodryder@gmail.com'} />}
      {tab === 'Forecasters' && <ForecastersTab showToast={showToast} />}
      {tab === 'Predictions' && <PredictionsTab showToast={showToast} />}
      {tab === 'Audit Log' && <AuditTab />}

      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[70] px-4 py-2.5 rounded-xl text-xs font-medium bg-surface border border-border shadow-lg">
          {toast}
        </div>
      )}
    </div>
  );
}


function StatCard({ label, value }) {
  return (
    <div className="bg-surface border border-border rounded-lg p-4 text-center">
      <div className="font-mono text-2xl font-bold text-accent">{value ?? '--'}</div>
      <div className="text-muted text-xs mt-1">{label}</div>
    </div>
  );
}


function OverviewTab({ dashboard }) {
  const d = dashboard || {};
  return (
    <div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <StatCard label="Predictions" value={d.total_predictions?.toLocaleString()} />
        <StatCard label="Forecasters" value={d.total_forecasters?.toLocaleString()} />
        <StatCard label="Users" value={d.total_users?.toLocaleString()} />
        <StatCard label="DB Size" value={d.db_size || '?'} />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-6">
        <StatCard label="Pending" value={d.pending_predictions?.toLocaleString()} />
        <StatCard label="Evaluated" value={d.evaluated_predictions?.toLocaleString()} />
        <StatCard label="User Predictions" value={d.total_user_predictions?.toLocaleString()} />
      </div>

      {/* Admins list */}
      {d.admins?.length > 0 && (
        <div className="card mb-6">
          <h3 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Current Admins</h3>
          <div className="space-y-2">
            {d.admins.map(a => (
              <div key={a.id} className="flex items-center gap-2 text-sm">
                <Shield className="w-3.5 h-3.5 text-accent" />
                <span className="font-medium">{a.username}</span>
                <span className="text-muted text-xs font-mono">{a.email}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent audit */}
      {d.recent_actions?.length > 0 && (
        <div className="card">
          <h3 className="text-sm font-semibold text-muted uppercase tracking-wider mb-3">Recent Actions</h3>
          <div className="space-y-2">
            {d.recent_actions.map(a => (
              <div key={a.id} className="flex items-center gap-2 text-xs">
                <span className="text-muted font-mono shrink-0">{a.created_at?.slice(0, 16)}</span>
                <span className="text-text-secondary">{a.admin_email}</span>
                <span className="text-accent">{a.action}</span>
                {a.details && <span className="text-muted truncate">{a.details}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}


function UsersTab({ showToast, isSuperAdmin }) {
  const [users, setUsers] = useState(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);

  const load = useCallback(() => {
    getAdminUsers({ search, page }).then(setUsers).catch(() => {});
  }, [search, page]);

  useEffect(() => { load(); }, [load]);

  async function handleAction(userId, action) {
    const actions = {
      ban: { fn: banUser, confirm: 'Ban this user?', msg: 'User banned' },
      unban: { fn: unbanUser, confirm: null, msg: 'User unbanned' },
      delete: { fn: deleteUserAccount, confirm: 'PERMANENTLY delete this user and all their data?', msg: 'User deleted' },
      promote: { fn: promoteAdmin, confirm: 'Make this user an admin?', msg: 'User promoted to admin' },
      demote: { fn: demoteAdmin, confirm: 'Remove admin access?', msg: 'Admin access removed' },
    };
    const a = actions[action];
    if (a.confirm && !confirm(a.confirm)) return;
    try { await a.fn(userId); showToast(a.msg); load(); } catch (e) { showToast(e.response?.data?.detail || 'Error'); }
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
            placeholder="Search users..." className="w-full pl-9 pr-3 py-2 bg-surface border border-border rounded-lg text-sm" />
        </div>
        <button onClick={load} className="text-muted"><RefreshCw className="w-4 h-4" /></button>
      </div>

      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted text-[10px] uppercase tracking-wider border-b border-border">
              <th className="px-3 py-2">ID</th>
              <th className="px-3 py-2">Username</th>
              <th className="px-3 py-2">Email</th>
              <th className="px-3 py-2">Provider</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users?.users?.map(u => (
              <tr key={u.id} className="border-b border-border/30 hover:bg-surface-2/30">
                <td className="px-3 py-2 text-muted font-mono text-xs">#{u.id}</td>
                <td className="px-3 py-2">
                  <Link to={`/profile/${u.id}`} className="text-accent hover:underline">{u.username}</Link>
                </td>
                <td className="px-3 py-2 text-xs text-muted font-mono">{u.email}</td>
                <td className="px-3 py-2 text-xs">{u.auth_provider}</td>
                <td className="px-3 py-2">
                  {u.is_admin && <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-accent/10 text-accent mr-1">ADMIN</span>}
                  {u.is_banned && <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-negative/10 text-negative">BANNED</span>}
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1">
                    {!u.is_admin && !u.is_banned && (
                      <button onClick={() => handleAction(u.id, 'ban')} className="text-[10px] text-muted hover:text-negative px-1">Ban</button>
                    )}
                    {u.is_banned && (
                      <button onClick={() => handleAction(u.id, 'unban')} className="text-[10px] text-muted hover:text-positive px-1">Unban</button>
                    )}
                    {!u.is_admin && (
                      <>
                        <button onClick={() => handleAction(u.id, 'promote')} className="text-[10px] text-muted hover:text-accent px-1">Admin</button>
                        <button onClick={() => handleAction(u.id, 'delete')} className="text-[10px] text-muted hover:text-negative px-1">Delete</button>
                      </>
                    )}
                    {u.is_admin && isSuperAdmin && u.email !== 'nimrodryder@gmail.com' && (
                      <button onClick={() => handleAction(u.id, 'demote')} className="text-[10px] text-muted hover:text-negative px-1">Demote</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {users && <Paginator page={page} totalPages={users.total_pages} setPage={setPage} total={users.total} />}
    </div>
  );
}


function ForecastersTab({ showToast }) {
  const [data, setData] = useState(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);

  const load = useCallback(() => {
    getAdminForecasters({ search, page }).then(setData).catch(() => {});
  }, [search, page]);

  useEffect(() => { load(); }, [load]);

  async function handleDelete(id, name) {
    if (!confirm(`Delete "${name}" and ALL their predictions? This cannot be undone.`)) return;
    try { await deleteForecasterAdmin(id); showToast(`Deleted ${name}`); load(); } catch (e) { showToast('Error'); }
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
            placeholder="Search forecasters..." className="w-full pl-9 pr-3 py-2 bg-surface border border-border rounded-lg text-sm" />
        </div>
      </div>

      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted text-[10px] uppercase tracking-wider border-b border-border">
              <th className="px-3 py-2">ID</th>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Platform</th>
              <th className="px-3 py-2 text-right">Predictions</th>
              <th className="px-3 py-2 text-right">Accuracy</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {data?.forecasters?.map(f => (
              <tr key={f.id} className="border-b border-border/30 hover:bg-surface-2/30">
                <td className="px-3 py-2 text-muted font-mono text-xs">#{f.id}</td>
                <td className="px-3 py-2">
                  <Link to={`/forecaster/${f.id}`} className="text-accent hover:underline">{f.name}</Link>
                </td>
                <td className="px-3 py-2 text-xs">{f.platform}</td>
                <td className="px-3 py-2 text-right font-mono text-xs">{f.total_predictions}</td>
                <td className="px-3 py-2 text-right font-mono text-xs">{f.accuracy_score?.toFixed(1)}%</td>
                <td className="px-3 py-2 text-right">
                  <button onClick={() => handleDelete(f.id, f.name)} className="text-muted hover:text-negative"><Trash2 className="w-3.5 h-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && <Paginator page={page} totalPages={data.total_pages} setPage={setPage} total={data.total} />}
    </div>
  );
}


function PredictionsTab({ showToast }) {
  const [data, setData] = useState(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);

  const adminHeaders = () => ({ Authorization: `Bearer ${sessionStorage.getItem('admin_token') || localStorage.getItem('eidolum_token') || ''}` });

  const load = useCallback(() => {
    getAdminPredictions({ page, per_page: 50, search }).then(setData).catch(() => {});
  }, [search, page]);

  useEffect(() => { load(); }, [load]);

  async function handleDelete(id) {
    if (!confirm(`Delete prediction #${id}?`)) return;
    try { await deletePredictionAdmin(id); showToast(`Deleted #${id}`); load(); } catch { showToast('Error'); }
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
          <input value={search} onChange={e => { setSearch(e.target.value); setPage(1); }}
            placeholder="Search ticker or forecaster..." className="w-full pl-9 pr-3 py-2 bg-surface border border-border rounded-lg text-sm" />
        </div>
      </div>

      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted text-[10px] uppercase tracking-wider border-b border-border">
              <th className="px-3 py-2">ID</th>
              <th className="px-3 py-2">Date</th>
              <th className="px-3 py-2">Forecaster</th>
              <th className="px-3 py-2">Ticker</th>
              <th className="px-3 py-2">Dir</th>
              <th className="px-3 py-2">Outcome</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {data?.predictions?.map(p => (
              <tr key={p.id} className="border-b border-border/30 hover:bg-surface-2/30">
                <td className="px-3 py-2 text-muted font-mono text-xs">#{p.id}</td>
                <td className="px-3 py-2 text-xs font-mono text-muted">{p.prediction_date?.slice(0, 10)}</td>
                <td className="px-3 py-2 text-xs">{p.forecaster_name}</td>
                <td className="px-3 py-2 font-mono font-bold text-accent">{p.ticker}</td>
                <td className="px-3 py-2">
                  <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${p.direction === 'bullish' ? 'text-positive bg-positive/10' : 'text-negative bg-negative/10'}`}>
                    {p.direction === 'bullish' ? 'BULL' : 'BEAR'}
                  </span>
                </td>
                <td className="px-3 py-2 text-xs text-muted">{p.outcome}</td>
                <td className="px-3 py-2 text-right">
                  <button onClick={() => handleDelete(p.id)} className="text-muted hover:text-negative"><Trash2 className="w-3.5 h-3.5" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && <Paginator page={page} totalPages={data.total_pages} setPage={setPage} total={data.total} />}
    </div>
  );
}


function AuditTab() {
  const [data, setData] = useState(null);
  const [page, setPage] = useState(1);

  useEffect(() => {
    getAdminAuditLog({ page }).then(setData).catch(() => {});
  }, [page]);

  return (
    <div>
      <div className="bg-surface border border-border rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted text-[10px] uppercase tracking-wider border-b border-border">
              <th className="px-3 py-2">Time</th>
              <th className="px-3 py-2">Admin</th>
              <th className="px-3 py-2">Action</th>
              <th className="px-3 py-2">Target</th>
              <th className="px-3 py-2">Details</th>
              <th className="px-3 py-2">IP</th>
            </tr>
          </thead>
          <tbody>
            {data?.entries?.map(a => (
              <tr key={a.id} className="border-b border-border/30">
                <td className="px-3 py-2 text-xs font-mono text-muted whitespace-nowrap">{a.created_at?.slice(0, 16)}</td>
                <td className="px-3 py-2 text-xs">{a.admin_email}</td>
                <td className="px-3 py-2 text-xs text-accent">{a.action}</td>
                <td className="px-3 py-2 text-xs text-muted">{a.target_type} #{a.target_id}</td>
                <td className="px-3 py-2 text-xs text-text-secondary max-w-[300px] truncate">{a.details}</td>
                <td className="px-3 py-2 text-xs text-muted font-mono">{a.ip_address}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data && <Paginator page={page} totalPages={data.total_pages} setPage={setPage} total={data.total} />}
    </div>
  );
}


function Paginator({ page, totalPages, setPage, total }) {
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-center gap-4 mt-4">
      <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}
        className="inline-flex items-center gap-1 text-sm text-accent disabled:text-muted">
        <ChevronLeft className="w-4 h-4" /> Prev
      </button>
      <span className="text-muted text-sm font-mono">{page} / {totalPages} ({total})</span>
      <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
        className="inline-flex items-center gap-1 text-sm text-accent disabled:text-muted">
        Next <ChevronRight className="w-4 h-4" />
      </button>
    </div>
  );
}
