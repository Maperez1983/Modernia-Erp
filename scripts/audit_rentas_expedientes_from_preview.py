#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


GENERIC_FOLDERS = {
    "1 CLIENTES TERE",
    "1 DATOS  FISCALES",
    "1 DATOS FISCALES",
    "2 HECHAS",
    "DNI  RENTAS HECHAS",
    "DNI RENTAS HECHAS",
    "EN PROCESO",
}


def compact_spaces(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def norm(value: object) -> str:
    text = compact_spaces(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.strip().upper()


def slug(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def normalize_nif(value: object) -> str:
    return compact_spaces(value).upper().replace(" ", "").replace(".", "").replace("-", "")


def looks_like_nif(value: object) -> bool:
    text = normalize_nif(value)
    if not re.fullmatch(r"[A-Z0-9]{8,10}", text):
        return False
    if not any(ch.isdigit() for ch in text):
        return False
    if text in {"DECLARANTE", "CONYUGE", "NOMBRE", "ES"}:
        return False
    return True


@dataclass(frozen=True)
class ClienteRow:
    id: str
    nombre: str


def load_clients_by_nif(conn: sqlite3.Connection) -> dict[str, list[ClienteRow]]:
    conn.row_factory = sqlite3.Row
    columns = {row[1] for row in conn.execute("PRAGMA table_info(clientes)").fetchall()}
    has_apellidos = "apellidos" in columns
    query = "SELECT id, nombre, apellidos, nif FROM clientes" if has_apellidos else "SELECT id, nombre, nif FROM clientes"
    out: dict[str, list[ClienteRow]] = defaultdict(list)
    for row in conn.execute(query):
        nif = normalize_nif(row["nif"])
        if not nif:
            continue
        nombre = compact_spaces(row["nombre"])
        apellidos = compact_spaces(row["apellidos"]) if has_apellidos else ""
        out[nif].append(ClienteRow(id=str(row["id"]), nombre=f"{nombre} {apellidos}".strip()))
    return out


def pick_expediente_name(source_dir: Path, source_files: list[str]) -> str:
    candidates: list[str] = []
    for raw in source_files or []:
        try:
            rel = Path(raw).resolve().relative_to(source_dir)
        except Exception:
            continue
        parts = [compact_spaces(p) for p in rel.parts if compact_spaces(p)]
        if not parts:
            continue
        # Common layouts:
        # - <EXPEDIENTE>/<files>
        # - 2 HECHAS/EN PROCESO/<EXPEDIENTE>/<files>
        # - 2 HECHAS/DNI RENTAS HECHAS/<files>
        if parts[0].upper() == "2 HECHAS" and len(parts) >= 3 and parts[1].upper() == "EN PROCESO":
            name = parts[2]
        elif parts[0].upper() == "2 HECHAS" and len(parts) >= 2 and parts[1].upper() in {"DNI  RENTAS HECHAS", "DNI RENTAS HECHAS"}:
            name = "2 HECHAS"
        else:
            name = parts[0]
        if not name or name.upper() in GENERIC_FOLDERS:
            continue
        if "RENTAS" in name.upper() and re.search(r"\b20[0-9]{2}\b", name):
            continue
        candidates.append(name)
    if not candidates:
        return "SIN_EXPEDIENTE"
    most_common = Counter(candidates).most_common(1)[0][0]
    return most_common


def infer_estado_from_sources(source_files: list[str]) -> str:
    joined = " | ".join(source_files or [])
    if "/2 HECHAS/" in joined and "/EN PROCESO/" not in joined:
        return "Presentada"
    return "Borrador"


def main() -> None:
    parser = argparse.ArgumentParser(description="Agrupa un preview de rentas por expediente (carpeta) y valida matches por DNI/NIF.")
    parser.add_argument("--preview", required=True, help="JSON generado por import_rentas_2024_to_crm.py")
    parser.add_argument("--source-dir", required=True, help="Carpeta raíz usada para generar el preview (para relativizar expedientes).")
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta SQLite CRM (solo lectura).")
    parser.add_argument("--out", default="reports/rentas_expedientes_audit.json", help="Salida JSON.")
    args = parser.parse_args()

    preview_path = Path(args.preview).expanduser().resolve()
    source_dir = Path(args.source_dir).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve()

    records = json.loads(preview_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise SystemExit("Preview inválido (no es lista).")

    conn = sqlite3.connect(str(db_path))
    try:
        clients_by_nif = load_clients_by_nif(conn)
    finally:
        conn.close()

    expedientes: dict[str, dict] = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        source_files = rec.get("source_files") or []
        exp_name = pick_expediente_name(source_dir, source_files)
        if exp_name == "SIN_EXPEDIENTE":
            fallback = compact_spaces(rec.get("cliente_nombre")) or compact_spaces(rec.get("cliente_nif")) or "SIN_EXPEDIENTE"
            exp_name = fallback
        exp_key = slug(norm(exp_name)) or "sin_expediente"
        exp = expedientes.setdefault(
            exp_key,
            {
                "expediente_key": exp_key,
                "expediente_nombre": exp_name,
                "estado_default": "Borrador",
                "estado_counts": {"Presentada": 0, "Borrador": 0},
                "people": [],
            },
        )
        estado = infer_estado_from_sources(source_files)
        exp["estado_counts"][estado] = int(exp["estado_counts"].get(estado, 0)) + 1

        nif = normalize_nif(rec.get("cliente_nif"))
        match = None
        if nif and looks_like_nif(nif):
            candidates = clients_by_nif.get(nif, [])
            if len(candidates) == 1:
                match = {"mode": "nif_unique", "cliente_id": candidates[0].id, "cliente_nombre": candidates[0].nombre}
            elif len(candidates) > 1:
                match = {"mode": "nif_ambiguous", "candidates": [{"id": c.id, "nombre": c.nombre} for c in candidates]}
            else:
                match = {"mode": "missing", "candidates": []}
        else:
            match = {"mode": "nif_invalid", "raw": rec.get("cliente_nif")}

        exp["people"].append(
            {
                "cliente_nombre": rec.get("cliente_nombre") or "",
                "cliente_nif": rec.get("cliente_nif") or "",
                "cliente_nif_norm": nif,
                "estado_inferido": estado,
                "safe_to_apply": 1 if rec.get("safe_to_apply") else 0,
                "critical_missing": rec.get("critical_missing") or "",
                "review_flags": rec.get("review_flags") or "",
                "source_file_count": len(source_files),
                "source_files": source_files,
                "match": match,
            }
        )

    # Summaries
    out_expedientes = []
    totals = Counter()
    for exp in sorted(expedientes.values(), key=lambda e: (e.get("estado_default") != "Presentada", e.get("expediente_nombre", ""))):
        counts = Counter()
        estado_counts = exp.get("estado_counts") or {"Presentada": 0, "Borrador": 0}
        # Default state for the expediente: only mark Presentada if ALL people in
        # that expediente come from "2 HECHAS" (otherwise it is mixed/encargada).
        exp["estado_default"] = "Presentada" if int(estado_counts.get("Borrador", 0)) == 0 and int(estado_counts.get("Presentada", 0)) > 0 else "Borrador"
        for person in exp.get("people") or []:
            totals["people_total"] += 1
            counts["people_total"] += 1
            if person.get("safe_to_apply"):
                totals["safe_to_apply"] += 1
                counts["safe_to_apply"] += 1
            mode = ((person.get("match") or {}).get("mode") or "").strip() or "unknown"
            totals[f"match_{mode}"] += 1
            counts[f"match_{mode}"] += 1
        exp["counts"] = dict(counts)
        out_expedientes.append(exp)
        totals["expedientes_total"] += 1
        if exp.get("estado_default") == "Presentada":
            totals["expedientes_presentadas"] += 1
        else:
            totals["expedientes_borrador"] += 1

    out = {
        "preview": str(preview_path),
        "source_dir": str(source_dir),
        "db": str(db_path),
        "totals": dict(totals),
        "expedientes": out_expedientes,
    }
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out_path), "totals": out["totals"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
