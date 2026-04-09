from pathlib import Path


def _detect_backend(conn) -> str:
    backend = getattr(conn, "__crm_backend__", "") or ""
    # sqlite3.Connection doesn't expose our marker; detect it by capability.
    if not backend and hasattr(conn, "executescript"):
        backend = "sqlite"
    return backend or "sqlite"


def _columns_cache(conn) -> dict:
    cache = getattr(conn, "__crm_table_columns_cache__", None)
    if isinstance(cache, dict):
        return cache
    cache = {}
    try:
        setattr(conn, "__crm_table_columns_cache__", cache)
    except Exception:
        # If the connection object doesn't allow attributes, we fallback to no caching.
        return {}
    return cache


def apply_schema_file(conn, schema_path):
    path = Path(schema_path)
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    backend = _detect_backend(conn)
    if backend != "postgres":
        conn.executescript(text)
        return True
    # Postgres: execute statements one by one (ignore SQLite PRAGMA).
    statements = []
    buff = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            buff.append(line)
            continue
        if stripped.upper().startswith("PRAGMA "):
            continue
        buff.append(line)
    script = "\n".join(buff)
    for stmt in script.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        statements.append(stmt)
    for stmt in statements:
        conn.execute(stmt)
    return True


def table_columns(conn, table_name):
    backend = _detect_backend(conn)
    key = str(table_name or "").strip().lower()
    cache = _columns_cache(conn)
    if key and key in cache:
        cols = cache.get(key) or set()
        return {c for c in set(cols) if c}
    if backend != "postgres":
        try:
            cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        except Exception:
            cols = set()
        if key and isinstance(cache, dict):
            cache[key] = set(cols)
        return {c for c in cols if c}
    try:
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (str(table_name or "").strip().lower(),),
        ).fetchall()
        cols = set()
        for row in rows:
            if isinstance(row, dict):
                cols.add(row.get("column_name"))
            else:
                cols.add(row[0])
        cols = {c for c in cols if c}
        if key and isinstance(cache, dict):
            cache[key] = set(cols)
        return cols
    except Exception:
        return set()


def ensure_column(conn, table_name, column_name, column_sql):
    if column_name in table_columns(conn, table_name):
        return False
    backend = _detect_backend(conn)
    if backend == "postgres":
        # Postgres supports IF NOT EXISTS.
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_sql}")
        cache = _columns_cache(conn)
        key = str(table_name or "").strip().lower()
        if key and isinstance(cache, dict):
            cache.setdefault(key, set()).add(column_name)
        return True
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")
    cache = _columns_cache(conn)
    key = str(table_name or "").strip().lower()
    if key and isinstance(cache, dict):
        cache.setdefault(key, set()).add(column_name)
    return True
