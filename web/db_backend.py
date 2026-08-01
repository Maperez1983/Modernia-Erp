from __future__ import annotations

import os
import queue
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"


def _load_env_file() -> None:
    # Keep this lightweight and dependency-free (no python-dotenv).
    if not ENV_PATH.exists():
        return
    try:
        with ENV_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                key, value = raw.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        return


_load_env_file()

_CONN_TRACKER: Any | None = None
_CONN_TRACKER_LOCK = threading.Lock()


def set_conn_tracker(callback):
    """
    Register a connection tracker callback (best-effort).

    The web server uses this to auto-close DB connections opened during a request
    even if a code path forgets to close them (important with Postgres pools).

    Returns a token that can be passed to `reset_conn_tracker()` to restore the
    previous tracker.
    """
    global _CONN_TRACKER
    with _CONN_TRACKER_LOCK:
        prev = _CONN_TRACKER
        _CONN_TRACKER = callback
        return prev


def reset_conn_tracker(token):
    """Restore a previous tracker token returned by `set_conn_tracker()`."""
    global _CONN_TRACKER
    with _CONN_TRACKER_LOCK:
        _CONN_TRACKER = token


def _notify_conn_tracker(conn):
    cb = None
    with _CONN_TRACKER_LOCK:
        cb = _CONN_TRACKER
    if not cb:
        return
    try:
        cb(conn)
    except Exception:
        # Best effort: never fail opening a connection because tracking failed.
        return


def is_postgres_enabled():
    forced = (os.environ.get("APP_DB_BACKEND") or "").strip().lower()
    if forced in {"sqlite", "sqlite3"}:
        return False
    # Toleramos errores comunes de escritura en Render (p.ej. "postgre").
    if forced in {"postgres", "postgresql", "postgre", "pg"}:
        return True
    # En Render, DATABASE_URL suele ser "internalConnectionString" (host privado).
    # Permitimos override explícito con POSTGRES_URL (p.ej. externalConnectionString) sin tener que tocar DATABASE_URL.
    raw = (os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or "").strip()
    return raw.lower().startswith("postgres")


def _postgres_dsn():
    raw = (os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or "").strip()
    return raw


def _strip_collate_nocase(sql):
    return re.sub(r"\s+COLLATE\s+NOCASE\b", "", sql, flags=re.IGNORECASE)


def _strip_foreign_keys(sql):
    # Postgres requires referenced tables to exist before adding FKs.
    # We don't rely on DB-level FK enforcement in the app, so we drop them to keep DDL order-agnostic.
    if not re.match(r"^\s*CREATE\s+TABLE\b", sql, flags=re.IGNORECASE):
        return sql
    lines = []
    for line in sql.splitlines():
        if re.search(r"\bFOREIGN\s+KEY\b", line, flags=re.IGNORECASE):
            continue
        lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = re.sub(r",\s*\)", "\n)", cleaned)
    return cleaned


def _rewrite_insert_or_ignore(sql):
    m = re.match(r"^\s*INSERT\s+OR\s+IGNORE\s+", sql, flags=re.IGNORECASE)
    if not m:
        return sql
    rewritten = re.sub(r"^\s*INSERT\s+OR\s+IGNORE\s+", "INSERT ", sql, flags=re.IGNORECASE)
    # Append ON CONFLICT DO NOTHING if not already present.
    if re.search(r"\bON\s+CONFLICT\b", rewritten, flags=re.IGNORECASE):
        return rewritten
    return rewritten.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"


def _rewrite_insert_or_replace(sql):
    # Best-effort: INSERT OR REPLACE INTO t (a,b,...) VALUES (...)  -> INSERT ... ON CONFLICT (id) DO UPDATE ...
    # Assumes a primary key column named "id" exists and is included in the column list.
    m = re.match(
        r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+([A-Za-z0-9_\".]+)\s*\((?P<cols>.*?)\)\s*VALUES\s*\(",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return sql
    cols_raw = m.group("cols") or ""
    cols = [c.strip() for c in cols_raw.split(",") if c.strip()]
    cols_norm = [c.strip('"').strip().lower() for c in cols]
    if "id" not in cols_norm:
        return sql
    # Build SET clause for all columns except id.
    set_cols = []
    for col, norm in zip(cols, cols_norm):
        if norm == "id":
            continue
        set_cols.append(f"{col} = EXCLUDED.{col}")
    if not set_cols:
        return re.sub(r"^\s*INSERT\s+OR\s+REPLACE\s+", "INSERT ", sql, flags=re.IGNORECASE)
    base = re.sub(r"^\s*INSERT\s+OR\s+REPLACE\s+", "INSERT ", sql, flags=re.IGNORECASE).rstrip().rstrip(";")
    if re.search(r"\bON\s+CONFLICT\b", base, flags=re.IGNORECASE):
        return base
    # Columnas derivadas del SQL parseado; no depende de entrada externa.
    return base + " ON CONFLICT (id) DO UPDATE SET " + ", ".join(set_cols)  # nosec B608


def _qmark_to_pyformat(sql):
    # Convert SQLite qmark paramstyle ("?") into psycopg "%s" while skipping quoted strings and comments.
    out = []
    in_squote = False
    in_dquote = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if in_line_comment:
            out.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            out.append(ch)
            if ch == "*" and nxt == "/":
                out.append(nxt)
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if not in_squote and not in_dquote:
            if ch == "-" and nxt == "-":
                out.append(ch)
                out.append(nxt)
                in_line_comment = True
                i += 2
                continue
            if ch == "/" and nxt == "*":
                out.append(ch)
                out.append(nxt)
                in_block_comment = True
                i += 2
                continue
        if ch == "'" and not in_dquote:
            out.append(ch)
            if in_squote and nxt == "'":
                # Escaped single quote
                out.append(nxt)
                i += 2
                continue
            in_squote = not in_squote
            i += 1
            continue
        if ch == '"' and not in_squote:
            out.append(ch)
            in_dquote = not in_dquote
            i += 1
            continue
        if ch == "?" and not in_squote and not in_dquote:
            out.append("%s")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)

def _escape_psycopg_pyformat_percents(sql: str) -> str:
    # psycopg3 pyformat placeholders use %s (and %b/%t). Any other % sequence must be escaped as %%,
    # otherwise psycopg raises: "only '%s', '%b', '%t' are allowed as placeholders".
    out = []
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch != "%":
            out.append(ch)
            i += 1
            continue
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if nxt in {"s", "b", "t", "%"}:
            out.append("%")
            if nxt:
                out.append(nxt)
            i += 2
            continue
        out.append("%%")
        i += 1
    return "".join(out)


def translate_sqlite_sql_to_postgres(sql):
    if not isinstance(sql, str):
        return sql
    text = sql
    text = _strip_collate_nocase(text)
    # Nota: No reescribimos ROUND(...) aquí porque también se ejecuta sobre DDL (CREATE FUNCTION),
    # y eso puede “autorreferenciar” nuestras funciones shim. En su lugar, creamos overloads de
    # round(real/int) en ensure_postgres_sqlite_compat.
    # SQLite GROUP_CONCAT -> Postgres STRING_AGG.
    # - GROUP_CONCAT(x) -> STRING_AGG(x, ',')
    # - GROUP_CONCAT(DISTINCT x) -> STRING_AGG(DISTINCT x, ',')
    # - GROUP_CONCAT(x, sep) -> STRING_AGG(x, sep)
    text = re.sub(
        r"\bGROUP_CONCAT\s*\(\s*DISTINCT\s+(.+?)\s*\)",
        r"STRING_AGG(DISTINCT \1, ',')",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r"\bGROUP_CONCAT\s*\(\s*([^,()]+?)\s*\)",
        r"STRING_AGG(\1, ',')",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bGROUP_CONCAT\s*\(\s*(.+?)\s*,\s*(.+?)\s*\)",
        r"STRING_AGG(\1, \2)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # SQLite date/time functions -> Postgres shim functions.
    text = re.sub(r"\bDATETIME\s*\(", "sqlite_datetime(", text, flags=re.IGNORECASE)
    text = re.sub(r"\bDATE\s*\(", "sqlite_date(", text, flags=re.IGNORECASE)
    text = re.sub(r"\bTIME\s*\(", "sqlite_time(", text, flags=re.IGNORECASE)
    text = re.sub(r"\bSTRFTIME\s*\(", "sqlite_strftime(", text, flags=re.IGNORECASE)
    text = _rewrite_insert_or_ignore(text)
    text = _rewrite_insert_or_replace(text)
    text = _strip_foreign_keys(text)
    text = _qmark_to_pyformat(text)
    text = _escape_psycopg_pyformat_percents(text)
    return text


class PostgresCompatConnection:
    __crm_backend__ = "postgres"

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        sql2 = translate_sqlite_sql_to_postgres(sql)
        try:
            if params is None:
                return self._conn.execute(sql2)
            return self._conn.execute(sql2, params)
        except Exception:
            # En Postgres, un error deja la transacción abortada hasta rollback.
            # Mucho código llama a execute dentro de try/except "best-effort" y luego continúa.
            # Si no hacemos rollback aquí, el siguiente comando puede fallar con InFailedSqlTransaction.
            try:
                self._conn.rollback()
            except Exception:
                pass
            raise

    def executemany(self, sql, seq_of_params):
        sql2 = translate_sqlite_sql_to_postgres(sql)
        try:
            # psycopg3: executemany lives on cursors, not on the connection.
            cur = self._conn.cursor()
            cur.executemany(sql2, seq_of_params)
            return cur
        except Exception:
            try:
                self._conn.rollback()
            except Exception:
                pass
            raise

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()


def open_sqlite_conn(db_path, with_row_factory=False):
    try:
        timeout_seconds = float(os.environ.get("APP_SQLITE_TIMEOUT_SECONDS") or "5")
    except Exception:
        timeout_seconds = 5.0
    conn = sqlite3.connect(db_path, timeout=max(1.0, timeout_seconds))
    if with_row_factory:
        conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    if os.environ.get("APP_SQLITE_FOREIGN_KEYS", "1").strip().lower() not in ("0", "false", "no", "off"):
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass
    try:
        busy_ms = int(os.environ.get("APP_SQLITE_BUSY_TIMEOUT_MS") or "5000")
        conn.execute(f"PRAGMA busy_timeout={max(0, busy_ms)}")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    _notify_conn_tracker(conn)
    return conn


def open_postgres_conn(with_row_factory=False, *, skip_compat=False, connect_timeout_override=None):
    dsn = _postgres_dsn()
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL/POSTGRES_URL no configurado. "
            "En local puedes exportar la variable o añadirla al archivo `.env` en la raíz del repo."
        )
    try:
        import psycopg
        from psycopg.rows import dict_row, tuple_row
    except Exception as exc:
        raise RuntimeError("psycopg no instalado. Añade `psycopg[binary]` a requirements.txt.") from exc
    connect_timeout = None
    if connect_timeout_override is not None:
        try:
            connect_timeout = int(connect_timeout_override)
        except Exception:
            connect_timeout = None
    if connect_timeout is None:
        try:
            connect_timeout = int(os.environ.get("APP_PG_CONNECT_TIMEOUT", "5"))
        except Exception:
            connect_timeout = 5

    # Pool ligero (sin dependencias) para Render/PG:
    # - Reduce el coste de handshake SSL + auth (muy notable en iOS/PWA).
    # - Evita avalanchas de conexiones que pueden tumbar Postgres (y se ven como "server closed connection unexpectedly").
    # Incluso para probes de health, reusar conexiones evita superar el max_connections y es más rápido.
    use_pool = True
    wrapped = None
    row_factory = dict_row if with_row_factory else tuple_row
    if use_pool:
        # Asegura que _PG_POOL_MAX/_PG_POOL_WAIT_S están inicializados.
        _pg_pool_configured()
        wrapped = _pg_pool_acquire(
            dsn,
            row_factory=row_factory,
            connect_timeout=max(2, connect_timeout),
        )
    if wrapped is None:
        # Importante: si el pool está configurado (APP_PG_POOL_MAX>0) y está saturado,
        # abrir conexiones "extra" rompe el propósito del pool y puede tumbar Postgres en planes pequeños.
        # Por defecto aplicamos backpressure (fallar rápido) y solo permitimos unpooled si el usuario lo fuerza.
        allow_unpooled = (os.environ.get("APP_PG_ALLOW_UNPOOLED") or "").strip().lower() in {"1", "true", "yes", "on"}
        if (not allow_unpooled) and (_PG_POOL_MAX or 0) > 0:
            raise RuntimeError(
                "Pool Postgres saturado. "
                "Aumenta APP_PG_POOL_MAX/APP_PG_POOL_WAIT_SECONDS o habilita APP_PG_ALLOW_UNPOOLED=1 (no recomendado)."
            )
        conn = psycopg.connect(
            dsn,
            row_factory=row_factory,
            connect_timeout=max(2, connect_timeout),
            application_name=(os.environ.get("APP_PG_APP_NAME") or "verifika2-crm").strip() or "verifika2-crm",
        )
        wrapped = PostgresCompatConnection(conn)

    # Safety defaults: evita queries colgadas que saturen la DB en planes pequeños.
    # Configurable por env. Se aplica por sesión y no requiere privilegios especiales.
    try:
        statement_ms = int(os.environ.get("APP_PG_STATEMENT_TIMEOUT_MS", "45000") or 45000)
    except Exception:
        statement_ms = 45000
    try:
        lock_ms = int(os.environ.get("APP_PG_LOCK_TIMEOUT_MS", "10000") or 10000)
    except Exception:
        lock_ms = 10000
    statement_ms = max(1000, min(300000, statement_ms))
    lock_ms = max(250, min(60000, lock_ms))
    try:
        wrapped.execute(f"SET statement_timeout TO '{statement_ms}ms'")
        wrapped.execute(f"SET lock_timeout TO '{lock_ms}ms'")
    except Exception:
        pass

    # Importante: crear las funciones shim en cada conexión puede ser MUY costoso (muchos CREATE OR REPLACE).
    # Las funciones se crean a nivel de BD, así que basta con hacerlo una sola vez por proceso.
    global _PG_COMPAT_READY
    if (not skip_compat) and os.environ.get("APP_PG_SQLITE_COMPAT", "1").strip().lower() not in ("0", "false", "no", "off"):
        if not _PG_COMPAT_READY:
            with _PG_COMPAT_LOCK:
                if not _PG_COMPAT_READY:
                    try:
                        ensure_postgres_sqlite_compat(wrapped)
                        wrapped.commit()
                        _PG_COMPAT_READY = True
                    except Exception:
                        try:
                            wrapped.rollback()
                        except Exception:
                            pass
    _notify_conn_tracker(wrapped)
    return wrapped


_PG_POOL_MAX = 0
_PG_POOL_WAIT_S = 0.0
_PG_POOL_CREATE = object()
_PG_POOL_QUEUE: queue.LifoQueue[Any] | None = None
_PG_POOL_LOCK = threading.Lock()
_PG_POOL_CREATED = 0


def _pg_pool_configured():
    global _PG_POOL_MAX, _PG_POOL_WAIT_S, _PG_POOL_QUEUE
    if _PG_POOL_QUEUE is not None:
        return
    try:
        # Default (Render): necesitamos algo más de margen porque iOS/PWA hace bursts de requests
        # (health/me/assets) y 4 conexiones puede saturarse fácilmente durante bootstrap o queries lentas.
        _PG_POOL_MAX = int(os.environ.get("APP_PG_POOL_MAX", "16") or 16)
    except Exception:
        _PG_POOL_MAX = 16
    try:
        _PG_POOL_WAIT_S = float(os.environ.get("APP_PG_POOL_WAIT_SECONDS", "15") or 15)
    except Exception:
        _PG_POOL_WAIT_S = 15.0
    _PG_POOL_MAX = max(0, min(50, _PG_POOL_MAX))
    _PG_POOL_WAIT_S = max(0.1, min(15.0, _PG_POOL_WAIT_S))
    _PG_POOL_QUEUE = queue.LifoQueue(maxsize=max(1, _PG_POOL_MAX or 1))


def get_postgres_pool_stats():
    """
    Devuelve estadísticas del pool interno de Postgres para diagnóstico.
    No hace IO de red.
    """
    try:
        _pg_pool_configured()
        pool_queue = _PG_POOL_QUEUE
        max_size = int(_PG_POOL_MAX or 0)
        wait_s = float(_PG_POOL_WAIT_S or 0.0)
        created = int(_PG_POOL_CREATED or 0)
        available = None
        try:
            available = int(pool_queue.qsize()) if pool_queue is not None else None
        except Exception:
            available = None
        in_use = None
        try:
            if available is not None:
                in_use = max(0, created - available)
        except Exception:
            in_use = None
        return {
            "max": max_size,
            "created": created,
            "available": available,
            "in_use": in_use,
            "wait_seconds": wait_s,
        }
    except Exception:
        return {}


def _pg_is_connection_error(exc):
    name = (type(exc).__name__ or "").lower()
    mod = (type(exc).__module__ or "").lower()
    if "psycopg" in mod and name in {"operationalerror", "interfaceerror", "adminshutdown", "crashshutdown"}:
        return True
    msg = str(exc or "").lower()
    if "server closed the connection unexpectedly" in msg:
        return True
    if "connection failed" in msg and "port" in msg:
        return True
    if "terminating connection" in msg or "connection reset" in msg:
        return True
    return False


class _PooledPostgresCompatConnection(PostgresCompatConnection):
    def __init__(self, conn, *, pool_dsn):
        super().__init__(conn)
        self._pool_dsn = pool_dsn
        self._pool_released = False
        self._pool_broken = False

    def execute(self, sql, params=None):
        try:
            return super().execute(sql, params)
        except Exception as exc:
            if _pg_is_connection_error(exc):
                self._pool_broken = True
            raise

    def executemany(self, sql, seq_of_params):
        try:
            return super().executemany(sql, seq_of_params)
        except Exception as exc:
            if _pg_is_connection_error(exc):
                self._pool_broken = True
            raise

    def commit(self):
        try:
            return super().commit()
        except Exception as exc:
            if _pg_is_connection_error(exc):
                self._pool_broken = True
            raise

    def rollback(self):
        try:
            return super().rollback()
        except Exception as exc:
            if _pg_is_connection_error(exc):
                self._pool_broken = True
            raise

    def close(self):
        if self._pool_released:
            return
        self._pool_released = True
        raw = getattr(self, "_conn", None)
        if raw is None:
            return
        _pg_pool_release(raw, broken=bool(self._pool_broken))


def _pg_pool_acquire(dsn, *, row_factory, connect_timeout):
    # Returns a PostgresCompatConnection whose `.close()` returns the raw connection to the pool.
    global _PG_POOL_CREATED
    _pg_pool_configured()
    pool_queue = _PG_POOL_QUEUE
    if pool_queue is None or _PG_POOL_MAX <= 0:
        return None
    # Best-effort to reuse an existing connection.
    raw: Any = None
    try:
        raw = pool_queue.get_nowait()
    except Exception:
        raw = None
    if raw is None:
        with _PG_POOL_LOCK:
            if _PG_POOL_CREATED < _PG_POOL_MAX:
                _PG_POOL_CREATED += 1
                raw = _PG_POOL_CREATE
    if raw is _PG_POOL_CREATE:
        try:
            import psycopg
        except Exception:
            with _PG_POOL_LOCK:
                _PG_POOL_CREATED = max(0, _PG_POOL_CREATED - 1)
            return None
        raw = psycopg.connect(
            dsn,
            row_factory=row_factory,
            connect_timeout=connect_timeout,
            application_name=(os.environ.get("APP_PG_APP_NAME") or "verifika2-crm").strip() or "verifika2-crm",
        )
    if raw is None:
        # Pool saturated: wait a bit to avoid opening infinite connections.
        try:
            raw = pool_queue.get(timeout=_PG_POOL_WAIT_S)
        except Exception:
            return None
    # Configure row_factory for this borrower (psycopg requiere callable; nunca usar None).
    try:
        raw.row_factory = row_factory
    except Exception:
        pass
    return _PooledPostgresCompatConnection(raw, pool_dsn=dsn)


def _pg_pool_release(raw_conn, *, broken=False):
    global _PG_POOL_CREATED
    _pg_pool_configured()
    pool_queue = _PG_POOL_QUEUE
    if raw_conn is None:
        return
    if pool_queue is None or _PG_POOL_MAX <= 0:
        try:
            raw_conn.close()
        except Exception:
            pass
        return
    # Reset transaction state before reuse.
    try:
        raw_conn.rollback()
    except Exception:
        pass
    # Reset autocommit if someone enabled it (bootstrap does this).
    try:
        raw_conn.autocommit = False
    except Exception:
        pass
    closed = False
    try:
        closed = bool(getattr(raw_conn, "closed", False))
    except Exception:
        closed = False
    if broken or closed:
        try:
            raw_conn.close()
        except Exception:
            pass
        with _PG_POOL_LOCK:
            _PG_POOL_CREATED = max(0, _PG_POOL_CREATED - 1)
        return
    try:
        pool_queue.put_nowait(raw_conn)
    except Exception:
        try:
            raw_conn.close()
        except Exception:
            pass
        with _PG_POOL_LOCK:
            _PG_POOL_CREATED = max(0, _PG_POOL_CREATED - 1)


_PG_COMPAT_READY = False
_PG_COMPAT_LOCK = threading.Lock()


def open_db_conn(db_path, with_row_factory=False):
    # Backend selection:
    # - If APP_DB_BACKEND forces a backend, obey it.
    # - Otherwise, if DATABASE_URL/POSTGRES_URL indicates Postgres, use Postgres.
    # - Otherwise, use SQLite at the provided path.
    forced = (os.environ.get("APP_DB_BACKEND") or "").strip().lower()
    if forced in {"sqlite", "sqlite3"}:
        return open_sqlite_conn(db_path, with_row_factory=with_row_factory)
    if forced in {"postgres", "postgresql", "postgre", "pg"}:
        return open_postgres_conn(with_row_factory=with_row_factory)
    if is_postgres_enabled():
        return open_postgres_conn(with_row_factory=with_row_factory)
    return open_sqlite_conn(db_path, with_row_factory=with_row_factory)


def ensure_postgres_sqlite_compat(conn):
    # Create small shim functions to support our SQLite-ish SQL in Postgres.
    if getattr(conn, "__crm_backend__", "") != "postgres":
        return
    # DB-level guard: estas funciones viven en la base de datos, así que no necesitamos recrearlas
    # en cada cold start. Guardamos un marker para saltarlas si ya están creadas.
    compat_key = "pg_sqlite_compat_v1"
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crm_meta (
              key TEXT PRIMARY KEY,
              value TEXT,
              updated_at TEXT
            )
            """
        )
        marker = None
        try:
            row = conn.execute("SELECT value FROM crm_meta WHERE key = ?", (compat_key,)).fetchone()
            if row:
                marker = (row.get("value") if isinstance(row, dict) else row[0])
        except Exception:
            marker = None
        if str(marker or "").strip() == "1":
            # Verify one known function exists; if it does, we can safely skip.
            try:
                exists = conn.execute(
                    """
                    SELECT 1
                    FROM pg_proc p
                    JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE p.proname = 'sqlite_datetime'
                    LIMIT 1
                    """
                ).fetchone()
            except Exception:
                exists = None
            if exists:
                return
    except Exception:
        # If meta probes fail, fall back to creating compat functions.
        pass
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_datetime(arg1 text)
        RETURNS text
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF arg1 IS NULL OR btrim(arg1) = '' THEN
            RETURN NULL;
          END IF;
          IF lower(btrim(arg1)) = 'now' THEN
            RETURN to_char(now(), 'YYYY-MM-DD HH24:MI:SS');
          END IF;
          RETURN btrim(arg1);
        END;
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_datetime(arg1 text, arg2 text)
        RETURNS text
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF arg2 IS NULL THEN
            RETURN sqlite_datetime(arg1);
          END IF;
          IF lower(btrim(arg1)) = 'now' THEN
            RETURN to_char(now(), 'YYYY-MM-DD HH24:MI:SS');
          END IF;
          RETURN btrim(arg1);
        END;
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_time(arg1 text)
        RETURNS text
        LANGUAGE plpgsql
        AS $$
        DECLARE v text;
        BEGIN
          v := btrim(coalesce(arg1, ''));
          IF v = '' THEN
            RETURN NULL;
          END IF;
          IF v ~ '^[0-9]{2}:[0-9]{2}$' THEN
            RETURN v || ':00';
          END IF;
          RETURN v;
        END;
        $$;
        """
    )

    # ROUND shim (SQLite compatibility)
    #
    # Nota: en versiones anteriores, reescrituras de SQL podían transformar `round(...)` dentro de estas
    # funciones y provocar recursion (stack depth exceeded). Para evitarlo:
    # - Definimos las funciones en LANGUAGE SQL (sin plpgsql).
    # - Referenciamos explícitamente `pg_catalog.round`.
    # - Hacemos DROP IF EXISTS antes para “limpiar” definiciones antiguas erróneas.
    conn.execute("DROP FUNCTION IF EXISTS sqlite_round(double precision)")
    conn.execute("DROP FUNCTION IF EXISTS sqlite_round(double precision, integer)")
    conn.execute("DROP FUNCTION IF EXISTS sqlite_round(numeric)")
    conn.execute("DROP FUNCTION IF EXISTS sqlite_round(numeric, integer)")
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_round(arg1 double precision)
        RETURNS double precision
        LANGUAGE SQL
        AS $$
          -- Cast a numeric para replicar el redondeo half-away-from-zero de SQLite ROUND()
          -- (pg_catalog.round(double) usa banker's rounding y divergiría: ROUND(2.5) -> 2 vs 3).
          SELECT CASE WHEN arg1 IS NULL THEN NULL ELSE pg_catalog.round(arg1::numeric)::double precision END
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_round(arg1 double precision, arg2 integer)
        RETURNS double precision
        LANGUAGE SQL
        AS $$
          SELECT CASE WHEN arg1 IS NULL THEN NULL ELSE pg_catalog.round(arg1::numeric, arg2)::double precision END
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_round(arg1 numeric)
        RETURNS double precision
        LANGUAGE SQL
        AS $$
          SELECT CASE WHEN arg1 IS NULL THEN NULL ELSE pg_catalog.round(arg1)::double precision END
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_round(arg1 numeric, arg2 integer)
        RETURNS double precision
        LANGUAGE SQL
        AS $$
          SELECT CASE WHEN arg1 IS NULL THEN NULL ELSE pg_catalog.round(arg1, arg2)::double precision END
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_date(arg1 text)
        RETURNS text
        LANGUAGE plpgsql
        AS $$
        DECLARE v text;
        BEGIN
          v := btrim(coalesce(arg1, ''));
          IF v = '' THEN
            RETURN NULL;
          END IF;
          IF lower(v) = 'now' THEN
            RETURN to_char(current_date, 'YYYY-MM-DD');
          END IF;
          -- best-effort: accept ISO-like timestamps and return YYYY-MM-DD.
          IF v ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN
            RETURN substr(v, 1, 10);
          END IF;
          RETURN NULL;
        END;
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_date(arg1 text, modifier text)
        RETURNS text
        LANGUAGE plpgsql
        AS $$
        DECLARE base date;
        DECLARE mod text;
        DECLARE days int;
        DECLARE years int;
        BEGIN
          mod := btrim(coalesce(modifier, ''));
          IF lower(btrim(coalesce(arg1,''))) = 'now' THEN
            base := current_date;
          ELSE
            BEGIN
              base := to_date(substr(btrim(coalesce(arg1,'')), 1, 10), 'YYYY-MM-DD');
            EXCEPTION WHEN others THEN
              RETURN NULL;
            END;
          END IF;
          IF mod = '' OR lower(mod) = 'localtime' THEN
            RETURN to_char(base, 'YYYY-MM-DD');
          END IF;
          IF mod ~ '^[+-]?[0-9]+\\s*day(s)?$' THEN
            days := (regexp_replace(mod, '[^0-9+-]', '', 'g'))::int;
            RETURN to_char((base + (days * interval '1 day'))::date, 'YYYY-MM-DD');
          END IF;
          IF mod ~ '^[+-]?[0-9]+\\s*year(s)?$' THEN
            years := (regexp_replace(mod, '[^0-9+-]', '', 'g'))::int;
            RETURN to_char((base + (years * interval '1 year'))::date, 'YYYY-MM-DD');
          END IF;
          RETURN to_char(base, 'YYYY-MM-DD');
        END;
        $$;
        """
    )
    try:
        conn.execute(
            """
            INSERT INTO crm_meta (key, value, updated_at)
            VALUES (?, '1', sqlite_datetime('now'))
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value,
                updated_at = EXCLUDED.updated_at
            """,
            (compat_key,),
        )
    except Exception:
        pass
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_date(arg1 text, modifier1 text, modifier2 text)
        RETURNS text
        LANGUAGE plpgsql
        AS $$
        DECLARE v text;
        BEGIN
          v := sqlite_date(arg1, modifier1);
          RETURN sqlite_date(v, modifier2);
        END;
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_strftime(fmt text, arg1 text)
        RETURNS text
        LANGUAGE plpgsql
        AS $$
        DECLARE f text;
        DECLARE v text;
        BEGIN
          f := btrim(coalesce(fmt,''));
          -- Nuestra capa de compatibilidad escapa '%' como '%%' para evitar que psycopg3
          -- lo interprete como placeholder. Normalizamos aquí para que '%Y' y '%%Y' funcionen igual.
          WHILE position('%%' in f) > 0 LOOP
            f := replace(f, '%%', '%');
          END LOOP;
          v := btrim(coalesce(arg1,''));
          IF v = '' THEN
            RETURN NULL;
          END IF;
          IF lower(v) = 'now' THEN
            v := to_char(now(), 'YYYY-MM-DD');
          END IF;
          IF f = '%Y' THEN
            RETURN substr(v, 1, 4);
          END IF;
          IF f = '%Y-%m' THEN
            RETURN substr(v, 1, 7);
          END IF;
          RETURN v;
        END;
        $$;
        """
    )

    # round(real|double precision, integer) no existe en Postgres (solo round(numeric, integer)).
    # Creamos shims para que SQL legado con ROUND(x, 2) funcione.
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION round(val real, digits integer)
        RETURNS double precision
        LANGUAGE SQL
        AS $$
          SELECT pg_catalog.round(val::numeric, digits)::double precision
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION round(val double precision, digits integer)
        RETURNS double precision
        LANGUAGE SQL
        AS $$
          SELECT pg_catalog.round(val::numeric, digits)::double precision
        $$;
        """
    )

    # printf shim (SQLite compatibility)
    # Usado en algunos SELECT legacy (formateo '%.2f'). Implementación limitada pero suficiente.
    conn.execute("DROP FUNCTION IF EXISTS printf(text, real)")
    conn.execute("DROP FUNCTION IF EXISTS printf(text, double precision)")
    conn.execute("DROP FUNCTION IF EXISTS printf(text, numeric)")
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION printf(fmt text, val double precision)
        RETURNS text
        LANGUAGE plpgsql
        AS $$
        DECLARE f text;
        DECLARE digits int;
        DECLARE pattern text;
        BEGIN
          f := btrim(coalesce(fmt, ''));
          IF val IS NULL THEN
            RETURN NULL;
          END IF;
          IF f ~ '^%\\.[0-9]+f$' THEN
            digits := (regexp_replace(f, '[^0-9]', '', 'g'))::int;
            pattern := 'FM999999999999990' || CASE WHEN digits > 0 THEN '.' || repeat('0', digits) ELSE '' END;
            RETURN btrim(to_char(val::numeric, pattern));
          END IF;
          RETURN val::text;
        END;
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION printf(fmt text, val real)
        RETURNS text
        LANGUAGE SQL
        AS $$
          SELECT printf(fmt, val::double precision)
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION printf(fmt text, val numeric)
        RETURNS text
        LANGUAGE SQL
        AS $$
          SELECT printf(fmt, val::double precision)
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_strftime(fmt text, arg1 text, arg2 text)
        RETURNS text
        LANGUAGE plpgsql
        AS $$
        BEGIN
          RETURN sqlite_strftime(fmt, arg1);
        END;
        $$;
        """
    )
    # Minimal sqlite_master compatibility (used for "table exists" checks).
    conn.execute(
        """
        CREATE OR REPLACE VIEW sqlite_master AS
        SELECT
          CASE
            WHEN c.relkind = 'r' THEN 'table'
            WHEN c.relkind = 'v' THEN 'view'
            ELSE 'other'
          END::text AS type,
          c.relname::text AS name,
          c.relname::text AS tbl_name,
          NULL::text AS sql,
          0::int AS rootpage
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'v');
        """
    )
    # (group_concat is rewritten to string_agg in SQL translation)
