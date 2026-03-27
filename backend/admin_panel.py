"""
Server-side admin panel — pure HTML served by FastAPI at /admin.
Also provides API endpoints for the React admin page at /admin on frontend.
"""
import os
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import or_

from database import get_db
from middleware.auth import require_admin
from models import Prediction, Forecaster

router = APIRouter()

# Global scheduler timestamps — updated by job wrappers in main.py
scheduler_last_run = {}


@router.get("/api/admin/predictions")
def list_predictions_admin(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Prediction, Forecaster).join(
        Forecaster, Prediction.forecaster_id == Forecaster.id
    )
    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                Prediction.ticker.ilike(term),
                Prediction.context.ilike(term),
                Forecaster.name.ilike(term),
            )
        )
    total = query.count()
    rows = (
        query.order_by(Prediction.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return {
        "predictions": [
            {
                "id": p.id,
                "forecaster_id": p.forecaster_id,
                "forecaster_name": f.name,
                "exact_quote": p.exact_quote,
                "context": p.context,
                "source_url": p.source_url,
                "archive_url": p.archive_url,
                "ticker": p.ticker,
                "direction": p.direction,
                "target_price": float(p.target_price) if p.target_price else None,
                "outcome": p.outcome,
                "prediction_date": str(p.prediction_date)[:10] if p.prediction_date else None,
            }
            for p, f in rows
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
    }


@router.delete("/api/admin/predictions/{prediction_id}")
def delete_prediction_admin(
    prediction_id: int,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    p = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    # Clean up archive file
    if p.archive_url and p.archive_url.startswith("/archive/"):
        filepath = os.path.join(
            os.getenv("ARCHIVE_DIR", "/app/archive"),
            p.archive_url.replace("/archive/", ""),
        )
        if os.path.exists(filepath):
            os.remove(filepath)
    db.delete(p)
    db.commit()
    return {"status": "deleted", "id": prediction_id}


class BulkDeleteRequest(BaseModel):
    ids: List[int]


@router.delete("/api/admin/predictions/bulk")
def bulk_delete_predictions(
    data: BulkDeleteRequest,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    deleted = 0
    for pid in data.ids:
        p = db.query(Prediction).filter(Prediction.id == pid).first()
        if p:
            db.delete(p)
            deleted += 1
    db.commit()
    return {"status": "deleted", "count": deleted}


@router.get("/api/admin/scheduler-status")
def get_scheduler_status(admin=Depends(require_admin)):
    """Return status of all scheduled jobs with last_run timestamps."""
    jobs = [
        {"id": "full_scraper", "name": "Full Scraper", "interval_minutes": 60},
        {"id": "fast_scraper", "name": "Fast Scraper", "interval_minutes": 15},
        {"id": "evaluator", "name": "Evaluator", "interval_minutes": 15},
        {"id": "leaderboard", "name": "Leaderboard Refresh", "interval_minutes": 60},
        {"id": "finnhub_upgrades", "name": "Finnhub Upgrades", "interval_minutes": 120},
        {"id": "fmp_upgrades", "name": "FMP RSS", "interval_minutes": 120},
        {"id": "fmp_price_targets", "name": "FMP Price Targets", "interval_minutes": 120},
        {"id": "fmp_daily_grades", "name": "FMP Daily Grades", "interval_minutes": 180},
        {"id": "alphavantage", "name": "Alpha Vantage", "interval_minutes": 360},
        {"id": "benzinga_rss", "name": "Benzinga RSS", "interval_minutes": 60},
        {"id": "marketbeat_rss", "name": "MarketBeat RSS", "interval_minutes": 120},
        {"id": "yfinance", "name": "yfinance Recs", "interval_minutes": 180},
        {"id": "newsapi", "name": "NewsAPI", "interval_minutes": 240},
    ]
    now = datetime.utcnow()
    result = []
    for job in jobs:
        last_run = scheduler_last_run.get(job["id"])
        next_run = None
        if last_run:
            from datetime import timedelta
            next_run = last_run + timedelta(minutes=job["interval_minutes"])
        result.append({
            "id": job["id"],
            "name": job["name"],
            "interval_minutes": job["interval_minutes"],
            "last_run": last_run.isoformat() if last_run else None,
            "next_run": next_run.isoformat() if next_run else None,
            "status": "ok" if last_run and (now - last_run).total_seconds() < job["interval_minutes"] * 120 else "unknown",
        })
    return result


class PredictionCreate(BaseModel):
    forecaster_id: Optional[int] = None
    forecaster_name: Optional[str] = None
    exact_quote: str
    source_url: str
    archive_url: Optional[str] = None
    ticker: str
    direction: str = "bullish"
    target_price: Optional[float] = None
    prediction_date: Optional[str] = None
    window_days: int = 365
    outcome: str = "pending"


@router.post("/api/admin/predictions")
def create_prediction_admin(
    data: PredictionCreate,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    forecaster = None
    if data.forecaster_id:
        forecaster = db.query(Forecaster).filter(Forecaster.id == data.forecaster_id).first()
    elif data.forecaster_name:
        forecaster = db.query(Forecaster).filter(Forecaster.name.ilike(data.forecaster_name)).first()
    if not forecaster:
        raise HTTPException(status_code=404, detail="Forecaster not found")

    pred_date = datetime.utcnow()
    if data.prediction_date:
        try:
            pred_date = datetime.strptime(data.prediction_date, "%Y-%m-%d")
        except Exception:
            pass

    # Map "bull"/"bear" from form to model values
    direction = data.direction
    if direction == "bull":
        direction = "bullish"
    elif direction == "bear":
        direction = "bearish"

    p = Prediction(
        forecaster_id=forecaster.id,
        exact_quote=data.exact_quote,
        context=data.exact_quote[:200],
        source_url=data.source_url,
        ticker=data.ticker.upper(),
        direction=direction,
        target_price=data.target_price,
        outcome=data.outcome,
        prediction_date=pred_date,
        window_days=data.window_days,
        verified_by="manual",
    )
    if data.archive_url:
        p.archive_url = data.archive_url

    db.add(p)
    db.flush()

    # Archive proof if not provided
    if not p.archive_url:
        try:
            from archiver.screenshot import archive_proof_sync
            archive_url = archive_proof_sync(
                data.source_url, p.id,
                exact_quote=data.exact_quote,
                forecaster_name=forecaster.name,
                prediction_date=str(pred_date.date()),
            )
            if archive_url:
                p.archive_url = archive_url
                p.archived_at = datetime.utcnow()
        except Exception as e:
            print(f"[Admin] Archive error: {e}")

    db.commit()

    # Recalculate forecaster stats
    try:
        from utils import recalculate_forecaster_stats
        recalculate_forecaster_stats(data.forecaster_id, db)
    except Exception:
        pass

    return {"status": "created", "id": p.id, "archive_url": p.archive_url}


# ---------------------------------------------------------------------------
# Admin HTML page
# ---------------------------------------------------------------------------

ADMIN_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Eidolum Admin</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#07090a;color:#e8e8e6;font-family:'Segoe UI',system-ui,sans-serif;font-size:14px}
.topbar{background:#0e1212;border-bottom:1px solid rgba(255,255,255,0.08);padding:14px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100}
.topbar h1{font-size:1rem;font-weight:700;color:#00a878}
.topbar span{color:#555;font-size:.82rem}
.container{max-width:1200px;margin:0 auto;padding:24px}
.card{background:#0e1212;border:1px solid rgba(255,255,255,0.08);border-radius:10px;padding:20px;margin-bottom:20px}
.tabs{display:flex;gap:8px;margin-bottom:20px}
.tab-btn{padding:8px 18px;border-radius:7px;cursor:pointer;font-size:.88rem;font-weight:500;border:1px solid rgba(255,255,255,0.1);background:transparent;color:#888;transition:all .15s}
.tab-btn.active{background:#00a878;color:#000;border-color:#00a878;font-weight:600}
.tab-btn:hover:not(.active){border-color:#00a878;color:#00a878}
.tab-content{display:none}.tab-content.active{display:block}
input,select,textarea{width:100%;background:#111;border:1px solid rgba(255,255,255,0.12);border-radius:7px;padding:9px 12px;color:#e8e8e6;font-size:.88rem;outline:none;transition:border-color .15s}
input:focus,select:focus,textarea:focus{border-color:#00a878}
textarea{resize:vertical;height:80px}select option{background:#111}
label{display:block;font-size:.72rem;color:#666;letter-spacing:.06em;text-transform:uppercase;margin-bottom:5px;margin-top:12px}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
.btn{padding:9px 18px;border-radius:7px;border:none;font-weight:600;font-size:.88rem;cursor:pointer;transition:opacity .15s}
.btn:hover{opacity:.85}
.btn-primary{background:#00a878;color:#000}
.btn-secondary{background:transparent;border:1px solid rgba(255,255,255,0.15);color:#888}
.btn-danger{background:rgba(239,68,68,0.15);color:#ef4444;border:1px solid rgba(239,68,68,0.3);padding:5px 10px;font-size:.78rem;border-radius:5px;cursor:pointer}
.btn-row{display:flex;gap:10px;margin-top:18px}
.filters{display:flex;gap:10px;margin-bottom:14px;align-items:center;flex-wrap:wrap}
.filters input,.filters select{max-width:260px}
.count{color:#555;font-size:.82rem;margin-left:auto}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;color:#555;padding:8px 10px;border-bottom:1px solid rgba(255,255,255,0.06)}
td{padding:10px;border-bottom:1px solid rgba(255,255,255,0.04);vertical-align:middle}
tr:hover td{background:rgba(255,255,255,0.02)}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.72rem;font-weight:700}
.bullish{background:rgba(0,168,120,0.15);color:#00a878}
.bearish{background:rgba(239,68,68,0.15);color:#ef4444}
.proof-yes{color:#00a878;font-size:.8rem}.proof-no{color:#ef4444;font-size:.8rem}
.quote-cell{max-width:350px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#aaa}
.ticker-cell{font-weight:700;color:#00a878;min-width:55px}
.id-cell{color:#444;font-size:.8rem;min-width:40px}
.forecaster-cell{color:#ccc;min-width:120px}
.link{color:#4fbdff;text-decoration:none;font-size:.8rem}.link:hover{text-decoration:underline}
.msg{padding:10px 14px;border-radius:7px;margin-bottom:16px;font-size:.88rem;display:none}
.msg.success{background:rgba(0,168,120,0.1);border:1px solid #00a878;color:#00a878;display:block}
.msg.error{background:rgba(239,68,68,0.1);border:1px solid #ef4444;color:#ef4444;display:block}
.login-wrap{display:flex;align-items:center;justify-content:center;min-height:100vh}
.login-box{background:#0e1212;border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:32px;width:360px}
.login-box h2{font-size:1.3rem;margin-bottom:6px}.login-box p{color:#666;font-size:.85rem;margin-bottom:20px}
.stats{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}
.stat{background:#111;border:1px solid rgba(255,255,255,0.06);border-radius:8px;padding:12px 18px}
.stat-num{font-size:1.4rem;font-weight:700;color:#00a878}.stat-label{font-size:.75rem;color:#555;margin-top:2px}
</style>
</head>
<body>
<script>
const API=window.location.origin;
const TOKEN=sessionStorage.getItem('admin_token')||'';
let allPredictions=[],allForecasters=[];
async function apiFetch(url,opts={}){
  return fetch(API+url,{...opts,headers:{'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json',...(opts.headers||{})}});
}
function showMsg(id,text,type='success'){const el=document.getElementById(id);el.textContent=text;el.className='msg '+type;setTimeout(()=>el.style.display='none',5000)}
function switchTab(name){document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));document.querySelector('[data-tab="'+name+'"]').classList.add('active');document.getElementById('tab-'+name).classList.add('active')}
function renderPredictions(preds){
  const tbody=document.getElementById('pred-tbody');
  document.getElementById('pred-count').textContent=preds.length+' predictions';
  if(!preds.length){tbody.innerHTML='<tr><td colspan="8" style="text-align:center;color:#555;padding:40px">No predictions found</td></tr>';return}
  tbody.innerHTML=preds.map(p=>`
    <tr id="row-${p.id}">
      <td class="id-cell">#${p.id}</td>
      <td class="ticker-cell">${p.ticker||'\\u2014'}</td>
      <td><span class="badge ${p.direction}">${(p.direction||'').toUpperCase()}</span></td>
      <td class="forecaster-cell">${p.forecaster_name||''}</td>
      <td class="quote-cell" title="${(p.exact_quote||'').replace(/"/g,'&quot;')}">${p.exact_quote||p.context||'\\u2014'}</td>
      <td style="color:#666;font-size:0.8rem">${p.outcome||'pending'}</td>
      <td>${p.archive_url?'<span class="proof-yes">\\u2713 Proof</span>':'<span class="proof-no">\\u2717 None</span>'}</td>
      <td style="display:flex;gap:8px;align-items:center">
        ${p.source_url?`<a href="${p.source_url}" target="_blank" class="link">View</a>`:''}
        ${p.archive_url?`<a href="${p.archive_url}" target="_blank" class="link">Proof</a>`:''}
        <button class="btn-danger" onclick="deletePred(${p.id})">Delete</button>
      </td>
    </tr>`).join('');
}
function filterPredictions(){
  const search=document.getElementById('search').value.toLowerCase();
  const fid=document.getElementById('filter-forecaster').value;
  let preds=allPredictions;
  if(search) preds=preds.filter(p=>(p.exact_quote||'').toLowerCase().includes(search)||(p.ticker||'').toLowerCase().includes(search)||(p.forecaster_name||'').toLowerCase().includes(search));
  if(fid) preds=preds.filter(p=>p.forecaster_id==fid);
  renderPredictions(preds);
}
async function loadPredictions(){
  document.getElementById('pred-count').textContent='Loading...';
  const r=await apiFetch('/api/admin/predictions?limit=500');
  if(!r.ok){showMsg('pred-msg','Failed to load predictions','error');return}
  allPredictions=await r.json();
  renderPredictions(allPredictions);
  document.getElementById('stat-total').textContent=allPredictions.length;
  document.getElementById('stat-proof').textContent=allPredictions.filter(p=>p.archive_url).length;
  document.getElementById('stat-pending').textContent=allPredictions.filter(p=>p.outcome==='pending').length;
  document.getElementById('stat-correct').textContent=allPredictions.filter(p=>p.outcome==='correct').length;
}
async function loadForecasters(){
  const r=await fetch(API+'/api/leaderboard');
  if(!r.ok)return;
  allForecasters=await r.json();
  const sel1=document.getElementById('filter-forecaster');
  const sel2=document.getElementById('form-forecaster');
  allForecasters.forEach(f=>{[sel1,sel2].forEach(sel=>{const o=document.createElement('option');o.value=f.id;o.textContent=f.name;sel.appendChild(o)})});
}
async function deletePred(id){
  if(!confirm('Delete prediction #'+id+'?'))return;
  const r=await apiFetch('/api/admin/predictions/'+id,{method:'DELETE'});
  if(r.ok){allPredictions=allPredictions.filter(p=>p.id!==id);document.getElementById('row-'+id)?.remove();showMsg('pred-msg','Deleted #'+id);document.getElementById('stat-total').textContent=allPredictions.length}
  else showMsg('pred-msg','Delete failed','error');
}
async function addPrediction(){
  const forecaster_id=document.getElementById('form-forecaster').value;
  const exact_quote=document.getElementById('form-quote').value.trim();
  const source_url=document.getElementById('form-url').value.trim();
  const ticker=document.getElementById('form-ticker').value.trim().toUpperCase();
  if(!forecaster_id||!exact_quote||!source_url||!ticker){showMsg('add-msg','Fill all required fields','error');return}
  document.getElementById('btn-add').textContent='Saving...';document.getElementById('btn-add').disabled=true;
  const body={forecaster_id:parseInt(forecaster_id),exact_quote,source_url,ticker,direction:document.getElementById('form-direction').value,target_price:parseFloat(document.getElementById('form-target').value)||null,prediction_date:document.getElementById('form-date').value,window_days:parseInt(document.getElementById('form-window').value),outcome:document.getElementById('form-outcome').value};
  const r=await apiFetch('/api/admin/predictions',{method:'POST',body:JSON.stringify(body)});
  document.getElementById('btn-add').textContent='Add Prediction';document.getElementById('btn-add').disabled=false;
  if(r.ok){const d=await r.json();showMsg('add-msg','Prediction #'+d.id+' added'+(d.archive_url?' with proof':' (no proof)'));['form-quote','form-url','form-ticker','form-target'].forEach(id=>document.getElementById(id).value='');loadPredictions()}
  else{const e=await r.json().catch(()=>({}));showMsg('add-msg','Failed: '+(e.detail||JSON.stringify(e)),'error')}
}
window.onload=async function(){
  if(!TOKEN){document.getElementById('app').style.display='none';document.getElementById('login').style.display='flex';return}
  const test=await apiFetch('/api/admin/predictions?limit=1');
  if(!test.ok){sessionStorage.removeItem('admin_token');document.getElementById('app').style.display='none';document.getElementById('login').style.display='flex';return}
  document.getElementById('app').style.display='block';document.getElementById('login').style.display='none';
  document.getElementById('form-date').value=new Date().toISOString().split('T')[0];
  await Promise.all([loadPredictions(),loadForecasters()]);
};
function doLogin(){const pw=document.getElementById('login-pw').value;if(!pw)return;sessionStorage.setItem('admin_token',pw);location.reload()}
</script>

<div id="login" style="display:none"><div class="login-wrap"><div class="login-box">
<h2>Eidolum Admin</h2><p>Enter your admin password</p>
<label>Password</label><input type="password" id="login-pw" placeholder="Admin password" onkeydown="if(event.key==='Enter')doLogin()">
<div class="btn-row"><button class="btn btn-primary" style="width:100%" onclick="doLogin()">Login</button></div>
</div></div></div>

<div id="app" style="display:none">
<div class="topbar"><h1>Eidolum Admin</h1><span><a href="https://eidolum.com" target="_blank" style="color:#4fbdff;text-decoration:none">Back to site</a></span></div>
<div class="container">
<div class="stats">
<div class="stat"><div class="stat-num" id="stat-total">&mdash;</div><div class="stat-label">Total Predictions</div></div>
<div class="stat"><div class="stat-num" id="stat-proof">&mdash;</div><div class="stat-label">With Proof</div></div>
<div class="stat"><div class="stat-num" id="stat-pending">&mdash;</div><div class="stat-label">Pending</div></div>
<div class="stat"><div class="stat-num" id="stat-correct">&mdash;</div><div class="stat-label">Correct</div></div>
</div>
<div class="tabs">
<button class="tab-btn active" data-tab="predictions" onclick="switchTab('predictions')">Predictions</button>
<button class="tab-btn" data-tab="add" onclick="switchTab('add')">Add New</button>
</div>

<div id="tab-predictions" class="tab-content active">
<div id="pred-msg" class="msg"></div>
<div class="filters">
<input id="search" placeholder="Search quote, ticker, forecaster..." oninput="filterPredictions()">
<select id="filter-forecaster" onchange="filterPredictions()"><option value="">All forecasters</option></select>
<button class="btn btn-secondary" onclick="loadPredictions()">Refresh</button>
<span class="count" id="pred-count">Loading...</span>
</div>
<div class="card" style="padding:0;overflow-x:auto">
<table><thead><tr><th>ID</th><th>Ticker</th><th>Dir</th><th>Forecaster</th><th>Quote</th><th>Outcome</th><th>Proof</th><th>Actions</th></tr></thead>
<tbody id="pred-tbody"><tr><td colspan="8" style="text-align:center;color:#555;padding:40px">Loading...</td></tr></tbody></table>
</div></div>

<div id="tab-add" class="tab-content">
<div class="card" style="max-width:700px">
<div style="font-size:1.05rem;font-weight:600;margin-bottom:4px">Add New Prediction</div>
<div style="color:#666;font-size:.85rem;margin-bottom:4px">Proof card generated automatically from the source URL.</div>
<div id="add-msg" class="msg"></div>
<label>Forecaster *</label><select id="form-forecaster"><option value="">Select forecaster...</option></select>
<label>Exact Quote *</label><textarea id="form-quote" placeholder="e.g. Tesla will reach $500 by end of 2025"></textarea>
<label>Source URL *</label><input id="form-url" placeholder="https://x.com/user/status/123">
<div class="grid-2"><div><label>Ticker *</label><input id="form-ticker" placeholder="TSLA"></div>
<div><label>Direction *</label><select id="form-direction"><option value="bull">Bullish</option><option value="bear">Bearish</option></select></div></div>
<div class="grid-3"><div><label>Price Target ($)</label><input id="form-target" type="number" placeholder="500"></div>
<div><label>Date Said</label><input id="form-date" type="date"></div>
<div><label>Timeframe</label><select id="form-window"><option value="30">30 days</option><option value="90">90 days</option><option value="180">180 days</option><option value="365" selected>1 year</option><option value="730">2 years</option></select></div></div>
<label>Outcome</label><select id="form-outcome"><option value="pending">Pending</option><option value="correct">Correct</option><option value="incorrect">Incorrect</option></select>
<div class="btn-row"><button class="btn btn-primary" id="btn-add" onclick="addPrediction()">Add Prediction</button>
<button class="btn btn-secondary" onclick="['form-quote','form-url','form-ticker','form-target'].forEach(id=>document.getElementById(id).value='')">Clear</button></div>
</div></div>
</div></div>
</body></html>"""


@router.get("/admin", response_class=HTMLResponse)
def admin_page():
    """Serve the admin panel. Auth is handled client-side via Bearer token."""
    return HTMLResponse(content=ADMIN_HTML)
