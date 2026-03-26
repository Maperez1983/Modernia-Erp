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

from scripts.import_rentas_2024_to_crm import finalize_record

SCORE_FIELDS = ["confidence_score", "critical_missing", "review_flags", "safe_to_apply", "review_status", "source_types", "source_file_count"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Recalcula score y flags de renta desde datos ya estructurados.")
    parser.add_argument("--dry-run", action="store_true", help="Solo informa cambios previstos.")
    args = parser.parse_args()

    db_path = ROOT / "data" / "erp_import2.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    updated = 0
    checked = 0
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
            for entry in payload.get("entries") or []:
                if not isinstance(entry, dict):
                    continue
                checked += 1
                source = entry.get("notas_ocr") if isinstance(entry.get("notas_ocr"), dict) else dict(entry)
                if not isinstance(source, dict):
                    source = dict(entry)
                source.setdefault("source_files", entry.get("source_files") or [])
                source.setdefault("source_types", source.get("source_types") or ["modelo_100"])
                source.setdefault("cliente_nombre", entry.get("cliente_nombre"))
                source.setdefault("cliente_nif", entry.get("cliente_nif"))
                source.setdefault("cliente_fecha_nacimiento", entry.get("cliente_fecha_nacimiento"))
                source.setdefault("cliente_estado_civil", entry.get("estado_civil"))
                source.setdefault("presentacion_fecha", entry.get("presentacion_fecha"))
                rebuilt = finalize_record(source)
                before = {field: entry.get(field) for field in SCORE_FIELDS}
                after = {field: rebuilt.get(field) for field in SCORE_FIELDS}
                if before == after:
                    continue
                print(f"{row['nombre']}\t{before['confidence_score']}->{after['confidence_score']}\t{before['review_status']}->{after['review_status']}")
                if not args.dry_run:
                    for field in SCORE_FIELDS:
                        entry[field] = rebuilt.get(field)
                    notas = entry.get("notas_ocr") or {}
                    if isinstance(notas, dict):
                        for field in SCORE_FIELDS:
                            notas[field] = rebuilt.get(field)
                        entry["notas_ocr"] = notas
                    changed = True
            if changed and not args.dry_run:
                conn.execute(
                    "UPDATE cliente_gestoria SET renta_detalles = ?, updated_at = datetime('now') WHERE id = ?",
                    (json.dumps(payload, ensure_ascii=False), row["cg_id"]),
                )
                updated += 1
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()
    print(f"checked={checked}")
    print(f"updated={updated}")


if __name__ == "__main__":
    main()
