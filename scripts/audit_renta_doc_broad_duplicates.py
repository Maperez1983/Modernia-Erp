#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from cleanup_renta_doc_duplicates import (
    RENTA_FILTER,
    env_first,
    load_env_file,
    pg_connect,
    s3_bucket,
    s3_client,
    s3_key_from_row,
)


def fetch_groups(conn):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH renta_docs AS (
              SELECT
                id,
                COALESCE(empresa_id, '') AS empresa_id,
                COALESCE(cliente_id, '') AS cliente_id,
                COALESCE(archivo_hash, '') AS archivo_hash,
                COALESCE(referencia_id, '') AS referencia_id,
                LOWER(COALESCE(tipo, '')) AS tipo,
                LOWER(COALESCE(estado, '')) AS estado,
                COALESCE(nombre, '') AS nombre,
                COALESCE(referencia_tipo, '') AS referencia_tipo,
                COALESCE(doc_key, '') AS doc_key,
                COALESCE(doc_url, '') AS doc_url,
                COALESCE(updated_at, created_at, '') AS sort_ts
              FROM gestoria_docs
              WHERE {RENTA_FILTER}
                AND COALESCE(cliente_id, '') <> ''
                AND COALESCE(archivo_hash, '') <> ''
            ),
            groups AS (
              SELECT cliente_id, archivo_hash, referencia_id, estado, tipo, COUNT(*) AS n
              FROM renta_docs
              GROUP BY cliente_id, archivo_hash, referencia_id, estado, tipo
              HAVING COUNT(*) > 1
            )
            SELECT rd.*
            FROM renta_docs rd
            JOIN groups g ON
              g.cliente_id = rd.cliente_id
              AND g.archivo_hash = rd.archivo_hash
              AND g.referencia_id = rd.referencia_id
              AND g.estado = rd.estado
              AND g.tipo = rd.tipo
            ORDER BY rd.cliente_id, rd.archivo_hash, rd.referencia_id, rd.estado, rd.tipo, rd.sort_ts DESC
            """
        )
        rows = [dict(row) for row in cur.fetchall()]
    grouped = {}
    for row in rows:
        key = (row["cliente_id"], row["archivo_hash"], row["referencia_id"], row["estado"], row["tipo"])
        grouped.setdefault(key, []).append(row)
    return grouped


def verify_rows(rows, client, bucket):
    errors = []
    cache = {}
    for row in rows:
        key = s3_key_from_row(row)
        if not key:
            errors.append({"id": row["id"], "error": "sin_key"})
            continue
        try:
            if key not in cache:
                obj = client.get_object(Bucket=bucket, Key=key)
                cache[key] = hashlib.sha256(obj["Body"].read()).hexdigest()
        except Exception as exc:
            errors.append({"id": row["id"], "error": type(exc).__name__})
            continue
        if cache[key].lower() != str(row["archivo_hash"]).lower():
            errors.append({"id": row["id"], "error": "hash_mismatch"})
    return errors


def classify(rows):
    empresas = {row["empresa_id"] for row in rows}
    nombres = {row["nombre"] for row in rows}
    ref_tipos = {row["referencia_tipo"] for row in rows}
    if len(empresas) > 1:
        return "misma_renta_mismo_pdf_en_varias_empresas"
    if len(ref_tipos) > 1:
        return "misma_renta_mismo_pdf_con_referencia_tipo_distinta"
    if len(nombres) > 1:
        return "misma_renta_mismo_pdf_con_nombre_distinto"
    return "duplicado_no_estricto"


def main() -> int:
    load_env_file(Path(".env"))
    dsn = env_first("POSTGRES_URL", "DATABASE_URL")
    if not dsn.startswith("postgres"):
        raise SystemExit("Falta POSTGRES_URL/DATABASE_URL de Postgres.")
    bucket = s3_bucket()
    if not bucket:
        raise SystemExit("Falta bucket S3.")
    client = s3_client()
    with pg_connect(dsn) as conn:
        groups = fetch_groups(conn)
    counters = Counter()
    report = []
    for key, rows in groups.items():
        errors = verify_rows(rows, client, bucket)
        category = classify(rows)
        counters[category] += 1
        if errors:
            counters["con_error_s3"] += 1
        report.append(
            {
                "category": category,
                "rows": len(rows),
                "cliente_id": key[0],
                "referencia_id": key[2],
                "estado": key[3],
                "tipo": key[4],
                "empresas": sorted({row["empresa_id"] for row in rows}),
                "nombres": sorted({row["nombre"] for row in rows}),
                "s3_errors": errors,
            }
        )
    print(json.dumps({"groups": len(groups), "summary": dict(counters), "report": report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
