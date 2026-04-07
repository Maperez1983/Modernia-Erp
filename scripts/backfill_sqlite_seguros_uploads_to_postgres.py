#!/usr/bin/env python3
"""
Backfill de subidas (S3 keys/URLs) desde una SQLite histórica hacia Postgres.

Caso típico: al principio el CRM usaba SQLite y se subieron PDFs (poliza_key/poliza_url y/o gestoria_docs).
Después se cambió a Postgres y los KPIs "pólizas cargadas" (uploaded_only) solo cuentan lo que está en Postgres.

Este script:
  - Copia/actualiza en Postgres `seguros.poliza_key/poliza_url` cuando estén vacíos.
  - Copia/actualiza `gestoria_docs` (solo docs de seguros) y fuerza `referencia_tipo='seguros'` si falta.

Es seguro de ejecutar varias veces (idempotente; no borra ni sobreescribe valores existentes no vacíos).
"""

import argparse
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.db_backend import open_postgres_conn, is_postgres_enabled  # noqa: E402
from web.server import ensure_tables  # noqa: E402


def _norm_text(value):
    if value is None:
        return ""
    return str(value).strip()


def main():
    parser = argparse.ArgumentParser(description="Backfill de pólizas subidas (SQLite -> Postgres).")
    parser.add_argument("--sqlite", required=True, help="Ruta a la SQLite origen (ej: /var/data/erp_import2.sqlite).")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Límite de filas a procesar (0 = sin límite).",
    )
    args = parser.parse_args()

    if not is_postgres_enabled():
        raise SystemExit("Postgres no habilitado (DATABASE_URL/POSTGRES_URL no empieza por 'postgres').")

    sqlite_path = Path(args.sqlite).expanduser().resolve()
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite no encontrada: {sqlite_path}")

    # Asegura esquema en Postgres antes de tocar nada.
    ensure_tables(str(sqlite_path))

    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = open_postgres_conn(with_row_factory=False)
    try:
        updated_policies = 0
        inserted_docs = 0
        updated_docs = 0

        limit_clause = ""
        values = []
        if args.limit and int(args.limit) > 0:
            limit_clause = " LIMIT ?"
            values.append(int(args.limit))

        # 1) Backfill de seguros.poliza_key/poliza_url (solo si vienen con dato).
        rows = sqlite_conn.execute(
            f"""
            SELECT id, empresa_id, poliza_key, poliza_url
            FROM seguros
            WHERE COALESCE(TRIM(poliza_key), '') <> '' OR COALESCE(TRIM(poliza_url), '') <> ''
            {limit_clause}
            """,
            values,
        ).fetchall()
        for row in rows:
            poliza_id = _norm_text(row["id"])
            if not poliza_id:
                continue
            poliza_key = _norm_text(row["poliza_key"])
            poliza_url = _norm_text(row["poliza_url"])
            if not poliza_key and not poliza_url:
                continue
            # Solo rellena si está vacío en destino.
            pg_conn.execute(
                """
                UPDATE seguros
                SET poliza_key = COALESCE(NULLIF(poliza_key, ''), %s),
                    poliza_url = COALESCE(NULLIF(poliza_url, ''), %s)
                WHERE id = %s
                """,
                (poliza_key or None, poliza_url or None, poliza_id),
            )
            if getattr(pg_conn, "rowcount", None):
                updated_policies += int(pg_conn.rowcount or 0)

        # 2) Backfill de gestoria_docs (solo docs de seguros).
        docs = sqlite_conn.execute(
            f"""
            SELECT *
            FROM gestoria_docs
            WHERE LOWER(TRIM(COALESCE(referencia_tipo, ''))) = 'seguros'
               OR LOWER(TRIM(COALESCE(tipo, ''))) = 'seguros'
            {limit_clause}
            """,
            values,
        ).fetchall()
        for row in docs:
            doc_id = _norm_text(row["id"])
            if not doc_id:
                continue
            referencia_id = _norm_text(row["referencia_id"])
            doc_key = _norm_text(row["doc_key"])
            doc_url = _norm_text(row["doc_url"])
            if not doc_key and not doc_url:
                continue
            empresa_id = _norm_text(row["empresa_id"])
            cliente_id = _norm_text(row["cliente_id"])
            nombre = _norm_text(row["nombre"]) or "Póliza seguro"
            fecha = _norm_text(row["fecha"])
            estado = _norm_text(row["estado"]) or "Recibido"
            notas = _norm_text(row["notas"])
            created_at = _norm_text(row["created_at"]) or "now"
            updated_at = _norm_text(row["updated_at"]) or "now"

            # Insert/Upsert seguro: no pisa valores existentes no vacíos.
            pg_conn.execute(
                """
                INSERT INTO gestoria_docs (
                  id, empresa_id, cliente_id, referencia_tipo, referencia_id,
                  nombre, tipo, fecha, estado, notas, doc_key, doc_url,
                  created_at, updated_at
                ) VALUES (
                  %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s,
                  %s, %s
                )
                ON CONFLICT (id) DO UPDATE SET
                  empresa_id = COALESCE(NULLIF(gestoria_docs.empresa_id, ''), EXCLUDED.empresa_id),
                  cliente_id = COALESCE(NULLIF(gestoria_docs.cliente_id, ''), EXCLUDED.cliente_id),
                  referencia_tipo = COALESCE(NULLIF(gestoria_docs.referencia_tipo, ''), 'seguros'),
                  referencia_id = COALESCE(gestoria_docs.referencia_id, EXCLUDED.referencia_id),
                  nombre = COALESCE(NULLIF(gestoria_docs.nombre, ''), EXCLUDED.nombre),
                  tipo = COALESCE(NULLIF(gestoria_docs.tipo, ''), EXCLUDED.tipo),
                  fecha = COALESCE(NULLIF(gestoria_docs.fecha, ''), EXCLUDED.fecha),
                  estado = COALESCE(NULLIF(gestoria_docs.estado, ''), EXCLUDED.estado),
                  notas = COALESCE(NULLIF(gestoria_docs.notas, ''), EXCLUDED.notas),
                  doc_key = COALESCE(NULLIF(gestoria_docs.doc_key, ''), EXCLUDED.doc_key),
                  doc_url = COALESCE(NULLIF(gestoria_docs.doc_url, ''), EXCLUDED.doc_url),
                  updated_at = EXCLUDED.updated_at
                """,
                (
                    doc_id,
                    empresa_id or None,
                    cliente_id or None,
                    "seguros",
                    referencia_id or None,
                    nombre,
                    "Seguros",
                    fecha or None,
                    estado,
                    notas or None,
                    doc_key or None,
                    doc_url or None,
                    created_at,
                    updated_at,
                ),
            )
            # No tenemos forma fiable de distinguir insert vs update sin un SELECT previo.
            # Contabilizamos de manera aproximada por rowcount (psycopg3 suele devolver 1).
            if getattr(pg_conn, "rowcount", None):
                # ON CONFLICT también cuenta como 1
                updated_docs += 1

        pg_conn.commit()
        print("OK")
        print(f"- seguros actualizados: {updated_policies}")
        print(f"- gestoria_docs upsert (seguros): {updated_docs}")
    finally:
        try:
            sqlite_conn.close()
        except Exception:
            pass
        try:
            pg_conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

