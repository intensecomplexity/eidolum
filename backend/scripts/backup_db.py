#!/usr/bin/env python3
"""
Eidolum Database Backup Script

Downloads a full PostgreSQL dump of the Eidolum database.

Usage:
  # Option 1: Set DATABASE_URL env var
  DATABASE_URL="postgresql://user:pass@host:port/db" python backend/scripts/backup_db.py

  # Option 2: Pass as argument
  python backend/scripts/backup_db.py "postgresql://user:pass@host:port/db"

  # Option 3: Plain SQL format (readable, larger file)
  python backend/scripts/backup_db.py --plain "postgresql://..."

Requirements:
  pg_dump must be installed:
    macOS:  brew install postgresql
    Linux:  apt install postgresql-client
    Windows: install PostgreSQL and add bin/ to PATH
"""
import os
import sys
import subprocess
import shutil
from datetime import datetime
from urllib.parse import urlparse


def main():
    # Parse arguments
    plain_format = "--plain" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    # Get DATABASE_URL
    db_url = args[0] if args else os.environ.get("DATABASE_URL", "")

    if not db_url:
        print("Error: No DATABASE_URL provided.")
        print()
        print("Usage:")
        print('  DATABASE_URL="postgresql://..." python backend/scripts/backup_db.py')
        print('  python backend/scripts/backup_db.py "postgresql://..."')
        print()
        print("Get the DATABASE_URL from Railway dashboard > Variables tab.")
        sys.exit(1)

    # Check pg_dump is installed
    if not shutil.which("pg_dump"):
        print("Error: pg_dump not found.")
        print()
        print("Install PostgreSQL client tools:")
        print("  macOS:   brew install postgresql")
        print("  Ubuntu:  sudo apt install postgresql-client")
        print("  Windows: install PostgreSQL and add bin/ to PATH")
        sys.exit(1)

    # Parse the URL
    parsed = urlparse(db_url)
    host = parsed.hostname
    port = parsed.port or 5432
    dbname = parsed.path.lstrip("/")
    user = parsed.username
    password = parsed.password

    if not all([host, dbname, user]):
        print(f"Error: Could not parse DATABASE_URL. Got host={host}, db={dbname}, user={user}")
        sys.exit(1)

    # Build output filename
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    ext = "sql" if plain_format else "dump"
    filename = f"eidolum_backup_{timestamp}.{ext}"

    print(f"Eidolum Database Backup")
    print(f"  Host:   {host}:{port}")
    print(f"  DB:     {dbname}")
    print(f"  User:   {user}")
    print(f"  Format: {'plain SQL' if plain_format else 'custom (compressed)'}")
    print(f"  Output: {filename}")
    print()

    # Build pg_dump command
    cmd = [
        "pg_dump",
        f"--host={host}",
        f"--port={port}",
        f"--username={user}",
        f"--dbname={dbname}",
        "--no-owner",
        "--no-privileges",
        f"--file={filename}",
    ]

    if plain_format:
        cmd.append("--format=plain")
    else:
        cmd.append("--format=custom")
        cmd.append("--compress=9")

    # Set password via environment (pg_dump reads PGPASSWORD)
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

        # Report success
        size = os.path.getsize(filename)
        if size < 1024:
            size_str = f"{size} bytes"
        elif size < 1024 * 1024:
            size_str = f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            size_str = f"{size / (1024 * 1024):.1f} MB"
        else:
            size_str = f"{size / (1024 * 1024 * 1024):.2f} GB"

        print()
        print(f"Backup complete: {filename} ({size_str})")
        if not plain_format:
            print(f"Restore with: pg_restore --no-owner --dbname=YOUR_DB {filename}")
        else:
            print(f"Restore with: psql YOUR_DB < {filename}")

    except subprocess.TimeoutExpired:
        print("Error: pg_dump timed out after 10 minutes")
        sys.exit(1)
    except FileNotFoundError:
        print("Error: pg_dump command not found")
        sys.exit(1)


if __name__ == "__main__":
    main()
