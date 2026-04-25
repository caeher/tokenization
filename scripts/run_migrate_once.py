from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit


STATE_DIR = Path(os.getenv("MIGRATE_STATE_DIR", "/var/lib/tokenization-migrate")).resolve()
LOCK_DIR = STATE_DIR / ".lock"


def _resolve_database_identity() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        parts = urlsplit(database_url)
        host = parts.hostname or "unknown-host"
        port = parts.port or 0
        database = parts.path.lstrip("/") or "unknown-db"
        username = parts.username or "unknown-user"
        identity = f"url:{username}@{host}:{port}/{database}"
    else:
        identity = "env:{user}@{host}:{port}/{db}".format(
            user=os.getenv("POSTGRES_USER", "unknown-user").strip() or "unknown-user",
            host=os.getenv("POSTGRES_HOST", "unknown-host").strip() or "unknown-host",
            port=os.getenv("POSTGRES_PORT", "0").strip() or "0",
            db=os.getenv("POSTGRES_DB", "unknown-db").strip() or "unknown-db",
        )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _marker_path() -> Path:
    return STATE_DIR / f"{_resolve_database_identity()}.done"


def main() -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    marker_path = _marker_path()

    if marker_path.exists():
        print(f"Migration already completed for this database. Marker: {marker_path}", flush=True)
        return 0

    try:
        LOCK_DIR.mkdir()
    except FileExistsError:
        print(
            "Another migrate process appears to be running or left a stale lock at "
            f"{LOCK_DIR}. Remove it if no migration is active.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    try:
        command = [sys.executable, "-u", "scripts/db_bootstrap.py", "--migrate-only"]
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            print("Migration failed. Success marker was not written.", file=sys.stderr, flush=True)
            return completed.returncode

        marker_path.write_text("ok\n", encoding="utf-8")
        print(f"Migration completed and marker written to {marker_path}", flush=True)
        return 0
    finally:
        try:
            LOCK_DIR.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
