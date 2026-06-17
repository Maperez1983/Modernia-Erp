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
import tarfile
from pathlib import Path

try:
    from .render_backend_guard import guard_remote_sqlite_sync
except ImportError:
    from render_backend_guard import guard_remote_sqlite_sync


GESTORIA_COMPANY = "Fincas Velazquez"
ROOT = Path(__file__).resolve().parents[1]
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
DEFAULT_LOCAL_UPLOADS = ROOT / "web" / "uploads"
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
        doc_rows = conn.execute(
            """
            SELECT
              d.cliente_id,
              d.nombre,
              d.tipo,
              d.fecha,
              d.estado,
              d.notas,
              d.doc_key,
              d.doc_url,
              d.referencia_tipo,
              d.referencia_id
            FROM gestoria_docs d
            JOIN cliente_gestoria cg ON cg.cliente_id = d.cliente_id
            WHERE COALESCE(cg.mod_renta, 0) = 1
              AND (
                LOWER(COALESCE(d.referencia_tipo, '')) = 'renta'
                OR LOWER(COALESCE(d.tipo, '')) = 'renta'
                OR LOWER(COALESCE(d.tipo, '')) = 'declaracion de renta'
                OR LOWER(COALESCE(d.nombre, '')) LIKE 'renta %'
              )
            ORDER BY d.updated_at DESC
            """
        ).fetchall()
        docs_by_client: dict[str, list[dict]] = {}
        for doc in doc_rows:
            docs_by_client.setdefault(str(doc["cliente_id"]), []).append(
                {
                    "nombre": doc["nombre"],
                    "tipo": doc["tipo"],
                    "fecha": doc["fecha"],
                    "estado": doc["estado"],
                    "notas": doc["notas"],
                    "doc_key": doc["doc_key"],
                    "doc_url": doc["doc_url"],
                    "referencia_tipo": doc["referencia_tipo"],
                    "referencia_id": doc["referencia_id"],
                }
            )
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
                    "docs": docs_by_client.get(str(row["cliente_id"]), []),
                }
            )
        return {
            "empresa_nombre": GESTORIA_COMPANY,
            "items": items,
        }
    finally:
        conn.close()


def build_docs_archive(payload: dict, local_uploads: Path, archive_path: Path) -> tuple[int, int]:
    local_uploads = local_uploads.expanduser().resolve()
    if not local_uploads.exists():
        return 0, 0
    seen = set()
    added = 0
    missing = 0
    with tarfile.open(archive_path, "w") as tar:
        for item in payload.get("items") or []:
            for doc in item.get("docs") or []:
                doc_url = str(doc.get("doc_url") or "").strip()
                if not doc_url.startswith("/uploads/"):
                    continue
                rel = doc_url.replace("/uploads/", "", 1)
                if rel in seen:
                    continue
                source_path = local_uploads / rel
                if not source_path.exists():
                    missing += 1
                    continue
                tar.add(source_path, arcname=rel)
                seen.add(rel)
                added += 1
    return added, missing


REMOTE_SCRIPT = r'''
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

db_path = sys.argv[1]
payload_path = sys.argv[2]
uploads_root = Path(sys.argv[3])

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
now = datetime.now(timezone.utc).isoformat()
uploads_root.mkdir(parents=True, exist_ok=True)

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

    for doc in item.get("docs") or []:
        doc_url = str(doc.get("doc_url") or "").strip()
        if doc_url.startswith("/uploads/"):
            rel = doc_url.replace("/uploads/", "", 1)
            target = uploads_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
        existing_doc = conn.execute(
            """
            SELECT id
            FROM gestoria_docs
            WHERE cliente_id = ? AND COALESCE(doc_url, '') = ?
            LIMIT 1
            """,
            (cliente_id, doc_url),
        ).fetchone()
        if existing_doc:
            conn.execute(
                """
                UPDATE gestoria_docs
                SET empresa_id = ?, referencia_tipo = ?, referencia_id = ?, nombre = ?, tipo = ?,
                    fecha = ?, estado = ?, notas = ?, doc_key = ?, doc_url = ?, updated_at = datetime(?)
                WHERE id = ?
                """,
                (
                    empresa_id,
                    doc.get("referencia_tipo"),
                    doc.get("referencia_id"),
                    doc.get("nombre"),
                    doc.get("tipo"),
                    doc.get("fecha"),
                    doc.get("estado"),
                    doc.get("notas"),
                    doc.get("doc_key"),
                    doc.get("doc_url"),
                    now,
                    existing_doc["id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO gestoria_docs (
                  id, empresa_id, cliente_id, referencia_tipo, referencia_id,
                  nombre, tipo, fecha, estado, notas, doc_key, doc_url, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    uuid.uuid4().hex,
                    empresa_id,
                    cliente_id,
                    doc.get("referencia_tipo"),
                    doc.get("referencia_id"),
                    doc.get("nombre"),
                    doc.get("tipo"),
                    doc.get("fecha"),
                    doc.get("estado"),
                    doc.get("notas"),
                    doc.get("doc_key"),
                    doc.get("doc_url"),
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
    parser.add_argument("--local-uploads", default=str(DEFAULT_LOCAL_UPLOADS), help="Carpeta local de uploads servidos por la app.")
    parser.add_argument("--render-host", required=True, help="Host SSH de Render, ej. srv-xxx@ssh.frankfurt.render.com")
    parser.add_argument("--render-db", default="/var/data/erp_import2.sqlite", help="Ruta SQLite en Render.")
    parser.add_argument("--render-uploads", default="/var/data/uploads", help="Carpeta persistente de uploads en Render.")
    parser.add_argument("--dry-run", action="store_true", help="Genera el payload pero no lo sube.")
    parser.add_argument("--force-sqlite-target", action="store_true", help="Permite escribir en SQLite remota aunque el proyecto este en modo Postgres.")
    args = parser.parse_args()

    guard_remote_sqlite_sync(force=args.force_sqlite_target, script_name=Path(__file__).name)

    local_db = Path(args.local_db).expanduser().resolve()
    local_uploads = Path(args.local_uploads).expanduser().resolve()
    if not local_db.exists():
        raise SystemExit(f"No existe la base local: {local_db}")

    payload = fetch_payload(local_db)
    if not payload["items"]:
        raise SystemExit("No se encontraron clientes de renta aplicados en la base local.")

    with tempfile.TemporaryDirectory() as tmpdir:
        payload_path = Path(tmpdir) / "rentas_sync.json"
        script_path = Path(tmpdir) / "rentas_sync_remote.py"
        docs_archive_path = Path(tmpdir) / "rentas_uploads.tar"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        script_path.write_text(REMOTE_SCRIPT, encoding="utf-8")
        docs_added, docs_missing = build_docs_archive(payload, local_uploads, docs_archive_path)
        docs_total = sum(len(item.get("docs") or []) for item in payload.get("items") or [])
        print(f"Preparados {len(payload['items'])} clientes de renta para sincronizar.")
        print(f"Documentos de renta detectados: {docs_total}. Ficheros empaquetados: {docs_added}. Faltantes: {docs_missing}.")
        print(f"Payload temporal: {payload_path}")
        if args.dry_run:
            return

        remote_payload = "/tmp/rentas_sync.json"
        remote_script = "/tmp/rentas_sync_remote.py"
        remote_archive = "/tmp/rentas_uploads.tar"
        run(["scp", *SSH_OPTIONS, str(payload_path), f"{args.render_host}:{remote_payload}"])
        run(["scp", *SSH_OPTIONS, str(script_path), f"{args.render_host}:{remote_script}"])
        run(["scp", *SSH_OPTIONS, str(docs_archive_path), f"{args.render_host}:{remote_archive}"])
        remote_cmd = (
            f"mkdir -p {args.render_uploads} "
            f"&& tar -xf {remote_archive} -C {args.render_uploads} "
            f"&& python3 {remote_script} {args.render_db} {remote_payload} {args.render_uploads} "
            f"&& rm -f {remote_script} {remote_payload} {remote_archive} "
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
