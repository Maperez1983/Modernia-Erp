#!/usr/bin/env python3
import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


RRHH_TABLES = [
    "workspaces",
    "workspace_empresas",
    "workspace_modulos",
    "workspace_registro_personal",
    "workspace_rrhh_profile",
    "workspace_rrhh_ausencias",
    "workspace_rrhh_gastos",
    "workspace_rrhh_documentos",
    "workspace_registro_horario",
    "workspace_registro_alerts",
    "workspace_registro_notifications",
    "workspace_registro_periodos",
    "workspace_registro_audit",
]


def _default_db_path():
    configured = (os.environ.get("DB_PATH") or os.environ.get("DATABASE_PATH") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return ROOT / "data" / "erp_import2.sqlite"


def _pragma_columns(conn, table):
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [str(row[1]) for row in cols]


def _table_exists(conn, table):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return bool(row)


def copy_table(src, dst, table, overwrite=False):
    if not _table_exists(src, table):
        return (0, 0, f"skip: tabla no existe en src")
    if not _table_exists(dst, table):
        return (0, 0, f"skip: tabla no existe en dst")

    src_cols = _pragma_columns(src, table)
    dst_cols = _pragma_columns(dst, table)
    common = [c for c in src_cols if c in set(dst_cols)]
    if not common:
        return (0, 0, "skip: sin columnas comunes")

    rows = src.execute(f"SELECT {', '.join(common)} FROM {table}").fetchall()
    if not rows:
        return (0, 0, "ok: 0 filas")

    verb = "INSERT OR REPLACE" if overwrite else "INSERT OR IGNORE"
    qmarks = ", ".join(["?"] * len(common))
    sql = f"{verb} INTO {table} ({', '.join(common)}) VALUES ({qmarks})"

    inserted = 0
    skipped = 0
    for row in rows:
        try:
            cur = dst.execute(sql, tuple(row))
            # sqlite3: rowcount can be -1; we approximate via changes() per row
            changed = dst.execute("SELECT changes()").fetchone()[0]
            if changed:
                inserted += 1
            else:
                skipped += 1
        except sqlite3.IntegrityError:
            skipped += 1
    return (inserted, skipped, f"ok: {len(rows)} leidas")


def main():
    parser = argparse.ArgumentParser(
        description="Fusiona tablas RRHH/Workspace desde un SQLite origen a uno destino (sin tocar otras áreas)."
    )
    parser.add_argument(
        "--src",
        default=str(ROOT / "data" / "erp_import2.local.sqlite"),
        help="SQLite origen (por defecto data/erp_import2.local.sqlite).",
    )
    parser.add_argument(
        "--dst",
        default=str(_default_db_path()),
        help="SQLite destino (por defecto DB_PATH o data/erp_import2.sqlite).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Sobrescribe filas existentes por id (INSERT OR REPLACE). Por defecto NO pisa: INSERT OR IGNORE.",
    )
    parser.add_argument(
        "--backup-dst",
        action="store_true",
        help="Crea una copia .bak del destino antes de escribir.",
    )
    parser.add_argument(
        "--backup-src",
        action="store_true",
        help="Renombra el origen a .bak al finalizar (solo si el merge va bien).",
    )
    parser.add_argument("--yes", action="store_true", help="No pedir confirmación.")
    args = parser.parse_args()

    src_path = Path(args.src).expanduser().resolve()
    dst_path = Path(args.dst).expanduser().resolve()
    if not src_path.exists():
        raise SystemExit(f"SQLite origen no encontrada: {src_path}")
    if not dst_path.exists():
        raise SystemExit(f"SQLite destino no encontrada: {dst_path}")

    if src_path == dst_path:
        raise SystemExit("src y dst son el mismo fichero; no hay nada que fusionar.")

    if not args.yes:
        print("Vas a fusionar RRHH/Workspace:")
        print(f"- src: {src_path}")
        print(f"- dst: {dst_path}")
        print(f"- overwrite: {bool(args.overwrite)}")
        answer = input("¿Continuar? (escribe YES): ").strip()
        if answer != "YES":
            raise SystemExit("Cancelado.")

    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    if args.backup_dst:
        backup = dst_path.with_suffix(dst_path.suffix + f".bak_{stamp}")
        backup.write_bytes(dst_path.read_bytes())
        print(f"Backup destino: {backup}")

    # Asegura esquema en destino (crea tablas RRHH si no existen).
    try:
        from web.server import ensure_tables
    except Exception:
        from server import ensure_tables  # type: ignore
    ensure_tables(str(dst_path))

    src = sqlite3.connect(str(src_path))
    dst = sqlite3.connect(str(dst_path))
    try:
        src.row_factory = sqlite3.Row
        dst.row_factory = sqlite3.Row
        total_ins = 0
        total_skip = 0
        for table in RRHH_TABLES:
            ins, skip, msg = copy_table(src, dst, table, overwrite=bool(args.overwrite))
            total_ins += ins
            total_skip += skip
            print(f"- {table}: +{ins} / skip {skip} · {msg}")
        dst.commit()
        print(f"OK. Insertadas: {total_ins} · Omitidas: {total_skip}")
    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass

    if args.backup_src:
        backup_src = src_path.with_suffix(src_path.suffix + f".bak_{stamp}")
        src_path.rename(backup_src)
        print(f"Origen renombrado: {backup_src}")


if __name__ == "__main__":
    main()
