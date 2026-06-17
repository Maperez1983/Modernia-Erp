#!/usr/bin/env python3
"""
Sincroniza pólizas de Seguros desde un CSV de extracción (local) hasta la SQLite
persistente de Render usando SSH, incluyendo sustitución del PDF (uploads).

Qué hace:
  - Lee un CSV tipo `seguros_analyze_*_unique.csv` o `seguros_extract_*.csv`.
  - Filtra doc_kind=poliza y deduplica por (poliza_numero_norm + compania_norm).
  - Copia los PDFs a `--render-uploads` bajo `/uploads/<uploads-subdir>/...`
    (se sirven por `web/server.py` y se abren como fallbackUrl).
  - Actualiza la ficha de la póliza en `seguros` (tomador, fechas, ramo, primas, etc).
  - Enlaza la póliza con el cliente por NIF (si existe en Render) y asegura
    el vínculo `clientes_empresas` (servicio='seguros').
  - Crea/actualiza `gestoria_docs` como documento asociado (referencia_tipo='seguros').

Uso:
  python3 scripts/sync_seguros_to_render.py \\
    --extract-csv reports/seguros_analyze_..._unique.csv \\
    --empresa-id a261e552-8b9c-4da4-a279-a21c33277789 \\
    --render-host srv-xxxx@ssh.frankfurt.render.com \\
    --render-db /var/data/erp_import2.sqlite
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .render_backend_guard import guard_remote_sqlite_sync
except ImportError:
    from render_backend_guard import guard_remote_sqlite_sync


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


def _norm_id(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper().strip() if ch.isalnum())


def _norm_poliza(value: Any) -> str:
    return _norm_id(value)


def _norm_company(value: Any) -> str:
    return _norm_id(value)


def _safe_filename(value: str) -> str:
    import re

    s = str(value or "").strip()
    if not s:
        return "archivo.pdf"
    s = re.sub(r"[^A-Za-z0-9._-]", "_", s)
    if len(s) > 140:
        s = s[:140]
    return s


@dataclass(frozen=True)
class Key:
    poliza_norm: str
    compania_norm: str

    def as_str(self) -> str:
        return f"{self.poliza_norm}|{self.compania_norm}"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _dedupe_polizas(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for r in rows:
        if (r.get("doc_kind") or "").strip() != "poliza":
            continue
        pol = _norm_poliza(r.get("poliza_numero") or r.get("poliza_numero_norm") or "")
        comp = _norm_company(r.get("compania") or r.get("compania_norm") or "")
        if not pol or not comp:
            continue
        k = Key(pol, comp).as_str()
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _build_upload_rel(empresa_id: str, row: dict[str, str], *, uploads_subdir: str) -> str:
    pol = _norm_poliza(row.get("poliza_numero") or row.get("poliza_numero_norm") or "")
    comp = _norm_company(row.get("compania") or row.get("compania_norm") or "")
    digest = hashlib.sha1(f"{empresa_id}|{pol}|{comp}".encode("utf-8")).hexdigest()[:12]
    prefix = (uploads_subdir or "seguros_sync").strip("/").strip() or "seguros_sync"
    base = f"poliza_{pol[:18]}_{comp[:12]}_{digest}.pdf"
    base = _safe_filename(base)
    return f"{prefix}/{empresa_id}/{base}"


def _build_archive(items: list[dict], archive_path: Path) -> tuple[int, int]:
    added = 0
    missing = 0
    with tarfile.open(archive_path, "w") as tar:
        for item in items:
            src = Path(item["local_pdf"]).expanduser()
            rel = str(item["upload_rel"]).lstrip("/").replace("\\", "/")
            if not src.exists():
                missing += 1
                continue
            tar.add(str(src), arcname=rel)
            added += 1
    return added, missing


REMOTE_SCRIPT = r'''
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


def norm_id(value):
    return "".join(ch for ch in str(value or "").upper().strip() if ch.isalnum())


def norm_poliza(value):
    return norm_id(value)


def norm_company(value):
    return norm_id(value)


def ensure_cliente_servicio(conn, *, cliente_id, empresa_id, servicio, now):
    if not cliente_id or not empresa_id:
        return
    row = conn.execute(
        """
        SELECT id
        FROM clientes_empresas
        WHERE cliente_id = ? AND empresa_id = ? AND LOWER(COALESCE(servicio,'')) = ?
        LIMIT 1
        """,
        (cliente_id, empresa_id, str(servicio or "").strip().lower()),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE clientes_empresas
            SET estado = 'Activo', fecha_fin = NULL, updated_at = datetime(?)
            WHERE id = ?
            """,
            (now, row["id"]),
        )
        return
    conn.execute(
        """
        INSERT INTO clientes_empresas (
          id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at
        ) VALUES (
          ?, ?, ?, ?, 'Activo', date('now','localtime'), NULL, datetime(?), datetime(?)
        )
        """,
        (uuid.uuid4().hex, cliente_id, empresa_id, str(servicio or "").strip().lower(), now, now),
    )


def find_cliente_id(conn, *, empresa_id, nif):
    nif = norm_id(nif)
    if not nif:
        return ""
    # Prefer cliente vinculado a la empresa (clientes.empresa_id o clientes_empresas).
    row = conn.execute(
        """
        SELECT c.id
        FROM clientes c
        LEFT JOIN clientes_empresas ce ON ce.cliente_id = c.id AND ce.empresa_id = ?
        WHERE UPPER(COALESCE(c.nif,'')) = ?
          AND (c.empresa_id = ? OR ce.id IS NOT NULL)
        ORDER BY COALESCE(c.updated_at, c.created_at) DESC
        LIMIT 1
        """,
        (empresa_id, nif, empresa_id),
    ).fetchone()
    if row:
        return str(row["id"] or "").strip()
    # fallback global por nif
    row = conn.execute(
        """
        SELECT id
        FROM clientes
        WHERE UPPER(COALESCE(nif,'')) = ?
        ORDER BY COALESCE(updated_at, created_at) DESC
        LIMIT 1
        """,
        (nif,),
    ).fetchone()
    return str(row["id"] or "").strip() if row else ""


def ensure_gestoria_doc(conn, *, empresa_id, cliente_id, seguro_id, doc_url, now, nombre="", notas=""):
    if not doc_url:
        return
    existing = conn.execute(
        """
        SELECT id
        FROM gestoria_docs
        WHERE empresa_id = ? AND cliente_id = ?
          AND (LOWER(COALESCE(referencia_tipo,'')) = 'seguros' OR LOWER(COALESCE(tipo,'')) = 'seguros')
          AND (referencia_id = ? OR COALESCE(doc_url,'') = ?)
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (empresa_id, cliente_id, seguro_id, doc_url),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE gestoria_docs
            SET referencia_tipo = 'seguros',
                referencia_id = ?,
                nombre = COALESCE(NULLIF(?, ''), nombre),
                tipo = COALESCE(NULLIF(?, ''), tipo),
                notas = COALESCE(NULLIF(?, ''), notas),
                doc_url = ?,
                doc_key = NULL,
                estado = COALESCE(NULLIF(estado, ''), 'Recibido'),
                updated_at = datetime(?)
            WHERE id = ?
            """,
            (seguro_id, nombre, "Seguros", notas, doc_url, now, existing["id"]),
        )
        return
    conn.execute(
        """
        INSERT INTO gestoria_docs (
          id, empresa_id, cliente_id, referencia_tipo, referencia_id,
          nombre, tipo, fecha, estado, notas, doc_key, doc_url, created_at, updated_at
        ) VALUES (
          ?, ?, ?, 'seguros', ?, ?, 'Seguros', date('now','localtime'), 'Recibido', ?, NULL, ?, datetime(?), datetime(?)
        )
        """,
        (uuid.uuid4().hex, empresa_id, cliente_id, seguro_id, nombre or "Póliza seguro", notas or "", doc_url, now, now),
    )


db_path = sys.argv[1]
payload_path = sys.argv[2]
uploads_root = Path(sys.argv[3])
opts_path = sys.argv[4]

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
now = datetime.now(timezone.utc).isoformat()
uploads_root.mkdir(parents=True, exist_ok=True)

with open(payload_path, "r", encoding="utf-8") as fh:
    payload = json.load(fh)
with open(opts_path, "r", encoding="utf-8") as fh:
    opts = json.load(fh)

empresa_id = str(payload.get("empresa_id") or "").strip()
if not empresa_id:
    raise SystemExit("empresa_id requerido")
empresa = conn.execute("SELECT id FROM empresas WHERE id = ? LIMIT 1", (empresa_id,)).fetchone()
if not empresa:
    raise SystemExit(f"Empresa no encontrada en Render: {empresa_id}")

create_missing = bool(opts.get("create_missing"))
force_doc = bool(opts.get("force_doc"))
force_fields = bool(opts.get("force_fields"))

rows = conn.execute(
    "SELECT * FROM seguros WHERE empresa_id = ?",
    (empresa_id,),
).fetchall()
seg_index = {}
for r in rows:
    k = f"{norm_poliza(r['poliza_numero'])}|{norm_company(r['compania'])}"
    if k and k not in seg_index:
        seg_index[k] = r

updated = 0
inserted = 0
linked_client = 0
docs = 0

for item in payload.get("items") or []:
    poliza = str(item.get("poliza_numero") or "").strip()
    compania = str(item.get("compania") or "").strip()
    key = f"{norm_poliza(poliza)}|{norm_company(compania)}"
    if "|" not in key or not key.split("|",1)[0] or not key.split("|",1)[1]:
        continue
    nif = str(item.get("nif") or item.get("dni") or "").strip()
    cliente_id = find_cliente_id(conn, empresa_id=empresa_id, nif=nif)
    doc_url = f"/uploads/{item.get('upload_rel')}".replace("//", "/")
    nombre_doc = str(item.get("poliza_numero") or item.get("tomador") or "Póliza seguro").strip()
    notas_doc = " · ".join([x for x in (str(item.get("compania") or "").strip(), str(item.get("ramo") or "").strip()) if x])

    current = seg_index.get(key)
    if current:
        seguro_id = str(current["id"])
        updates = {}
        # Campos ficha póliza
        for field in ("tomador","fecha_efecto","fecha_vencimiento","ramo","poliza_numero","compania","estado_poliza","estado"):
            incoming = str(item.get(field) or "").strip()
            if not incoming:
                continue
            if force_fields or not str(current.get(field) or "").strip():
                updates[field] = incoming
        for field in ("prima_neta","prima_total","comision"):
            incoming = str(item.get(field) or "").strip()
            if not incoming:
                continue
            if force_fields or (current.get(field) in (None, "", 0, 0.0, "0")):
                updates[field] = incoming
        if cliente_id and (force_fields or not str(current.get("cliente_id") or "").strip()):
            updates["cliente_id"] = cliente_id

        # Documento: sustituir/enlazar
        if force_doc or not str(current.get("poliza_url") or "").strip():
            updates["poliza_url"] = doc_url
            updates["poliza_key"] = ""

        if updates:
            set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
            values = list(updates.values()) + [now, seguro_id]
            conn.execute(
                f"UPDATE seguros SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
            updated += 1
        if cliente_id:
            ensure_cliente_servicio(conn, cliente_id=cliente_id, empresa_id=empresa_id, servicio="seguros", now=now)
            linked_client += 1
        ensure_gestoria_doc(conn, empresa_id=empresa_id, cliente_id=cliente_id or (current.get("cliente_id") or ""), seguro_id=seguro_id, doc_url=doc_url, now=now, nombre=nombre_doc, notas=notas_doc)
        docs += 1
        continue

    if not create_missing:
        continue

    # Insertar nueva póliza
    seguro_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO seguros (
          id, empresa_id, cliente_id, mes_creacion, fecha_efecto, fecha_vencimiento,
          tomador, compania, ramo, poliza_numero, prima_neta, prima_total, comision,
          produccion, colaborador, estado, estado_poliza, poliza_key, poliza_url,
          created_at, updated_at
        ) VALUES (
          ?, ?, ?, strftime('%Y-%m','now','localtime'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'activa', NULL, ?, datetime(?), datetime(?)
        )
        """,
        (
            seguro_id,
            empresa_id,
            cliente_id or None,
            str(item.get("fecha_efecto") or "").strip() or None,
            str(item.get("fecha_vencimiento") or "").strip() or None,
            str(item.get("tomador") or "").strip() or None,
            compania or None,
            str(item.get("ramo") or "").strip() or None,
            poliza or None,
            str(item.get("prima_neta") or "").strip() or None,
            str(item.get("prima_total") or "").strip() or None,
            str(item.get("comision") or "").strip() or None,
            str(item.get("produccion") or "").strip() or None,
            str(item.get("colaborador") or "").strip() or None,
            str(item.get("estado") or "En vigor").strip() or "En vigor",
            doc_url,
            now,
            now,
        ),
    )
    seg_index[key] = conn.execute("SELECT * FROM seguros WHERE id = ?", (seguro_id,)).fetchone()
    inserted += 1
    if cliente_id:
        ensure_cliente_servicio(conn, cliente_id=cliente_id, empresa_id=empresa_id, servicio="seguros", now=now)
        linked_client += 1
    ensure_gestoria_doc(conn, empresa_id=empresa_id, cliente_id=cliente_id, seguro_id=seguro_id, doc_url=doc_url, now=now, nombre=nombre_doc, notas=notas_doc)
    docs += 1

conn.commit()
print(json.dumps({"ok": True, "updated": updated, "inserted": inserted, "linked_client": linked_client, "docs": docs}, ensure_ascii=False))
'''


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    ap = argparse.ArgumentParser(description="Sincroniza pólizas (y PDFs) a Render por SSH.")
    ap.add_argument("--extract-csv", required=True, help="CSV de extracción/unique con columnas de póliza y path.")
    ap.add_argument("--empresa-id", required=True, help="UUID de empresa (Render).")
    ap.add_argument("--render-host", required=True, help="Host SSH Render, ej. srv-xxx@ssh.frankfurt.render.com")
    ap.add_argument("--render-db", default="/var/data/erp_import2.sqlite", help="Ruta SQLite en Render.")
    ap.add_argument("--render-uploads", default="/var/data/uploads", help="Carpeta persistente de uploads en Render.")
    ap.add_argument("--uploads-subdir", default="seguros_sync", help="Subcarpeta bajo uploads para los PDFs sincronizados.")
    ap.add_argument("--create-missing", action="store_true", help="Crea pólizas faltantes en Render.")
    ap.add_argument("--force-doc", action="store_true", help="Sobrescribe siempre poliza_url/poliza_key.")
    ap.add_argument("--force-fields", action="store_true", help="Sobrescribe campos de ficha si vienen en el CSV.")
    ap.add_argument("--limit", type=int, default=0, help="Limita nº de pólizas a sincronizar (0=sin límite).")
    ap.add_argument("--dry-run", action="store_true", help="Genera payload+tar pero no sube a Render.")
    ap.add_argument("--force-sqlite-target", action="store_true", help="Permite escribir en SQLite remota aunque el proyecto este en modo Postgres.")
    args = ap.parse_args()

    guard_remote_sqlite_sync(force=args.force_sqlite_target, script_name=Path(__file__).name)

    csv_path = Path(args.extract_csv).expanduser().resolve()
    if not csv_path.exists():
        raise SystemExit(f"No existe el CSV: {csv_path}")

    rows = _dedupe_polizas(_read_csv(csv_path))
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit("No hay pólizas deduplicadas en el CSV.")

    items = []
    for r in rows:
        local_pdf = str(r.get("path") or "").strip()
        if not local_pdf:
            continue
        items.append(
            {
                "poliza_numero": str(r.get("poliza_numero") or "").strip(),
                "compania": str(r.get("compania") or "").strip(),
                "ramo": str(r.get("ramo") or "").strip(),
                "fecha_efecto": str(r.get("fecha_efecto") or "").strip(),
                "fecha_vencimiento": str(r.get("fecha_vencimiento") or "").strip(),
                "tomador": str(r.get("tomador") or "").strip(),
                "nif": str(r.get("nif") or "").strip(),
                "dni": str(r.get("dni") or "").strip(),
                "prima_neta": str(r.get("prima_neta") or "").strip(),
                "prima_total": str(r.get("prima_total") or "").strip(),
                "comision": str(r.get("comision") or "").strip(),
                "estado": str(r.get("estado") or "").strip(),
                "estado_poliza": str(r.get("estado_poliza") or "").strip(),
                "local_pdf": local_pdf,
                "upload_rel": _build_upload_rel(args.empresa_id, r, uploads_subdir=args.uploads_subdir),
            }
        )

    payload = {"empresa_id": args.empresa_id, "items": items}
    opts = {
        "create_missing": bool(args.create_missing),
        "force_doc": bool(args.force_doc),
        "force_fields": bool(args.force_fields),
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        payload_path = tmpdir / "seguros_sync.json"
        opts_path = tmpdir / "seguros_sync_opts.json"
        script_path = tmpdir / "seguros_sync_remote.py"
        archive_path = tmpdir / "seguros_uploads.tar"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        opts_path.write_text(json.dumps(opts, ensure_ascii=False, indent=2), encoding="utf-8")
        script_path.write_text(REMOTE_SCRIPT, encoding="utf-8")
        added, missing = _build_archive(items, archive_path)

        print(f"Polizas a sincronizar: {len(items)} (archivos empaquetados={added}, faltantes={missing}).")
        print(f"Payload temporal: {payload_path}")
        if args.dry_run:
            return

        remote_payload = "/tmp/seguros_sync.json"
        remote_opts = "/tmp/seguros_sync_opts.json"
        remote_script = "/tmp/seguros_sync_remote.py"
        remote_archive = "/tmp/seguros_uploads.tar"

        run(["scp", *SSH_OPTIONS, str(payload_path), f"{args.render_host}:{remote_payload}"])
        run(["scp", *SSH_OPTIONS, str(opts_path), f"{args.render_host}:{remote_opts}"])
        run(["scp", *SSH_OPTIONS, str(script_path), f"{args.render_host}:{remote_script}"])
        run(["scp", *SSH_OPTIONS, str(archive_path), f"{args.render_host}:{remote_archive}"])
        remote_cmd = (
            f"mkdir -p {args.render_uploads} "
            f"&& tar -xf {remote_archive} -C {args.render_uploads} "
            f"&& python3 {remote_script} {args.render_db} {remote_payload} {args.render_uploads} {remote_opts} "
            f"&& rm -f {remote_script} {remote_payload} {remote_opts} {remote_archive} "
            f"&& echo '__SYNC_OK__'"
        )
        run(["ssh", *SSH_OPTIONS, args.render_host, "sh", "-lc", remote_cmd])
        print("Sincronizacion de seguros completada.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
