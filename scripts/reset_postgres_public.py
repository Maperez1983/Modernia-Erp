#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.db_backend import open_postgres_conn, is_postgres_enabled  # noqa: E402


def qident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def main():
    parser = argparse.ArgumentParser(description="Resetea el esquema public de Postgres (Render).")
    parser.add_argument("--drop-schema", action="store_true", help="DROP SCHEMA public CASCADE + CREATE SCHEMA public.")
    parser.add_argument("--truncate-all", action="store_true", help="TRUNCATE de todas las tablas del schema public.")
    parser.add_argument("--yes", action="store_true", help="Confirmación obligatoria para acciones destructivas.")
    args = parser.parse_args()

    if not is_postgres_enabled():
        raise SystemExit("DATABASE_URL/POSTGRES_URL no apunta a Postgres.")
    if not (args.drop_schema or args.truncate_all):
        raise SystemExit("Indica una acción: --drop-schema o --truncate-all")
    if not args.yes:
        raise SystemExit("Aborta: añade --yes para confirmar.")

    conn = open_postgres_conn(with_row_factory=True)
    try:
        if args.drop_schema:
            conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
            conn.execute("CREATE SCHEMA public")
            # Permisos estándar; el owner suele ser el mismo usuario.
            try:
                conn.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER")
            except Exception:
                pass
            print("OK: schema public recreado.")
            return

        rows = conn.execute(
            """
            SELECT tablename
            FROM pg_catalog.pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        ).fetchall()
        tables = [str(r.get("tablename") or "").strip() for r in (rows or []) if str(r.get("tablename") or "").strip()]
        if not tables:
            print("OK: no hay tablas en public.")
            return
        joined = ", ".join([qident(t) for t in tables])
        conn.execute(f"TRUNCATE TABLE {joined} CASCADE")
        print(f"OK: truncadas {len(tables)} tablas en public.")
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

