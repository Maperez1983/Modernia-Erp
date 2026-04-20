#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


def compact_spaces(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_nif(value: object) -> str:
    return compact_spaces(value).upper().replace(" ", "").replace(".", "").replace("-", "")


def looks_like_spanish_id(value: object) -> bool:
    text = normalize_nif(value)
    if not text:
        return False
    # NIF/NIE/CIF (loose)
    if re.fullmatch(r"[0-9]{8}[A-Z]", text):
        return True
    if re.fullmatch(r"[XYZ][0-9]{7}[A-Z]", text):
        return True
    if re.fullmatch(r"[A-Z][0-9]{7}[0-9A-Z]", text):
        return True
    return False


@dataclass(frozen=True)
class ClientMatch:
    cliente_id: str
    cliente_nombre: str
    score: float


def load_client_index(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    conn.row_factory = sqlite3.Row
    columns = {row[1] for row in conn.execute("PRAGMA table_info(clientes)").fetchall()}
    has_apellidos = "apellidos" in columns
    query = "SELECT id, nombre, apellidos, nif FROM clientes" if has_apellidos else "SELECT id, nombre, nif FROM clientes"
    by_nif: dict[str, list[dict]] = defaultdict(list)
    for row in conn.execute(query):
        nif = normalize_nif(row["nif"])
        if not nif:
            continue
        nombre = compact_spaces(row["nombre"])
        apellidos = compact_spaces(row["apellidos"]) if has_apellidos else ""
        full = f"{nombre} {apellidos}".strip()
        by_nif[nif].append({"id": row["id"], "nombre": full})
    return by_nif


def infer_status_from_sources(source_files: list[str]) -> str:
    joined = " | ".join(source_files or [])
    if "/2 HECHAS/" in joined and "/EN PROCESO/" not in joined:
        return "Presentada"
    return "Borrador"


def main() -> None:
    parser = argparse.ArgumentParser(description="Audita una carpeta de Rentas (PDFs) y genera un informe para importación sin duplicados.")
    parser.add_argument("--source-dir", required=True, help="Carpeta raíz con PDFs/imágenes de renta.")
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta SQLite CRM (solo lectura).")
    parser.add_argument("--ejercicio", default="", help="Ejercicio fiscal objetivo (ej: 2025).")
    parser.add_argument("--out", default="reports/rentas_folder_audit.json", help="Salida JSON del informe.")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser().resolve()
    if not source_dir.exists():
        raise SystemExit(f"No existe: {source_dir}")

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        raise SystemExit(f"No existe la BD: {db_path}")

    # Allow importing sibling package when executed as a script.
    repo_root = Path(__file__).resolve().parent.parent
    import sys

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from scripts.import_rentas_2024_to_crm import build_validation_summary, scan_folder

    records = scan_folder(source_dir, limit=0)
    if args.ejercicio:
        ejercicio = compact_spaces(args.ejercicio)
        records = [r for r in records if compact_spaces(r.get("ejercicio") or ejercicio) in {"", ejercicio}]
        for r in records:
            if not r.get("ejercicio"):
                r["ejercicio"] = ejercicio

    conn = sqlite3.connect(str(db_path))
    try:
        clients_by_nif = load_client_index(conn)
    finally:
        conn.close()

    items = []
    stats = Counter()
    missing_clients = []
    for rec in records:
        nif_raw = rec.get("cliente_nif")
        nif = normalize_nif(nif_raw)
        status = infer_status_from_sources(rec.get("source_files") or [])
        match_ids = clients_by_nif.get(nif, []) if nif else []
        match = None
        if nif and len(match_ids) == 1:
            match = {"cliente_id": match_ids[0]["id"], "cliente_nombre": match_ids[0]["nombre"], "mode": "nif_unique"}
            stats["matched_unique"] += 1
        elif nif and len(match_ids) > 1:
            stats["matched_ambiguous"] += 1
            match = {"cliente_id": "", "cliente_nombre": "", "mode": "nif_ambiguous", "candidates": match_ids}
        else:
            stats["missing_cliente"] += 1
            missing_clients.append({"cliente_nif": nif, "cliente_nombre": rec.get("cliente_nombre")})

        if nif and not looks_like_spanish_id(nif):
            stats["nif_suspect"] += 1

        safe = bool(rec.get("safe_to_apply"))
        stats["safe_to_apply" if safe else "needs_review"] += 1
        items.append(
            {
                "ejercicio": rec.get("ejercicio") or compact_spaces(args.ejercicio),
                "cliente_nombre": rec.get("cliente_nombre") or "",
                "cliente_nif": nif_raw or "",
                "cliente_nif_norm": nif,
                "recommended_estado_presentacion": status,
                "safe_to_apply": 1 if safe else 0,
                "critical_missing": rec.get("critical_missing") or "",
                "review_flags": rec.get("review_flags") or "",
                "source_file_count": len(rec.get("source_files") or []),
                "source_files": rec.get("source_files") or [],
                "client_match": match,
            }
        )

    out = {
        "source_dir": str(source_dir),
        "db": str(db_path),
        "ejercicio": compact_spaces(args.ejercicio),
        "counts": {
            "records_total": len(records),
            **{k: int(v) for k, v in stats.items()},
        },
        "validation": build_validation_summary(records),
        "missing_clients": missing_clients[:200],
        "items": items,
    }

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out_path), "counts": out["counts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

