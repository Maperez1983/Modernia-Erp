#!/usr/bin/env python3
import argparse
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _env_first(*keys: str) -> str:
    for key in keys:
        value = os.environ.get(key) or ""
        if value.strip():
            return value.strip()
    return ""


def _try_import_boto3():
    try:
        import boto3  # noqa: F401
    except Exception:
        return None
    return boto3


def _s3_client():
    boto3 = _try_import_boto3()
    if not boto3:
        return None, "", ""
    bucket = _env_first("AWS_S3_BUCKET", "S3_BUCKET")
    region = _env_first("AWS_REGION", "AWS_DEFAULT_REGION")
    if not bucket or not region:
        return None, bucket, region
    return boto3.client("s3", region_name=region), bucket, region


def _normalize_poliza_token(value: str) -> str:
    text = str(value or "").upper()
    text = re.sub(r"\\s+", "", text)
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text


def list_s3_keys(prefix: str) -> list[str]:
    client, bucket, _region = _s3_client()
    if not client:
        return []
    keys: list[str] = []
    token = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = client.list_objects_v2(**kwargs)
        for item in resp.get("Contents") or []:
            k = str(item.get("Key") or "").strip()
            if k:
                keys.append(k)
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
            continue
        break
    return keys


def open_db(args):
    sqlite_path = Path(args.sqlite).expanduser().resolve()
    if args.backend == "sqlite":
        import sqlite3

        if not sqlite_path.exists():
            raise SystemExit(f"SQLite no existe: {sqlite_path}")
        conn = sqlite3.connect(str(sqlite_path))
        conn.row_factory = sqlite3.Row
        return conn, "sqlite"

    # postgres
    from web.db_backend import open_postgres_conn  # noqa: E402

    conn = open_postgres_conn(with_row_factory=True)
    return conn, "postgres"


def fetch_counts(conn, empresa_id: str):
    empresa_id = str(empresa_id or "").strip()
    where = []
    values = []
    if empresa_id:
        where.append("empresa_id = ?")
        values.append(empresa_id)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM seguros {where_sql}",
        values,
    ).fetchone()["n"]
    with_pdf = conn.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM seguros
        {where_sql}
        {"AND" if where_sql else "WHERE"} (COALESCE(TRIM(poliza_key), '') <> '' OR COALESCE(TRIM(poliza_url), '') <> '')
        """,
        values,
    ).fetchone()["n"]
    with_cliente = conn.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM seguros
        {where_sql}
        {"AND" if where_sql else "WHERE"} COALESCE(TRIM(cliente_id), '') <> ''
        """,
        values,
    ).fetchone()["n"]
    distinct_clientes = conn.execute(
        f"""
        SELECT COUNT(DISTINCT cliente_id) AS n
        FROM seguros
        {where_sql}
        {"AND" if where_sql else "WHERE"} COALESCE(TRIM(cliente_id), '') <> ''
        """,
        values,
    ).fetchone()["n"]
    return {
        "seguros_total": int(total or 0),
        "seguros_con_pdf": int(with_pdf or 0),
        "seguros_con_cliente_id": int(with_cliente or 0),
        "seguros_clientes_distintos": int(distinct_clientes or 0),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Auditoría: cuántas pólizas existen y cuántas tienen PDF (poliza_key/url), y cuántos PDFs hay en S3 bajo un prefijo."
    )
    parser.add_argument(
        "--backend",
        choices=("sqlite", "postgres"),
        default=os.environ.get("AUDIT_BACKEND") or "sqlite",
        help="Backend para contar pólizas (default: sqlite).",
    )
    parser.add_argument(
        "--sqlite",
        default=str(ROOT / "data" / "erp_import2.sqlite"),
        help="Ruta SQLite si backend=sqlite.",
    )
    parser.add_argument("--empresa-id", default="", help="Filtra por empresa_id.")
    parser.add_argument("--s3-prefix", default="seguros/", help="Prefijo S3 a listar (default: seguros/).")
    parser.add_argument(
        "--limit-sample",
        type=int,
        default=0,
        help="Muestra una muestra de keys S3 (default 0; usa >0 si lo necesitas).",
    )
    args = parser.parse_args()

    conn, backend = open_db(args)
    empresa_id = str(args.empresa_id or "").strip()
    counts = fetch_counts(conn, empresa_id)

    now = datetime.now(timezone.utc).isoformat()
    print(f"ts={now}")
    print(f"backend={backend}")
    print(f"empresa_id={empresa_id or '(all)'}")
    for k in ("seguros_total", "seguros_con_cliente_id", "seguros_clientes_distintos", "seguros_con_pdf"):
        print(f"{k}={counts[k]}")

    # S3 listing (best-effort)
    client, bucket, region = _s3_client()
    if not client:
        missing = []
        if not _try_import_boto3():
            missing.append("boto3")
        if not bucket:
            missing.append("AWS_S3_BUCKET/S3_BUCKET")
        if not region:
            missing.append("AWS_REGION/AWS_DEFAULT_REGION")
        print(f"s3=unavailable missing={','.join(missing) if missing else 'unknown'}")
        return

    prefix = str(args.s3_prefix or "").lstrip("/")
    keys = list_s3_keys(prefix)
    pdf_keys = [k for k in keys if k.lower().endswith(".pdf")]
    print(f"s3_bucket={bucket}")
    print(f"s3_region={region}")
    print(f"s3_prefix={prefix}")
    print(f"s3_objects_total={len(keys)}")
    print(f"s3_pdfs_total={len(pdf_keys)}")

    # Quick token scan (for potential backfill later)
    token_counts = Counter()
    for k in pdf_keys:
        base = os.path.basename(k)
        for tok in re.findall(r"[A-Za-z0-9]{6,}", base):
            token_counts[_normalize_poliza_token(tok)] += 1
    if token_counts:
        common = token_counts.most_common(8)
        print("s3_pdf_tokens_common=" + ",".join(f"{t}:{c}" for t, c in common))

    sample = pdf_keys[: max(0, int(args.limit_sample or 0))]
    if sample:
        print("s3_pdf_sample:")
        for k in sample:
            print(f"- {k}")


if __name__ == "__main__":
    main()
