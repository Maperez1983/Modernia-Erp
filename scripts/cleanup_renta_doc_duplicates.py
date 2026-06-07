#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


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


def norm(value: object) -> str:
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().upper()


RENTA_FILTER = """
(
  LOWER(COALESCE(referencia_tipo, '')) = 'renta'
  OR LOWER(COALESCE(tipo, '')) LIKE '%renta%'
  OR LOWER(COALESCE(nombre, '')) LIKE '%renta%'
)
"""


def fetch_safe_groups(conn):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH renta_docs AS (
              SELECT
                id,
                COALESCE(empresa_id, '') AS empresa_id_key,
                COALESCE(cliente_id, '') AS cliente_id_key,
                COALESCE(archivo_hash, '') AS archivo_hash_key,
                UPPER(regexp_replace(
                  translate(COALESCE(nombre, ''), 'áéíóúÁÉÍÓÚäëïöüÄËÏÖÜñÑ', 'aeiouAEIOUaeiouAEIOUnN'),
                  '\\s+', ' ', 'g'
                )) AS nombre_key,
                LOWER(COALESCE(referencia_tipo, '')) AS referencia_tipo_key,
                COALESCE(referencia_id, '') AS referencia_id_key,
                LOWER(COALESCE(tipo, '')) AS tipo_key,
                LOWER(COALESCE(estado, '')) AS estado_key,
                COALESCE(doc_key, '') AS doc_key,
                COALESCE(doc_url, '') AS doc_url,
                COALESCE(updated_at, created_at, '') AS sort_ts
              FROM gestoria_docs
              WHERE {RENTA_FILTER}
                AND COALESCE(cliente_id, '') <> ''
                AND COALESCE(archivo_hash, '') <> ''
            ),
            groups AS (
              SELECT
                empresa_id_key, cliente_id_key, archivo_hash_key, nombre_key,
                referencia_tipo_key, referencia_id_key, tipo_key, estado_key,
                COUNT(*) AS n
              FROM renta_docs
              GROUP BY
                empresa_id_key, cliente_id_key, archivo_hash_key, nombre_key,
                referencia_tipo_key, referencia_id_key, tipo_key, estado_key
              HAVING COUNT(*) > 1
            )
            SELECT rd.*
            FROM renta_docs rd
            JOIN groups g ON
              g.empresa_id_key = rd.empresa_id_key
              AND g.cliente_id_key = rd.cliente_id_key
              AND g.archivo_hash_key = rd.archivo_hash_key
              AND g.nombre_key = rd.nombre_key
              AND g.referencia_tipo_key = rd.referencia_tipo_key
              AND g.referencia_id_key = rd.referencia_id_key
              AND g.tipo_key = rd.tipo_key
              AND g.estado_key = rd.estado_key
            ORDER BY
              rd.empresa_id_key, rd.cliente_id_key, rd.archivo_hash_key, rd.nombre_key,
              rd.referencia_tipo_key, rd.referencia_id_key, rd.tipo_key, rd.estado_key,
              CASE WHEN rd.doc_key <> '' OR rd.doc_url <> '' THEN 0 ELSE 1 END,
              rd.sort_ts DESC,
              rd.id ASC
            """
        )
        rows = cur.fetchall()

    grouped: dict[tuple[str, ...], list[dict]] = {}
    for row in rows:
        key = (
            row["empresa_id_key"],
            row["cliente_id_key"],
            row["archivo_hash_key"],
            row["nombre_key"],
            row["referencia_tipo_key"],
            row["referencia_id_key"],
            row["tipo_key"],
            row["estado_key"],
        )
        grouped.setdefault(key, []).append(dict(row))
    return grouped


def summarize_risky(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH base AS (
              SELECT
                COALESCE(cliente_id, '') AS cliente_id,
                COALESCE(archivo_hash, '') AS archivo_hash,
                COALESCE(referencia_id, '') AS referencia_id,
                LOWER(COALESCE(estado, '')) AS estado,
                LOWER(COALESCE(tipo, '')) AS tipo,
                COUNT(*) AS n
              FROM gestoria_docs
              WHERE {RENTA_FILTER}
                AND COALESCE(archivo_hash, '') <> ''
              GROUP BY cliente_id, archivo_hash, referencia_id, estado, tipo
              HAVING COUNT(*) > 1
            )
            SELECT
              COUNT(*) FILTER (WHERE cliente_id = '') AS grupos_sin_cliente,
              COUNT(*) FILTER (WHERE cliente_id <> '') AS grupos_con_cliente_amplios
            FROM base
            """
        )
        row = cur.fetchone() or {}
    return {
        "grupos_sin_cliente": int(row.get("grupos_sin_cliente") or 0),
        "grupos_con_cliente_amplios": int(row.get("grupos_con_cliente_amplios") or 0),
    }


def ensure_backup_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS renta_doc_duplicate_cleanup_backup (
              run_id TEXT NOT NULL,
              backed_up_at TIMESTAMPTZ NOT NULL,
              deleted_by TEXT NOT NULL,
              reason TEXT NOT NULL,
              kept_id TEXT NOT NULL,
              deleted_id TEXT NOT NULL,
              row_data JSONB NOT NULL
            )
            """
        )


def apply_cleanup(conn, grouped: dict[tuple[str, ...], list[dict]], run_id: str, deleted_by: str) -> tuple[int, int]:
    ensure_backup_table(conn)
    deleted = 0
    groups_cleaned = 0
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        for rows in grouped.values():
            if len(rows) < 2:
                continue
            kept_id = rows[0]["id"]
            delete_ids = [row["id"] for row in rows[1:]]
            for deleted_id in delete_ids:
                cur.execute(
                    """
                    INSERT INTO renta_doc_duplicate_cleanup_backup (
                      run_id, backed_up_at, deleted_by, reason, kept_id, deleted_id, row_data
                    )
                    SELECT %s, %s, %s, %s, %s, id, to_jsonb(gestoria_docs)
                    FROM gestoria_docs
                    WHERE id = %s
                    """,
                    (
                        run_id,
                        now,
                        deleted_by,
                        "exact_renta_doc_duplicate_same_client_reference_hash_name_type_state",
                        kept_id,
                        deleted_id,
                    ),
                )
                cur.execute("DELETE FROM gestoria_docs WHERE id = %s", (deleted_id,))
                deleted += cur.rowcount
            groups_cleaned += 1
    return groups_cleaned, deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Limpia duplicados exactos y seguros en gestoria_docs de renta.")
    parser.add_argument("--apply", action="store_true", help="Aplica la limpieza. Sin esto sólo informa.")
    parser.add_argument("--env-file", default=".env", help="Archivo env local para leer POSTGRES_URL/DATABASE_URL.")
    parser.add_argument("--run-id", default="", help="Identificador de ejecución.")
    parser.add_argument("--deleted-by", default="codex", help="Actor para backup/auditoría.")
    args = parser.parse_args()

    load_env_file(Path(args.env_file))
    dsn = env_first("POSTGRES_URL", "DATABASE_URL")
    if not dsn.startswith("postgres"):
        raise SystemExit("Falta POSTGRES_URL/DATABASE_URL de Postgres.")

    run_id = args.run_id or f"cleanup_renta_doc_duplicates_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    with pg_connect(dsn) as conn:
        grouped = fetch_safe_groups(conn)
        duplicate_rows = sum(len(rows) for rows in grouped.values())
        rows_to_delete = sum(max(0, len(rows) - 1) for rows in grouped.values())
        risky = summarize_risky(conn)
        print(f"run_id={run_id}")
        print(f"safe_groups={len(grouped)}")
        print(f"safe_duplicate_rows={duplicate_rows}")
        print(f"safe_rows_to_delete={rows_to_delete}")
        print(f"risky_groups_without_client={risky['grupos_sin_cliente']}")
        print(f"broader_groups_with_client={risky['grupos_con_cliente_amplios']}")
        if not args.apply:
            conn.rollback()
            return 0
        groups_cleaned, deleted = apply_cleanup(conn, grouped, run_id, args.deleted_by)
        conn.commit()
        print(f"groups_cleaned={groups_cleaned}")
        print(f"deleted_rows={deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
