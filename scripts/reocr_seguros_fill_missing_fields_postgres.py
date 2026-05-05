#!/usr/bin/env python3
"""
Re-OCR selectivo para rellenar campos faltantes en Seguros (Postgres/Render).

Rellena SOLO si el campo actual está vacío para no pisar ediciones manuales.
Campos objetivo:
  - tomador
  - poliza_numero
  - ramo (canónico)
  - matricula / direccion_riesgo / referencia_catastral (si vienen del OCR)

Requiere:
  - DATABASE_URL (Render Postgres)
  - AWS_* para poder leer PDFs desde S3 usando `poliza_key`
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.db_backend import open_postgres_conn  # noqa: E402
from web.server import (  # noqa: E402
    canonicalize_ramo,
    normalize_poliza_key,
    process_seguros_ocr,
)


def _is_empty(value) -> bool:
    return not str(value or "").strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-OCR selectivo: rellenar faltantes de Seguros en Postgres.")
    ap.add_argument("--empresa-id", required=True)
    ap.add_argument("--limit", type=int, default=0, help="0 = sin límite")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--fast", action="store_true", help="Modo rápido (menos OCR pesado).")
    args = ap.parse_args()

    empresa_id = str(args.empresa_id or "").strip()
    limit = int(args.limit or 0)
    now = datetime.now(timezone.utc).isoformat()

    conn = open_postgres_conn(with_row_factory=True)

    rows = conn.execute(
        """
        SELECT id, cliente_id, COALESCE(tomador,'') AS tomador,
               COALESCE(poliza_numero,'') AS poliza_numero,
               COALESCE(ramo,'') AS ramo,
               COALESCE(matricula,'') AS matricula,
               COALESCE(direccion_riesgo,'') AS direccion_riesgo,
               COALESCE(referencia_catastral,'') AS referencia_catastral,
               COALESCE(poliza_key,'') AS poliza_key
        FROM seguros
        WHERE empresa_id = %s
          AND COALESCE(TRIM(poliza_key), '') <> ''
        ORDER BY created_at ASC NULLS LAST
        """,
        (empresa_id,),
    ).fetchall()

    candidates = []
    for r in rows:
        if (
            _is_empty(r.get("tomador"))
            or _is_empty(r.get("poliza_numero"))
            or _is_empty(r.get("ramo"))
            or _is_empty(r.get("matricula"))
            or _is_empty(r.get("direccion_riesgo"))
            or _is_empty(r.get("referencia_catastral"))
        ):
            candidates.append(r)
    if limit and limit > 0:
        candidates = candidates[:limit]

    print(f"[{now}] empresa_id={empresa_id} total_with_pdf={len(rows)} candidates={len(candidates)} dry_run={not args.apply}")

    updated = 0
    errors = 0
    skipped = 0
    for r in candidates:
        sid = str(r.get("id") or "").strip()
        key = str(r.get("poliza_key") or "").strip()
        if not sid or not key:
            skipped += 1
            continue
        try:
            payload = {
                "s3_key": key,
                "filename": os.path.basename(key) or "poliza.pdf",
                "source_hint": key,
                "fast_mode": bool(args.fast),
            }
            res = process_seguros_ocr(payload, conn, session=None) or {}
            fields = res.get("fields") or {}
            smart = fields.get("datos_ramo") if isinstance(fields.get("datos_ramo"), dict) else {}

            patch = {}
            # tomador
            if _is_empty(r.get("tomador")) and str(fields.get("tomador") or "").strip():
                patch["tomador"] = str(fields.get("tomador") or "").strip()
            # poliza_numero
            if _is_empty(r.get("poliza_numero")) and str(fields.get("poliza_numero") or "").strip():
                pol = str(fields.get("poliza_numero") or "").strip()
                if normalize_poliza_key(pol):
                    patch["poliza_numero"] = pol
            # ramo (canónico)
            if _is_empty(r.get("ramo")) and str(fields.get("ramo") or "").strip():
                ramo = canonicalize_ramo(fields.get("ramo") or "")
                if ramo:
                    patch["ramo"] = ramo
            # smart fields (si vienen del OCR)
            if _is_empty(r.get("matricula")) and str(fields.get("matricula") or "").strip():
                patch["matricula"] = str(fields.get("matricula") or "").strip()
            if _is_empty(r.get("direccion_riesgo")) and str(fields.get("direccion_riesgo") or "").strip():
                patch["direccion_riesgo"] = str(fields.get("direccion_riesgo") or "").strip()
            if _is_empty(r.get("referencia_catastral")) and str(fields.get("referencia_catastral") or "").strip():
                patch["referencia_catastral"] = str(fields.get("referencia_catastral") or "").strip()

            if not patch:
                skipped += 1
                continue
            if args.apply:
                cols = ", ".join([f"{k}=%s" for k in patch.keys()])
                values = list(patch.values()) + [now, sid, empresa_id]
                conn.execute(f"UPDATE seguros SET {cols}, updated_at=%s WHERE id=%s AND empresa_id=%s", tuple(values))
                conn.commit()
            updated += 1
            if updated <= 25:
                print(f"- updated {sid}: {patch}")
        except Exception as exc:
            errors += 1
            if errors <= 15:
                print(f"[ERR] {sid} key={key} {type(exc).__name__}: {exc}")

    print(f"done updated={updated} skipped={skipped} errors={errors} dry_run={not args.apply}")


if __name__ == "__main__":
    main()

