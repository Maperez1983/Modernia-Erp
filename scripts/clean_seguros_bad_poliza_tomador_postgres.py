#!/usr/bin/env python3
"""
Limpia valores basura introducidos por OCR en producción:
- `seguros.tomador` tipo "El Tomador del Seguro", "El mismo..." o que parezca dirección.
- `seguros.poliza_numero` que sea una fecha compacta (8 dígitos tipo 20260505 / 17012025).

Seguro: solo toca filas donde el valor actual es claramente inválido.
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
from web.server import normalize_lookup_text  # noqa: E402


def looks_like_compact_date(token: str) -> bool:
    t = str(token or "").strip()
    if not t.isdigit() or len(t) != 8:
        return False
    try:
        y = int(t[:4]); m = int(t[4:6]); d = int(t[6:8])
        if 2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
            return True
    except Exception:
        pass
    try:
        d = int(t[:2]); m = int(t[2:4]); y = int(t[4:8])
        if 2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
            return True
    except Exception:
        pass
    return False


def bad_tomador(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    key = normalize_lookup_text(raw)
    if any(tok in key for tok in ("EL TOMADOR DEL SEGURO", "TOMADOR DEL SEGURO", "DATOS DEL TOMADOR", "ASEGURADORA")):
        return True
    if key.startswith("EL MISMO") or key.startswith("EL MISMA") or key in ("EL MISMO", "MISMO", "MISMA"):
        return True
    if any(tok in f" {key} " for tok in (" CL ", " CALLE ", " AVDA ", " AVD ", " AVENIDA ", " DIRECCION ", " DIRECCIÓN ")):
        if re.search(r"\\d", raw):
            return True
    # Frases largas que claramente no son nombre
    if len(raw) > 80 and any(tok in key for tok in ("DECLARACION", "DECLARACIÓN", "MEDIADOR", "PROVINCIA", "FECHA NACIMIENTO")):
        return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Limpia tomador/póliza inválidos en Postgres.")
    ap.add_argument("--empresa-id", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    empresa_id = str(args.empresa_id or "").strip()
    now = datetime.now(timezone.utc).isoformat()
    conn = open_postgres_conn(with_row_factory=True)

    rows = conn.execute(
        """
        SELECT id, COALESCE(tomador,'') AS tomador, COALESCE(poliza_numero,'') AS poliza_numero
        FROM seguros
        WHERE empresa_id = %s
        """,
        (empresa_id,),
    ).fetchall()

    updates = []
    for r in rows:
        tom = str(r.get("tomador") or "").strip()
        pol = str(r.get("poliza_numero") or "").strip()
        new_tom = "" if bad_tomador(tom) else tom
        new_pol = "" if looks_like_compact_date(pol) else pol
        if new_tom != tom or new_pol != pol:
            updates.append((new_tom, new_pol, now, r.get("id")))

    print(f"[{now}] empresa_id={empresa_id} scanned={len(rows)} to_update={len(updates)} dry_run={not args.apply}")
    for tom, pol, _now, rid in updates[:25]:
        print(f"- {rid}: tomador={tom!r} poliza={pol!r}")

    if args.apply and updates:
        conn.executemany(
            "UPDATE seguros SET tomador=%s, poliza_numero=%s, updated_at=%s WHERE id=%s",
            updates,
        )
        conn.commit()
        print("Cambios aplicados.")
    elif not args.apply:
        print("Dry-run: no se aplicaron cambios.")


if __name__ == "__main__":
    main()

