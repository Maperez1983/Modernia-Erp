#!/usr/bin/env python3
"""
Backfill de subidas (S3 keys/URLs) desde una SQLite histórica hacia Postgres.

Caso típico: al principio el CRM usaba SQLite y se subieron PDFs (poliza_key/poliza_url y/o gestoria_docs).
Después se cambió a Postgres y los KPIs "pólizas cargadas" (uploaded_only) solo cuentan lo que está en Postgres.

Este script:
  - Copia/actualiza en Postgres `seguros.poliza_key/poliza_url` cuando estén vacíos.
  - Copia/actualiza `gestoria_docs` (solo docs de seguros) creando/actualizando enlaces a la póliza.
  - Asegura el vínculo `clientes_empresas` para servicio "seguros" (si falta), para que la ficha salga como propia.

Notas sobre migraciones:
  - Si en la migración se preservaron IDs, el modo `id` funciona directo.
  - Si los IDs cambiaron (p.ej. se re-crearon registros), usa `--match-mode id_or_natural`, que intenta mapear
    la póliza destino por clave natural (empresa_id + poliza_numero + compania).

Es seguro de ejecutar varias veces (idempotente; no borra ni sobreescribe valores existentes no vacíos).
"""

import argparse
import os
import re
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


def _compact_poliza(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (value or "").upper()).strip()


def _norm_company(value: str) -> str:
    return " ".join((value or "").split()).strip().lower()


def _find_dest_seguro_id(pg_conn, src: dict, *, match_mode: str):
    """
    Returns (dest_id, reason).
    match_mode:
      - "id": only by id
      - "id_or_natural": try by id, else by (empresa_id + poliza_numero + compania)
    """
    src_id = _norm_text(src.get("id"))
    if src_id:
        row = pg_conn.execute("SELECT id FROM seguros WHERE id = %s LIMIT 1", (src_id,)).fetchone()
        if row:
            return (row[0] if not isinstance(row, dict) else row.get("id")), "id"
        if match_mode == "id":
            return None, "id_not_found"

    if match_mode != "id_or_natural":
        return None, "no_match"

    empresa_id = _norm_text(src.get("empresa_id"))
    poliza_raw = _norm_text(src.get("poliza_numero"))
    compania = _norm_text(src.get("compania"))
    if not empresa_id or not poliza_raw or not compania:
        return None, "natural_missing_fields"

    company_norm = _norm_company(compania)
    poliza_compact = _compact_poliza(poliza_raw)
    if not poliza_compact:
        return None, "natural_invalid_poliza"

    # 1) Match estricto: TRIM(poliza_numero) + company normalizada (lower trim)
    rows = pg_conn.execute(
        """
        SELECT id
        FROM seguros
        WHERE empresa_id = %s
          AND TRIM(COALESCE(poliza_numero::text, '')) = TRIM(%s)
          AND LOWER(TRIM(COALESCE(compania::text, ''))) = %s
        LIMIT 2
        """,
        (empresa_id, poliza_raw, company_norm),
    ).fetchall()
    if len(rows or []) == 1:
        return (rows[0][0] if not isinstance(rows[0], dict) else rows[0].get("id")), "natural_exact"
    if len(rows or []) > 1:
        return None, "natural_ambiguous_exact"

    # 2) Match por poliza normalizada (sin separadores) + company normalizada.
    rows = pg_conn.execute(
        """
        SELECT id
        FROM seguros
        WHERE empresa_id = %s
          AND regexp_replace(UPPER(COALESCE(poliza_numero::text, '')), '[^A-Z0-9]+', '', 'g') = %s
          AND LOWER(TRIM(COALESCE(compania::text, ''))) = %s
        LIMIT 2
        """,
        (empresa_id, poliza_compact, company_norm),
    ).fetchall()
    if len(rows or []) == 1:
        return (rows[0][0] if not isinstance(rows[0], dict) else rows[0].get("id")), "natural_fuzzy"
    if len(rows or []) > 1:
        return None, "natural_ambiguous_fuzzy"

    # 3) Fallback (solo si es único en la empresa): por poliza normalizada sin company.
    rows = pg_conn.execute(
        """
        SELECT id
        FROM seguros
        WHERE empresa_id = %s
          AND regexp_replace(UPPER(COALESCE(poliza_numero::text, '')), '[^A-Z0-9]+', '', 'g') = %s
        LIMIT 2
        """,
        (empresa_id, poliza_compact),
    ).fetchall()
    if len(rows or []) == 1:
        return (rows[0][0] if not isinstance(rows[0], dict) else rows[0].get("id")), "natural_unique_poliza"
    if len(rows or []) > 1:
        return None, "natural_ambiguous_poliza"

    return None, "natural_not_found"


def _ensure_cliente_servicio_link(pg_conn, *, cliente_id: str, empresa_id: str, servicio: str, now: str, cache: set):
    if not cliente_id or not empresa_id or not servicio:
        return False
    key = (cliente_id, empresa_id, servicio.lower())
    if key in cache:
        return False
    cache.add(key)
    exists = pg_conn.execute(
        """
        SELECT id
        FROM clientes_empresas
        WHERE cliente_id = %s AND empresa_id = %s AND LOWER(servicio) = LOWER(%s)
        LIMIT 1
        """,
        (cliente_id, empresa_id, servicio),
    ).fetchone()
    if exists:
        return False
    rel_id = os.urandom(16).hex()
    pg_conn.execute(
        """
        INSERT INTO clientes_empresas (
          id, cliente_id, empresa_id, servicio, estado,
          fecha_inicio, fecha_fin, created_at, updated_at
        ) VALUES (
          %s, %s, %s, %s, %s,
          %s, %s, %s, %s
        )
        """,
        (rel_id, cliente_id, empresa_id, servicio, "Activo", None, None, now, now),
    )
    return True


def _upsert_gestoria_doc_for_seguro(
    pg_conn,
    *,
    empresa_id: str,
    cliente_id: str,
    seguro_id: str,
    doc_key: str,
    doc_url: str,
    nombre: str,
    fecha: str,
    estado: str,
    notas: str,
    now: str,
):
    doc_key = _norm_text(doc_key)
    doc_url = _norm_text(doc_url)
    if not doc_key and not doc_url:
        return {"inserted": 0, "updated": 0, "skipped": 1}
    empresa_id = _norm_text(empresa_id)
    cliente_id = _norm_text(cliente_id) or None
    seguro_id = _norm_text(seguro_id)
    nombre = _norm_text(nombre) or "Póliza seguro"
    fecha = _norm_text(fecha) or None
    estado = _norm_text(estado) or "Recibido"
    notas = _norm_text(notas) or None

    where = [
        "empresa_id = %s",
        "(LOWER(TRIM(COALESCE(referencia_tipo, ''))) = 'seguros' OR LOWER(TRIM(COALESCE(tipo, ''))) = 'seguros')",
    ]
    params = [empresa_id]
    if doc_key and doc_url:
        where.append("(doc_key = %s OR doc_url = %s)")
        params.extend([doc_key, doc_url])
    elif doc_key:
        where.append("doc_key = %s")
        params.append(doc_key)
    else:
        where.append("doc_url = %s")
        params.append(doc_url)

    existing = pg_conn.execute(
        f"SELECT id FROM gestoria_docs WHERE {' AND '.join(where)} LIMIT 1",
        tuple(params),
    ).fetchone()
    if existing:
        doc_id = existing[0] if not isinstance(existing, dict) else existing.get("id")
        pg_conn.execute(
            """
            UPDATE gestoria_docs
            SET
              empresa_id = COALESCE(NULLIF(empresa_id, ''), %s),
              cliente_id = COALESCE(NULLIF(cliente_id, ''), %s),
              referencia_tipo = COALESCE(NULLIF(referencia_tipo, ''), 'seguros'),
              referencia_id = COALESCE(NULLIF(referencia_id, ''), %s),
              nombre = COALESCE(NULLIF(nombre, ''), %s),
              tipo = COALESCE(NULLIF(tipo, ''), 'Seguros'),
              fecha = COALESCE(NULLIF(fecha, ''), %s),
              estado = COALESCE(NULLIF(estado, ''), %s),
              notas = COALESCE(NULLIF(notas, ''), %s),
              doc_key = COALESCE(NULLIF(doc_key, ''), %s),
              doc_url = COALESCE(NULLIF(doc_url, ''), %s),
              updated_at = %s
            WHERE id = %s
            """,
            (
                empresa_id or None,
                cliente_id,
                seguro_id,
                nombre,
                fecha,
                estado,
                notas,
                doc_key or None,
                doc_url or None,
                now,
                doc_id,
            ),
        )
        return {"inserted": 0, "updated": 1, "skipped": 0}

    new_id = os.urandom(16).hex()
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
        """,
        (
            new_id,
            empresa_id or None,
            cliente_id,
            "seguros",
            seguro_id,
            nombre,
            "Seguros",
            fecha,
            estado,
            notas,
            doc_key or None,
            doc_url or None,
            now,
            now,
        ),
    )
    return {"inserted": 1, "updated": 0, "skipped": 0}


def main():
    parser = argparse.ArgumentParser(description="Backfill de pólizas subidas (SQLite -> Postgres).")
    parser.add_argument("--sqlite", required=True, help="Ruta a la SQLite origen (ej: /var/data/erp_import2.sqlite).")
    parser.add_argument(
        "--match-mode",
        default="id",
        choices=("id", "id_or_natural"),
        help="Cómo mapear pólizas al destino: por id o por (empresa_id+poliza_numero+compania).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ejecuta el backfill pero hace rollback (no deja cambios).",
    )
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

    sqlite_conn = None
    pg_conn = None
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = open_postgres_conn(with_row_factory=False)
    now = datetime.now(timezone.utc).isoformat()  # noqa: F821 (imported below)
    # Nota: datetime/timezone import al final para evitar coste al importar en ciertos entornos.
    try:
        updated_policies = 0
        skipped_policies = 0
        unmapped_policies = 0
        inserted_docs = 0
        updated_docs = 0
        skipped_docs = 0
        unmapped_docs = 0
        service_links_inserted = 0

        limit_clause = ""
        values = []
        if args.limit and int(args.limit) > 0:
            limit_clause = " LIMIT ?"
            values.append(int(args.limit))

        service_link_cache = set()

        # 1) Backfill de seguros.poliza_key/poliza_url (solo si vienen con dato).
        src_rows = sqlite_conn.execute(
            f"""
            SELECT id, empresa_id, poliza_numero, compania, poliza_key, poliza_url
            FROM seguros
            WHERE COALESCE(TRIM(poliza_key), '') <> '' OR COALESCE(TRIM(poliza_url), '') <> ''
            {limit_clause}
            """,
            values,
        ).fetchall()
        for row in src_rows:
            row_dict = dict(row)
            dest_id, _reason = _find_dest_seguro_id(pg_conn, row_dict, match_mode=args.match_mode)
            if not dest_id:
                unmapped_policies += 1
                continue
            poliza_key = _norm_text(row_dict.get("poliza_key"))
            poliza_url = _norm_text(row_dict.get("poliza_url"))
            if not poliza_key and not poliza_url:
                skipped_policies += 1
                continue
            cur = pg_conn.execute(
                """
                UPDATE seguros
                SET poliza_key = COALESCE(NULLIF(poliza_key, ''), %s),
                    poliza_url = COALESCE(NULLIF(poliza_url, ''), %s)
                WHERE id = %s
                """,
                (poliza_key or None, poliza_url or None, dest_id),
            )
            try:
                updated_policies += int(getattr(cur, "rowcount", 0) or 0)
            except Exception:
                pass
            # Asegura vínculo servicio seguros para la ficha.
            dest_row = pg_conn.execute(
                "SELECT cliente_id, empresa_id FROM seguros WHERE id = %s LIMIT 1",
                (dest_id,),
            ).fetchone()
            if dest_row:
                cliente_id = _norm_text(dest_row[0] if not isinstance(dest_row, dict) else dest_row.get("cliente_id"))
                empresa_id = _norm_text(dest_row[1] if not isinstance(dest_row, dict) else dest_row.get("empresa_id"))
                if cliente_id and empresa_id:
                    if _ensure_cliente_servicio_link(pg_conn, cliente_id=cliente_id, empresa_id=empresa_id, servicio="seguros", now=now, cache=service_link_cache):
                        service_links_inserted += 1

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
            row_dict = dict(row)
            doc_key = _norm_text(row_dict.get("doc_key"))
            doc_url = _norm_text(row_dict.get("doc_url"))
            if not doc_key and not doc_url:
                skipped_docs += 1
                continue
            referencia_id = _norm_text(row_dict.get("referencia_id"))
            if not referencia_id:
                skipped_docs += 1
                continue
            src_seg = sqlite_conn.execute(
                "SELECT id, empresa_id, poliza_numero, compania FROM seguros WHERE id = ? LIMIT 1",
                (referencia_id,),
            ).fetchone()
            if not src_seg:
                unmapped_docs += 1
                continue
            dest_id, _reason = _find_dest_seguro_id(pg_conn, dict(src_seg), match_mode=args.match_mode)
            if not dest_id:
                unmapped_docs += 1
                continue

            dest_seg = pg_conn.execute(
                "SELECT cliente_id, empresa_id, fecha_efecto, poliza_numero, compania, ramo FROM seguros WHERE id = %s LIMIT 1",
                (dest_id,),
            ).fetchone()
            if not dest_seg:
                unmapped_docs += 1
                continue
            cliente_id = _norm_text(dest_seg[0] if not isinstance(dest_seg, dict) else dest_seg.get("cliente_id"))
            empresa_id = _norm_text(dest_seg[1] if not isinstance(dest_seg, dict) else dest_seg.get("empresa_id"))
            fecha_efecto = _norm_text(dest_seg[2] if not isinstance(dest_seg, dict) else dest_seg.get("fecha_efecto"))
            poliza_num = _norm_text(dest_seg[3] if not isinstance(dest_seg, dict) else dest_seg.get("poliza_numero"))
            compania = _norm_text(dest_seg[4] if not isinstance(dest_seg, dict) else dest_seg.get("compania"))
            ramo = _norm_text(dest_seg[5] if not isinstance(dest_seg, dict) else dest_seg.get("ramo"))

            if cliente_id and empresa_id:
                if _ensure_cliente_servicio_link(pg_conn, cliente_id=cliente_id, empresa_id=empresa_id, servicio="seguros", now=now, cache=service_link_cache):
                    service_links_inserted += 1

            nombre = _norm_text(row_dict.get("nombre")) or poliza_num or "Póliza seguro"
            fecha = _norm_text(row_dict.get("fecha")) or fecha_efecto
            estado = _norm_text(row_dict.get("estado")) or "Recibido"
            notas = _norm_text(row_dict.get("notas")) or " · ".join([v for v in (compania, ramo) if v])

            res = _upsert_gestoria_doc_for_seguro(
                pg_conn,
                empresa_id=empresa_id,
                cliente_id=cliente_id,
                seguro_id=dest_id,
                doc_key=doc_key,
                doc_url=doc_url,
                nombre=nombre,
                fecha=fecha,
                estado=estado,
                notas=notas,
                now=now,
            )
            inserted_docs += int(res.get("inserted", 0) or 0)
            updated_docs += int(res.get("updated", 0) or 0)

            # Rellenar también poliza_key/poliza_url desde el doc si sigue vacío.
            pg_conn.execute(
                """
                UPDATE seguros
                SET poliza_key = COALESCE(NULLIF(poliza_key, ''), %s),
                    poliza_url = COALESCE(NULLIF(poliza_url, ''), %s)
                WHERE id = %s
                """,
                (doc_key or None, doc_url or None, dest_id),
            )

        if args.dry_run:
            pg_conn.rollback()
        else:
            pg_conn.commit()
        print("OK")
        print(f"- match_mode: {args.match_mode}")
        print(f"- dry_run: {1 if args.dry_run else 0}")
        print(f"- seguros actualizados: {updated_policies}")
        print(f"- seguros sin doc_key/url en origen (skip): {skipped_policies}")
        print(f"- seguros no mapeados (skip): {unmapped_policies}")
        print(f"- gestoria_docs insertados: {inserted_docs}")
        print(f"- gestoria_docs actualizados: {updated_docs}")
        print(f"- gestoria_docs sin doc_key/url (skip): {skipped_docs}")
        print(f"- gestoria_docs no mapeados (skip): {unmapped_docs}")
        print(f"- clientes_empresas insertados (seguros): {service_links_inserted}")
    finally:
        try:
            if sqlite_conn is not None:
                sqlite_conn.close()
        except Exception:
            pass
        try:
            if pg_conn is not None:
                pg_conn.close()
        except Exception:
            pass


# Imports tardíos: evita importar datetime/timezone al cargar el módulo en ciertos entornos.
from datetime import datetime, timezone  # noqa: E402


if __name__ == "__main__":
    main()
