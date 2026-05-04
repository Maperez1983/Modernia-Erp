#!/usr/bin/env python3
"""
Re-OCR selectivo en producción: arregla tomador (y opcionalmente algunos campos) para pólizas con PDF.

Motivación: algunos registros quedan con tomador basura (p.ej. "Aseguradora no La") y distorsionan KPIs.

Estrategia:
  - Selecciona pólizas (empresa_id) con PDF asociado (poliza_key/url o doc) y tomador sospechoso.
  - Descarga el PDF desde S3 (poliza_key) y ejecuta el extractor OCR existente (process_seguros_ocr).
  - Si el tomador extraído parece mejor, actualiza `seguros.tomador`.
  - También rellena `ramo` si está vacío y el OCR devuelve un ramo canónico.

NOTA: requiere `DATABASE_URL` apuntando a Postgres (Render) y credenciales S3 (AWS_*).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.db_backend import open_postgres_conn  # noqa: E402
from web.server import (  # noqa: E402
    canonicalize_ramo,
    clean_tomador_value,
    normalize_lookup_text,
    process_seguros_ocr,
)


def looks_bad_tomador(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return True
    key = normalize_lookup_text(raw)
    if len(raw) < 5:
        return True
    bad_markers = (
        "ASEGURADORA",
        "ASEGURADOR",
        "ASEGURADO",
        "DATOS DEL TOMADOR",
        "TOMADOR DEL SEGURO",
        "ASEGURADORA NO",
        "ASEGURADORA N0",
        "ASEGURADORA NO LA",
        "NO LA",
    )
    if any(m in key for m in bad_markers):
        return True
    # Valores que suelen ser fragmentos: "Aseguradora no La", "Aseguradora"
    if len(raw.split()) <= 2 and ("ASEGURADORA" in key or "TOMADOR" in key):
        return True
    return False


def looks_good_tomador(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    cleaned = clean_tomador_value(raw)
    if not cleaned or len(cleaned) < 5:
        return False
    key = normalize_lookup_text(cleaned)
    if any(token in key for token in ("ASEGURADORA", "POLIZA", "PÓLIZA", "TOMADOR", "SEGURO")):
        return False
    # Persona: al menos 2 palabras; Empresa: admite 2 palabras + SL/S.A.
    parts = [p for p in re.split(r"\s+", cleaned) if p]
    if len(parts) >= 2:
        return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-OCR selectivo para arreglar tomadores en Seguros (Postgres).")
    ap.add_argument("--empresa-id", required=True, help="ID empresa (UUID).")
    ap.add_argument("--limit", type=int, default=0, help="Límite de pólizas a procesar (0 = sin límite).")
    ap.add_argument("--apply", action="store_true", help="Aplica cambios (por defecto dry-run).")
    ap.add_argument("--fast", action="store_true", help="Modo rápido (evita OCR all-pages/docai).")
    args = ap.parse_args()

    empresa_id = str(args.empresa_id or "").strip()
    limit = int(args.limit or 0)
    now = datetime.now(timezone.utc).isoformat()

    conn = open_postgres_conn(with_row_factory=True)

    # Solo pólizas con PDF subido (poliza_key/url o doc asociado).
    pdf_assoc_expr = (
        "("
        "(NULLIF(TRIM(s.poliza_url), '') IS NOT NULL OR NULLIF(TRIM(s.poliza_key), '') IS NOT NULL)"
        " OR EXISTS ("
        "   SELECT 1 FROM gestoria_docs gd"
        "   WHERE gd.empresa_id = s.empresa_id"
        "     AND gd.cliente_id = s.cliente_id"
        "     AND gd.referencia_id = s.id"
        "     AND (LOWER(COALESCE(gd.referencia_tipo,'')) = 'seguros' OR LOWER(COALESCE(gd.tipo,'')) = 'seguros')"
        "     AND (NULLIF(TRIM(COALESCE(gd.doc_url,'')), '') IS NOT NULL OR NULLIF(TRIM(COALESCE(gd.doc_key,'')), '') IS NOT NULL)"
        " )"
        ")"
    )

    rows = conn.execute(
        f"""
        SELECT s.id, COALESCE(s.tomador,'') AS tomador, COALESCE(s.ramo,'') AS ramo,
               COALESCE(s.compania,'') AS compania,
               COALESCE(s.poliza_key,'') AS poliza_key, COALESCE(s.poliza_url,'') AS poliza_url
        FROM seguros s
        WHERE s.empresa_id = %s
          AND {pdf_assoc_expr}
          AND (COALESCE(TRIM(s.poliza_key), '') <> '')
        ORDER BY s.created_at ASC NULLS LAST
        """,
        (empresa_id,),
    ).fetchall()

    candidates = []
    for r in rows:
        if looks_bad_tomador(r.get("tomador")):
            candidates.append(r)
    if limit and limit > 0:
        candidates = candidates[:limit]

    print(f"[{now}] empresa_id={empresa_id} total_pdf={len(rows)} candidates={len(candidates)} dry_run={not args.apply}")

    updated = 0
    skipped = 0
    errors = 0
    for r in candidates:
        seguro_id = str(r.get("id") or "").strip()
        s3_key = str(r.get("poliza_key") or "").strip()
        if not seguro_id or not s3_key:
            skipped += 1
            continue
        try:
            payload = {
                "s3_key": s3_key,
                "filename": os.path.basename(s3_key) or "poliza.pdf",
                "source_hint": s3_key,
                "fast_mode": bool(args.fast),
            }
            res = process_seguros_ocr(payload, conn, session=None) or {}
            fields = res.get("fields") or {}
            new_tomador = clean_tomador_value(fields.get("tomador") or "")
            new_ramo = canonicalize_ramo(fields.get("ramo") or "")
            patch = {}
            if looks_good_tomador(new_tomador) and looks_bad_tomador(r.get("tomador") or ""):
                patch["tomador"] = new_tomador
            if (not str(r.get("ramo") or "").strip()) and new_ramo:
                patch["ramo"] = new_ramo
            if not patch:
                skipped += 1
                continue
            if args.apply:
                cols = ", ".join([f"{k}=%s" for k in patch.keys()])
                values = list(patch.values()) + [now, seguro_id, empresa_id]
                conn.execute(
                    f"UPDATE seguros SET {cols}, updated_at=%s WHERE id=%s AND empresa_id=%s",
                    tuple(values),
                )
                conn.commit()
            updated += 1
            if updated <= 25:
                print(f"- updated {seguro_id}: {patch}")
        except Exception as exc:
            errors += 1
            if errors <= 15:
                print(f"[ERR] {seguro_id} key={s3_key} {type(exc).__name__}: {exc}")

    print(
        f"done candidates={len(candidates)} updated={updated} skipped={skipped} errors={errors} dry_run={not args.apply}"
    )


if __name__ == "__main__":
    main()

