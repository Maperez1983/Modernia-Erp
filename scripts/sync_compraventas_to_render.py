#!/usr/bin/env python3
"""
Sincroniza compraventas inmobiliarias desde la SQLite local hasta la SQLite
persistente de Render usando SSH.

Uso:
  python3 scripts/sync_compraventas_to_render.py \
    --local-db data/erp_import2.sqlite \
    --render-host srv-xxxx@ssh.frankfurt.render.com \
    --render-db /var/data/erp_import2.sqlite \
    --year-from 2020
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


DEFAULT_COMPANY = "Estudio Velazquez 2012 SL"
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

CLIENT_COLUMNS = [
    "id",
    "empresa_id",
    "nombre",
    "nif",
    "telefono",
    "email",
    "tipo",
    "perfil",
    "estado",
    "created_at",
    "updated_at",
    "fecha_nacimiento",
    "direccion",
    "tipo_persona",
    "codigo_postal",
    "poblacion",
    "provincia",
]

CLIENT_EMPRESA_COLUMNS = [
    "id",
    "cliente_id",
    "empresa_id",
    "servicio",
    "estado",
    "fecha_inicio",
    "fecha_fin",
    "created_at",
    "updated_at",
]

INMUEBLE_COLUMNS = [
    "id",
    "empresa_id",
    "referencia",
    "direccion",
    "referencia_catastral",
    "codigo_postal",
    "poblacion",
    "provincia",
    "zona",
    "tipo_inmueble",
    "m2",
    "habitaciones",
    "banos",
    "precio_objetivo",
    "precio_valoracion",
    "valor_referencia",
    "estado",
    "lat",
    "lon",
    "created_at",
    "updated_at",
]

INMUEBLE_PROPIETARIO_COLUMNS = [
    "id",
    "inmueble_id",
    "cliente_id",
    "created_at",
    "updated_at",
]

CAPTACION_COLUMNS = [
    "id",
    "empresa_id",
    "inmueble_id",
    "propietario",
    "tipo_inmueble",
    "direccion",
    "zona",
    "m2",
    "habitaciones",
    "banos",
    "precio_objetivo",
    "precio_valoracion",
    "urgencia",
    "motivo",
    "canal",
    "etapa",
    "probabilidad",
    "proxima_accion",
    "fecha_contacto",
    "asesor",
    "codigo_postal",
    "poblacion",
    "provincia",
    "notas",
    "created_at",
    "updated_at",
]

OPERACION_COLUMNS = [
    "id",
    "empresa_id",
    "tipo_operacion",
    "estado",
    "origen",
    "origen_inmueble",
    "expediente_path",
    "expediente_hash",
    "anio",
    "mes",
    "inmueble_id",
    "direccion",
    "referencia_catastral",
    "propietario1_id",
    "propietario1_nombre",
    "propietario1_nif",
    "propietario1_telefono",
    "propietario1_email",
    "propietario1_fecha_nacimiento",
    "propietario2_id",
    "propietario2_nombre",
    "propietario2_nif",
    "propietario2_telefono",
    "propietario2_email",
    "propietario2_fecha_nacimiento",
    "contraparte1_id",
    "contraparte2_id",
    "contraparte_nombre",
    "contraparte_nif",
    "contraparte_telefono",
    "contraparte_email",
    "contraparte_fecha_nacimiento",
    "fecha_encargo",
    "fecha_propuesta",
    "fecha_contrato",
    "fecha_escritura",
    "fecha_operacion",
    "precio_encargo",
    "precio_propuesta",
    "precio_contrato",
    "precio_escritura",
    "precio_renta",
    "desviacion_euros",
    "desviacion_pct",
    "dias_hasta_venta",
    "num_visitas",
    "honorarios",
    "agente",
    "responsable_gestion",
    "oficina",
    "doc_nota_encargo_path",
    "doc_propuesta_path",
    "doc_escritura_path",
    "doc_nota_simple_path",
    "doc_partes_visita_paths",
    "estado_documental",
    "calidad_ocr",
    "notas",
    "datos_extraidos_json",
    "created_at",
    "updated_at",
]


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return json.dumps(value, ensure_ascii=False)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def fetch_payload(local_db: Path, company_name: str, year_from: int | None) -> dict:
    conn = sqlite3.connect(str(local_db))
    conn.row_factory = sqlite3.Row
    try:
        empresa = conn.execute(
            "SELECT id, nombre FROM empresas WHERE nombre = ? LIMIT 1",
            (company_name,),
        ).fetchone()
        if not empresa:
            raise SystemExit(f"No existe la empresa {company_name!r} en la base local.")
        empresa_id = empresa["id"]

        where = [
            "empresa_id = ?",
            "LOWER(COALESCE(tipo_operacion, 'venta')) = 'venta'",
        ]
        values: list[object] = [empresa_id]
        if year_from is not None:
            where.append("COALESCE(anio, 0) >= ?")
            values.append(year_from)
        where_sql = " AND ".join(where)

        operaciones = conn.execute(
            f"""
            SELECT {", ".join(OPERACION_COLUMNS)}
            FROM operaciones_inmobiliarias
            WHERE {where_sql}
            ORDER BY COALESCE(NULLIF(fecha_escritura, ''), NULLIF(fecha_operacion, ''), updated_at, created_at) DESC
            """,
            values,
        ).fetchall()
        if not operaciones:
            raise SystemExit("No se encontraron compraventas para sincronizar.")

        inmueble_ids = sorted(
            {
                row["inmueble_id"]
                for row in operaciones
                if str(row["inmueble_id"] or "").strip()
            }
        )
        cliente_ids = sorted(
            {
                row[key]
                for row in operaciones
                for key in (
                    "propietario1_id",
                    "propietario2_id",
                    "contraparte1_id",
                    "contraparte2_id",
                )
                if str(row[key] or "").strip()
            }
        )

        inmuebles = []
        if inmueble_ids:
            placeholders = ", ".join(["?"] * len(inmueble_ids))
            inmuebles = conn.execute(
                f"""
                SELECT {", ".join(INMUEBLE_COLUMNS)}
                FROM inmuebles
                WHERE id IN ({placeholders})
                """,
                inmueble_ids,
            ).fetchall()

        relaciones = []
        if inmueble_ids:
            placeholders = ", ".join(["?"] * len(inmueble_ids))
            relaciones = conn.execute(
                f"""
                SELECT {", ".join(INMUEBLE_PROPIETARIO_COLUMNS)}
                FROM inmueble_propietarios
                WHERE inmueble_id IN ({placeholders})
                """,
                inmueble_ids,
            ).fetchall()
            for row in relaciones:
                cliente_id = row["cliente_id"]
                if cliente_id and cliente_id not in cliente_ids:
                    cliente_ids.append(cliente_id)
            cliente_ids.sort()

        clientes = []
        clientes_empresas = []
        captaciones = conn.execute(
            f"""
            SELECT {", ".join(CAPTACION_COLUMNS)}
            FROM captaciones
            WHERE empresa_id = ?
            ORDER BY updated_at DESC, created_at DESC
            """,
            (empresa_id,),
        ).fetchall()
        if cliente_ids:
            placeholders = ", ".join(["?"] * len(cliente_ids))
            clientes = conn.execute(
                f"""
                SELECT {", ".join(CLIENT_COLUMNS)}
                FROM clientes
                WHERE id IN ({placeholders})
                """,
                cliente_ids,
            ).fetchall()
            clientes_empresas = conn.execute(
                f"""
                SELECT {", ".join(CLIENT_EMPRESA_COLUMNS)}
                FROM clientes_empresas
                WHERE empresa_id = ?
                  AND cliente_id IN ({placeholders})
                  AND LOWER(COALESCE(servicio, '')) = 'inmobiliaria'
                """,
                [empresa_id, *cliente_ids],
            ).fetchall()

        return {
            "empresa_id": empresa_id,
            "empresa_nombre": empresa["nombre"],
            "year_from": year_from,
            "counts": {
                "operaciones": len(operaciones),
                "inmuebles": len(inmuebles),
                "clientes": len(clientes),
                "clientes_empresas": len(clientes_empresas),
                "inmueble_propietarios": len(relaciones),
                "captaciones": len(captaciones),
            },
            "operaciones": rows_to_dicts(operaciones),
            "inmuebles": rows_to_dicts(inmuebles),
            "clientes": rows_to_dicts(clientes),
            "clientes_empresas": rows_to_dicts(clientes_empresas),
            "inmueble_propietarios": rows_to_dicts(relaciones),
            "captaciones": rows_to_dicts(captaciones),
        }
    finally:
        conn.close()


def build_upsert_sql(table_name: str, columns: list[str], rows: list[dict]) -> list[str]:
    if not rows:
        return []
    assignments = ", ".join([f"{col} = excluded.{col}" for col in columns if col != "id"])
    lines: list[str] = []
    for row in rows:
        values = ", ".join(sql_literal(row.get(col)) for col in columns)
        lines.append(
            f"INSERT INTO {table_name} ({', '.join(columns)}) "
            f"VALUES ({values}) "
            f"ON CONFLICT(id) DO UPDATE SET {assignments};"
        )
    return lines


def build_sql(payload: dict) -> str:
    lines = [
        "PRAGMA foreign_keys = OFF;",
        "PRAGMA busy_timeout = 60000;",
        "BEGIN;",
    ]
    lines.extend(build_upsert_sql("clientes", CLIENT_COLUMNS, payload.get("clientes") or []))
    lines.extend(build_upsert_sql("clientes_empresas", CLIENT_EMPRESA_COLUMNS, payload.get("clientes_empresas") or []))
    lines.extend(build_upsert_sql("inmuebles", INMUEBLE_COLUMNS, payload.get("inmuebles") or []))
    lines.extend(
        build_upsert_sql(
            "inmueble_propietarios",
            INMUEBLE_PROPIETARIO_COLUMNS,
            payload.get("inmueble_propietarios") or [],
        )
    )
    lines.extend(build_upsert_sql("captaciones", CAPTACION_COLUMNS, payload.get("captaciones") or []))
    lines.extend(build_upsert_sql("operaciones_inmobiliarias", OPERACION_COLUMNS, payload.get("operaciones") or []))
    lines.extend(["COMMIT;", "PRAGMA foreign_keys = ON;"])
    return "\n".join(lines) + "\n"


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza compraventas a Render por SSH.")
    parser.add_argument("--local-db", default="data/erp_import2.sqlite", help="Ruta a la SQLite local.")
    parser.add_argument("--company", default=DEFAULT_COMPANY, help="Empresa origen en la base local.")
    parser.add_argument("--year-from", type=int, default=2020, help="Año mínimo a sincronizar.")
    parser.add_argument("--render-host", required=True, help="Host SSH de Render, ej. srv-xxx@ssh.frankfurt.render.com")
    parser.add_argument("--render-db", default="/var/data/erp_import2.sqlite", help="Ruta SQLite en Render.")
    parser.add_argument("--dry-run", action="store_true", help="Prepara el payload pero no lo sube.")
    parser.add_argument("--force-sqlite-target", action="store_true", help="Permite escribir en SQLite remota aunque el proyecto este en modo Postgres.")
    args = parser.parse_args()

    guard_remote_sqlite_sync(force=args.force_sqlite_target, script_name=Path(__file__).name)

    local_db = Path(args.local_db).expanduser().resolve()
    if not local_db.exists():
        raise SystemExit(f"No existe la base local: {local_db}")

    payload = fetch_payload(local_db, args.company, args.year_from)
    counts = payload["counts"]
    print(
        "Preparadas "
        f"{counts['operaciones']} compraventas, "
        f"{counts['inmuebles']} inmuebles, "
        f"{counts['captaciones']} captaciones, "
        f"{counts['clientes']} clientes y "
        f"{counts['clientes_empresas']} relaciones cliente-servicio."
    )
    if args.dry_run:
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        sql_path = Path(tmpdir) / "compraventas_sync.sql"
        sql_path.write_text(build_sql(payload), encoding="utf-8")

        remote_sql = "/tmp/compraventas_sync.sql"
        run(["scp", *SSH_OPTIONS, str(sql_path), f"{args.render_host}:{remote_sql}"])
        remote_cmd = (
            f"sqlite3 {args.render_db} < {remote_sql} "
            f"&& rm -f {remote_sql} "
            f"&& echo '__SYNC_OK__'"
        )
        run(["ssh", *SSH_OPTIONS, args.render_host, "sh", "-lc", remote_cmd])
        print("Sincronizacion completada.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
