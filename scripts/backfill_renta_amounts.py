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

FIELDS = [
    "rendimientos_trabajo_total",
    "rendimientos_actividades_economicas_total",
    "rendimientos_capital_inmobiliario_total",
    "rendimientos_capital_mobiliario_total",
    "base_imponible_general",
    "base_liquidable_general",
    "casilla_505",
    "resultado_declaracion",
    "ingresos_principales_total",
]


def needs_amount_review(entry: dict) -> bool:
    ingresos = entry.get("ingresos_principales_total")
    casilla_505 = entry.get("casilla_505")
    if isinstance(ingresos, (int, float)) and isinstance(casilla_505, (int, float)) and ingresos > 0:
        return casilla_505 > ingresos * 5
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Reprocesa importes de renta sospechosos desde PDFs origen.")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra cambios previstos.")
    args = parser.parse_args()

    db_path = ROOT / "data" / "erp_import2.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 90000")
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
                if not isinstance(entry, dict) or not needs_amount_review(entry):
                    continue
                source_files = entry.get("source_files") or []
                if not source_files:
                    continue
                checked += 1
                text_parts = []
                for raw_path in source_files:
                    text, _ = get_pdf_text(Path(raw_path))
                    if text:
                        text_parts.append(text)
                if not text_parts:
                    continue
                parsed = parse_modelo_100_text("\n\n".join(text_parts))
                before = {field: entry.get(field) for field in FIELDS}
                after = {field: parsed.get(field) for field in FIELDS}
                if before == after:
                    continue
                print(
                    f"{row['nombre']}\t"
                    f"ingresos:{before['ingresos_principales_total']}->{after['ingresos_principales_total']}\t"
                    f"trabajo:{before['rendimientos_trabajo_total']}->{after['rendimientos_trabajo_total']}\t"
                    f"actividad:{before['rendimientos_actividades_economicas_total']}->{after['rendimientos_actividades_economicas_total']}\t"
                    f"cap_inm:{before['rendimientos_capital_inmobiliario_total']}->{after['rendimientos_capital_inmobiliario_total']}"
                )
                if not args.dry_run:
                    for field in FIELDS:
                        if field in parsed:
                            entry[field] = parsed.get(field)
                    notas = entry.get("notas_ocr") or {}
                    if isinstance(notas, dict):
                        for field in FIELDS:
                            if field in parsed:
                                notas[field] = parsed.get(field)
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
