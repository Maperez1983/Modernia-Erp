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
    normalize_lookup_text,
    normalize_person_name,
    process_seguros_ocr,
)


def _is_empty(value) -> bool:
    return not str(value or "").strip()

def _looks_like_compact_date(token: str) -> bool:
    t = str(token or "").strip()
    if not t.isdigit() or len(t) != 8:
        return False
    # YYYYMMDD
    try:
        y = int(t[:4]); m = int(t[4:6]); d = int(t[6:8])
        if 2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
            return True
    except Exception:
        pass
    # DDMMYYYY
    try:
        d = int(t[:2]); m = int(t[2:4]); y = int(t[4:8])
        if 2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
            return True
    except Exception:
        pass
    return False


def _clean_tomador(value: str) -> str:
    raw = str(value or "").replace("\u00a0", " ")
    raw = " ".join(raw.split()).strip(" ,;:-")
    if not raw:
        return ""
    # Corta en tokens donde empieza el ruido OCR.
    upper = normalize_lookup_text(raw)
    for marker in ("DOCUMENTO", "NIF", "DNI", "CIF", "DECLARACION", "DECLARACIÓN", "DATOS DEL MEDIADOR", "MEDIADOR", "DIRECCION", "DIRECCIÓN", "DOMICILIO"):
        idx = upper.find(marker)
        if idx > 0:
            raw = raw[:idx].strip(" ,;:-")
            upper = normalize_lookup_text(raw)
            break
    cleaned = normalize_person_name(raw) or raw
    cleaned = " ".join(str(cleaned).split()).strip(" ,;:-")
    return cleaned


def _is_good_tomador(value: str) -> bool:
    cleaned = _clean_tomador(value)
    if not cleaned:
        return False
    key = normalize_lookup_text(cleaned)
    # Genéricos / etiquetas
    if any(tok in key for tok in ("EL TOMADOR DEL SEGURO", "TOMADOR DEL SEGURO", "DATOS DEL TOMADOR", "ASEGURADORA")):
        return False
    if key in ("EL MISMO", "MISMO", "EL MISMA", "MISMA"):
        return False
    # Direcciones
    if any(tok in f" {key} " for tok in (" CL ", " CALLE ", " AVDA ", " AVD ", " AVENIDA ", " DIRECCION ", " DIRECCIÓN ")):
        return False
    # Muy corto
    parts = [p for p in cleaned.split() if p]
    return len(parts) >= 2


def _is_good_poliza_numero(value: str) -> bool:
    token = normalize_poliza_key(value)
    if not token or len(token) < 6:
        return False
    if _looks_like_compact_date(token):
        return False
    return True


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
                tom = _clean_tomador(fields.get("tomador") or "")
                if _is_good_tomador(tom):
                    patch["tomador"] = tom
            # poliza_numero
            if _is_empty(r.get("poliza_numero")) and str(fields.get("poliza_numero") or "").strip():
                pol = str(fields.get("poliza_numero") or "").strip()
                if _is_good_poliza_numero(pol):
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
