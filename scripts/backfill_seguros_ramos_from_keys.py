#!/usr/bin/env python3
"""
Backfill de ramos (catálogo canónico) a partir del nombre de archivo (poliza_key / poliza_url).

Objetivo: reducir "Sin ramo" sin re-OCR completo, usando heurísticas estables basadas en el filename.
No inventa ramos nuevos: solo asigna valores dentro de LEGAL_RAMOS_CANONICAL.
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

from web.db_backend import open_postgres_conn  # noqa: E402
from web.server import infer_ramo_from_source_hint  # noqa: E402


def filename_from_poliza(poliza_key: str, poliza_url: str) -> str:
    key = str(poliza_key or "").strip()
    url = str(poliza_url or "").strip()
    if key:
        return os.path.basename(key)
    if url:
        # https://bucket.s3.region.amazonaws.com/<key>
        tail = url.split("?", 1)[0].rstrip("/")
        return os.path.basename(tail)
    return ""


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill de ramos (Seguros) desde poliza_key/poliza_url.")
    ap.add_argument("--empresa-id", required=True, help="ID empresa (UUID) en Postgres.")
    ap.add_argument("--limit", type=int, default=0, help="Límite de filas (0 = sin límite).")
    ap.add_argument("--apply", action="store_true", help="Aplica cambios (por defecto dry-run).")
    ap.add_argument(
        "--only-empty",
        action="store_true",
        help="Solo actualizar si ramo está vacío/NULL (recomendado).",
    )
    args = ap.parse_args()

    empresa_id = str(args.empresa_id or "").strip()
    if not empresa_id:
        raise SystemExit("empresa-id requerido")

    limit = int(args.limit or 0)
    now = datetime.now(timezone.utc).isoformat()

    conn = open_postgres_conn(with_row_factory=True)
    where = ["empresa_id = %s"]
    params = [empresa_id]
    if args.only_empty:
        where.append("(COALESCE(TRIM(ramo), '') = '')")
    where.append("(COALESCE(TRIM(poliza_key), '') <> '' OR COALESCE(TRIM(poliza_url), '') <> '')")
    limit_sql = f"LIMIT {limit}" if limit and limit > 0 else ""
    rows = conn.execute(
        f"""
        SELECT id, COALESCE(ramo,'') AS ramo, COALESCE(poliza_key,'') AS poliza_key, COALESCE(poliza_url,'') AS poliza_url
        FROM seguros
        WHERE {' AND '.join(where)}
        ORDER BY created_at ASC NULLS LAST
        {limit_sql}
        """,
        tuple(params),
    ).fetchall()

    updates = []
    scanned = 0
    guessed = 0
    for row in rows:
        scanned += 1
        current = str(row.get("ramo") or "").strip()
        hint = filename_from_poliza(row.get("poliza_key"), row.get("poliza_url"))
        if not hint:
            continue
        new_ramo = infer_ramo_from_source_hint(hint)
        if not new_ramo:
            continue
        guessed += 1
        if current == new_ramo:
            continue
        # Si no only_empty, evitamos pisar ramos ya "buenos" salvo que sean vacíos.
        if (not args.only_empty) and current:
            continue
        updates.append((new_ramo, now, row.get("id")))

    print(
        f"[{now}] empresa_id={empresa_id} scanned={scanned} candidates={len(rows)} guessed={guessed} updates={len(updates)} dry_run={not args.apply}"
    )
    if updates:
        print("muestras:")
        for ramo, _now, rid in updates[:20]:
            print(f"- {rid}: {ramo}")

    if args.apply and updates:
        conn.executemany(
            "UPDATE seguros SET ramo=%s, updated_at=%s WHERE id=%s",
            updates,
        )
        conn.commit()
        print("Cambios aplicados.")
    elif not args.apply:
        print("Dry-run: no se aplicaron cambios.")


if __name__ == "__main__":
    main()

