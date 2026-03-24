# Eidolum

**Who should you actually listen to?**

Eidolum tracks predictions from 50+ finance YouTubers, Twitter analysts, and Reddit investors — then verifies who was actually right. Ranked by accuracy, not follower count.

## Live site
https://www.eidolum.com

## Features

- **Leaderboard** — Ranked table of all tracked forecasters by accuracy rate, alpha vs S&P 500, and sector performance
- **Forecaster Profiles** — Detailed prediction history, sector breakdown, and accuracy-over-time chart
- **Asset Consensus** — Search any ticker to see who's bullish/bearish and who has historically been right
- **Platform Intelligence** — Compare accuracy across YouTube, Twitter, Congress, Reddit, and Wall Street
- **Saved Predictions** — Bookmark and track predictions with live price movement
- **YouTube Sync** — Pull predictions from video titles/descriptions via YouTube Data API v3
- **Scoring Engine** — Compare predictions against real market data (yfinance) after 30/60/90 days

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + Vite + Tailwind CSS |
| Backend | Python FastAPI |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Market Data | yfinance |
| YouTube | YouTube Data API v3 |

## Quick Start

### Prerequisites

- Node.js 18+
- Python 3.10+

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt

# (Optional) Set your YouTube API key
export YOUTUBE_API_KEY=your_key_here

# Seed the database with demo data
python seed.py

# Start the API server
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 in your browser.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/leaderboard` | Ranked list of forecasters. Query params: `sector`, `period_days`, `direction` |
| GET | `/api/forecaster/{id}` | Detailed forecaster profile with prediction history |
| GET | `/api/asset/{ticker}/consensus` | Consensus view for a stock ticker |
| GET | `/api/platforms` | Platform overview with accuracy stats |
| GET | `/api/platforms/{id}` | Platform-specific leaderboard |
| POST | `/api/sync` | Trigger YouTube data pull and prediction evaluation |
| GET | `/api/health` | Health check |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `YOUTUBE_API_KEY` | YouTube Data API v3 key | (none — sync returns empty without it) |
| `DATABASE_URL` | SQLAlchemy database URL | `sqlite:///./eidolum.db` |
