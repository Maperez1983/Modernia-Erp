#!/usr/bin/env python3
"""
Limpia ramos inválidos en Postgres (p.ej. cuando se han colado nombres de archivo).

- Si `seguros.ramo` no está en el catálogo canónico LEGAL_RAMOS_CANONICAL, lo deja vacío.
- No toca ramos válidos.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.db_backend import open_postgres_conn  # noqa: E402
from web.server import LEGAL_RAMOS_CANONICAL, normalize_lookup_text  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Limpia ramos inválidos en tabla seguros (Postgres).")
    ap.add_argument("--empresa-id", required=True, help="ID empresa (UUID) en Postgres.")
    ap.add_argument("--apply", action="store_true", help="Aplica cambios (por defecto dry-run).")
    args = ap.parse_args()

    empresa_id = str(args.empresa_id or "").strip()
    if not empresa_id:
        raise SystemExit("empresa-id requerido")

    now = datetime.now(timezone.utc).isoformat()
    canonical = {normalize_lookup_text(item) for item in LEGAL_RAMOS_CANONICAL}

    conn = open_postgres_conn(with_row_factory=True)
    rows = conn.execute(
        """
        SELECT id, COALESCE(ramo,'') AS ramo
        FROM seguros
        WHERE empresa_id = %s
          AND COALESCE(TRIM(ramo), '') <> ''
        """,
        (empresa_id,),
    ).fetchall()

    bad = []
    for r in rows:
        ramo = str(r.get("ramo") or "").strip()
        if normalize_lookup_text(ramo) not in canonical:
            bad.append((now, r.get("id"), ramo))

    print(f"[{now}] empresa_id={empresa_id} scanned={len(rows)} invalid={len(bad)} dry_run={not args.apply}")
    for _now, rid, ramo in bad[:30]:
        print(f"- {rid}: {ramo!r}")

    if args.apply and bad:
        conn.executemany(
            "UPDATE seguros SET ramo=%s, updated_at=%s WHERE id=%s",
            [("", now, rid) for _now, rid, _ramo in bad],
        )
        conn.commit()
        print("Cambios aplicados.")
    elif not args.apply:
        print("Dry-run: no se aplicaron cambios.")


if __name__ == "__main__":
    main()

