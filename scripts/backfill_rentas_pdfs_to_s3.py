#!/usr/bin/env python3
"""
Backfill de PDFs de Renta importados desde rutas locales (OneDrive/iCloud/etc) a S3.

Caso típico:
- `gestoria_docs.notas` contiene una ruta local absoluta a un PDF (p.ej. /Users/.../OneDrive/...pdf)
- `gestoria_docs.doc_key` contiene un placeholder (32-hex) o está vacío
- `gestoria_docs.doc_url` está vacío

En producción (Render) el backend no tiene acceso a esa ruta local, así que el botón "PDF" debe apuntar
obligatoriamente a S3 (doc_key real).
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


PLACEHOLDER_HEX_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def env_first(*keys: str) -> str:
    for key in keys:
        value = os.environ.get(key) or ""
        if value.strip():
            return value.strip()
    return ""


def s3_client(region_override: str = ""):
    try:
        import boto3
    except Exception:
        return None
    region = (region_override or "").strip() or env_first("AWS_REGION", "AWS_DEFAULT_REGION")
    return boto3.client("s3", region_name=region) if region else boto3.client("s3")


def s3_config():
    bucket = env_first("AWS_S3_BUCKET", "S3_BUCKET")
    region = env_first("AWS_REGION", "AWS_DEFAULT_REGION")
    return bucket, region


def looks_like_placeholder(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if "/" in text or "." in text:
        return False
    return bool(PLACEHOLDER_HEX_RE.fullmatch(text))


def is_local_pdf_path(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if not text.lower().endswith(".pdf"):
        return False
    return text.startswith("/") or re.match(r"^[A-Za-z]:\\\\", text) is not None


def safe_filename(name: str) -> str:
    base = os.path.basename(str(name or "archivo.pdf"))
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return cleaned or "archivo.pdf"


def build_s3_key(prefix: str, filename: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rand = os.urandom(4).hex()
    pref = (prefix or "gestoria/rentas").strip().strip("/")
    return f"{pref}/{stamp}_{rand}_{safe_filename(filename)}"


def pg_connect(dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:
        raise SystemExit(f"Postgres no disponible: falta psycopg. ({type(exc).__name__})")
    return psycopg.connect(dsn, row_factory=dict_row)


def _is_public_url(url: str) -> bool:
    url = str(url or "").strip()
    return url.startswith("/uploads/") or url.startswith("http://") or url.startswith("https://") or url.startswith("s3://")


def _looks_like_real_key(doc_key: str) -> bool:
    text = str(doc_key or "").strip()
    if not text:
        return False
    if looks_like_placeholder(text):
        return False
    return ("/" in text) or ("." in text)


def _iter_target_rows_sqlite(conn: sqlite3.Connection, empresa_id: str | None):
    where_empresa = ""
    values: tuple[object, ...] = ()
    if empresa_id:
        where_empresa = "AND empresa_id = ?"
        values = (empresa_id,)
    return conn.execute(
        f"""
        SELECT id, empresa_id, cliente_id, referencia_tipo, referencia_id,
               nombre, tipo, fecha, estado, notas, doc_key, doc_url, updated_at
        FROM gestoria_docs
        WHERE (
          LOWER(COALESCE(referencia_tipo, '')) = 'renta'
          OR LOWER(COALESCE(tipo, '')) = 'renta'
          OR LOWER(COALESCE(tipo, '')) = 'declaracion de renta'
          OR LOWER(COALESCE(nombre, '')) LIKE 'renta %'
          OR LOWER(COALESCE(tipo, '')) LIKE 'modelo 100%'
        )
        {where_empresa}
        ORDER BY COALESCE(updated_at, created_at) DESC
        """,
        values,
    ).fetchall()


def _iter_target_rows_pg(conn, empresa_id: str | None):
    # psycopg usa "pyformat": el carácter "%" es especial y NO puede aparecer literal en el SQL.
    # Por eso pasamos los patrones LIKE como parámetros en vez de escribir "renta %" / "modelo 100%".
    where_empresa = ""
    values: list[object] = ["renta %", "modelo 100%"]
    if empresa_id:
        where_empresa = "AND empresa_id = %s"
        values.append(empresa_id)
    with conn.cursor() as cur:
        return cur.execute(
            f"""
            SELECT id, empresa_id, cliente_id, referencia_tipo, referencia_id,
                   nombre, tipo, fecha, estado, notas, doc_key, doc_url, updated_at
            FROM gestoria_docs
            WHERE (
              LOWER(COALESCE(referencia_tipo, '')) = 'renta'
              OR LOWER(COALESCE(tipo, '')) = 'renta'
              OR LOWER(COALESCE(tipo, '')) = 'declaracion de renta'
              OR LOWER(COALESCE(nombre, '')) LIKE %s
              OR LOWER(COALESCE(tipo, '')) LIKE %s
            )
            {where_empresa}
            ORDER BY COALESCE(updated_at, created_at) DESC
            """,
            tuple(values),
        ).fetchall()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sube PDFs de renta (rutas locales) a S3 y actualiza gestoria_docs.doc_key.")
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta a la SQLite local (solo si no usas Postgres).")
    parser.add_argument("--use-postgres", action="store_true", help="Opera contra Postgres (Render) en vez de SQLite.")
    parser.add_argument("--postgres-dsn", default="", help="DSN de Postgres (si vacío usa POSTGRES_URL/DATABASE_URL).")
    parser.add_argument("--empresa-id", default="", help="Filtra por empresa_id (opcional).")
    parser.add_argument("--prefix", default="gestoria/rentas", help="Prefijo S3 para los PDFs subidos.")
    parser.add_argument("--s3-bucket", default="", help="Bucket S3 (si vacío usa AWS_S3_BUCKET/S3_BUCKET).")
    parser.add_argument("--aws-region", default="", help="Región AWS (si vacío usa AWS_REGION/AWS_DEFAULT_REGION).")
    parser.add_argument("--limit", type=int, default=0, help="Máximo de documentos a procesar (0 = sin límite).")
    parser.add_argument("--dry-run", action="store_true", help="No sube ni actualiza, solo muestra qué haría.")
    args = parser.parse_args()

    bucket = (args.s3_bucket or "").strip()
    region = (args.aws_region or "").strip()
    if not bucket or not region:
        env_bucket, env_region = s3_config()
        bucket = bucket or env_bucket
        region = region or env_region

    client = None
    if not args.dry_run:
        client = s3_client(region)
        if not client:
            raise SystemExit("S3 no disponible: falta boto3.")
        if not bucket:
            raise SystemExit("S3 no configurado: falta AWS_S3_BUCKET (o S3_BUCKET).")
    else:
        bucket = bucket or "<AWS_S3_BUCKET>"

    empresa_id = str(args.empresa_id or "").strip() or None

    pg_conn = None
    sqlite_conn = None
    try:
        if args.use_postgres:
            dsn = (args.postgres_dsn or env_first("POSTGRES_URL", "DATABASE_URL")).strip()
            if not dsn.lower().startswith("postgres"):
                raise SystemExit("DSN inválido: usa --postgres-dsn o define POSTGRES_URL/DATABASE_URL (postgres...).")
            pg_conn = pg_connect(dsn)
            pg_conn.autocommit = False
            rows = _iter_target_rows_pg(pg_conn, empresa_id)
        else:
            db_path = Path(args.db).expanduser().resolve()
            if not db_path.exists():
                raise SystemExit(f"No existe la base: {db_path}")
            sqlite_conn = sqlite3.connect(str(db_path))
            sqlite_conn.row_factory = sqlite3.Row
            rows = _iter_target_rows_sqlite(sqlite_conn, empresa_id)

        processed = 0
        updated = 0
        skipped = 0
        missing = 0
        for row in rows:
            if args.limit and processed >= args.limit:
                break
            processed += 1
            doc_id = str(row["id"] or "").strip()
            notas = str(row["notas"] or "").strip()
            doc_key = str(row["doc_key"] or "").strip()
            doc_url = str(row["doc_url"] or "").strip()

            # Solo backfill si NO hay enlace público real.
            if _is_public_url(doc_url):
                skipped += 1
                continue
            if _looks_like_real_key(doc_key):
                # Parece un key real; lo dejamos.
                skipped += 1
                continue
            if not is_local_pdf_path(notas):
                skipped += 1
                continue
            src = Path(notas).expanduser()
            if not src.exists():
                missing += 1
                continue

            key = build_s3_key(args.prefix, row["nombre"] or src.name)
            if args.dry_run:
                print(f"[dry-run] {doc_id}: {src} -> s3://{bucket}/{key}")
                continue

            try:
                client.upload_file(
                    str(src),
                    bucket,
                    key,
                    ExtraArgs={
                        "ContentType": "application/pdf",
                    },
                )
            except Exception as exc:
                print(f"[error] upload failed doc_id={doc_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue

            try:
                if pg_conn:
                    with pg_conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE gestoria_docs
                            SET doc_key = %s,
                                updated_at = NOW()
                            WHERE id = %s
                            """,
                            (key, doc_id),
                        )
                elif sqlite_conn:
                    sqlite_conn.execute(
                        """
                        UPDATE gestoria_docs
                        SET doc_key = ?, doc_url = COALESCE(NULLIF(doc_url, ''), ''), updated_at = datetime('now')
                        WHERE id = ?
                        """,
                        (key, doc_id),
                    )
                updated += 1
            except Exception as exc:
                print(f"[error] db update failed doc_id={doc_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue

        if not args.dry_run:
            if pg_conn:
                pg_conn.commit()
            if sqlite_conn:
                sqlite_conn.commit()

        print(
            f"ok processed={processed} updated={updated} skipped={skipped} missing_local_file={missing}",
            file=sys.stdout,
        )
    finally:
        try:
            if sqlite_conn:
                sqlite_conn.close()
        except Exception:
            pass
        try:
            if pg_conn:
                pg_conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
