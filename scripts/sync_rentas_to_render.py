#!/usr/bin/env python3
"""
Sincroniza a Render los clientes y módulos de renta creados en gestoría.

Uso:
  python3 scripts/sync_rentas_to_render.py \
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


GESTORIA_COMPANY = "Fincas Velazquez"
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
CLIENT_FIELDS = [
    "nombre",
    "nif",
    "telefono",
    "email",
    "tipo",
    "perfil",
    "estado",
    "fecha_nacimiento",
    "direccion",
    "tipo_persona",
    "codigo_postal",
    "poblacion",
    "provincia",
]


def fetch_payload(local_db: Path) -> dict:
    conn = sqlite3.connect(str(local_db))
    conn.row_factory = sqlite3.Row
    try:
        empresa = conn.execute(
            "SELECT id FROM empresas WHERE nombre = ? LIMIT 1",
            (GESTORIA_COMPANY,),
        ).fetchone()
        if not empresa:
            raise SystemExit(f"No existe la empresa {GESTORIA_COMPANY!r} en la base local.")
        empresa_id = empresa["id"]
        rows = conn.execute(
            """
            SELECT
              c.id AS cliente_id,
              c.nombre,
              c.nif,
              c.telefono,
              c.email,
              c.tipo,
              c.perfil,
              c.estado,
              c.fecha_nacimiento,
              c.direccion,
              c.tipo_persona,
              c.codigo_postal,
              c.poblacion,
              c.provincia,
              cg.tipo_cliente,
              cg.mod_fiscal,
              cg.mod_laboral,
              cg.mod_contable,
              cg.mod_registro,
              cg.mod_trafico,
              cg.mod_puntuales,
              cg.mod_renta,
              cg.renta_detalles,
              gt.tipo_trabajo,
              gt.estado AS trabajo_estado,
              gt.fecha_inicio,
              gt.fecha_fin,
              gt.responsable,
              gt.importe,
              gt.notas
            FROM cliente_gestoria cg
            JOIN clientes c ON c.id = cg.cliente_id
            LEFT JOIN gestoria_trabajos gt
              ON gt.cliente_id = c.id
             AND (UPPER(COALESCE(gt.tipo_trabajo, '')) = 'DECLARACIÓN EN PERIODO'
               OR UPPER(COALESCE(gt.tipo_trabajo, '')) = 'DECLARACION EN PERIODO')
            WHERE COALESCE(cg.mod_renta, 0) = 1
              AND COALESCE(TRIM(c.nif), '') <> ''
            ORDER BY c.updated_at DESC
            """,
        ).fetchall()
        items = []
        for row in rows:
            client = {field: row[field] for field in CLIENT_FIELDS}
            gestoria = {
                "tipo_cliente": row["tipo_cliente"],
                "mod_fiscal": row["mod_fiscal"],
                "mod_laboral": row["mod_laboral"],
                "mod_contable": row["mod_contable"],
                "mod_registro": row["mod_registro"],
                "mod_trafico": row["mod_trafico"],
                "mod_puntuales": row["mod_puntuales"],
                "mod_renta": row["mod_renta"],
                "renta_detalles": row["renta_detalles"],
            }
            trabajo = None
            if row["tipo_trabajo"]:
                trabajo = {
                    "tipo_trabajo": row["tipo_trabajo"],
                    "estado": row["trabajo_estado"],
                    "fecha_inicio": row["fecha_inicio"],
                    "fecha_fin": row["fecha_fin"],
                    "responsable": row["responsable"],
                    "importe": row["importe"],
                    "notas": row["notas"],
                }
            items.append(
                {
                    "client": client,
                    "gestoria": gestoria,
                    "trabajo": trabajo,
                }
            )
        return {
            "empresa_nombre": GESTORIA_COMPANY,
            "items": items,
        }
    finally:
        conn.close()


REMOTE_SCRIPT = r'''
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

db_path = sys.argv[1]
payload_path = sys.argv[2]

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
now = datetime.now(timezone.utc).isoformat()

with open(payload_path, 'r', encoding='utf-8') as fh:
    payload = json.load(fh)

empresa_nombre = payload["empresa_nombre"]
empresa = conn.execute("SELECT id FROM empresas WHERE nombre = ? LIMIT 1", (empresa_nombre,)).fetchone()
if not empresa:
    raise SystemExit(f"Empresa no encontrada en Render: {empresa_nombre}")
empresa_id = empresa["id"]

for item in payload["items"]:
    client = item["client"]
    gestoria = item["gestoria"]
    trabajo = item.get("trabajo")
    nif = str(client.get("nif") or "").strip().upper()
    if not nif:
        continue
    existing = conn.execute(
        "SELECT id FROM clientes WHERE UPPER(COALESCE(nif,'')) = ? ORDER BY updated_at DESC LIMIT 1",
        (nif,),
    ).fetchone()
    if existing:
        cliente_id = existing["id"]
        updates = [
            "empresa_id = ?",
            "nombre = ?",
            "telefono = ?",
            "email = ?",
            "tipo = ?",
            "perfil = ?",
            "estado = ?",
            "fecha_nacimiento = ?",
            "direccion = ?",
            "tipo_persona = ?",
            "codigo_postal = ?",
            "poblacion = ?",
            "provincia = ?",
            "updated_at = datetime(?)",
        ]
        conn.execute(
            f"UPDATE clientes SET {', '.join(updates)} WHERE id = ?",
            (
                empresa_id,
                client.get("nombre"),
                client.get("telefono"),
                client.get("email"),
                client.get("tipo"),
                client.get("perfil"),
                client.get("estado"),
                client.get("fecha_nacimiento"),
                client.get("direccion"),
                client.get("tipo_persona"),
                client.get("codigo_postal"),
                client.get("poblacion"),
                client.get("provincia"),
                now,
                cliente_id,
            ),
        )
    else:
        cliente_id = uuid.uuid4().hex
        conn.execute(
            """
            INSERT INTO clientes (
              id, empresa_id, nombre, nif, telefono, email, tipo, perfil, estado, created_at, updated_at,
              fecha_nacimiento, direccion, tipo_persona, codigo_postal, poblacion, provincia
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?), ?, ?, ?, ?, ?, ?
            )
            """,
            (
                cliente_id,
                empresa_id,
                client.get("nombre"),
                client.get("nif"),
                client.get("telefono"),
                client.get("email"),
                client.get("tipo"),
                client.get("perfil"),
                client.get("estado"),
                now,
                now,
                client.get("fecha_nacimiento"),
                client.get("direccion"),
                client.get("tipo_persona"),
                client.get("codigo_postal"),
                client.get("poblacion"),
                client.get("provincia"),
            ),
        )

    link = conn.execute(
        """
        SELECT id
        FROM clientes_empresas
        WHERE cliente_id = ? AND empresa_id = ? AND LOWER(COALESCE(servicio,'')) = 'gestoria'
        LIMIT 1
        """,
        (cliente_id, empresa_id),
    ).fetchone()
    if link:
        conn.execute(
            """
            UPDATE clientes_empresas
            SET estado = 'Activo', fecha_fin = NULL, updated_at = datetime(?)
            WHERE id = ?
            """,
            (now, link["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO clientes_empresas (
              id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at
            ) VALUES (
              ?, ?, ?, 'gestoria', 'Activo', date('now','localtime'), NULL, datetime(?), datetime(?)
            )
            """,
            (uuid.uuid4().hex, cliente_id, empresa_id, now, now),
        )

    cg = conn.execute("SELECT id FROM cliente_gestoria WHERE cliente_id = ? LIMIT 1", (cliente_id,)).fetchone()
    if cg:
        conn.execute(
            """
            UPDATE cliente_gestoria
            SET tipo_cliente = ?, mod_fiscal = ?, mod_laboral = ?, mod_contable = ?, mod_registro = ?,
                mod_trafico = ?, mod_puntuales = ?, mod_renta = ?, renta_detalles = ?, updated_at = datetime(?)
            WHERE cliente_id = ?
            """,
            (
                gestoria.get("tipo_cliente"),
                gestoria.get("mod_fiscal"),
                gestoria.get("mod_laboral"),
                gestoria.get("mod_contable"),
                gestoria.get("mod_registro"),
                gestoria.get("mod_trafico"),
                gestoria.get("mod_puntuales"),
                gestoria.get("mod_renta"),
                gestoria.get("renta_detalles"),
                now,
                cliente_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO cliente_gestoria (
              id, cliente_id, tipo_cliente, mod_fiscal, mod_laboral, mod_contable, mod_registro, mod_trafico,
              mod_puntuales, created_at, updated_at, mod_renta, renta_detalles
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?), ?, ?
            )
            """,
            (
                uuid.uuid4().hex,
                cliente_id,
                gestoria.get("tipo_cliente"),
                gestoria.get("mod_fiscal"),
                gestoria.get("mod_laboral"),
                gestoria.get("mod_contable"),
                gestoria.get("mod_registro"),
                gestoria.get("mod_trafico"),
                gestoria.get("mod_puntuales"),
                now,
                now,
                gestoria.get("mod_renta"),
                gestoria.get("renta_detalles"),
            ),
        )

    if trabajo:
        gt = conn.execute(
            """
            SELECT id
            FROM gestoria_trabajos
            WHERE cliente_id = ?
              AND (UPPER(COALESCE(tipo_trabajo,'')) = 'DECLARACIÓN EN PERIODO'
               OR UPPER(COALESCE(tipo_trabajo,'')) = 'DECLARACION EN PERIODO')
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (cliente_id,),
        ).fetchone()
        if gt:
            conn.execute(
                """
                UPDATE gestoria_trabajos
                SET empresa_id = ?, estado = ?, fecha_inicio = ?, fecha_fin = ?, responsable = ?,
                    importe = ?, notas = ?, updated_at = datetime(?)
                WHERE id = ?
                """,
                (
                    empresa_id,
                    trabajo.get("estado"),
                    trabajo.get("fecha_inicio"),
                    trabajo.get("fecha_fin"),
                    trabajo.get("responsable"),
                    trabajo.get("importe"),
                    trabajo.get("notas"),
                    now,
                    gt["id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO gestoria_trabajos (
                  id, empresa_id, cliente_id, tipo_trabajo, estado, fecha_inicio, fecha_fin, responsable, importe, notas,
                  created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    uuid.uuid4().hex,
                    empresa_id,
                    cliente_id,
                    trabajo.get("tipo_trabajo"),
                    trabajo.get("estado"),
                    trabajo.get("fecha_inicio"),
                    trabajo.get("fecha_fin"),
                    trabajo.get("responsable"),
                    trabajo.get("importe"),
                    trabajo.get("notas"),
                    now,
                    now,
                ),
            )

conn.commit()
print(json.dumps({"ok": True, "items": len(payload["items"])}, ensure_ascii=False))
'''


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza rentas a Render por SSH.")
    parser.add_argument("--local-db", default="data/erp_import2.sqlite", help="Ruta a la SQLite local.")
    parser.add_argument("--render-host", required=True, help="Host SSH de Render, ej. srv-xxx@ssh.frankfurt.render.com")
    parser.add_argument("--render-db", default="/var/data/erp_import2.sqlite", help="Ruta SQLite en Render.")
    parser.add_argument("--dry-run", action="store_true", help="Genera el payload pero no lo sube.")
    args = parser.parse_args()

    local_db = Path(args.local_db).expanduser().resolve()
    if not local_db.exists():
        raise SystemExit(f"No existe la base local: {local_db}")

    payload = fetch_payload(local_db)
    if not payload["items"]:
        raise SystemExit("No se encontraron clientes de renta aplicados en la base local.")

    with tempfile.TemporaryDirectory() as tmpdir:
        payload_path = Path(tmpdir) / "rentas_sync.json"
        script_path = Path(tmpdir) / "rentas_sync_remote.py"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        script_path.write_text(REMOTE_SCRIPT, encoding="utf-8")
        print(f"Preparados {len(payload['items'])} clientes de renta para sincronizar.")
        print(f"Payload temporal: {payload_path}")
        if args.dry_run:
            return

        remote_payload = "/tmp/rentas_sync.json"
        remote_script = "/tmp/rentas_sync_remote.py"
        run(["scp", *SSH_OPTIONS, str(payload_path), f"{args.render_host}:{remote_payload}"])
        run(["scp", *SSH_OPTIONS, str(script_path), f"{args.render_host}:{remote_script}"])
        remote_cmd = (
            f"python3 {remote_script} {args.render_db} {remote_payload} "
            f"&& rm -f {remote_script} {remote_payload} "
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
        print("Sincronizacion de rentas completada.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
