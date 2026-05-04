#!/usr/bin/env python3
"""
Limpia `seguros.tomador` en Postgres cuando se ha colado ruido OCR (NIF/DNI/Declaración/mediador/direcciones).

No requiere S3; solo DB. Reescribe tomador aplicando un recorte por tokens.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.db_backend import open_postgres_conn  # noqa: E402
from web.server import normalize_lookup_text, normalize_person_name  # noqa: E402


STOP_RE = re.compile(
    r"\b(DOCUMENTO|DOC\.?|NIF|DNI|CIF|DECLARACION|DECLARACIÓN|FECHA|PROVINCIA|"
    r"DATOS\s+DEL\s+MEDIADOR|MEDIADOR|DIRECCION|DIRECCIÓN|DOMICILIO|"
    r"MATRICULA|MATRÍCULA|VEHICULO|VEHÍCULO)\b",
    re.IGNORECASE,
)


def clean(value: str) -> str:
    raw = str(value or "").replace("\u00a0", " ")
    raw = re.sub(r"\s+", " ", raw).strip(" ,;:-\n\r\t")
    if not raw:
        return ""
    m = STOP_RE.search(raw)
    if m:
        raw = raw[: m.start()].strip(" ,;:-")
    raw = normalize_person_name(raw) or raw
    raw = re.sub(r"\s+", " ", raw).strip(" ,;:-")
    key = normalize_lookup_text(raw)
    if not raw or key in ("TOMADOR", "ASEGURADO", "ASEGURADORA", "EL MISMO", "MISMO"):
        return ""
    # Evita direcciones simples
    if re.search(r"(^|\s)(CL|CALLE|AVDA|AVD|AVENIDA|PASEO|PLAZA|URB|URBANIZACION)\b", key) and re.search(r"\d", raw):
        return ""
    return raw


def main() -> None:
    ap = argparse.ArgumentParser(description="Limpia tomadores con ruido OCR en Postgres.")
    ap.add_argument("--empresa-id", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    empresa_id = str(args.empresa_id or "").strip()
    now = datetime.now(timezone.utc).isoformat()

    conn = open_postgres_conn(with_row_factory=True)
    rows = conn.execute(
        """
        SELECT id, COALESCE(tomador,'') AS tomador
        FROM seguros
        WHERE empresa_id = %s
          AND COALESCE(TRIM(tomador), '') <> ''
        """,
        (empresa_id,),
    ).fetchall()

    updates = []
    for r in rows:
        cur = str(r.get("tomador") or "").strip()
        new = clean(cur)
        if new != cur:
            updates.append((new, now, r.get("id")))

    print(f"[{now}] empresa_id={empresa_id} scanned={len(rows)} to_update={len(updates)} dry_run={not args.apply}")
    for new, _now, rid in updates[:20]:
        print(f"- {rid}: {new!r}")
    if args.apply and updates:
        conn.executemany("UPDATE seguros SET tomador=%s, updated_at=%s WHERE id=%s", updates)
        conn.commit()
        print("Cambios aplicados.")
    elif not args.apply:
        print("Dry-run: no se aplicaron cambios.")


if __name__ == "__main__":
    main()

