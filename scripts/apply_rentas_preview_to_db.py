#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path


def compact_spaces(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_nif(value: object) -> str:
    return compact_spaces(value).upper().replace(" ", "").replace(".", "").replace("-", "")


def year_from_text_preview(record: dict) -> str:
    text = compact_spaces(record.get("text_preview"))
    if not text:
        return ""
    match = re.search(r"Ejercicio\s+(20\d{2})", text, re.IGNORECASE)
    return match.group(1) if match else ""


def load_db_nifs_for_year(db_path: Path, ejercicio: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        nifs: set[str] = set()
        for row in conn.execute(
            "SELECT clientes.nif, cliente_gestoria.renta_detalles FROM cliente_gestoria JOIN clientes ON clientes.id = cliente_gestoria.cliente_id"
        ):
            nif = normalize_nif(row["nif"])
            if not nif:
                continue
            try:
                payload = json.loads(row["renta_detalles"] or "")
            except Exception:
                continue
            entries = payload.get("entries") if isinstance(payload, dict) else None
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("ejercicio") or "") == ejercicio:
                    nifs.add(nif)
                    break
        return nifs
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aplica a la SQLite un preview JSON (ya OCR) filtrando por ejercicio real en text_preview."
    )
    parser.add_argument("--preview", required=True, help="JSON generado por import_rentas_2024_to_crm.py")
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta SQLite CRM")
    parser.add_argument("--company", default="Fincas Velazquez", help="Empresa destino")
    parser.add_argument("--ejercicio", required=True, help="Ejercicio fiscal a aplicar (ej: 2024)")
    parser.add_argument("--estado-presentacion", default="Presentada", choices=("Borrador", "Presentada"))
    parser.add_argument("--only-safe", action="store_true", help="Solo aplica registros safe_to_apply")
    parser.add_argument("--only-missing", action="store_true", help="Solo aplica NIFs que no existan ya en la BD para ese ejercicio")
    parser.add_argument(
        "--allow-unknown-year",
        action="store_true",
        help="Permite aplicar registros sin 'Ejercicio YYYY' detectado en text_preview (NO recomendado).",
    )
    args = parser.parse_args()

    preview_path = Path(args.preview).expanduser()
    db_path = Path(args.db).expanduser()
    ejercicio = compact_spaces(args.ejercicio)
    if not ejercicio:
        raise SystemExit("Ejercicio vacío")

    records = json.loads(preview_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise SystemExit("Preview inválido: no es una lista JSON")

    filtered: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        detected = year_from_text_preview(record) or compact_spaces(record.get("ejercicio"))
        if not detected and not args.allow_unknown_year:
            continue
        if detected and detected != ejercicio:
            continue
        if args.only_safe and not record.get("safe_to_apply"):
            continue
        filtered.append(record)

    existing_nifs: set[str] = set()
    if args.only_missing:
        existing_nifs = load_db_nifs_for_year(db_path, ejercicio)
        filtered = [r for r in filtered if normalize_nif(r.get("cliente_nif")) not in existing_nifs]

    if not filtered:
        print(json.dumps({"to_apply": 0, "applied": 0}, ensure_ascii=False, indent=2))
        return

    # Allow importing sibling package when executed as a script.
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from scripts.import_rentas_2024_to_crm import apply_to_db

    result = apply_to_db(
        db_path=db_path,
        records=filtered,
        company_name=str(args.company),
        ejercicio=ejercicio,
        estado_presentacion=str(args.estado_presentacion),
    )
    print(
        json.dumps(
            {
                "to_apply": len(filtered),
                "result": result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
