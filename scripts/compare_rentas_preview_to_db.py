#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


def compact_spaces(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def norm(value: object) -> str:
    text = compact_spaces(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.strip().upper()

def looks_like_nif(value: object) -> bool:
    text = norm(value).replace(" ", "").replace(".", "").replace("-", "")
    if not re.fullmatch(r"[A-Z0-9]{8,10}", text):
        return False
    if not any(ch.isdigit() for ch in text):
        return False
    if text in {"DECLARANTE", "CONYUGE", "NOMBRE"}:
        return False
    return True


@dataclass(frozen=True)
class RentaKey:
    ejercicio: str
    nif: str


def load_preview(preview_json: Path, default_ejercicio: str = "") -> dict[RentaKey, dict]:
    data = json.loads(preview_json.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"Preview JSON inválido (no es lista): {preview_json}")
    out: dict[RentaKey, dict] = {}
    for rec in data:
        if not isinstance(rec, dict):
            continue
        ejercicio = compact_spaces(rec.get("ejercicio")) or compact_spaces(default_ejercicio)
        nif = norm(rec.get("cliente_nif"))
        if not ejercicio or not nif or not looks_like_nif(nif):
            continue
        out[RentaKey(ejercicio=ejercicio, nif=nif)] = rec
    return out


def parse_renta_entries(payload_raw: object) -> list[dict]:
    if payload_raw in (None, ""):
        return []
    try:
        payload = json.loads(payload_raw)
    except Exception:
        return []
    if isinstance(payload, dict):
        entries = payload.get("entries") or []
    elif isinstance(payload, list):
        entries = payload
    else:
        return []
    return [e for e in entries if isinstance(e, dict)]


def load_db_entries(conn: sqlite3.Connection) -> tuple[dict[RentaKey, dict], dict[str, dict]]:
    conn.row_factory = sqlite3.Row
    clientes_by_id: dict[str, dict] = {}
    # Schema compatibility: some DBs store full name in `nombre` only.
    columns = {r[1] for r in conn.execute("PRAGMA table_info(clientes)").fetchall()}
    has_apellidos = "apellidos" in columns
    if has_apellidos:
        query = "SELECT id, nombre, apellidos, nif FROM clientes"
    else:
        query = "SELECT id, nombre, nif FROM clientes"
    for row in conn.execute(query):
        clientes_by_id[row["id"]] = {
            "id": row["id"],
            "nombre": compact_spaces(row["nombre"]),
            "apellidos": compact_spaces(row["apellidos"]) if has_apellidos else "",
            "nif": norm(row["nif"]),
        }
    entries: dict[RentaKey, dict] = {}
    for row in conn.execute("SELECT cliente_id, renta_detalles FROM cliente_gestoria"):
        cliente = clientes_by_id.get(row["cliente_id"])
        if not cliente:
            continue
        nif = cliente.get("nif") or ""
        if not nif:
            continue
        for entry in parse_renta_entries(row["renta_detalles"]):
            ejercicio = compact_spaces(entry.get("ejercicio"))
            if not ejercicio:
                continue
            entries[RentaKey(ejercicio=ejercicio, nif=nif)] = {
                **entry,
                "_cliente_id": row["cliente_id"],
                "_cliente_nombre": f"{cliente.get('nombre','')} {cliente.get('apellidos','')}".strip(),
            }
    return entries, clientes_by_id


def floatish(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def comparable_fields(rec: dict) -> dict:
    return {
        "presentacion_fecha": compact_spaces(rec.get("presentacion_fecha")),
        "estado": compact_spaces(rec.get("estado_presentacion") or rec.get("doc_status") or rec.get("estado")),
        "ingresos": floatish(rec.get("ingresos_principales_total")),
        "resultado": floatish(rec.get("resultado_declaracion")),
        "casilla_505": floatish(rec.get("casilla_505")),
        "precio": floatish(rec.get("precio_servicio")),
        "cobrada": int(str(rec.get("cobrada") or 0).strip() in {"1", "true", "yes", "si", "sí"}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compara un preview de rentas OCR contra la SQLite del CRM.")
    parser.add_argument("--preview", required=True, help="Ruta al JSON generado por import_rentas_2024_to_crm.py")
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta a la SQLite del CRM")
    parser.add_argument("--ejercicio", default="", help="Filtra por ejercicio (ej: 2024)")
    parser.add_argument("--out-csv", default="reports/rentas_preview_vs_db_diff.csv", help="CSV de diferencias")
    args = parser.parse_args()

    preview_path = Path(args.preview).expanduser()
    db_path = Path(args.db).expanduser()
    out_csv = Path(args.out_csv).expanduser()
    ejercicio_filter = compact_spaces(args.ejercicio)

    preview = load_preview(preview_path, default_ejercicio=ejercicio_filter)
    conn = sqlite3.connect(str(db_path))
    try:
        db_entries, _ = load_db_entries(conn)
    finally:
        conn.close()

    if ejercicio_filter:
        preview = {k: v for k, v in preview.items() if k.ejercicio == ejercicio_filter}
        db_entries = {k: v for k, v in db_entries.items() if k.ejercicio == ejercicio_filter}

    only_preview = sorted(set(preview) - set(db_entries), key=lambda k: (k.ejercicio, k.nif))
    only_db = sorted(set(db_entries) - set(preview), key=lambda k: (k.ejercicio, k.nif))
    common = sorted(set(preview) & set(db_entries), key=lambda k: (k.ejercicio, k.nif))

    diffs = []
    changed = 0
    for key in common:
        a = comparable_fields(preview[key])
        b = comparable_fields(db_entries[key])
        delta = {field: (b.get(field), a.get(field)) for field in a.keys() if a.get(field) != b.get(field)}
        if delta:
            changed += 1
            diffs.append((key, delta))

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ejercicio",
                "nif",
                "status",
                "cliente_nombre",
                "diff_fields",
                "db_values",
                "preview_values",
            ],
        )
        writer.writeheader()

        for key in only_preview:
            writer.writerow(
                {
                    "ejercicio": key.ejercicio,
                    "nif": key.nif,
                    "status": "only_preview",
                    "cliente_nombre": compact_spaces(preview[key].get("cliente_nombre")),
                    "diff_fields": "",
                    "db_values": "",
                    "preview_values": json.dumps(comparable_fields(preview[key]), ensure_ascii=False),
                }
            )

        for key in only_db:
            writer.writerow(
                {
                    "ejercicio": key.ejercicio,
                    "nif": key.nif,
                    "status": "only_db",
                    "cliente_nombre": compact_spaces(db_entries[key].get("_cliente_nombre")),
                    "diff_fields": "",
                    "db_values": json.dumps(comparable_fields(db_entries[key]), ensure_ascii=False),
                    "preview_values": "",
                }
            )

        for key, delta in diffs:
            writer.writerow(
                {
                    "ejercicio": key.ejercicio,
                    "nif": key.nif,
                    "status": "changed",
                    "cliente_nombre": compact_spaces(preview[key].get("cliente_nombre") or db_entries[key].get("_cliente_nombre")),
                    "diff_fields": "|".join(sorted(delta.keys())),
                    "db_values": json.dumps(comparable_fields(db_entries[key]), ensure_ascii=False),
                    "preview_values": json.dumps(comparable_fields(preview[key]), ensure_ascii=False),
                }
            )

    summary = {
        "preview_total": len(preview),
        "db_total": len(db_entries),
        "only_preview": len(only_preview),
        "only_db": len(only_db),
        "changed": changed,
        "out_csv": str(out_csv),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
