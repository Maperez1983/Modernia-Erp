#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.import_rentas_2024_to_crm import get_pdf_text, parse_modelo_100_text

VALID_ESTADO_TOKENS = ("soltero", "casado", "divorciado", "separado", "viudo")
VALID_COMMUNITIES = {
    "ANDALUCIA",
    "ARAGON",
    "ASTURIAS",
    "ILLES BALEARS",
    "BALEARES",
    "CANARIAS",
    "CANTABRIA",
    "CASTILLA-LA MANCHA",
    "CASTILLA Y LEON",
    "CATALUNA",
    "CATALUNYA",
    "COMUNITAT VALENCIANA",
    "EXTREMADURA",
    "GALICIA",
    "LA RIOJA",
    "MADRID",
    "MURCIA",
    "NAVARRA",
    "PAIS VASCO",
}


def needs_metadata_review(entry: dict) -> bool:
    notas = entry.get("notas_ocr") or {}
    patrimonio = entry.get("patrimonio") or {}
    comunidad = ""
    if isinstance(notas, dict):
        comunidad = str(notas.get("comunidad_autonoma") or "").strip()
    ref_cat = ""
    if isinstance(patrimonio, dict):
        ref_cat = str(patrimonio.get("referencia_catastral_principal") or "").strip()
    return (
        not str(entry.get("estado_civil") or "").strip()
        or not comunidad
        or (not str(entry.get("direccion") or "").strip() and not str((patrimonio.get("direccion_inmueble_principal") if isinstance(patrimonio, dict) else "") or "").strip())
        or (ref_cat and not re.fullmatch(r"[A-Z0-9]{14,20}", ref_cat))
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Reprocesa metadatos de renta faltantes o corruptos.")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra cambios previstos.")
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
            for entry in payload.get("entries") or []:
                if not isinstance(entry, dict) or not needs_metadata_review(entry):
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
                before = {
                    "estado_civil": entry.get("estado_civil"),
                    "comunidad_autonoma": (entry.get("notas_ocr") or {}).get("comunidad_autonoma"),
                    "referencia_catastral_principal": (entry.get("patrimonio") or {}).get("referencia_catastral_principal"),
                }
                notas = entry.get("notas_ocr") or {}
                patrimonio = entry.get("patrimonio") or {}

                estado = str(parsed.get("cliente_estado_civil") or "").strip()
                if estado and any(token in estado.lower() for token in VALID_ESTADO_TOKENS) and not str(entry.get("estado_civil") or "").strip():
                    entry["estado_civil"] = estado
                    if isinstance(notas, dict):
                        notas["cliente_estado_civil"] = estado
                    changed = True
                comunidad = parsed.get("comunidad_autonoma")
                if comunidade := str(comunidad or "").strip():
                    normalized = comunidade.upper()
                    if normalized in VALID_COMMUNITIES and isinstance(notas, dict) and not str(notas.get("comunidad_autonoma") or "").strip():
                        notas["comunidad_autonoma"] = comunidade
                        changed = True
                ref_cat = parsed.get("referencia_catastral_principal")
                if ref_cat and re.fullmatch(r"[A-Z0-9]{14,20}", str(ref_cat)):
                    if not isinstance(patrimonio, dict):
                        patrimonio = {}
                    current_ref = str(patrimonio.get("referencia_catastral_principal") or "").strip()
                    if current_ref != ref_cat:
                        patrimonio["referencia_catastral_principal"] = ref_cat
                        changed = True
                if changed:
                    if isinstance(notas, dict) and not str(notas.get("comunidad_autonoma") or "").strip():
                        entry["notas_ocr"] = notas
                    entry["patrimonio"] = patrimonio
                    after = {
                        "estado_civil": entry.get("estado_civil"),
                        "comunidad_autonoma": (entry.get("notas_ocr") or {}).get("comunidad_autonoma"),
                        "referencia_catastral_principal": (entry.get("patrimonio") or {}).get("referencia_catastral_principal"),
                    }
                    print(f"{row['nombre']}\t{before}\t=>\t{after}")
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
