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


def pg_table_column_types(conn, table: str) -> dict[str, str]:
    table = norm_ident(table)
    rows = conn.execute(
        """
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table,),
    ).fetchall()
    out: dict[str, str] = {}
    for row in rows:
        if isinstance(row, dict):
            col = row.get("column_name")
            data_type = row.get("data_type")
            udt = row.get("udt_name")
        else:
            col = row[0] if len(row) > 0 else None
            data_type = row[1] if len(row) > 1 else None
            udt = row[2] if len(row) > 2 else None
        if not col:
            continue
        key = str(col).strip().lower()
        out[key] = str(udt or data_type or "").strip().lower()
    return out


def _coerce_pg_value(value, pg_type: str):
    if value is None:
        return None
    t = str(pg_type or "").lower()
    is_int = t in {"int2", "int4", "int8", "smallint", "integer", "bigint"}
    is_num = is_int or t in {"float4", "float8", "real", "double precision", "numeric", "decimal"}
    if not is_num:
        return value
    if isinstance(value, str):
        v = value.strip()
        if v == "":
            return None
        # Normaliza decimal con coma si apareciera.
        v2 = v.replace(",", ".")
        try:
            if is_int:
                f = float(v2)
                return int(f) if f.is_integer() else None
            return float(v2)
        except Exception:
            return None
    if isinstance(value, (int, float)):
        if is_int:
            try:
                f = float(value)
                return int(f) if f.is_integer() else None
            except Exception:
                return None
        try:
            return float(value)
        except Exception:
            return None
    return value


def _norm_ci_key(value) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def copy_table(*, sqlite_conn: sqlite3.Connection, pg_conn, table: str, batch_size: int = 500) -> int:
    table = norm_ident(table)
    sqlite_cols = sqlite_table_columns(sqlite_conn, table)
    if not sqlite_cols:
        return 0
    dest_cols = pg_table_columns(pg_conn, table)
    dest_types = pg_table_column_types(pg_conn, table)
    cols = [c for c in sqlite_cols if c in dest_cols]
    if not cols:
        return 0
    types = [dest_types.get(c, "") for c in cols]

    select_cols = ", ".join([qident(c) for c in cols])
    insert_cols = ", ".join([qident(c) for c in cols])
    placeholders = ", ".join(["?"] * len(cols))
    # Idempotencia: usamos INSERT OR IGNORE para que el wrapper de Postgres lo traduzca a
    # "INSERT ... ON CONFLICT DO NOTHING" y así no se rompa si ya hay datos en Postgres.
    insert_sql = f"INSERT OR IGNORE INTO {qident(table)} ({insert_cols}) VALUES ({placeholders})"

    cur = sqlite_conn.execute(f"SELECT {select_cols} FROM {qident(table)}")
    total = 0
    seen_usernames: set[str] = set()
    seen_emails: set[str] = set()
    email_idx = cols.index("email") if table == "usuarios" and "email" in cols else -1
    user_idx = cols.index("usuario") if table == "usuarios" and "usuario" in cols else -1
    while True:
        rows = cur.fetchmany(batch_size)
        if not rows:
            break
        coerced = []
        for row in rows:
            # sqlite3 row is tuple-like
            values = list(row)
            if table == "usuarios":
                if email_idx >= 0:
                    key = _norm_ci_key(values[email_idx])
                    if key and key in seen_emails:
                        values[email_idx] = None
                    elif key:
                        seen_emails.add(key)
                if user_idx >= 0:
                    key = _norm_ci_key(values[user_idx])
                    if key and key in seen_usernames:
                        values[user_idx] = None
                    elif key:
                        seen_usernames.add(key)
            coerced.append(tuple(_coerce_pg_value(v, t) for v, t in zip(values, types)))
        pg_conn.executemany(insert_sql, coerced)
        total += len(rows)
    return total


def main():
    parser = argparse.ArgumentParser(description="Copia una SQLite local al Postgres configurado en DATABASE_URL.")
    parser.add_argument("--sqlite", required=True, help="Ruta a la SQLite origen (ej: /var/data/erp.sqlite).")
    parser.add_argument("--only", action="append", default=[], help="Tabla(s) a copiar (puede repetirse).")
    parser.add_argument("--skip", action="append", default=[], help="Tabla(s) a saltar (puede repetirse).")
    parser.add_argument(
        "--rrhh-only",
        action="store_true",
        help="Atajo: copia solo tablas de RRHH/Registro Horario (más workspaces/empresas/usuarios).",
    )
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
        rrhh_only = []
        if args.rrhh_only:
            rrhh_only = [
                "usuarios",
                "empresas",
                "workspaces",
                "workspace_empresas",
                "workspace_modulos",
                "workspace_registro_personal",
                "workspace_registro_horario",
                "workspace_registro_periodos",
                "workspace_registro_audit",
                "workspace_registro_alerts",
                "workspace_registro_notifications",
                "workspace_rrhh_profile",
                "workspace_rrhh_ausencias",
                "workspace_rrhh_gastos",
                "workspace_rrhh_documentos",
            ]
        only = [norm_ident(t) for t in ([*rrhh_only, *(args.only or [])]) if str(t or "").strip()]
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
