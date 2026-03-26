#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.import_rentas_2024_to_crm import compact_spaces, looks_like_nif, parse_pdf


def likely_matches_client_name(client_name: str, filename: str) -> bool:
    base = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii").upper()
    if any(flag in base for flag in ("RECTIFICATIVA", "COMPLEMENTARIA", "COMPRA VENTA")):
        return True
    tokens = [
        token
        for token in unicodedata.normalize("NFKD", client_name).encode("ascii", "ignore").decode("ascii").upper().replace(",", " ").split()
        if len(token) >= 4
    ]
    matches = sum(1 for token in tokens if token in base)
    return matches > 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Elimina PDFs de renta mal asociados a otro cliente.")
    parser.add_argument("--dry-run", action="store_true", help="Solo informa cambios previstos.")
    args = parser.parse_args()

    db_path = ROOT / "data" / "erp_import2.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 90000")
    removed_entries = 0
    removed_files = 0
    removed_docs = 0
    try:
        rows = conn.execute(
            """
            SELECT cg.id AS cg_id, c.id AS cliente_id, c.nombre, c.nif, cg.renta_detalles
            FROM cliente_gestoria cg
            JOIN clientes c ON c.id = cg.cliente_id
            WHERE COALESCE(cg.mod_renta, 0) = 1
            ORDER BY c.nombre COLLATE NOCASE
            """
        ).fetchall()
        for row in rows:
            client_nif = compact_spaces(row["nif"]).upper()
            payload = json.loads(row["renta_detalles"] or "{}")
            entries = payload.get("entries") or []
            changed = False
            kept_entries = []
            removed_basenames: set[str] = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                files = entry.get("source_files") or []
                kept_files = []
                for raw_file in files:
                    basename = os.path.basename(raw_file)
                    if likely_matches_client_name(str(row["nombre"] or ""), basename):
                        kept_files.append(raw_file)
                        continue
                    parsed = parse_pdf(Path(raw_file))
                    parsed_nif = compact_spaces(parsed.get("cliente_nif")).upper()
                    if looks_like_nif(parsed_nif) and looks_like_nif(client_nif) and parsed_nif != client_nif:
                        removed_files += 1
                        removed_basenames.add(basename)
                        changed = True
                        continue
                    kept_files.append(raw_file)
                if not kept_files:
                    removed_entries += 1
                    changed = True
                    continue
                if kept_files != files:
                    entry["source_files"] = kept_files
                    entry["source_file_count"] = len(kept_files)
                    notas = entry.get("notas_ocr") or {}
                    if isinstance(notas, dict):
                        notas["source_files"] = kept_files
                        entry["notas_ocr"] = notas
                kept_entries.append(entry)
            if changed:
                payload["entries"] = kept_entries
                print(f"{row['nombre']}\tremoved_files={removed_files}\tremoved_entries={removed_entries}\tbasenames={sorted(removed_basenames)}")
                if not args.dry_run:
                    conn.execute(
                        "UPDATE cliente_gestoria SET renta_detalles = ?, updated_at = datetime('now') WHERE id = ?",
                        (json.dumps(payload, ensure_ascii=False), row["cg_id"]),
                    )
                    docs = conn.execute(
                        "SELECT id, notas FROM gestoria_docs WHERE cliente_id = ?",
                        (row["cliente_id"],),
                    ).fetchall()
                    delete_ids = []
                    for doc in docs:
                        notas = str(doc["notas"] or "")
                        if "origen:" not in notas:
                            continue
                        basename = os.path.basename(notas.split("origen:")[-1].strip())
                        if basename in removed_basenames:
                            delete_ids.append((doc["id"],))
                    if delete_ids:
                        conn.executemany("DELETE FROM gestoria_docs WHERE id = ?", delete_ids)
                        removed_docs += len(delete_ids)
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    print(f"removed_entries={removed_entries}")
    print(f"removed_files={removed_files}")
    print(f"removed_docs={removed_docs}")


if __name__ == "__main__":
    main()
