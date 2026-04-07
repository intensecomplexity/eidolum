"""One-time cleanup: delete x_scraper predictions with year 1900 or empty context.
Run manually: cd backend && python3 scripts/cleanup_x_scraper_bad_rows.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

# Count bad rows
count_1900 = db.execute(text("""
    SELECT COUNT(*) FROM predictions
    WHERE verified_by = 'x_scraper'
    AND EXTRACT(YEAR FROM prediction_date) = 1900
""")).scalar() or 0

count_empty = db.execute(text("""
    SELECT COUNT(*) FROM predictions
    WHERE verified_by = 'x_scraper'
    AND (context IS NULL OR context = '' OR context = '@: ')
""")).scalar() or 0

# Show sample
rows = db.execute(text("""
    SELECT id, ticker, direction, prediction_date, LEFT(context, 60) as ctx
    FROM predictions
    WHERE verified_by = 'x_scraper'
    AND (EXTRACT(YEAR FROM prediction_date) = 1900 OR context IS NULL OR context = '' OR context = '@: ')
    ORDER BY id DESC LIMIT 10
""")).fetchall()

print(f"Found {count_1900} predictions with year=1900")
print(f"Found {count_empty} predictions with empty context")
print(f"Sample rows:")
for r in rows:
    print(f"  id={r[0]} ticker={r[1]} dir={r[2]} date={r[3]} ctx='{r[4]}'")

confirm = input(f"\nType DELETE to delete these bad rows: ")
if confirm.strip() != "DELETE":
    print("Aborted.")
    db.close()
    sys.exit(0)

result = db.execute(text("""
    DELETE FROM predictions
    WHERE verified_by = 'x_scraper'
    AND (EXTRACT(YEAR FROM prediction_date) = 1900 OR context IS NULL OR context = '' OR context = '@: ')
"""))
db.commit()
print(f"Deleted {result.rowcount} bad x_scraper predictions")
db.close()
