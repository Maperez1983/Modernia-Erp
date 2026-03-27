#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.import_rentas_2024_to_crm import (
    DEFAULT_EJERCICIO,
    detect_renta_doc_status,
    extract_dni_metadata_from_sources,
)


def backfill(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    updated_rows = 0
    updated_entries = 0
    now = datetime.now(timezone.utc).isoformat()
    try:
        rows = conn.execute(
            """
            SELECT cliente_id, renta_detalles
            FROM cliente_gestoria
            WHERE mod_renta = 1
              AND renta_detalles IS NOT NULL
              AND TRIM(renta_detalles) != ''
            """
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["renta_detalles"])
            except Exception:
                continue
            entries = payload.get("entries")
            if not isinstance(entries, list):
                continue
            changed = False
            next_entries = []
            for entry in entries:
                if not isinstance(entry, dict):
                    next_entries.append(entry)
                    continue
                current = dict(entry)
                source_files = current.get("source_files") or []
                dni_meta = extract_dni_metadata_from_sources(source_files)
                before = json.dumps(current, ensure_ascii=False, sort_keys=True)
                if not str(current.get("ejercicio") or "").strip():
                    current["ejercicio"] = DEFAULT_EJERCICIO
                current["estado_presentacion"] = detect_renta_doc_status(
                    current.get("estado_presentacion") or current.get("doc_status") or "Presentada"
                )
                current["doc_status"] = current["estado_presentacion"]
                if not str(current.get("dni_expedicion") or "").strip():
                    current["dni_expedicion"] = dni_meta.get("dni_expedicion") or ""
                if not str(current.get("dni_caducidad") or "").strip():
                    current["dni_caducidad"] = dni_meta.get("dni_caducidad") or ""
                if current.get("dni_permanente") in (None, "", 0, "0", False):
                    current["dni_permanente"] = 1 if dni_meta.get("dni_permanente") else 0
                after = json.dumps(current, ensure_ascii=False, sort_keys=True)
                if after != before:
                    changed = True
                    updated_entries += 1
                next_entries.append(current)
            if not changed:
                continue
            payload["entries"] = next_entries
            conn.execute(
                """
                UPDATE cliente_gestoria
                SET renta_detalles = ?, updated_at = datetime(?)
                WHERE cliente_id = ?
                """,
                (json.dumps(payload, ensure_ascii=False), now, row["cliente_id"]),
            )
            updated_rows += 1
        conn.commit()
        return {
            "updated_rows": updated_rows,
            "updated_entries": updated_entries,
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill de metadata de campañas de renta ya importadas.")
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta a la SQLite del CRM.")
    args = parser.parse_args()
    result = backfill(Path(args.db).expanduser())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
