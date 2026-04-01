#!/usr/bin/env python3
import argparse
import re
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.db_backend import open_postgres_conn, is_postgres_enabled  # noqa: E402
from web.server import ensure_tables  # noqa: E402


SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def norm_ident(name: str) -> str:
    name = str(name or "").strip()
    if not SAFE_IDENT_RE.match(name):
        raise ValueError(f"Identificador no permitido: {name!r}")
    return name.lower()


def qident(name: str) -> str:
    return '"' + norm_ident(name).replace('"', '""') + '"'


def sqlite_table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [str(r[0]) for r in rows if r and str(r[0] or "").strip()]


def sqlite_table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    table = norm_ident(table)
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    cols: list[str] = []
    for row in rows:
        # (cid, name, type, notnull, dflt_value, pk)
        if not row:
            continue
        col = str(row[1] or "").strip()
        if not col:
            continue
        cols.append(norm_ident(col))
    return cols


def pg_table_columns(conn, table: str) -> set[str]:
    table = norm_ident(table)
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    ).fetchall()
    out = set()
    for row in rows:
        if isinstance(row, dict):
            val = row.get("column_name")
        else:
            val = row[0] if row else None
        if val:
            out.add(str(val).strip().lower())
    return out


def copy_table(*, sqlite_conn: sqlite3.Connection, pg_conn, table: str, batch_size: int = 500) -> int:
    table = norm_ident(table)
    sqlite_cols = sqlite_table_columns(sqlite_conn, table)
    if not sqlite_cols:
        return 0
    dest_cols = pg_table_columns(pg_conn, table)
    cols = [c for c in sqlite_cols if c in dest_cols]
    if not cols:
        return 0

    select_cols = ", ".join([qident(c) for c in cols])
    insert_cols = ", ".join([qident(c) for c in cols])
    placeholders = ", ".join(["?"] * len(cols))
    insert_sql = f"INSERT INTO {qident(table)} ({insert_cols}) VALUES ({placeholders})"

    cur = sqlite_conn.execute(f"SELECT {select_cols} FROM {qident(table)}")
    total = 0
    while True:
        rows = cur.fetchmany(batch_size)
        if not rows:
            break
        pg_conn.executemany(insert_sql, rows)
        total += len(rows)
    return total


def main():
    parser = argparse.ArgumentParser(description="Copia una SQLite local al Postgres configurado en DATABASE_URL.")
    parser.add_argument("--sqlite", required=True, help="Ruta a la SQLite origen (ej: /var/data/erp.sqlite).")
    parser.add_argument("--only", action="append", default=[], help="Tabla(s) a copiar (puede repetirse).")
    parser.add_argument("--skip", action="append", default=[], help="Tabla(s) a saltar (puede repetirse).")
    parser.add_argument("--truncate", action="store_true", help="TRUNCATE de tablas destino antes de copiar (destructivo).")
    parser.add_argument("--batch-size", type=int, default=500, help="Tamaño de lote para inserts.")
    parser.add_argument("--yes", action="store_true", help="Confirma acciones destructivas (truncate).")
    args = parser.parse_args()

    if not is_postgres_enabled():
        raise SystemExit("DATABASE_URL/POSTGRES_URL no apunta a Postgres (no empieza por 'postgres').")

    sqlite_path = Path(args.sqlite).expanduser().resolve()
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite no encontrada: {sqlite_path}")

    # Inicializa esquema en Postgres (usa DATABASE_URL).
    ensure_tables(str(sqlite_path))

    sqlite_conn = sqlite3.connect(str(sqlite_path))
    try:
        pg_conn = open_postgres_conn(with_row_factory=False)
    except Exception:
        sqlite_conn.close()
        raise

    try:
        tables = sqlite_table_names(sqlite_conn)
        only = [norm_ident(t) for t in (args.only or []) if str(t or "").strip()]
        skip = {norm_ident(t) for t in (args.skip or []) if str(t or "").strip()}
        if only:
            tables = [t for t in tables if norm_ident(t) in set(only)]
        if skip:
            tables = [t for t in tables if norm_ident(t) not in skip]

        if args.truncate:
            if not args.yes:
                raise SystemExit("Aborta: añade --yes para confirmar --truncate.")
            for t in tables:
                try:
                    pg_conn.execute(f"TRUNCATE TABLE {qident(t)}")
                except Exception:
                    # Tabla puede no existir en destino.
                    pass
            pg_conn.commit()

        copied_total = 0
        batch_size = max(1, min(int(args.batch_size or 500), 5000))
        for t in tables:
            try:
                n = copy_table(sqlite_conn=sqlite_conn, pg_conn=pg_conn, table=t, batch_size=batch_size)
                copied_total += n
                if n:
                    print(f"- {t}: {n} filas")
            except Exception as exc:
                print(f"- {t}: ERROR {exc}")
                raise
        pg_conn.commit()
        print(f"OK: {copied_total} filas copiadas a Postgres.")
    finally:
        try:
            sqlite_conn.close()
        except Exception:
            pass
        try:
            pg_conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
