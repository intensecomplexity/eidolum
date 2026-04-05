"""Quick stats check — run via: railway run python scripts/check_stats.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

print('=== PREDICTIONS BY YEAR ===')
rows = db.execute(text(
    "SELECT EXTRACT(YEAR FROM prediction_date)::int as year, COUNT(*) "
    "FROM predictions GROUP BY year ORDER BY year"
)).fetchall()
total = 0
for r in rows:
    print(f'  {r[0]}: {r[1]:,}')
    total += r[1]
print(f'  TOTAL: {total:,}')

print()
print('=== PREDICTIONS BY SOURCE ===')
rows = db.execute(text(
    "SELECT COALESCE(verified_by, 'unknown'), COUNT(*) "
    "FROM predictions GROUP BY verified_by ORDER BY COUNT(*) DESC"
)).fetchall()
for r in rows:
    print(f'  {r[0]:20s} {r[1]:>8,}')

print()
print('=== OUTCOME DISTRIBUTION ===')
rows = db.execute(text(
    "SELECT outcome, COUNT(*) FROM predictions GROUP BY outcome ORDER BY COUNT(*) DESC"
)).fetchall()
for r in rows:
    print(f'  {r[0]:20s} {r[1]:>8,}')

print()
print('=== FMP BACKFILL STATUS ===')
try:
    rows = db.execute(text(
        "SELECT key, value FROM config WHERE key LIKE '%fmp%' OR key LIKE '%backfill%'"
    )).fetchall()
    if rows:
        for r in rows:
            print(f'  {r[0]}: {r[1]}')
    else:
        print('  No config entries found')
except Exception as e:
    print(f'  (no config table: {e})')

print()
print('=== LAST 24H INSERTS BY SOURCE ===')
rows = db.execute(text(
    "SELECT COALESCE(verified_by, 'unknown'), COUNT(*) "
    "FROM predictions WHERE created_at > NOW() - INTERVAL '24 hours' "
    "GROUP BY verified_by ORDER BY COUNT(*) DESC"
)).fetchall()
if rows:
    for r in rows:
        print(f'  {r[0]:20s} {r[1]:>8,}')
else:
    print('  No predictions in last 24h')

db.close()
