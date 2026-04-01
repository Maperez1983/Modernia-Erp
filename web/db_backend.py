import os
import re
import sqlite3
from contextlib import contextmanager


def is_postgres_enabled():
    forced = (os.environ.get("APP_DB_BACKEND") or "").strip().lower()
    if forced in {"sqlite", "sqlite3"}:
        return False
    if forced in {"postgres", "postgresql", "pg"}:
        return True
    raw = (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or "").strip()
    return raw.lower().startswith("postgres")


def _postgres_dsn():
    raw = (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or "").strip()
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
    return base + " ON CONFLICT (id) DO UPDATE SET " + ", ".join(set_cols)


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
    # SQLite ROUND(x, n) acepta floats; en Postgres, ROUND(x, n) solo existe para NUMERIC.
    # Reescribimos a un shim que hace cast seguro.
    text = re.sub(r"\bROUND\s*\(", "sqlite_round(", text, flags=re.IGNORECASE)
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
    return conn


def open_postgres_conn(with_row_factory=False):
    dsn = _postgres_dsn()
    if not dsn:
        raise RuntimeError("DATABASE_URL/POSTGRES_URL no configurado.")
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:
        raise RuntimeError("psycopg no instalado. Añade `psycopg[binary]` a requirements.txt.") from exc
    conn = psycopg.connect(dsn, row_factory=(dict_row if with_row_factory else None))
    wrapped = PostgresCompatConnection(conn)
    if os.environ.get("APP_PG_SQLITE_COMPAT", "1").strip().lower() not in ("0", "false", "no", "off"):
        try:
            ensure_postgres_sqlite_compat(wrapped)
            wrapped.commit()
        except Exception:
            try:
                wrapped.rollback()
            except Exception:
                pass
    return wrapped


def open_db_conn(db_path, with_row_factory=False):
    if is_postgres_enabled():
        return open_postgres_conn(with_row_factory=with_row_factory)
    return open_sqlite_conn(db_path, with_row_factory=with_row_factory)


def ensure_postgres_sqlite_compat(conn):
    # Create small shim functions to support our SQLite-ish SQL in Postgres.
    if getattr(conn, "__crm_backend__", "") != "postgres":
        return
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

    # ROUND shim (SQLite compatibility):
    # - sqlite_round(double precision, int) -> round(arg1::numeric, int)::double precision
    # - sqlite_round(double precision) -> round(arg1)
    # - sqlite_round(numeric, int) -> round(arg1, int)::double precision
    # - sqlite_round(numeric) -> round(arg1)::double precision
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_round(arg1 double precision)
        RETURNS double precision
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF arg1 IS NULL THEN
            RETURN NULL;
          END IF;
          RETURN round(arg1);
        END;
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_round(arg1 double precision, arg2 integer)
        RETURNS double precision
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF arg1 IS NULL THEN
            RETURN NULL;
          END IF;
          RETURN round(arg1::numeric, arg2)::double precision;
        END;
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_round(arg1 numeric)
        RETURNS double precision
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF arg1 IS NULL THEN
            RETURN NULL;
          END IF;
          RETURN round(arg1)::double precision;
        END;
        $$;
        """
    )
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION sqlite_round(arg1 numeric, arg2 integer)
        RETURNS double precision
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF arg1 IS NULL THEN
            RETURN NULL;
          END IF;
          RETURN round(arg1, arg2)::double precision;
        END;
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
