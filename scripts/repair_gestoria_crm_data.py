#!/usr/bin/env python3
"""Reparaciones controladas del CRM de gestoría en Postgres."""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


RENTA_DOC_FILTER = """
(
    LOWER(COALESCE(referencia_tipo,'')) = 'renta'
    OR LOWER(COALESCE(tipo,'')) IN ('renta', 'declaracion de renta', 'declaración de renta', 'modelo 100', 'renta presentada')
    OR LOWER(COALESCE(nombre,'')) LIKE '%modelo 100%'
    OR LOWER(COALESCE(nombre,'')) LIKE 'renta %'
)
"""


def d(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def fetch_rows(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [d(r) for r in (conn.execute(sql, params).fetchall() or [])]


def scalar(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = d(conn.execute(sql, params).fetchone())
    try:
        return int(next(iter(row.values())) or 0)
    except Exception:
        return 0


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def default_gestoria_empresa_id(conn: Any) -> str:
    rows = fetch_rows(
        conn,
        f"""
        SELECT empresa_id, COUNT(*) AS total
        FROM gestoria_docs
        WHERE {RENTA_DOC_FILTER}
          AND COALESCE(TRIM(empresa_id), '') <> ''
        GROUP BY empresa_id
        ORDER BY total DESC
        LIMIT 1
        """,
    )
    return str(rows[0].get("empresa_id") or "").strip() if rows else ""


def norm_nif(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def extract_nif_from_doc(row: dict[str, Any]) -> str:
    text = "\n".join(str(row.get(key) or "") for key in ("notas", "doc_key", "nombre"))
    patterns = [
        r"NIF\s+detectado:\s*([A-Z0-9]{7,12})",
        r"\b([XYZ]\d{7}[A-Z])\b",
        r"\b(\d{8}[A-Z])\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return norm_nif(match.group(1))
    return ""


def infer_name_from_doc(row: dict[str, Any], nif: str = "") -> str:
    raw = str(row.get("doc_key") or row.get("nombre") or "").split("/")[-1]
    raw = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", raw)
    raw = re.sub(r"^\d{8}_\d{6}_[a-f0-9]{8}_", "", raw, flags=re.IGNORECASE)
    tokens = re.split(r"[_\s\-]+", raw)
    name_tokens: list[str] = []
    for token in tokens:
        clean = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", token)
        token_norm = norm_nif(token)
        if not clean or token_norm == nif:
            continue
        if any(ch.isdigit() for ch in token) or (len(token_norm) >= 5 and any(ch.isdigit() for ch in token_norm)):
            break
        if clean.lower() in {"renta", "presentada", "modelo", "firma", "pdf"}:
            continue
        name_tokens.append(clean.upper())
        if len(name_tokens) >= 4:
            break
    return " ".join(name_tokens).strip() or (f"CLIENTE RENTA {nif}" if nif else "PENDIENTE ASIGNAR GESTORIA")


def find_cliente_by_nif(conn: Any, nif: str) -> str:
    if not nif:
        return ""
    found = fetch_rows(
        conn,
        """
        SELECT id
        FROM clientes
        WHERE UPPER(REGEXP_REPLACE(COALESCE(nif,''), '[^A-Za-z0-9]', '', 'g')) = ?
        ORDER BY updated_at DESC
        LIMIT 2
        """,
        (nif,),
    )
    return str(found[0].get("id") or "") if len(found) == 1 else ""


def create_cliente(conn: Any, *, nombre: str, nif: str, empresa_id: str, apply: bool) -> str:
    cliente_id = uuid.uuid4().hex
    if not apply:
        return cliente_id
    now = now_iso()
    conn.execute(
        """
        INSERT INTO clientes (
          id, empresa_id, nombre, tipo_persona, nif, tipo, perfil, estado, created_at, updated_at
        ) VALUES (?, ?, ?, 'fisica', ?, 'Cliente', 'Gestoría', 'Activo', ?, ?)
        """,
        (cliente_id, empresa_id or None, nombre, nif, now, now),
    )
    return cliente_id


def ensure_pending_cliente(conn: Any, empresa_id: str, *, apply: bool) -> str:
    name = "PENDIENTE ASIGNAR GESTORIA"
    rows = fetch_rows(
        conn,
        """
        SELECT id
        FROM clientes
        WHERE UPPER(COALESCE(nombre,'')) = ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (name,),
    )
    if rows:
        return str(rows[0].get("id") or "")
    return create_cliente(conn, nombre=name, nif="", empresa_id=empresa_id, apply=apply)


def ensure_cliente_renta_state(conn: Any, cliente_id: str, empresa_id: str, *, apply: bool) -> tuple[int, int]:
    if not cliente_id:
        return 0, 0
    now = now_iso()
    module_exists = scalar(conn, "SELECT COUNT(*) AS total FROM cliente_gestoria WHERE cliente_id = ?", (cliente_id,))
    link_exists = 1
    if empresa_id:
        link_exists = scalar(
            conn,
            """
            SELECT COUNT(*) AS total
            FROM clientes_empresas
            WHERE cliente_id = ?
              AND empresa_id = ?
              AND LOWER(COALESCE(servicio,'')) IN ('gestoria', 'gestoría')
            """,
            (cliente_id, empresa_id),
        )
    if apply:
        conn.execute(
            """
            INSERT INTO cliente_gestoria (
              id, cliente_id, tipo_cliente, mod_fiscal, mod_laboral, mod_contable,
              mod_renta, mod_registro, mod_trafico, mod_puntuales, renta_detalles,
              created_at, updated_at
            ) VALUES (?, ?, 'Particular', 0, 0, 0, 1, 0, 0, 0, '{}', ?, ?)
            ON CONFLICT (cliente_id) DO UPDATE SET
              mod_renta = 1,
              updated_at = EXCLUDED.updated_at
            """,
            (uuid.uuid4().hex, cliente_id, now, now),
        )
        if empresa_id and not link_exists:
            conn.execute(
                """
                INSERT INTO clientes_empresas (
                  id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at
                ) VALUES (?, ?, ?, 'gestoria', 'Activo', CURRENT_DATE, NULL, ?, ?)
                """,
                (uuid.uuid4().hex, cliente_id, empresa_id, now, now),
            )
    return (0 if module_exists else 1), (0 if link_exists else 1)


def assign_orphan_docs(conn: Any, *, apply: bool) -> dict[str, int]:
    default_empresa_id = default_gestoria_empresa_id(conn)
    orphan_rows = fetch_rows(
        conn,
        """
        SELECT id, empresa_id, nombre, tipo, doc_key, archivo_hash, notas, campos_ocr
        FROM gestoria_docs
        WHERE COALESCE(TRIM(cliente_id), '') = ''
           OR NOT EXISTS (SELECT 1 FROM clientes WHERE id = gestoria_docs.cliente_id)
        ORDER BY updated_at DESC
        """,
    )
    stats = {
        "assigned_existing_by_nif": 0,
        "created_clients_by_nif": 0,
        "assigned_pending": 0,
        "created_modules": 0,
        "created_links": 0,
    }
    pending_by_empresa: dict[str, str] = {}
    created_by_nif: dict[str, str] = {}
    for row in orphan_rows:
        doc_id = str(row.get("id") or "").strip()
        empresa_id = str(row.get("empresa_id") or "").strip() or default_empresa_id
        nif = extract_nif_from_doc(row)
        cliente_id = ""
        if nif:
            cliente_id = find_cliente_by_nif(conn, nif) or created_by_nif.get(nif, "")
            if cliente_id:
                stats["assigned_existing_by_nif"] += 1
            else:
                cliente_id = create_cliente(
                    conn,
                    nombre=infer_name_from_doc(row, nif),
                    nif=nif,
                    empresa_id=empresa_id,
                    apply=apply,
                )
                created_by_nif[nif] = cliente_id
                stats["created_clients_by_nif"] += 1
        if not cliente_id:
            key = empresa_id or "__global__"
            cliente_id = pending_by_empresa.get(key, "")
            if not cliente_id:
                cliente_id = ensure_pending_cliente(conn, empresa_id, apply=apply)
                pending_by_empresa[key] = cliente_id
            stats["assigned_pending"] += 1
        new_mods, new_links = ensure_cliente_renta_state(conn, cliente_id, empresa_id, apply=apply)
        stats["created_modules"] += new_mods
        stats["created_links"] += new_links
        if apply and doc_id:
            conn.execute(
                """
                UPDATE gestoria_docs
                SET cliente_id = ?,
                    empresa_id = COALESCE(NULLIF(TRIM(empresa_id), ''), ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (cliente_id, empresa_id or None, now_iso(), doc_id),
            )
    return stats


def repair_gestoria_links_without_empresa(conn: Any, *, apply: bool) -> dict[str, int]:
    default_empresa_id = default_gestoria_empresa_id(conn)
    stats = {"docs_empresa_backfilled": 0, "client_empresa_backfilled": 0, "created_links": 0}
    if not default_empresa_id:
        return stats
    rows = fetch_rows(
        conn,
        """
        SELECT cg.cliente_id
        FROM cliente_gestoria cg
        JOIN clientes c ON c.id = cg.cliente_id
        WHERE NOT EXISTS (
            SELECT 1 FROM clientes_empresas ce
            WHERE ce.cliente_id = cg.cliente_id
              AND LOWER(COALESCE(ce.servicio,'')) IN ('gestoria', 'gestoría')
              AND LOWER(COALESCE(ce.estado, 'activo')) NOT IN ('baja', 'inactivo')
        )
        ORDER BY c.updated_at DESC
        """
    )
    for row in rows:
        cliente_id = str(row.get("cliente_id") or "").strip()
        if not cliente_id:
            continue
        if apply:
            res = conn.execute(
                """
                UPDATE gestoria_docs
                SET empresa_id = ?, updated_at = ?
                WHERE cliente_id = ?
                  AND (empresa_id IS NULL OR TRIM(empresa_id) = '')
                """,
                (default_empresa_id, now_iso(), cliente_id),
            )
            try:
                stats["docs_empresa_backfilled"] += int(res.rowcount or 0)
            except Exception:
                pass
            res = conn.execute(
                """
                UPDATE clientes
                SET empresa_id = COALESCE(NULLIF(TRIM(empresa_id), ''), ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (default_empresa_id, now_iso(), cliente_id),
            )
            try:
                stats["client_empresa_backfilled"] += int(res.rowcount or 0)
            except Exception:
                pass
        new_mods, new_links = ensure_cliente_renta_state(conn, cliente_id, default_empresa_id, apply=apply)
        stats["created_links"] += new_links
    return stats


def docs_to_delete_same_client(conn: Any) -> list[str]:
    rows = fetch_rows(
        conn,
        """
        SELECT id, cliente_id, archivo_hash, doc_key, doc_url, updated_at, created_at
        FROM gestoria_docs
        WHERE COALESCE(TRIM(cliente_id), '') <> ''
          AND COALESCE(TRIM(archivo_hash), '') <> ''
        ORDER BY cliente_id, archivo_hash,
                 CASE WHEN COALESCE(TRIM(doc_key), '') <> '' OR COALESCE(TRIM(doc_url), '') <> '' THEN 0 ELSE 1 END,
                 COALESCE(NULLIF(TRIM(updated_at), ''), created_at) DESC,
                 id ASC
        """
    )
    keep: set[tuple[str, str]] = set()
    delete_ids: list[str] = []
    for row in rows:
        key = (str(row.get("cliente_id") or ""), str(row.get("archivo_hash") or ""))
        if key in keep:
            delete_ids.append(str(row.get("id")))
        else:
            keep.add(key)
    return delete_ids


def orphan_duplicate_docs(conn: Any) -> list[str]:
    rows = fetch_rows(
        conn,
        """
        SELECT d.id
        FROM gestoria_docs d
        WHERE (COALESCE(TRIM(d.cliente_id), '') = ''
               OR NOT EXISTS (SELECT 1 FROM clientes c WHERE c.id = d.cliente_id))
          AND COALESCE(TRIM(d.archivo_hash), '') <> ''
          AND EXISTS (
              SELECT 1
              FROM gestoria_docs x
              JOIN clientes c ON c.id = x.cliente_id
              WHERE x.archivo_hash = d.archivo_hash
          )
        ORDER BY d.updated_at DESC
        """
    )
    return [str(row.get("id")) for row in rows if row.get("id")]


def renta_clients_without_module(conn: Any) -> list[dict[str, Any]]:
    return fetch_rows(
        conn,
        f"""
        SELECT d.cliente_id,
               COALESCE(NULLIF(TRIM(d.empresa_id), ''), '') AS empresa_id,
               COUNT(*) AS docs
        FROM gestoria_docs d
        LEFT JOIN cliente_gestoria cg ON cg.cliente_id = d.cliente_id
        WHERE {RENTA_DOC_FILTER}
          AND COALESCE(TRIM(d.cliente_id), '') <> ''
          AND EXISTS (SELECT 1 FROM clientes c WHERE c.id = d.cliente_id)
          AND cg.cliente_id IS NULL
        GROUP BY d.cliente_id, COALESCE(NULLIF(TRIM(d.empresa_id), ''), '')
        ORDER BY docs DESC
        """
    )


def ensure_renta_module(conn: Any, rows: list[dict[str, Any]], *, apply: bool) -> tuple[int, int]:
    created_modules = 0
    created_links = 0
    now = now_iso()
    seen_clients: set[str] = set()
    seen_links: set[tuple[str, str]] = set()
    for row in rows:
        cliente_id = str(row.get("cliente_id") or "").strip()
        empresa_id = str(row.get("empresa_id") or "").strip()
        if not cliente_id:
            continue
        if cliente_id not in seen_clients:
            seen_clients.add(cliente_id)
            created_modules += 1
            if apply:
                conn.execute(
                    """
                    INSERT INTO cliente_gestoria (
                      id, cliente_id, tipo_cliente, mod_fiscal, mod_laboral, mod_contable,
                      mod_renta, mod_registro, mod_trafico, mod_puntuales, renta_detalles,
                      created_at, updated_at
                    ) VALUES (?, ?, 'Particular', 0, 0, 0, 1, 0, 0, 0, '{}', ?, ?)
                    ON CONFLICT (cliente_id) DO UPDATE SET
                      mod_renta = 1,
                      updated_at = EXCLUDED.updated_at
                    """,
                    (uuid.uuid4().hex, cliente_id, now, now),
                )
        if empresa_id and (cliente_id, empresa_id) not in seen_links:
            seen_links.add((cliente_id, empresa_id))
            exists = scalar(
                conn,
                """
                SELECT COUNT(*) AS total
                FROM clientes_empresas
                WHERE cliente_id = ?
                  AND empresa_id = ?
                  AND LOWER(COALESCE(servicio,'')) IN ('gestoria', 'gestoría')
                """,
                (cliente_id, empresa_id),
            )
            if not exists:
                created_links += 1
                if apply:
                    conn.execute(
                        """
                        INSERT INTO clientes_empresas (
                          id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at
                        ) VALUES (?, ?, ?, 'gestoria', 'Activo', CURRENT_DATE, NULL, ?, ?)
                        """,
                        (uuid.uuid4().hex, cliente_id, empresa_id, now, now),
                    )
    return created_modules, created_links


def delete_ids(conn: Any, table: str, ids: list[str], *, apply: bool) -> int:
    if not ids:
        return 0
    if apply:
        for doc_id in ids:
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (doc_id,))
    return len(ids)


def main() -> int:
    parser = argparse.ArgumentParser(description="Repara inconsistencias controladas del CRM gestoría.")
    parser.add_argument("--apply", action="store_true", help="Aplica los cambios. Sin esto es dry-run.")
    args = parser.parse_args()

    from web.db_backend import open_postgres_conn

    conn = open_postgres_conn(with_row_factory=True)
    try:
        same_client_delete = docs_to_delete_same_client(conn)
        orphan_delete = orphan_duplicate_docs(conn)
        renta_rows = renta_clients_without_module(conn)

        deleted_same = delete_ids(conn, "gestoria_docs", same_client_delete, apply=args.apply)
        deleted_orphans = delete_ids(conn, "gestoria_docs", orphan_delete, apply=args.apply)
        created_modules, created_links = ensure_renta_module(conn, renta_rows, apply=args.apply)
        orphan_assign = assign_orphan_docs(conn, apply=args.apply)
        missing_links = repair_gestoria_links_without_empresa(conn, apply=args.apply)

        if args.apply:
            conn.commit()
        else:
            conn.rollback()

        print(f"mode={'apply' if args.apply else 'dry-run'}")
        print(f"delete_same_client_duplicate_docs={deleted_same}")
        print(f"delete_orphan_duplicate_docs={deleted_orphans}")
        print(f"ensure_renta_modules={created_modules}")
        print(f"ensure_gestoria_service_links={created_links}")
        for key, value in orphan_assign.items():
            print(f"orphan_{key}={value}")
        for key, value in missing_links.items():
            print(f"missing_link_{key}={value}")
        return 0
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
