# How to Deploy Eidolum

## Architecture

- **Frontend**: React + Vite → Vercel (www.eidolum.com)
- **Backend**: FastAPI + SQLAlchemy → Railway (api.eidolum.com)
- **Database**: PostgreSQL → Railway (auto-provisioned)

---

## Step 1: Push to GitHub

```bash
git add .
git commit -m "Prepare for deployment"
git push origin main
```

---

## Step 2: Deploy Frontend to Vercel

1. Go to [vercel.com](https://vercel.com) → Sign up with GitHub
2. Click **New Project**
3. Import your GitHub repo
4. Set **Root Directory** to: `frontend`
5. **Framework Preset**: Vite
6. Add environment variables:
   - `VITE_API_URL` = `https://api.eidolum.com`
   - `VITE_APP_URL` = `https://www.eidolum.com`
   - `VITE_APP_NAME` = `Eidolum`
7. Click **Deploy**
8. Go to **Settings → Domains**
9. Add: `www.eidolum.com` and `eidolum.com`
10. Copy the DNS records Vercel shows you

---

## Step 3: Connect Domain DNS

1. Log into your domain registrar (GoDaddy/Namecheap/Cloudflare/etc.)
2. Go to DNS settings for `eidolum.com`
3. Add the records Vercel provides:
   - Type: `A`, Name: `@`, Value: `76.76.21.21`
   - Type: `CNAME`, Name: `www`, Value: `cname.vercel-dns.com`
4. Wait 10-30 minutes for DNS to propagate

---

## Step 4: Deploy Backend to Railway

1. Go to [railway.app](https://railway.app) → Sign up with GitHub
2. Click **New Project** → **Deploy from GitHub repo**
3. Select your repo → set **Root Directory** to `backend`
4. **Add a PostgreSQL database**:
   - Click **New** → **Database** → **PostgreSQL**
   - Railway auto-sets `DATABASE_URL` for you
5. Add environment variables in the Railway dashboard:
   - `YOUTUBE_API_KEY` = your YouTube Data API key
   - `ANTHROPIC_API_KEY` = your Anthropic API key
   - `RESEND_API_KEY` = your Resend API key
   - `FROM_EMAIL` = `alerts@eidolum.com`
   - `FRONTEND_URL` = `https://www.eidolum.com`
   - `ENVIRONMENT` = `production`
   - `SEED_DATA` = `true` (only for first deploy, then set to `false`)
6. Go to **Settings → Networking → Generate Domain**
   - It gives you something like `eidolum-backend.up.railway.app`
7. Add custom domain: `api.eidolum.com`
   - Add the CNAME record Railway shows you to your DNS:
   - Type: `CNAME`, Name: `api`, Value: (the Railway domain)

---

## Step 5: Run Database Setup

In Railway dashboard → your backend service → **Settings → Deploy** → run command:

```bash
python setup_db.py
```

This creates all tables. If `SEED_DATA=true`, it also loads demo data.

After the first successful seed, set `SEED_DATA=false` in Railway environment variables.

---

## Step 6: Submit to Google

1. Go to [Google Search Console](https://search.google.com/search-console)
2. Add property: `https://www.eidolum.com`
3. Verify via HTML tag (add the meta tag in `frontend/index.html`)
4. Submit sitemap: `https://www.eidolum.com/sitemap.xml`
5. Request indexing on the homepage URL

---

## Environment Variables Reference

### Frontend (Vercel)

| Variable | Production Value |
|----------|-----------------|
| `VITE_APP_NAME` | `Eidolum` |
| `VITE_APP_URL` | `https://www.eidolum.com` |
| `VITE_API_URL` | `https://api.eidolum.com` |

### Backend (Railway)

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Auto-set by Railway PostgreSQL addon |
| `YOUTUBE_API_KEY` | YouTube Data API v3 key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `RESEND_API_KEY` | Resend email API key |
| `FROM_EMAIL` | `alerts@eidolum.com` |
| `FRONTEND_URL` | `https://www.eidolum.com` |
| `NEWSLETTER_SEND_DAY` | `monday` |
| `NEWSLETTER_SEND_HOUR` | `8` |
| `ENVIRONMENT` | `production` |
| `SEED_DATA` | `true` first time, then `false` |

---

## Enabling Automatic Backups on Railway

1. Go to Railway dashboard → your project
2. Click the **Postgres** service (not eidolum, the database)
3. Go to **Settings** tab
4. Find **Backups** section
5. Enable automatic backups
6. Railway keeps 7 days of backups for free

### How to restore from backup if data is lost

1. Go to Postgres service → **Backups** tab
2. Find the backup from before the data loss
3. Click **Restore** → confirm
4. The database is restored to that point in time
5. Redeploy the eidolum service to reconnect

### Quick data health check

Hit this endpoint to verify data integrity at any time:

```
GET https://api.eidolum.com/api/admin/check-data
```

If predictions are missing, trigger a safe recovery:

```
GET https://api.eidolum.com/api/admin/reseed
```

---

## Troubleshooting

- **CORS errors**: Make sure `api.eidolum.com` DNS is pointing to Railway and the backend CORS config includes `https://www.eidolum.com`
- **Database connection**: Railway auto-provides `DATABASE_URL`. If it starts with `postgres://`, the app automatically rewrites it to `postgresql://` for SQLAlchemy
- **Build failures on Vercel**: Check that Root Directory is set to `frontend` and Framework Preset is `Vite`
- **502 on Railway**: Check logs; ensure `Procfile` has the correct uvicorn command and `$PORT` is used
