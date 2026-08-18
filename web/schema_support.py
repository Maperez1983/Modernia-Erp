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


def _rollback_best_effort(conn):
    try:
        if conn:
            conn.rollback()
    except Exception:
        pass


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
    for stmt in _trocea_por_sentencias(script):
        stmt = stmt.strip()
        if not stmt:
            continue
        statements.append(stmt)
    for stmt in statements:
        conn.execute(stmt)
    return True


def _trocea_por_sentencias(script):
    """Parte el script por sentencias, sin dejarse engañar por un comentario.

    Era un `script.split(";")` a secas. Un punto y coma dentro de un comentario
    `--` partía la sentencia por la mitad, y Postgres respondía «syntax error at
    end of input» sobre la línea del comentario.

    No es hipotético: pasó. Un comentario que explicaba una columna decía «536
    resuelven a un cliente único por nombre y empresa; 10 nombres no existen», y
    ese punto y coma cortó el `CREATE TABLE gestoria`. El esquema dejó de
    aplicarse, el arranque falló en bucle y el CRM estuvo caído. Un comentario no
    puede tumbar el arranque.

    También se respetan las comillas: un punto y coma dentro de un literal
    tampoco separa.
    """
    sentencias, actual = [], []
    en_comentario = en_simple = en_doble = False
    i, n = 0, len(script)
    while i < n:
        c = script[i]
        siguiente = script[i + 1] if i + 1 < n else ""
        if en_comentario:
            actual.append(c)
            if c == "\n":
                en_comentario = False
        elif en_simple:
            actual.append(c)
            if c == "'":
                en_simple = False
        elif en_doble:
            actual.append(c)
            if c == '"':
                en_doble = False
        elif c == "-" and siguiente == "-":
            en_comentario = True
            actual.append(c)
        elif c == "'":
            en_simple = True
            actual.append(c)
        elif c == '"':
            en_doble = True
            actual.append(c)
        elif c == ";":
            sentencias.append("".join(actual))
            actual = []
        else:
            actual.append(c)
        i += 1
    sentencias.append("".join(actual))
    return sentencias


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
            _rollback_best_effort(conn)
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
        _rollback_best_effort(conn)
        return set()


def ensure_not_null(conn, table_name, column_name):
    """Pone NOT NULL en una columna que ya está poblada, sin romper nada si no.

    Solo actúa en Postgres: SQLite no sabe añadir NOT NULL a una columna existente
    sin reconstruir la tabla, y no compensa para una base de desarrollo.

    Es idempotente y cobarde a propósito: si queda una sola fila a NULL o vacía, no
    hace nada. Poner la restricción con datos sucios tumbaría el arranque de la
    aplicación entera, que es peor que la fila sucia.
    """
    try:  # como paquete o como script suelto, igual que el resto del proyecto
        from .db_backend import is_postgres_enabled
    except ImportError:
        from db_backend import is_postgres_enabled
    if not is_postgres_enabled():
        return False
    try:
        fila = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table_name} WHERE {column_name} IS NULL OR TRIM({column_name}) = ''"  # nosec B608 - nombres del propio código
        ).fetchone()
        sucias = int((fila[0] if not hasattr(fila, "keys") else fila["n"]) or 0)
    except Exception:
        return False
    if sucias:
        return False
    try:
        conn.execute(f"ALTER TABLE {table_name} ALTER COLUMN {column_name} SET NOT NULL")  # nosec B608 - nombres del propio código
        conn.commit()
        return True
    except Exception:
        # Ya estaba puesta, o la base no deja: no es motivo para no arrancar.
        try:
            conn.rollback()
        except Exception:
            pass
        return False


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
