#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detecta y corrige fecha_efecto anómala en seguros (años fuera de rango)."
    )
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta sqlite")
    parser.add_argument("--min-year", type=int, default=2000, help="Año mínimo válido")
    parser.add_argument("--max-year", type=int, default=datetime.now().year + 1, help="Año máximo válido")
    parser.add_argument("--apply", action="store_true", help="Aplica cambios (sin esto solo simula)")
    parser.add_argument("--backup", action="store_true", help="Crea backup .bak antes de aplicar")
    return parser.parse_args()


def rows_with_anomaly(conn: sqlite3.Connection, min_year: int, max_year: int):
    query = """
    WITH calc AS (
      SELECT
        id,
        poliza_numero,
        tomador,
        fecha_efecto,
        created_at,
        CASE
          WHEN DATE(fecha_efecto) IS NOT NULL THEN CAST(STRFTIME('%Y', DATE(fecha_efecto)) AS INTEGER)
          WHEN TRIM(COALESCE(fecha_efecto,'')) GLOB '[0-3][0-9]/[0-1][0-9]/[1-2][0-9][0-9][0-9]' THEN CAST(SUBSTR(TRIM(fecha_efecto),7,4) AS INTEGER)
          WHEN TRIM(COALESCE(fecha_efecto,'')) GLOB '[0-3][0-9]-[0-1][0-9]-[1-2][0-9][0-9][0-9]' THEN CAST(SUBSTR(TRIM(fecha_efecto),7,4) AS INTEGER)
          ELSE NULL
        END AS efecto_year,
        DATE(created_at) AS created_date
      FROM seguros
    )
    SELECT id, poliza_numero, tomador, fecha_efecto, created_at, efecto_year, created_date
    FROM calc
    WHERE efecto_year IS NOT NULL
      AND (efecto_year < ? OR efecto_year > ?)
    ORDER BY efecto_year, id
    """
    return conn.execute(query, (min_year, max_year)).fetchall()


def apply_fix(conn: sqlite3.Connection, min_year: int, max_year: int) -> int:
    update_sql = """
    UPDATE seguros
    SET fecha_efecto = DATE(created_at)
    WHERE id IN (
      WITH calc AS (
        SELECT
          id,
          CASE
            WHEN DATE(fecha_efecto) IS NOT NULL THEN CAST(STRFTIME('%Y', DATE(fecha_efecto)) AS INTEGER)
            WHEN TRIM(COALESCE(fecha_efecto,'')) GLOB '[0-3][0-9]/[0-1][0-9]/[1-2][0-9][0-9][0-9]' THEN CAST(SUBSTR(TRIM(fecha_efecto),7,4) AS INTEGER)
            WHEN TRIM(COALESCE(fecha_efecto,'')) GLOB '[0-3][0-9]-[0-1][0-9]-[1-2][0-9][0-9][0-9]' THEN CAST(SUBSTR(TRIM(fecha_efecto),7,4) AS INTEGER)
            ELSE NULL
          END AS efecto_year
        FROM seguros
      )
      SELECT id
      FROM calc
      WHERE efecto_year IS NOT NULL
        AND (efecto_year < ? OR efecto_year > ?)
    )
    """
    cur = conn.execute(update_sql, (min_year, max_year))
    return cur.rowcount if cur.rowcount is not None else 0


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
      print(f"DB no encontrada: {db_path}")
      return 1

    if args.apply and args.backup:
        backup_path = db_path.with_suffix(db_path.suffix + ".bak")
        shutil.copy2(db_path, backup_path)
        print(f"Backup creado: {backup_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")

    rows = rows_with_anomaly(conn, args.min_year, args.max_year)
    print(f"Anomalías detectadas: {len(rows)}")
    for row in rows[:30]:
        print(
            f"- {row['id']} | poliza={row['poliza_numero'] or '-'} | "
            f"fecha_efecto={row['fecha_efecto'] or '-'} | created_at={row['created_at'] or '-'} | year={row['efecto_year']}"
        )

    if not args.apply:
        print("Simulación: sin cambios. Usa --apply para corregir.")
        return 0

    updated = apply_fix(conn, args.min_year, args.max_year)
    conn.commit()
    print(f"Registros corregidos: {updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
