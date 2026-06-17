from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def _load_env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_PATH.exists():
        return values
    try:
        for line in ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        return values
    return values


def project_backend_mode() -> str:
    env_file = _load_env_file()
    forced = (os.environ.get("APP_DB_BACKEND") or env_file.get("APP_DB_BACKEND") or "").strip().lower()
    if forced in {"postgres", "postgresql", "postgre", "pg"}:
        return "postgres"
    if forced in {"sqlite", "sqlite3"}:
        return "sqlite"
    raw_dsn = (os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not raw_dsn:
        raw_dsn = (env_file.get("POSTGRES_URL") or env_file.get("DATABASE_URL") or "").strip()
    if raw_dsn.lower().startswith("postgres"):
        return "postgres"
    return "sqlite"


def guard_remote_sqlite_sync(*, force: bool = False, script_name: str = "") -> None:
    if force or project_backend_mode() != "postgres":
        return
    label = script_name or "sqlite_sync"
    raise SystemExit(
        f"{label}: abortado. El proyecto esta configurado en Postgres. "
        "No ejecutes syncs hacia SQLite remota salvo recuperacion controlada. "
        "Usa el sync *_postgres o repite con --force-sqlite-target si es intencional."
    )
