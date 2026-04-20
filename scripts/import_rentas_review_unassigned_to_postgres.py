#!/usr/bin/env python3
"""
Importa a Postgres (Render) los PDFs de renta que han quedado en la cola de revisión
`reports/rentas_folder_import_review.json` asignándolos a un cliente "SIN ASIGNAR".

Esto garantiza que *todos* los PDFs estén en el sistema (Docs) aunque no podamos
inferir el cliente con seguridad por nombre.

Uso:
  set -a; source .env; set +a
  python3 scripts/import_rentas_review_unassigned_to_postgres.py \\
    --empresa-id a261... \\
    --review-json reports/rentas_folder_import_review.json \\
    --ejercicio 2024 \\
    --apply

Primero probar:
  python3 scripts/import_rentas_review_unassigned_to_postgres.py ... --dry-run --limit 50
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


def env_first(*keys: str) -> str:
    for key in keys:
        value = os.environ.get(key) or ""
        if value.strip():
            return value.strip()
    return ""


def pg_connect(dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:
        raise SystemExit(f"Postgres no disponible: falta psycopg. ({type(exc).__name__})")
    return psycopg.connect(dsn, row_factory=dict_row)


def s3_client():
    try:
        import boto3
    except Exception:
        return None
    region = env_first("AWS_REGION", "AWS_DEFAULT_REGION")
    return boto3.client("s3", region_name=region) if region else boto3.client("s3")


def safe_filename(name: str) -> str:
    base = os.path.basename(str(name or "archivo.pdf"))
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return cleaned or "archivo.pdf"


def build_s3_key(prefix: str, filename: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rand = os.urandom(4).hex()
    pref = (prefix or "gestoria/rentas").strip().strip("/")
    return f"{pref}/{stamp}_{rand}_{safe_filename(filename)}"


def ensure_unassigned_client(conn, *, empresa_id: str, nombre: str) -> str:
    with conn.cursor() as cur:
        row = cur.execute(
            "SELECT id FROM clientes WHERE empresa_id = %s AND LOWER(COALESCE(nombre,'')) = LOWER(%s) LIMIT 1",
            (empresa_id, nombre),
        ).fetchone()
        if row:
            return str(row["id"])
        cliente_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            INSERT INTO clientes (
              id, empresa_id, nombre, tipo_persona, nif, telefono, email, estado,
              created_at, updated_at
            ) VALUES (
              %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s
            )
            """,
            (cliente_id, empresa_id, nombre, "Particular", "", "", "", "Activo", now, now),
        )
        # Vincula a la empresa en gestoría para que salga en búsquedas/listados.
        cur.execute(
            """
            INSERT INTO clientes_empresas (
              id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at
            ) VALUES (
              %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
            )
            """,
            (uuid.uuid4().hex, cliente_id, empresa_id, "gestoria", "Activo", "", ""),
        )
        return cliente_id


def gestoria_doc_exists(conn, *, empresa_id: str, cliente_id: str, nombre: str) -> bool:
    with conn.cursor() as cur:
        row = cur.execute(
            """
            SELECT 1
            FROM gestoria_docs
            WHERE empresa_id = %s AND cliente_id = %s AND LOWER(COALESCE(nombre,'')) = LOWER(%s)
            LIMIT 1
            """,
            (empresa_id, cliente_id, nombre),
        ).fetchone()
    return bool(row)


def insert_gestoria_doc(
    conn,
    *,
    empresa_id: str,
    cliente_id: str,
    ejercicio: str,
    estado: str,
    pdf_path: Path,
    doc_key: str,
) -> None:
    doc_name = f"Renta {ejercicio} · {estado} · {pdf_path.name}"
    referencia_id = f"renta-{ejercicio}-sin_asignar"
    tipo = f"Renta {estado}"
    notas = str(pdf_path)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO gestoria_docs (
              id, empresa_id, cliente_id, referencia_tipo, referencia_id,
              nombre, tipo, fecha, estado, notas, doc_key, doc_url,
              calidad_ocr, campos_ocr, created_at, updated_at
            ) VALUES (
              %s, %s, %s, 'renta', %s,
              %s, %s, '', %s, %s, %s, '',
              0, %s, NOW(), NOW()
            )
            """,
            (
                uuid.uuid4().hex,
                empresa_id,
                cliente_id,
                referencia_id,
                doc_name,
                tipo,
                estado,
                notas,
                doc_key,
                json.dumps({"source": "review_unassigned"}, ensure_ascii=False),
            ),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa PDFs de renta no enlazados a un cliente SIN ASIGNAR (Postgres+S3).")
    parser.add_argument("--empresa-id", required=True)
    parser.add_argument("--review-json", default="reports/rentas_folder_import_review.json")
    parser.add_argument("--ejercicio", default="2024")
    parser.add_argument("--estado", default="Pendiente asignar")
    parser.add_argument("--unassigned-client-name", default="RENTAS 2024 · SIN ASIGNAR")
    parser.add_argument("--s3-prefix", default="gestoria/rentas_unassigned")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    do_apply = bool(args.apply) and (not args.dry_run)
    if not do_apply:
        args.dry_run = True

    dsn = env_first("POSTGRES_URL", "DATABASE_URL")
    if not dsn.lower().startswith("postgres"):
        raise SystemExit("Falta POSTGRES_URL/DATABASE_URL (postgres...).")
    bucket = env_first("AWS_S3_BUCKET", "S3_BUCKET")
    if do_apply and not bucket:
        raise SystemExit("Falta AWS_S3_BUCKET/S3_BUCKET para subir a S3.")
    s3 = s3_client() if do_apply else None
    if do_apply and not s3:
        raise SystemExit("No se pudo inicializar S3 (falta boto3 o región).")

    review_path = Path(args.review_json).expanduser().resolve()
    if not review_path.exists():
        raise SystemExit(f"No existe: {review_path}")
    items = json.loads(review_path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise SystemExit("review_json inválido (no es lista).")
    if args.limit and int(args.limit) > 0:
        items = items[: int(args.limit)]

    conn = pg_connect(dsn)
    conn.autocommit = False
    try:
        unassigned_id = ensure_unassigned_client(
            conn,
            empresa_id=str(args.empresa_id),
            nombre=str(args.unassigned_client_name),
        )

        processed = 0
        created = 0
        skipped = 0
        missing = 0
        for it in items:
            processed += 1
            pdf_raw = str((it or {}).get("pdf") or "").strip()
            if not pdf_raw:
                skipped += 1
                continue
            pdf = Path(pdf_raw).expanduser()
            if not pdf.exists():
                missing += 1
                continue
            doc_name = f"Renta {str(args.ejercicio).strip()} · {str(args.estado).strip()} · {pdf.name}"
            if gestoria_doc_exists(conn, empresa_id=str(args.empresa_id), cliente_id=unassigned_id, nombre=doc_name):
                skipped += 1
                continue
            if args.dry_run:
                print(f"[dry-run] {pdf} -> {doc_name}")
                created += 1
                continue

            key = build_s3_key(str(args.s3_prefix), doc_name)
            try:
                s3.upload_file(str(pdf), bucket, key, ExtraArgs={"ContentType": "application/pdf"})
            except Exception as exc:
                print(f"[error] S3 upload failed: {pdf}: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            insert_gestoria_doc(
                conn,
                empresa_id=str(args.empresa_id),
                cliente_id=unassigned_id,
                ejercicio=str(args.ejercicio).strip(),
                estado=str(args.estado).strip(),
                pdf_path=pdf,
                doc_key=key,
            )
            created += 1

        if do_apply:
            conn.commit()
        print(
            json.dumps(
                {
                    "processed": processed,
                    "created": created,
                    "skipped": skipped,
                    "missing_local_file": missing,
                    "dry_run": bool(args.dry_run),
                    "unassigned_client_id": unassigned_id,
                },
                ensure_ascii=False,
            )
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

