#!/usr/bin/env python3
"""
Recupera pólizas (tabla `seguros`) a partir de PDFs ya subidos a S3 y vinculados a clientes.

Escenario:
  - Existen documentos en `gestoria_docs` con `cliente_id` y `doc_key`/`doc_url` (S3),
    pero no existen registros en `seguros` (o no están enlazados).
  - El dashboard/fichas no los consideran "pólizas" porque `seguros` está vacío o no tiene
    `poliza_key/poliza_url` y/o `gestoria_docs.referencia_id` no apunta a un seguro.

Qué hace:
  - Para cada doc candidato crea (o enlaza) un registro en `seguros` y lo marca como "En vigor".
  - Rellena `seguros.poliza_key/poliza_url` con `gestoria_docs.doc_key/doc_url`.
  - Actualiza `gestoria_docs.referencia_tipo='seguros'` y `referencia_id=<seguro_id>`.
  - Asegura el vínculo `clientes_empresas` para servicio "seguros" si falta.

Precaución:
  - Por defecto hace dry-run (`--apply` requerido para persistir cambios).
  - No hace OCR del PDF: intenta inferir `compania` y `poliza_numero` desde metadatos/nombre/key.
"""

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.db_backend import open_postgres_conn, is_postgres_enabled  # noqa: E402
from web.server import (  # noqa: E402
    detect_company_from_metadata,
    ensure_tables,
    guess_poliza_from_filename,
)


def _norm_text(value):
    if value is None:
        return ""
    return str(value).strip()


def _compact_poliza(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (value or "").upper()).strip()


def _ensure_cliente_servicio_link(conn, cliente_id: str, empresa_id: str, servicio: str, now: str) -> int:
    if not cliente_id or not empresa_id or not servicio:
        return 0
    exists = conn.execute(
        """
        SELECT id
        FROM clientes_empresas
        WHERE cliente_id = ? AND empresa_id = ? AND LOWER(servicio) = LOWER(?)
        LIMIT 1
        """,
        (cliente_id, empresa_id, servicio),
    ).fetchone()
    if exists:
        return 0
    conn.execute(
        """
        INSERT INTO clientes_empresas (
          id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at
        ) VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (os.urandom(16).hex(), cliente_id, empresa_id, servicio, "Activo", None, None, now, now),
    )
    return 1


def _guess_fields(doc: dict, cliente_nombre: str):
    source_hint = " ".join(
        [
            _norm_text(doc.get("nombre")),
            _norm_text(doc.get("doc_key")),
            _norm_text(doc.get("doc_url")),
            _norm_text(doc.get("notas")),
        ]
    ).strip()
    compania = detect_company_from_metadata(source_hint)
    poliza_guess = guess_poliza_from_filename(_norm_text(doc.get("nombre")) or _norm_text(doc.get("doc_key")) or _norm_text(doc.get("doc_url")))
    poliza_numero = _norm_text(poliza_guess)
    if not poliza_numero:
        # fallback: tokens largos en key/nombre
        token_candidates = re.findall(r"[A-Z0-9]{6,}", re.sub(r"[^A-Za-z0-9]+", " ", source_hint.upper()))
        for token in token_candidates:
            compact = _compact_poliza(token)
            if len(compact) >= 6 and re.search(r"\d", compact):
                poliza_numero = token.strip()
                break
    tomador = _norm_text(cliente_nombre) or ""
    return {
        "tomador": tomador,
        "compania": _norm_text(compania),
        "poliza_numero": poliza_numero,
    }


def _find_seguro_by_doc(conn, doc_key: str, doc_url: str):
    doc_key = _norm_text(doc_key)
    doc_url = _norm_text(doc_url)
    if not doc_key and not doc_url:
        return None
    where = []
    values = []
    if doc_key:
        where.append("poliza_key = ?")
        values.append(doc_key)
    if doc_url:
        where.append("poliza_url = ?")
        values.append(doc_url)
    if not where:
        return None
    row = conn.execute(
        f"""
        SELECT *
        FROM seguros
        WHERE {' OR '.join(where)}
        LIMIT 1
        """,
        values,
    ).fetchone()
    return row


def _seguro_exists(conn, seguro_id: str) -> bool:
    seguro_id = _norm_text(seguro_id)
    if not seguro_id:
        return False
    row = conn.execute("SELECT id FROM seguros WHERE id = ? LIMIT 1", (seguro_id,)).fetchone()
    return bool(row)


def main():
    ap = argparse.ArgumentParser(description="Recupera pólizas desde docs (S3) vinculados a clientes.")
    ap.add_argument("--limit", type=int, default=0, help="Límite de documentos (0 = sin límite).")
    ap.add_argument("--apply", action="store_true", help="Aplica cambios (por defecto: dry-run con rollback).")
    ap.add_argument("--empresa-id", default="", help="Filtra por empresa_id (opcional).")
    ap.add_argument(
        "--doc-prefix",
        default="seguros/",
        help="Filtra doc_key por prefijo (ej: 'seguros/'). Vacío para no filtrar.",
    )
    ap.add_argument(
        "--include-non-seguros",
        action="store_true",
        help="Incluye docs que no estén marcados como seguros (usa solo doc_prefix + cliente_id).",
    )
    ap.add_argument(
        "--only-unlinked",
        action="store_true",
        help="Solo procesa docs sin referencia_id o con referencia_id inválida.",
    )
    args = ap.parse_args()

    if not is_postgres_enabled():
        raise SystemExit("Postgres no habilitado (DATABASE_URL/POSTGRES_URL no empieza por 'postgres').")

    conn = open_postgres_conn(with_row_factory=True)
    now = datetime.now(timezone.utc).isoformat()
    try:
        # Asegura tablas/columnas esenciales antes de operar.
        ensure_tables("unused_for_postgres")

        where = ["COALESCE(TRIM(cliente_id), '') <> ''", "(COALESCE(TRIM(doc_key), '') <> '' OR COALESCE(TRIM(doc_url), '') <> '')"]
        values = []
        if args.empresa_id:
            where.append("empresa_id = ?")
            values.append(_norm_text(args.empresa_id))
        if args.doc_prefix:
            where.append("COALESCE(doc_key, '') LIKE ?")
            values.append(_norm_text(args.doc_prefix) + "%")
        if not args.include_non_seguros:
            where.append(
                "("
                "LOWER(TRIM(COALESCE(referencia_tipo, ''))) = 'seguros' "
                "OR LOWER(TRIM(COALESCE(tipo, ''))) = 'seguros' "
                "OR COALESCE(doc_key, '') LIKE 'seguros/%'"
                ")"
            )
        if args.only_unlinked:
            where.append(
                "("
                "COALESCE(TRIM(referencia_id), '') = '' "
                "OR NOT EXISTS (SELECT 1 FROM seguros s WHERE s.id = gestoria_docs.referencia_id)"
                ")"
            )

        limit_clause = ""
        if args.limit and int(args.limit) > 0:
            limit_clause = " LIMIT ?"
            values.append(int(args.limit))

        docs = conn.execute(
            f"""
            SELECT id, empresa_id, cliente_id, referencia_id, referencia_tipo, tipo,
                   nombre, fecha, estado, notas, doc_key, doc_url, created_at
            FROM gestoria_docs
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            {limit_clause}
            """,
            values,
        ).fetchall()

        created = 0
        linked_existing = 0
        updated_refs = 0
        updated_keys = 0
        service_links = 0
        skipped = 0

        for d in docs:
            doc = dict(d)
            doc_id = _norm_text(doc.get("id"))
            empresa_id = _norm_text(doc.get("empresa_id"))
            cliente_id = _norm_text(doc.get("cliente_id"))
            doc_key = _norm_text(doc.get("doc_key"))
            doc_url = _norm_text(doc.get("doc_url"))
            if not doc_id or not empresa_id or not cliente_id or (not doc_key and not doc_url):
                skipped += 1
                continue

            ref_id = _norm_text(doc.get("referencia_id"))
            seguro_row = None
            if ref_id and _seguro_exists(conn, ref_id):
                seguro_row = conn.execute("SELECT * FROM seguros WHERE id = ? LIMIT 1", (ref_id,)).fetchone()
            if not seguro_row:
                seguro_row = _find_seguro_by_doc(conn, doc_key, doc_url)

            cliente = conn.execute("SELECT nombre FROM clientes WHERE id = ? LIMIT 1", (cliente_id,)).fetchone()
            cliente_nombre = ""
            if cliente:
                try:
                    cliente_nombre = _norm_text(cliente.get("nombre"))
                except Exception:
                    try:
                        cliente_nombre = _norm_text(cliente[0])
                    except Exception:
                        cliente_nombre = ""

            if seguro_row:
                seguro_id = _norm_text(seguro_row.get("id") if isinstance(seguro_row, dict) else seguro_row["id"])
                # Enlaza doc -> seguro si falta.
                if ref_id != seguro_id or _norm_text(doc.get("referencia_tipo")).lower() != "seguros":
                    conn.execute(
                        """
                        UPDATE gestoria_docs
                        SET referencia_tipo = 'seguros',
                            referencia_id = ?,
                            updated_at = ?
                        WHERE id = ?
                        """,
                        (seguro_id, now, doc_id),
                    )
                    updated_refs += 1
                # Rellena keys/url y cliente_id si están vacíos.
                cur = conn.execute(
                    """
                    UPDATE seguros
                    SET
                      cliente_id = COALESCE(NULLIF(cliente_id, ''), ?),
                      poliza_key = COALESCE(NULLIF(poliza_key, ''), ?),
                      poliza_url = COALESCE(NULLIF(poliza_url, ''), ?),
                      updated_at = ?
                    WHERE id = ?
                    """,
                    (cliente_id, doc_key or None, doc_url or None, now, seguro_id),
                )
                try:
                    updated_keys += int(getattr(cur, "rowcount", 0) or 0)
                except Exception:
                    pass
                service_links += _ensure_cliente_servicio_link(conn, cliente_id, empresa_id, "seguros", now)
                linked_existing += 1
                continue

            fields = _guess_fields(doc, cliente_nombre)
            seguro_id = os.urandom(16).hex()
            fecha_efecto = _norm_text(doc.get("fecha")) or ""
            mes_creacion = ""
            try:
                if fecha_efecto and len(fecha_efecto) >= 7:
                    mes_creacion = fecha_efecto[:7]
            except Exception:
                mes_creacion = ""

            conn.execute(
                """
                INSERT INTO seguros (
                  id, empresa_id, cliente_id, mes_creacion,
                  fecha_efecto, fecha_vencimiento,
                  tomador, compania, ramo, poliza_numero,
                  estado, estado_poliza,
                  poliza_key, poliza_url,
                  version_grupo, tipo_vigencia,
                  created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?,
                  ?, ?,
                  ?, ?, ?, ?,
                  ?, ?,
                  ?, ?,
                  ?, ?,
                  ?, ?
                )
                """,
                (
                    seguro_id,
                    empresa_id,
                    cliente_id,
                    mes_creacion or None,
                    fecha_efecto or None,
                    None,
                    fields.get("tomador") or None,
                    fields.get("compania") or None,
                    None,
                    fields.get("poliza_numero") or None,
                    "En vigor",
                    "activa",
                    doc_key or None,
                    doc_url or None,
                    seguro_id,
                    None,
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE gestoria_docs
                SET referencia_tipo = 'seguros',
                    referencia_id = ?,
                    tipo = COALESCE(NULLIF(tipo, ''), 'Seguros'),
                    updated_at = ?
                WHERE id = ?
                """,
                (seguro_id, now, doc_id),
            )
            service_links += _ensure_cliente_servicio_link(conn, cliente_id, empresa_id, "seguros", now)
            created += 1

        if args.apply:
            conn.commit()
        else:
            conn.rollback()

        print("OK")
        print(f"- apply={1 if args.apply else 0}")
        print(f"- docs={len(docs)}")
        print(f"- seguros_created={created}")
        print(f"- linked_existing={linked_existing}")
        print(f"- updated_doc_refs={updated_refs}")
        print(f"- updated_seguros_keys={updated_keys}")
        print(f"- clientes_empresas_inserted={service_links}")
        print(f"- skipped={skipped}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

