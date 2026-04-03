#!/usr/bin/env python3
"""
Eidolum Database Backup Script

Modes:
  --info     Print counts of recent changes (default)
  --full     Full pg_dump of the entire database
  --daily    Export rows created/updated in the last 24 hours as INSERT statements
  --plain    (with --full) Use plain SQL format instead of compressed

Usage:
  DATABASE_URL="postgresql://..." python backend/scripts/backup_db.py
  DATABASE_URL="postgresql://..." python backend/scripts/backup_db.py --full
  DATABASE_URL="postgresql://..." python backend/scripts/backup_db.py --daily
  python backend/scripts/backup_db.py "postgresql://..." --info

Requirements:
  --full mode: pg_dump (brew install postgresql / apt install postgresql-client)
  --info/--daily: psycopg2 (pip install psycopg2-binary)
"""
import os
import sys
import subprocess
import shutil
from datetime import datetime
from urllib.parse import urlparse


def _get_db_url():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    db_url = args[0] if args else os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("Error: No DATABASE_URL provided.")
        print()
        print("Usage:")
        print('  DATABASE_URL="postgresql://..." python backend/scripts/backup_db.py')
        print('  python backend/scripts/backup_db.py "postgresql://..." --info')
        print()
        print("Get the DATABASE_URL from Railway dashboard > Variables tab.")
        sys.exit(1)
    return db_url


def _connect(db_url):
    try:
        import psycopg2
    except ImportError:
        print("Error: psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)
    try:
        conn = psycopg2.connect(db_url)
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)


def _format_size(size):
    if size < 1024:
        return f"{size} bytes"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.2f} GB"


# ── INFO MODE ────────────────────────────────────────────────────────────────


def run_info(db_url):
    conn = _connect(db_url)
    cur = conn.cursor()

    print("Eidolum Database — Last 24 Hours")
    print("=" * 50)

    queries = [
        ("New predictions", "SELECT COUNT(*) FROM predictions WHERE created_at > NOW() - INTERVAL '24 hours'"),
        ("Updated predictions", "SELECT COUNT(*) FROM predictions WHERE evaluated_at > NOW() - INTERVAL '24 hours'"),
        ("URL backfills", """SELECT COUNT(*) FROM predictions
            WHERE source_url LIKE '%%benzinga.com/news%%'
            OR source_url LIKE '%%benzinga.com/markets%%'"""),
        ("Pending predictions", "SELECT COUNT(*) FROM predictions WHERE outcome = 'pending'"),
        ("No-data predictions", "SELECT COUNT(*) FROM predictions WHERE outcome = 'no_data'"),
        ("Evaluated predictions", "SELECT COUNT(*) FROM predictions WHERE outcome IN ('hit','near','miss','correct','incorrect')"),
        ("Total predictions", "SELECT COUNT(*) FROM predictions"),
        ("Total forecasters", "SELECT COUNT(*) FROM forecasters"),
        ("Total users", "SELECT COUNT(*) FROM users"),
        ("New users (24h)", "SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '24 hours'"),
    ]

    for label, sql in queries:
        try:
            cur.execute(sql)
            count = cur.fetchone()[0]
            print(f"  {label}: {count:,}")
        except Exception as e:
            print(f"  {label}: ERROR ({e})")
            conn.rollback()

    # Outcome breakdown
    print()
    print("Outcome Breakdown:")
    try:
        cur.execute("SELECT outcome, COUNT(*) FROM predictions GROUP BY outcome ORDER BY COUNT(*) DESC")
        for row in cur.fetchall():
            print(f"  {row[0] or 'NULL'}: {row[1]:,}")
    except Exception:
        pass

    conn.close()


# ── DAILY MODE ───────────────────────────────────────────────────────────────


DAILY_TABLES = [
    {
        "name": "predictions",
        "query": """SELECT * FROM predictions
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                       OR evaluated_at > NOW() - INTERVAL '24 hours'""",
    },
    {
        "name": "forecasters",
        "query": "SELECT * FROM forecasters WHERE created_at > NOW() - INTERVAL '24 hours'",
    },
    {
        "name": "users",
        "query": "SELECT * FROM users WHERE created_at > NOW() - INTERVAL '24 hours'",
    },
    {
        "name": "user_predictions",
        "query": """SELECT * FROM user_predictions
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                       OR evaluated_at > NOW() - INTERVAL '24 hours'""",
    },
    {
        "name": "notification_queue",
        "query": "SELECT * FROM notification_queue WHERE created_at > NOW() - INTERVAL '24 hours'",
    },
    {
        "name": "audit_log",
        "query": "SELECT * FROM audit_log WHERE created_at > NOW() - INTERVAL '24 hours'",
    },
]


def _escape_value(val):
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, datetime):
        return f"'{val.isoformat()}'"
    s = str(val).replace("'", "''")
    return f"'{s}'"


def run_daily(db_url):
    conn = _connect(db_url)
    cur = conn.cursor()

    timestamp = datetime.now().strftime("%Y-%m-%d")
    filename = f"eidolum_daily_{timestamp}.sql"

    print(f"Eidolum Daily Export — Last 24 Hours")
    print(f"Output: {filename}")
    print()

    total_rows = 0

    with open(filename, "w") as f:
        f.write(f"-- Eidolum daily export: {timestamp}\n")
        f.write(f"-- Rows created or updated in the last 24 hours\n\n")

        for table in DAILY_TABLES:
            try:
                cur.execute(table["query"])
                rows = cur.fetchall()
                cols = [desc[0] for desc in cur.description]

                f.write(f"\n-- ═══ {table['name'].upper()} ({len(rows)} rows) ═══\n\n")

                for row in rows:
                    values = ", ".join(_escape_value(v) for v in row)
                    col_names = ", ".join(cols)
                    f.write(f"INSERT INTO {table['name']} ({col_names}) VALUES ({values}) ON CONFLICT DO NOTHING;\n")

                total_rows += len(rows)
                print(f"  {table['name']}: {len(rows):,} rows")

            except Exception as e:
                f.write(f"\n-- ERROR on {table['name']}: {e}\n")
                print(f"  {table['name']}: ERROR ({e})")
                conn.rollback()

    conn.close()

    size = os.path.getsize(filename)
    print()
    print(f"Export complete: {filename} ({_format_size(size)}, {total_rows:,} total rows)")
    print(f"Restore with: psql YOUR_DB < {filename}")


# ── FULL MODE ────────────────────────────────────────────────────────────────


def run_full(db_url):
    plain_format = "--plain" in sys.argv

    if not shutil.which("pg_dump"):
        print("Error: pg_dump not found.")
        print("  macOS:   brew install postgresql")
        print("  Ubuntu:  sudo apt install postgresql-client")
        sys.exit(1)

    parsed = urlparse(db_url)
    host = parsed.hostname
    port = parsed.port or 5432
    dbname = parsed.path.lstrip("/")
    user = parsed.username
    password = parsed.password

    if not all([host, dbname, user]):
        print(f"Error: Could not parse DATABASE_URL.")
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    ext = "sql" if plain_format else "dump"
    filename = f"eidolum_full_backup_{timestamp}.{ext}"

    print(f"Eidolum Full Database Backup")
    print(f"  Host:   {host}:{port}")
    print(f"  DB:     {dbname}")
    print(f"  Format: {'plain SQL' if plain_format else 'custom (compressed)'}")
    print(f"  Output: {filename}")
    print()

    cmd = [
        "pg_dump",
        f"--host={host}", f"--port={port}",
        f"--username={user}", f"--dbname={dbname}",
        "--no-owner", "--no-privileges",
        f"--file={filename}",
    ]
    if plain_format:
        cmd.append("--format=plain")
    else:
        cmd += ["--format=custom", "--compress=9"]

    env = os.environ.copy()
    env["PGPASSWORD"] = password or ""

    print("Running pg_dump...")
    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            print(f"Error: pg_dump failed (exit code {result.returncode})")
            if result.stderr:
                print(result.stderr)
            sys.exit(1)

        size = os.path.getsize(filename)
        print()
        print(f"Backup complete: {filename} ({_format_size(size)})")
        if not plain_format:
            print(f"Restore with: pg_restore --no-owner --dbname=YOUR_DB {filename}")
        else:
            print(f"Restore with: psql YOUR_DB < {filename}")

    except subprocess.TimeoutExpired:
        print("Error: pg_dump timed out after 10 minutes")
        sys.exit(1)


# ── MAIN ─────────────────────────────────────────────────────────────────────


def main():
    db_url = _get_db_url()

    if "--full" in sys.argv:
        run_full(db_url)
    elif "--daily" in sys.argv:
        run_daily(db_url)
    else:
        run_info(db_url)


if __name__ == "__main__":
    main()
