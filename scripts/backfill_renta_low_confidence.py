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

from scripts.import_rentas_2024_to_crm import (
    build_renta_entry,
    finalize_record,
    merge_record,
    parse_pdf,
)


def should_refresh(entry: dict) -> bool:
    score = entry.get("confidence_score")
    notas = entry.get("notas_ocr") or {}
    comunidad = ""
    if isinstance(notas, dict):
        comunidad = str(notas.get("comunidad_autonoma") or "").strip()
    return (
        (isinstance(score, (int, float)) and score < 85)
        or not str(entry.get("estado_civil") or "").strip()
        or not comunidad
    )


def rebuild_from_sources(source_files: list[str]) -> dict | None:
    record: dict = {}
    for raw_file in source_files or []:
        pdf_path = Path(raw_file)
        if not pdf_path.exists():
            continue
        fields = parse_pdf(pdf_path)
        merge_record(record, fields, pdf_path)
    if not record:
        return None
    return finalize_record(record)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reprocesa expedientes de renta low confidence con el parser actual.")
    parser.add_argument("--dry-run", action="store_true", help="Solo informa cambios previstos.")
    parser.add_argument("--limit", type=int, default=0, help="Limita el número de entries refrescadas.")
    args = parser.parse_args()

    db_path = ROOT / "data" / "erp_import2.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 90000")
    checked = 0
    updated = 0
    try:
        rows = conn.execute(
            """
            SELECT cg.id AS cg_id, c.nombre, cg.renta_detalles
            FROM cliente_gestoria cg
            JOIN clientes c ON c.id = cg.cliente_id
            WHERE COALESCE(cg.mod_renta, 0) = 1
            ORDER BY c.nombre COLLATE NOCASE
            """
        ).fetchall()
        for row in rows:
            payload = json.loads(row["renta_detalles"] or "{}")
            changed = False
            entries = payload.get("entries") or []
            for idx, entry in enumerate(entries):
                if not isinstance(entry, dict) or not should_refresh(entry):
                    continue
                if args.limit and checked >= args.limit:
                    break
                source_files = entry.get("source_files") or []
                if not source_files:
                    continue
                checked += 1
                rebuilt = rebuild_from_sources(source_files)
                if not rebuilt:
                    continue
                new_entry = build_renta_entry(rebuilt)
                if new_entry == entry:
                    continue
                print(
                    f"{row['nombre']}\t"
                    f"score:{entry.get('confidence_score')}->{new_entry.get('confidence_score')}\t"
                    f"estado:{entry.get('estado_civil')}->{new_entry.get('estado_civil')}\t"
                    f"ingresos:{entry.get('ingresos_principales_total')}->{new_entry.get('ingresos_principales_total')}"
                )
                if not args.dry_run:
                    entries[idx] = new_entry
                    changed = True
            if changed and not args.dry_run:
                conn.execute(
                    "UPDATE cliente_gestoria SET renta_detalles = ?, updated_at = datetime('now') WHERE id = ?",
                    (json.dumps(payload, ensure_ascii=False), row["cg_id"]),
                )
                updated += 1
            if args.limit and checked >= args.limit:
                break
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    print(f"checked={checked}")
    print(f"updated={updated}")


if __name__ == "__main__":
    main()
