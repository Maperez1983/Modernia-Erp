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
    compact_spaces,
    get_pdf_text,
    looks_like_nif,
    parse_modelo_100_text,
)


def iter_tables_with_cliente_id(conn: sqlite3.Connection) -> list[str]:
    tables: list[str] = []
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if name.startswith("sqlite_") or name == "clientes":
            continue
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({name})")}
        if "cliente_id" in cols:
            tables.append(name)
    return tables


def merge_client(conn: sqlite3.Connection, source_id: str, target_id: str) -> list[str]:
    touched: list[str] = []
    for table in iter_tables_with_cliente_id(conn):
        cur = conn.execute(f"UPDATE {table} SET cliente_id = ? WHERE cliente_id = ?", (target_id, source_id))
        if cur.rowcount:
            touched.append(f"{table}:{cur.rowcount}")
    conn.execute("DELETE FROM clientes WHERE id = ?", (source_id,))
    return touched


def main() -> None:
    parser = argparse.ArgumentParser(description="Corrige NIF/identidad defectuosos en renta.")
    parser.add_argument("--dry-run", action="store_true", help="Solo informa cambios previstos.")
    args = parser.parse_args()

    db_path = ROOT / "data" / "erp_import2.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 90000")
    fixed = 0
    merged = 0
    try:
        rows = conn.execute(
            """
            SELECT c.id AS cliente_id, c.nombre, c.nif, cg.id AS cg_id, cg.renta_detalles
            FROM cliente_gestoria cg
            JOIN clientes c ON c.id = cg.cliente_id
            WHERE COALESCE(cg.mod_renta, 0) = 1
            ORDER BY c.nombre COLLATE NOCASE
            """
        ).fetchall()
        for row in rows:
            payload = json.loads(row["renta_detalles"] or "{}")
            entries = payload.get("entries") or []
            if not entries:
                continue
            entry = entries[0]
            current_nif = compact_spaces(entry.get("cliente_nif")).upper()
            client_nif = compact_spaces(row["nif"]).upper()
            if looks_like_nif(current_nif) and looks_like_nif(client_nif):
                continue
            if looks_like_nif(current_nif) and not looks_like_nif(client_nif):
                parsed_nif = current_nif
                parsed_name = compact_spaces(entry.get("cliente_nombre"))
                print(f"fix\t{row['nombre']}\t{row['nif']}\t{parsed_nif}\t{parsed_name}")
                if not args.dry_run:
                    conn.execute(
                        "UPDATE clientes SET nif = ?, nombre = COALESCE(NULLIF(?, ''), nombre), updated_at = datetime('now') WHERE id = ?",
                        (parsed_nif, parsed_name, row["cliente_id"]),
                    )
                fixed += 1
                continue
            source_files = entry.get("source_files") or []
            if not source_files:
                continue
            text, _ = get_pdf_text(Path(source_files[0]))
            parsed = parse_modelo_100_text(text)
            parsed_nif = compact_spaces(parsed.get("cliente_nif")).upper()
            parsed_name = compact_spaces(parsed.get("cliente_nombre"))
            if not looks_like_nif(parsed_nif):
                continue

            target = conn.execute(
                "SELECT id, nombre, nif FROM clientes WHERE UPPER(COALESCE(nif,'')) = ? AND id <> ? LIMIT 1",
                (parsed_nif, row["cliente_id"]),
            ).fetchone()
            if target:
                print(f"merge\t{row['nombre']}\t{row['nif']}\t{parsed_nif}\t{target['nombre']}")
                if not args.dry_run:
                    merge_client(conn, row["cliente_id"], target["id"])
                    target_row = conn.execute(
                        "SELECT id, renta_detalles FROM cliente_gestoria WHERE cliente_id = ? LIMIT 1",
                        (target["id"],),
                    ).fetchone()
                    if target_row:
                        target_payload = json.loads(target_row["renta_detalles"] or "{}")
                        for target_entry in target_payload.get("entries") or []:
                            if not isinstance(target_entry, dict):
                                continue
                            target_entry["cliente_nif"] = parsed_nif
                            if parsed_name:
                                target_entry["cliente_nombre"] = parsed_name
                            notas = target_entry.get("notas_ocr") or {}
                            if isinstance(notas, dict):
                                notas["cliente_nif"] = parsed_nif
                                if parsed_name:
                                    notas["cliente_nombre"] = parsed_name
                                target_entry["notas_ocr"] = notas
                        conn.execute(
                            "UPDATE cliente_gestoria SET renta_detalles = ?, updated_at = datetime('now') WHERE id = ?",
                            (json.dumps(target_payload, ensure_ascii=False), target_row["id"]),
                        )
                    if parsed_name:
                        conn.execute(
                            "UPDATE clientes SET nombre = ?, updated_at = datetime('now') WHERE id = ?",
                            (parsed_name, target["id"]),
                        )
                merged += 1
                continue

            entry["cliente_nif"] = parsed_nif
            if parsed_name:
                entry["cliente_nombre"] = parsed_name
            notas = entry.get("notas_ocr") or {}
            if isinstance(notas, dict):
                notas["cliente_nif"] = parsed_nif
                if parsed_name:
                    notas["cliente_nombre"] = parsed_name
                entry["notas_ocr"] = notas
            print(f"fix\t{row['nombre']}\t{row['nif']}\t{parsed_nif}\t{parsed_name}")
            if not args.dry_run:
                conn.execute(
                    "UPDATE cliente_gestoria SET renta_detalles = ?, updated_at = datetime('now') WHERE id = ?",
                    (json.dumps(payload, ensure_ascii=False), row["cg_id"]),
                )
                conn.execute(
                    "UPDATE clientes SET nif = ?, nombre = COALESCE(NULLIF(?, ''), nombre), updated_at = datetime('now') WHERE id = ?",
                    (parsed_nif, parsed_name, row["cliente_id"]),
                )
            fixed += 1
        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    print(f"fixed={fixed}")
    print(f"merged={merged}")


if __name__ == "__main__":
    main()
