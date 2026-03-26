#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.import_rentas_2024_to_crm import get_pdf_text, parse_modelo_100_text


def resolve_source_path(raw: str) -> Path:
    path = Path(raw)
    if path.exists():
        return path
    legacy_prefix = "/Users/miguelperezrodriguez/"
    current_prefix = "/Volumes/Mac Satecchi/Mac/"
    if raw.startswith(legacy_prefix):
        alt = Path(raw.replace(legacy_prefix, current_prefix, 1))
        if alt.exists():
            return alt
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Rellena fechas de presentación de renta desde PDFs individuales.")
    parser.add_argument("--dry-run", action="store_true", help="Solo analiza y reporta, sin escribir en SQLite.")
    args = parser.parse_args()
    db_path = ROOT / "data" / "erp_import2.sqlite"
    conn = sqlite3.connect(str(db_path), timeout=90)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 90000")
    try:
        rows = conn.execute(
            """
            SELECT cg.id AS cg_id, c.nombre, c.nif, cg.renta_detalles
            FROM cliente_gestoria cg
            JOIN clientes c ON c.id = cg.cliente_id
            WHERE cg.mod_renta = 1
            ORDER BY c.nombre COLLATE NOCASE
            """
        ).fetchall()
        checked = 0
        updated_records = 0
        recovered_entries: list[tuple[str, str, str, str]] = []
        for row in rows:
            payload = json.loads(row["renta_detalles"] or "{}")
            changed = False
            entries = payload.get("entries") or []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("presentacion_fecha") or "").strip():
                    continue
                source_files = entry.get("source_files") or []
                if len(source_files) != 1:
                    continue
                path = resolve_source_path(str(source_files[0]))
                if not path.exists():
                    continue
                checked += 1
                text, _ = get_pdf_text(path)
                parsed = parse_modelo_100_text(text)
                fecha = str(parsed.get("presentacion_fecha") or "").strip()
                if not fecha:
                    continue
                entry["presentacion_fecha"] = fecha
                changed = True
                recovered_entries.append(
                    (
                        str(row["nombre"] or ""),
                        str(row["nif"] or ""),
                        fecha,
                        path.name,
                    )
                )
            if changed:
                if not args.dry_run:
                    conn.execute(
                        "UPDATE cliente_gestoria SET renta_detalles = ?, updated_at = datetime('now') WHERE id = ?",
                        (json.dumps(payload, ensure_ascii=False), row["cg_id"]),
                    )
                updated_records += 1
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    print(f"checked={checked}")
    print(f"updated_records={updated_records}")
    print(f"recovered_entries={len(recovered_entries)}")
    for nombre, nif, fecha, filename in recovered_entries[:50]:
        print(f"{nombre}\t{nif}\t{fecha}\t{filename}")


if __name__ == "__main__":
    main()
