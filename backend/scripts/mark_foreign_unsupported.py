"""One-time script: mark foreign-listed no_data predictions as 'unsupported'.
Run manually: cd backend && python3 scripts/mark_foreign_unsupported.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

result = db.execute(text("""
    UPDATE predictions
    SET outcome = 'unsupported', updated_at = NOW()
    WHERE outcome = 'no_data'
    AND (ticker LIKE '%.L' OR ticker LIKE '%.TO' OR ticker LIKE '%.HK'
         OR ticker LIKE '%.PA' OR ticker LIKE '%.DE' OR ticker LIKE '%.SS'
         OR ticker LIKE '%.SZ' OR ticker LIKE '%.AX' OR ticker LIKE '%.SI'
         OR ticker LIKE '%.MI' OR ticker LIKE '%.MC' OR ticker LIKE '%.AS'
         OR ticker LIKE '%.BR' OR ticker LIKE '%.ST' OR ticker LIKE '%.HE'
         OR ticker LIKE '%.OL' OR ticker LIKE '%.CO' OR ticker LIKE '%.T'
         OR ticker LIKE '%.KS')
"""))
db.commit()

print(f"Marked {result.rowcount} foreign no_data predictions as 'unsupported'")
db.close()
