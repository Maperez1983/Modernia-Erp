#!/usr/bin/env python3
"""
Sincroniza a Render (Postgres) los clientes y módulos de renta creados en gestoría.

Uso:
  python3 scripts/sync_rentas_to_render_postgres.py \
    --local-db data/erp_import2.sqlite \
    --render-host srv-xxxx@ssh.frankfurt.render.com

Filtrar a una lista de NIFs (por ejemplo, `reports/rentas_2024_missing_in_system.csv`):
  python3 scripts/sync_rentas_to_render_postgres.py \
    --local-db data/erp_import2.sqlite \
    --render-host srv-xxxx@ssh.frankfurt.render.com \
    --only-nifs-csv reports/rentas_2024_missing_in_system.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path


GESTORIA_COMPANY = "Fincas Velazquez"
DEFAULT_RENDER_WORKDIR = "/opt/render/project/src"
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


def _normalize_nif(value: object) -> str:
    return str(value or "").strip().upper().replace(" ", "").replace(".", "").replace("-", "")


def load_only_nifs_csv(path: Path) -> set[str]:
    path = path.expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"No existe el CSV de NIFs: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise SystemExit(f"CSV inválido (sin cabecera): {path}")
        nif_key = None
        for key in ("nif", "NIF"):
            if key in reader.fieldnames:
                nif_key = key
                break
        if not nif_key:
            raise SystemExit(f"CSV inválido (no tiene columna nif): {path}")
        out: set[str] = set()
        for row in reader:
            nif = _normalize_nif(row.get(nif_key))
            if nif:
                out.add(nif)
        return out


def fetch_payload(local_db: Path, only_nifs: set[str] | None = None) -> dict:
    conn = sqlite3.connect(str(local_db))
    conn.row_factory = sqlite3.Row
    try:
        empresa = conn.execute(
            "SELECT id FROM empresas WHERE nombre = ? LIMIT 1",
            (GESTORIA_COMPANY,),
        ).fetchone()
        if not empresa:
            raise SystemExit(f"No existe la empresa {GESTORIA_COMPANY!r} en la base local.")

        try:
            cliente_cols = {row["name"] for row in conn.execute("PRAGMA table_info(clientes)").fetchall()}
        except Exception:
            cliente_cols = set()
        hijos_select = "c.hijos_count AS hijos_count," if "hijos_count" in cliente_cols else "NULL AS hijos_count,"

        rows = conn.execute(
            f"""
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
              {hijos_select}
              c.direccion,
              c.tipo_persona,
              c.codigo_postal,
              c.poblacion,
              c.provincia,
              (SELECT iban FROM cliente_profesional p WHERE p.cliente_id = c.id ORDER BY COALESCE(p.principal, 0) DESC, p.created_at ASC LIMIT 1) AS iban,
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

        if only_nifs:
            rows = [row for row in rows if _normalize_nif(row["nif"]) in only_nifs]

        allowed_cliente_ids = {str(row["cliente_id"]) for row in rows}

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
            """,
        ).fetchall()

        docs_by_client: dict[str, list[dict]] = {}
        for doc in doc_rows:
            if allowed_cliente_ids and str(doc["cliente_id"]) not in allowed_cliente_ids:
                continue
            doc_key = str(doc["doc_key"] or "").strip()
            doc_url = str(doc["doc_url"] or "").strip()
            # Si no hay doc_key/doc_url reales (por ejemplo, solo rutas locales en notas), no sincronizamos.
            if not doc_key and not doc_url:
                continue
            docs_by_client.setdefault(str(doc["cliente_id"]), []).append(
                {
                    "nombre": doc["nombre"],
                    "tipo": doc["tipo"],
                    "fecha": doc["fecha"],
                    "estado": doc["estado"],
                    "notas": doc["notas"],
                    "doc_key": doc_key,
                    "doc_url": doc_url,
                    "referencia_tipo": doc["referencia_tipo"],
                    "referencia_id": doc["referencia_id"],
                }
            )

        items = []
        for row in rows:
            client = {key: row[key] for key in ("nombre", "nif", "telefono", "email", "tipo", "perfil", "estado", "fecha_nacimiento", "hijos_count", "direccion", "tipo_persona", "codigo_postal", "poblacion", "provincia", "iban")}
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
        return {"empresa_nombre": GESTORIA_COMPANY, "items": items}
    finally:
        conn.close()


REMOTE_SCRIPT_PG = r'''
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

payload_path = sys.argv[1]
now = datetime.now(timezone.utc).isoformat()

dsn = (os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or "").strip()
if not dsn.lower().startswith("postgres"):
    raise SystemExit("DATABASE_URL/POSTGRES_URL no apunta a Postgres.")

with open(payload_path, "r", encoding="utf-8") as fh:
    payload = json.load(fh)

conn = psycopg.connect(dsn, row_factory=dict_row)
conn.autocommit = False
try:
	    with conn.cursor() as cur:
	        empresa_nombre = payload["empresa_nombre"]
	        empresa = cur.execute("SELECT id FROM empresas WHERE nombre = %s LIMIT 1", (empresa_nombre,)).fetchone()
	        if not empresa:
	            raise SystemExit(f"Empresa no encontrada en Render: {empresa_nombre}")
	        empresa_id = empresa["id"]
	
	        # Migración ligera: asegurar columna para no depender del arranque del server.
	        cur.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS hijos_count integer")

	        processed = 0
	        for item in payload.get("items") or []:
	            client = item.get("client") or {}
            gestoria = item.get("gestoria") or {}
            trabajo = item.get("trabajo") or None
            docs = item.get("docs") or []

            nif = str(client.get("nif") or "").strip().upper()
            if not nif:
                continue

	            existing = cur.execute(
	                "SELECT id, hijos_count FROM clientes WHERE UPPER(COALESCE(nif,'')) = %s ORDER BY updated_at DESC LIMIT 1",
	                (nif,),
	            ).fetchone()
	            if existing:
	                cliente_id = existing["id"]
                # IMPORTANTE: no pisar datos existentes con valores vacíos.
                # Solo rellenar campos cuando el payload trae un valor real.
                updates = {"empresa_id": empresa_id, "updated_at": now}
                def _nonempty(v):
                    s = str(v or "").strip()
                    return s if s else ""
	                for key in (
	                    "nombre",
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
	                ):
                    value = client.get(key)
                    if value is None:
                        continue
                    if key in {"codigo_postal"}:
                        # Puede venir como None/"" en SQLite; tratamos "" como vacío.
                        value = _nonempty(value)
                    if isinstance(value, str):
                        value = value.strip()
	                    if value == "" or value is None:
	                        continue
	                    updates[key] = value
	                hijos_count = client.get("hijos_count")
	                if hijos_count is not None and existing.get("hijos_count") is None:
	                    try:
	                        updates["hijos_count"] = int(hijos_count)
	                    except Exception:
	                        pass
	                set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
	                cur.execute(
	                    f"UPDATE clientes SET {set_clause} WHERE id = %s",
	                    (*updates.values(), cliente_id),
	                )
	            else:
	                cliente_id = uuid.uuid4().hex
	                cur.execute(
	                    """
	                    INSERT INTO clientes (
	                      id, empresa_id, nombre, nif, telefono, email, tipo, perfil, estado,
	                      created_at, updated_at, fecha_nacimiento, hijos_count, direccion, tipo_persona, codigo_postal, poblacion, provincia
	                    ) VALUES (
	                      %s, %s, %s, %s, %s, %s, %s, %s, %s,
	                      %s, %s, %s, %s, %s, %s, %s, %s, %s
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
	                        client.get("hijos_count"),
	                        client.get("direccion"),
	                        client.get("tipo_persona"),
	                        client.get("codigo_postal"),
	                        client.get("poblacion"),
	                        client.get("provincia"),
	                    ),
	                )

            link = cur.execute(
                """
                SELECT id
                FROM clientes_empresas
                WHERE cliente_id = %s AND empresa_id = %s AND LOWER(COALESCE(servicio,'')) = 'gestoria'
                LIMIT 1
                """,
                (cliente_id, empresa_id),
            ).fetchone()
            if link:
                cur.execute(
                    "UPDATE clientes_empresas SET estado='Activo', fecha_fin=NULL, updated_at=%s WHERE id=%s",
                    (now, link["id"]),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO clientes_empresas (
                      id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at
                    ) VALUES (
                      %s, %s, %s, 'gestoria', 'Activo', CURRENT_DATE, NULL, %s, %s
                    )
                    """,
                    (uuid.uuid4().hex, cliente_id, empresa_id, now, now),
                )

            iban = str(client.get("iban") or "").strip()
            if iban:
                try:
                    prof = cur.execute(
                        """
                        SELECT id, iban
                        FROM cliente_profesional
                        WHERE cliente_id = %s
                        ORDER BY COALESCE(principal, 0) DESC, created_at ASC
                        LIMIT 1
                        """,
                        (cliente_id,),
                    ).fetchone()
                    if prof:
                        existing_iban = str(prof.get("iban") or "").strip()
                        if not existing_iban:
                            cur.execute(
                                "UPDATE cliente_profesional SET iban=%s, principal=COALESCE(principal,1), updated_at=%s WHERE id=%s",
                                (iban, now, prof["id"]),
                            )
                    else:
                        cur.execute(
                            """
                            INSERT INTO cliente_profesional (
                              id, cliente_id, cnae, iae, actividad, iban, principal, created_at, updated_at
                            ) VALUES (
                              %s, %s, '', '', '', %s, 1, %s, %s
                            )
                            """,
                            (uuid.uuid4().hex, cliente_id, iban, now, now),
                        )
                except Exception:
                    # Best effort: no bloquear el sync por este extra.
                    conn.rollback()

            cg = cur.execute("SELECT id FROM cliente_gestoria WHERE cliente_id = %s LIMIT 1", (cliente_id,)).fetchone()
            if cg:
                cur.execute(
                    """
                    UPDATE cliente_gestoria
                    SET tipo_cliente = %s, mod_fiscal = %s, mod_laboral = %s, mod_contable = %s, mod_registro = %s,
                        mod_trafico = %s, mod_puntuales = %s, mod_renta = %s, renta_detalles = %s, updated_at = %s
                    WHERE cliente_id = %s
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
                cur.execute(
                    """
                    INSERT INTO cliente_gestoria (
                      id, cliente_id, tipo_cliente, mod_fiscal, mod_laboral, mod_contable, mod_registro, mod_trafico,
                      mod_puntuales, created_at, updated_at, mod_renta, renta_detalles
                    ) VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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
                row = cur.execute(
                    """
                    SELECT id FROM gestoria_trabajos
                    WHERE cliente_id=%s
                      AND (UPPER(COALESCE(tipo_trabajo,''))='DECLARACIÓN EN PERIODO' OR UPPER(COALESCE(tipo_trabajo,''))='DECLARACION EN PERIODO')
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (cliente_id,),
                ).fetchone()
                if row:
                    cur.execute(
                        """
                        UPDATE gestoria_trabajos SET
                          empresa_id=%s, estado=%s, fecha_inicio=%s, fecha_fin=%s, responsable=%s, importe=%s, notas=%s, updated_at=%s
                        WHERE id=%s
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
                            row["id"],
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO gestoria_trabajos (
                          id, empresa_id, cliente_id, tipo_trabajo, estado, fecha_inicio, fecha_fin, responsable, importe, notas, created_at, updated_at
                        ) VALUES (
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            uuid.uuid4().hex,
                            empresa_id,
                            cliente_id,
                            trabajo.get("tipo_trabajo") or "Declaración en periodo",
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

            for doc in docs:
                doc_url = str(doc.get("doc_url") or "").strip()
                if doc_url:
                    existing_doc = cur.execute(
                        "SELECT id FROM gestoria_docs WHERE cliente_id=%s AND COALESCE(doc_url,'')=%s LIMIT 1",
                        (cliente_id, doc_url),
                    ).fetchone()
                else:
                    existing_doc = cur.execute(
                        "SELECT id FROM gestoria_docs WHERE cliente_id=%s AND LOWER(COALESCE(nombre,''))=LOWER(%s) LIMIT 1",
                        (cliente_id, doc.get("nombre")),
                    ).fetchone()
                if existing_doc:
                    cur.execute(
                        """
                        UPDATE gestoria_docs SET
                          empresa_id=%s, referencia_tipo=%s, referencia_id=%s, nombre=%s, tipo=%s, fecha=%s, estado=%s,
                          notas=%s, doc_key=%s, doc_url=%s, updated_at=%s
                        WHERE id=%s
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
                            doc.get("doc_key") or uuid.uuid4().hex,
                            doc_url,
                            now,
                            existing_doc["id"],
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO gestoria_docs (
                          id, empresa_id, cliente_id, referencia_tipo, referencia_id,
                          nombre, tipo, fecha, estado, notas, doc_key, doc_url, created_at, updated_at
                        ) VALUES (
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
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
                            doc.get("doc_key") or uuid.uuid4().hex,
                            doc_url,
                            now,
                            now,
                        ),
                    )

            processed += 1

    conn.commit()
    print(json.dumps({"ok": True, "items": processed}, ensure_ascii=False))
finally:
    conn.close()
'''

# El string anterior se mantiene por compatibilidad/histórico, pero el script remoto real vive en
# `scripts/rentas_sync_remote_pg.py` para evitar problemas de indentación/tabulaciones.
try:
    REMOTE_SCRIPT_PG = Path(__file__).with_name("rentas_sync_remote_pg.py").read_text(encoding="utf-8")
except Exception as exc:
    raise SystemExit(f"No se pudo leer scripts/rentas_sync_remote_pg.py: {exc}") from exc


class CommandError(RuntimeError):
    def __init__(self, cmd: list[str], returncode: int, stdout: str, stderr: str):
        super().__init__("command failed")
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout or ""
        self.stderr = stderr or ""


def run(cmd: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[str]:
    if input_bytes is None:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    else:
        # Python 3.9: si `text=True`, `input` debe ser str. Enviamos bytes sin modo texto y decodificamos.
        proc = subprocess.run(cmd, input=input_bytes, capture_output=True)
        if isinstance(proc.stdout, (bytes, bytearray)):
            proc.stdout = proc.stdout.decode("utf-8", errors="replace")
        if isinstance(proc.stderr, (bytes, bytearray)):
            proc.stderr = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode == 0:
        return proc
    raise CommandError(cmd, proc.returncode, proc.stdout or "", proc.stderr or "")


def is_transient_ssh_error(err: CommandError) -> bool:
    text = f"{err.stdout}\n{err.stderr}".lower()
    if err.returncode == 255:
        return True
    for token in ("is unavailable", "connection closed", "connection reset", "broken pipe", "timed out", "timeout"):
        if token in text:
            return True
    return False


def run_retry(cmd: list[str], retries: int, wait_seconds: float) -> None:
    attempt = 0
    last: CommandError | None = None
    while attempt <= max(0, int(retries)):
        try:
            run(cmd)
            return
        except CommandError as err:
            last = err
            if attempt >= retries or not is_transient_ssh_error(err):
                break
            print(f"[sync] Transient failure, retry {attempt + 1}/{retries}: {' '.join(cmd)}", file=sys.stderr)
            time.sleep(max(0.5, float(wait_seconds)))
            attempt += 1
    assert last is not None
    print(f"[sync] Command failed ({last.returncode}): {' '.join(last.cmd)}", file=sys.stderr)
    if last.stdout:
        print(last.stdout.rstrip(), file=sys.stderr)
    if last.stderr:
        print(last.stderr.rstrip(), file=sys.stderr)
    raise SystemExit(last.returncode)


def build_tar_gz(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            info.mtime = int(time.time())
            tf.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def run_retry_with_input(cmd: list[str], input_bytes: bytes, retries: int, wait_seconds: float) -> subprocess.CompletedProcess[str]:
    attempt = 0
    last: CommandError | None = None
    while attempt <= max(0, int(retries)):
        try:
            return run(cmd, input_bytes=input_bytes)
        except CommandError as err:
            last = err
            if attempt >= retries or not is_transient_ssh_error(err):
                break
            print(f"[sync] Transient failure, retry {attempt + 1}/{retries}: {' '.join(cmd)}", file=sys.stderr)
            time.sleep(max(0.5, float(wait_seconds)))
            attempt += 1
    assert last is not None
    print(f"[sync] Command failed ({last.returncode}): {' '.join(last.cmd)}", file=sys.stderr)
    if last.stdout:
        print(last.stdout.rstrip(), file=sys.stderr)
    if last.stderr:
        print(last.stderr.rstrip(), file=sys.stderr)
    raise SystemExit(last.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza rentas a Render (Postgres) por SSH.")
    parser.add_argument("--local-db", default="data/erp_import2.sqlite", help="Ruta a la SQLite local.")
    parser.add_argument("--render-host", required=True, help="Host SSH de Render, ej. srv-xxx@ssh.frankfurt.render.com")
    parser.add_argument("--render-workdir", default=DEFAULT_RENDER_WORKDIR, help="Directorio del proyecto en Render para ficheros temporales.")
    parser.add_argument("--render-python", default="", help="Python a usar en Render (si vacío: .venv/bin/python).")
    parser.add_argument("--only-nifs-csv", default="", help="CSV con columna 'nif' para sincronizar solo esos clientes.")
    parser.add_argument("--retries", type=int, default=6, help="Reintentos ante fallos transitorios de SSH/SCP.")
    parser.add_argument("--retry-wait", type=float, default=8.0, help="Segundos entre reintentos.")
    parser.add_argument("--via-stdin", action="store_true", help="Sincroniza en una sola conexión SSH (recomendado en Render).")
    parser.add_argument("--keep-remote", action="store_true", help="No borra los ficheros temporales en /tmp tras sincronizar.")
    parser.add_argument("--dry-run", action="store_true", help="Genera el payload pero no lo sube.")
    args = parser.parse_args()

    local_db = Path(args.local_db).expanduser().resolve()
    if not local_db.exists():
        raise SystemExit(f"No existe la base local: {local_db}")

    only_nifs = load_only_nifs_csv(Path(args.only_nifs_csv)) if str(args.only_nifs_csv or "").strip() else None
    payload = fetch_payload(local_db, only_nifs=only_nifs)
    if not payload["items"]:
        raise SystemExit("No se encontraron clientes de renta aplicados en la base local.")

    render_workdir = str(args.render_workdir or DEFAULT_RENDER_WORKDIR).rstrip("/")
    # En Render, el repo puede no ser escribible en algunos despliegues. Usamos /tmp para ficheros temporales.
    scratch_dir = "/tmp/rentas_sync"
    remote_payload = f"{scratch_dir}/rentas_sync.json"
    remote_script = f"{scratch_dir}/rentas_sync_remote_pg.py"
    render_python = str(args.render_python or "").strip() or f"{render_workdir}/.venv/bin/python"

    with tempfile.TemporaryDirectory() as tmpdir:
        payload_path = Path(tmpdir) / "rentas_sync.json"
        script_path = Path(tmpdir) / "rentas_sync_remote_pg.py"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        script_path.write_text(REMOTE_SCRIPT_PG, encoding="utf-8")
        try:
            compile(REMOTE_SCRIPT_PG, "rentas_sync_remote_pg.py", "exec")
        except SyntaxError as exc:
            raise SystemExit(f"El script remoto no compila: {exc}") from exc

        docs_total = sum(len(item.get("docs") or []) for item in payload.get("items") or [])
        print(f"Preparados {len(payload['items'])} clientes de renta para sincronizar.")
        print(f"Documentos de renta detectados: {docs_total}.")
        print(f"Payload temporal: {payload_path}")
        if args.dry_run:
            return

        if args.via_stdin:
            tar_bytes = build_tar_gz(
                {
                    "rentas_sync.json": payload_path.read_bytes(),
                    "rentas_sync_remote_pg.py": script_path.read_bytes(),
                }
            )
            cleanup = "" if args.keep_remote else f" && rm -rf {scratch_dir}"
            remote_cmd = (
                f"set -e; mkdir -p {scratch_dir} "
                f"&& tar -xzf - -C {scratch_dir} "
                f"&& {render_python} {remote_script} {remote_payload}{cleanup} "
                f"&& echo '__SYNC_OK__'"
            )
            proc = run_retry_with_input(["ssh", *SSH_OPTIONS, args.render_host, remote_cmd], tar_bytes, args.retries, args.retry_wait)
            if proc.stdout.strip():
                print(proc.stdout.strip())
        else:
            run_retry(["ssh", *SSH_OPTIONS, args.render_host, f"mkdir -p {scratch_dir}"], args.retries, args.retry_wait)
            run_retry(["scp", *SSH_OPTIONS, str(payload_path), f"{args.render_host}:{remote_payload}"], args.retries, args.retry_wait)
            run_retry(["scp", *SSH_OPTIONS, str(script_path), f"{args.render_host}:{remote_script}"], args.retries, args.retry_wait)
            cleanup = "" if args.keep_remote else f" && rm -rf {scratch_dir}"
            remote_cmd = f"{render_python} {remote_script} {remote_payload}{cleanup} && echo '__SYNC_OK__'"
            run_retry(["ssh", *SSH_OPTIONS, args.render_host, remote_cmd], args.retries, args.retry_wait)
        print("Sincronización de rentas completada (Render Postgres).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
