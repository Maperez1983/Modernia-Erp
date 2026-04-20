#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def compact_spaces(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def infer_estado_presentacion(record: dict) -> str:
    sources = record.get("source_files") or []
    joined = " | ".join(str(p) for p in sources)
    if "/2 HECHAS/" in joined and "/EN PROCESO/" not in joined:
        return "Presentada"
    return "Borrador"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aplica un preview de rentas (OCR) a la SQLite, asignando estado Presentada/Borrador según la carpeta origen."
    )
    parser.add_argument("--preview", required=True, help="JSON generado por import_rentas_2024_to_crm.py")
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta SQLite CRM")
    parser.add_argument("--company", default="Fincas Velazquez", help="Empresa destino")
    parser.add_argument("--ejercicio", required=True, help="Ejercicio fiscal (ej: 2025)")
    parser.add_argument("--only-safe", action="store_true", help="Solo aplica registros safe_to_apply")
    parser.add_argument("--apply", action="store_true", help="Escribe en la SQLite (por defecto: solo informa)")
    args = parser.parse_args()

    preview_path = Path(args.preview).expanduser().resolve()
    records = json.loads(preview_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise SystemExit(f"Preview inválido: {preview_path}")

    ejercicio = compact_spaces(args.ejercicio)
    if not ejercicio:
        raise SystemExit("Ejercicio vacío")

    prepared = []
    counts = {"total": 0, "safe": 0, "presentada": 0, "borrador": 0}
    for record in records:
        if not isinstance(record, dict):
            continue
        counts["total"] += 1
        if args.only_safe and not record.get("safe_to_apply"):
            continue
        if record.get("safe_to_apply"):
            counts["safe"] += 1
        estado = infer_estado_presentacion(record)
        counts["presentada" if estado == "Presentada" else "borrador"] += 1
        next_rec = dict(record)
        next_rec["ejercicio"] = ejercicio
        next_rec["estado_presentacion"] = estado
        prepared.append(next_rec)

    if not args.apply:
        print(json.dumps({"ok": True, "apply": False, "counts": counts, "prepared": len(prepared)}, ensure_ascii=False, indent=2))
        return

    # Allow importing sibling package when executed as a script.
    repo_root = Path(__file__).resolve().parent.parent
    import sys

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from scripts.import_rentas_2024_to_crm import apply_to_db

    result = apply_to_db(
        db_path=Path(args.db).expanduser().resolve(),
        records=prepared,
        company_name=str(args.company),
        ejercicio=ejercicio,
        estado_presentacion="Borrador",
    )
    print(json.dumps({"ok": True, "apply": True, "counts": counts, "result": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

