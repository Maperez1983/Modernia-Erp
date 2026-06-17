#!/usr/bin/env python3
"""
Sincroniza la tabla `hipotecas` de Financiaciones Modernia desde una SQLite local
hasta la SQLite persistente de Render usando SSH.

Uso:
  python3 scripts/sync_hipotecas_to_render.py \
    --local-db data/erp_import2.sqlite \
    --render-host srv-xxxx@ssh.frankfurt.render.com \
    --render-db /var/data/erp_import2.sqlite
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from .render_backend_guard import guard_remote_sqlite_sync
except ImportError:
    from render_backend_guard import guard_remote_sqlite_sync


FINANCIACIONES_EMPRESA_ID = "5a676274-4ba8-4ec5-8010-af2bd2bfada7"
SSH_OPTIONS = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UpdateHostKeys=no",
    "-o",
    "ServerAliveInterval=15",
    "-o",
    "ServerAliveCountMax=4",
]
HIPOTECAS_COLUMNS = [
    "id",
    "empresa_id",
    "cliente",
    "cliente_id",
    "banco",
    "precio",
    "importe_hipoteca",
    "porcentaje",
    "entrada",
    "comision",
    "oficina",
    "fecha_encargo",
    "encargo",
    "tipo_hipoteca",
    "fecha_firma",
    "cesion",
    "comision_juan",
    "comision_modernia",
    "inmobiliaria_compra",
    "asesor",
    "estado",
    "anio",
    "created_at",
    "updated_at",
    "cliente_inmueble_json",
    "hipoteca_detalle_json",
    "liquidacion_json",
]


def fetch_rows(local_db: Path) -> list[dict]:
    conn = sqlite3.connect(str(local_db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT {", ".join(HIPOTECAS_COLUMNS)}
            FROM hipotecas
            WHERE empresa_id = ?
            ORDER BY COALESCE(NULLIF(fecha_firma, ''), NULLIF(fecha_encargo, ''), updated_at, created_at) DESC
            """,
            (FINANCIACIONES_EMPRESA_ID,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def build_sql(rows: list[dict]) -> str:
    lines = [
        "PRAGMA foreign_keys = OFF;",
        "BEGIN IMMEDIATE;",
        f"DELETE FROM hipotecas WHERE empresa_id = '{FINANCIACIONES_EMPRESA_ID}';",
    ]
    placeholders = ", ".join(["?"] * len(HIPOTECAS_COLUMNS))
    insert_prefix = f"INSERT INTO hipotecas ({', '.join(HIPOTECAS_COLUMNS)}) VALUES ({placeholders});"
    for row in rows:
        values = [row.get(col) for col in HIPOTECAS_COLUMNS]
        quoted = []
        for value in values:
            if value is None:
                quoted.append("NULL")
            elif isinstance(value, (int, float)):
                quoted.append(json.dumps(value, ensure_ascii=False))
            else:
                text = str(value).replace("'", "''")
                quoted.append(f"'{text}'")
        statement = insert_prefix.replace(placeholders, ", ".join(quoted), 1)
        lines.append(statement)
    lines.extend(["COMMIT;", "PRAGMA foreign_keys = ON;"])
    return "\n".join(lines) + "\n"


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza hipotecas a Render por SSH.")
    parser.add_argument("--local-db", default="data/erp_import2.sqlite", help="Ruta a la SQLite local.")
    parser.add_argument("--render-host", required=True, help="Host SSH de Render, ej. srv-xxx@ssh.frankfurt.render.com")
    parser.add_argument("--render-db", default="/var/data/erp_import2.sqlite", help="Ruta SQLite en Render.")
    parser.add_argument("--dry-run", action="store_true", help="Genera el SQL pero no lo sube.")
    parser.add_argument("--force-sqlite-target", action="store_true", help="Permite escribir en SQLite remota aunque el proyecto este en modo Postgres.")
    args = parser.parse_args()

    guard_remote_sqlite_sync(force=args.force_sqlite_target, script_name=Path(__file__).name)

    local_db = Path(args.local_db).expanduser().resolve()
    if not local_db.exists():
        raise SystemExit(f"No existe la base local: {local_db}")

    rows = fetch_rows(local_db)
    if not rows:
        raise SystemExit("No se encontraron hipotecas de Financiaciones Modernia en la base local.")

    sql = build_sql(rows)
    with tempfile.TemporaryDirectory() as tmpdir:
        sql_path = Path(tmpdir) / "hipotecas_sync.sql"
        sql_path.write_text(sql, encoding="utf-8")
        print(f"Preparadas {len(rows)} hipotecas para sincronizar.")
        print(f"SQL temporal: {sql_path}")
        if args.dry_run:
            return

        remote_sql = "/tmp/hipotecas_sync.sql"
        run(["scp", *SSH_OPTIONS, str(sql_path), f"{args.render_host}:{remote_sql}"])
        remote_cmd = (
            f"sqlite3 {args.render_db} < {remote_sql} "
            f"&& rm -f {remote_sql} "
            f"&& echo '__SYNC_OK__'"
        )
        run(
            [
                "ssh",
                *SSH_OPTIONS,
                args.render_host,
                "sh",
                "-lc",
                remote_cmd,
            ]
        )
        print("Sincronizacion completada.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
