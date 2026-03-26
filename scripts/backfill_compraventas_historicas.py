#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.import_inmuebles_vendidos_historial import (  # type: ignore
    DEFAULT_COMPANY,
    DEFAULT_DB,
    CaseEntry,
    extract_case_data,
    slug,
)

DEFAULT_DOWNLOADS_ROOT = Path("/Volumes/Mac Satecchi/Mac/Downloads")

MONTH_FOLDERS = {
    "enero": "01 ENERO",
    "febrero": "02 FEBRERO",
    "marzo": "03 MARZO",
    "abril": "04 ABRIL",
    "mayo": "05 MAYO",
    "junio": "06 JUNIO",
    "julio": "07 JULIO",
    "agosto": "08 AGOSTO",
    "septiembre": "09 SEPTIEMBRE",
    "octubre": "10 OCTUBRE",
    "noviembre": "11 NOVIEMBRE",
    "diciembre": "12 DICIEMBRE",
}

STOPWORDS = {
    "piso",
    "local",
    "bloque",
    "blq",
    "esc",
    "escalera",
    "avda",
    "avenida",
    "calle",
    "de",
    "del",
    "la",
    "el",
    "los",
    "las",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9áéíóúñ]+", " ", (value or "").lower()).strip()


def significant_tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize_text(value).split()
        if len(token) > 2 and token not in STOPWORDS
    }


def numeric_tokens(value: str) -> set[str]:
    return {token for token in normalize_text(value).split() if token.isdigit()}


def movement_match_score(address: str, sold_label: str) -> float:
    address_norm = normalize_text(address)
    sold_norm = normalize_text(sold_label)
    if not address_norm or not sold_norm:
        return 0.0
    ratio = SequenceMatcher(None, address_norm, sold_norm).ratio()
    addr_tokens = significant_tokens(address)
    sold_tokens = significant_tokens(sold_label)
    overlap = len(addr_tokens & sold_tokens)
    addr_numbers = numeric_tokens(address)
    sold_numbers = numeric_tokens(sold_label)
    if addr_numbers and sold_numbers and not (addr_numbers & sold_numbers):
        return 0.0
    if overlap:
        ratio += min(0.25, overlap * 0.08)
    if sold_norm in address_norm or address_norm in sold_norm:
        ratio += 0.12
    return round(max(ratio, 0.0), 4)


def resolve_case_path(downloads_root: Path, year: int, month: str, direccion: str) -> Path | None:
    month_folder = MONTH_FOLDERS.get((month or "").strip().lower())
    if not month_folder:
        return None
    base = downloads_root / month_folder
    if not base.exists():
        return None
    direct = base / direccion
    if direct.exists():
        return direct
    wanted = slug(direccion)
    for child in base.iterdir():
        if child.is_dir() and slug(child.name) == wanted:
            return child
    return None


def best_movement_for_operation(movements: list[sqlite3.Row], month: str, direccion: str) -> sqlite3.Row | None:
    same_month = [row for row in movements if (row["mes"] or "").strip().lower() == (month or "").strip().lower()]
    if not same_month:
        return None
    scored = [
        (movement_match_score(direccion, str(row["pisos_vendidos"] or "")), row)
        for row in same_month
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_row = scored[0]
    if best_score >= 0.72:
        return best_row
    sold_label = str(best_row["pisos_vendidos"] or "")
    sold_norm = normalize_text(sold_label)
    address_norm = normalize_text(direccion)
    sold_tokens = significant_tokens(sold_label)
    address_tokens = significant_tokens(direccion)
    if sold_norm and sold_norm in address_norm:
        return best_row
    if sold_tokens and sold_tokens.issubset(address_tokens) and best_score >= 0.45:
        return best_row
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill de compraventas históricas importadas.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--downloads-root", type=Path, default=DEFAULT_DOWNLOADS_ROOT)
    parser.add_argument("--company", default=DEFAULT_COMPANY)
    parser.add_argument("--year", type=int, default=2020)
    parser.add_argument("--skip-docs", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    empresa = conn.execute("SELECT id FROM empresas WHERE nombre = ? LIMIT 1", (args.company,)).fetchone()
    if not empresa:
        raise SystemExit(f"Empresa no encontrada: {args.company}")
    empresa_id = str(empresa["id"])

    operations = conn.execute(
        """
        SELECT id, direccion, anio, mes, precio_encargo, precio_propuesta, precio_contrato,
               precio_escritura, num_visitas, honorarios, responsable_gestion,
               expediente_path, doc_nota_encargo_path, doc_propuesta_path, doc_partes_visita_paths
        FROM operaciones_inmobiliarias
        WHERE empresa_id = ? AND LOWER(COALESCE(tipo_operacion, 'venta')) = 'venta' AND anio = ?
        ORDER BY fecha_escritura, direccion
        """,
        (empresa_id, args.year),
    ).fetchall()

    movements = conn.execute(
        """
        SELECT id, mes, pisos_vendidos, comision, asesor
        FROM movimientos
        WHERE empresa_id = ? AND UPPER(TRIM(concepto)) = 'COMPRAVENTA' AND anio = ?
        """,
        (empresa_id, args.year),
    ).fetchall()

    changes = []
    timestamp = now_iso()
    for op in operations:
        update: dict[str, object] = {}
        case_path = None if args.skip_docs else resolve_case_path(args.downloads_root, int(op["anio"] or 0), str(op["mes"] or ""), str(op["direccion"] or ""))
        if case_path:
            files = [path for path in case_path.rglob("*") if path.is_file()]
            case = CaseEntry(
                year=int(op["anio"] or 0),
                month=str(op["mes"] or ""),
                label=str(op["direccion"] or ""),
                case_path=case_path,
                files=files,
            )
            extracted = extract_case_data(case, args.downloads_root / MONTH_FOLDERS.get(str(op["mes"] or "").lower(), ""))
            if extracted.get("precio_encargo") and not op["precio_encargo"]:
                update["precio_encargo"] = extracted["precio_encargo"]
            if extracted.get("precio_propuesta") and not op["precio_propuesta"]:
                update["precio_propuesta"] = extracted["precio_propuesta"]
            if extracted.get("precio_contrato") and not op["precio_contrato"]:
                update["precio_contrato"] = extracted["precio_contrato"]
            if extracted.get("num_visitas") and int(extracted["num_visitas"] or 0) > int(op["num_visitas"] or 0):
                update["num_visitas"] = int(extracted["num_visitas"] or 0)
            if extracted.get("doc_nota_encargo_path") and not op["doc_nota_encargo_path"]:
                update["doc_nota_encargo_path"] = extracted["doc_nota_encargo_path"]
            if extracted.get("doc_propuesta_path") and not op["doc_propuesta_path"]:
                update["doc_propuesta_path"] = extracted["doc_propuesta_path"]
            if extracted.get("doc_partes_visita_paths") and not op["doc_partes_visita_paths"]:
                update["doc_partes_visita_paths"] = extracted["doc_partes_visita_paths"]
            precio_salida = update.get("precio_encargo", op["precio_encargo"])
            precio_venta = update.get("precio_contrato", op["precio_contrato"]) or update.get("precio_propuesta", op["precio_propuesta"])
            if precio_salida and precio_venta:
                update["desviacion_euros"] = round(float(precio_salida) - float(precio_venta), 2)
                update["desviacion_pct"] = round(((float(precio_salida) - float(precio_venta)) / float(precio_salida)) * 100.0, 2)

        movement = best_movement_for_operation(movements, str(op["mes"] or ""), str(op["direccion"] or ""))
        if movement:
            if float(op["honorarios"] or 0) <= 0 and float(movement["comision"] or 0) > 0:
                update["honorarios"] = float(movement["comision"] or 0)
            if not str(op["responsable_gestion"] or "").strip() and str(movement["asesor"] or "").strip():
                update["responsable_gestion"] = str(movement["asesor"] or "").strip()

        if update:
            update["updated_at"] = timestamp
            changes.append((str(op["direccion"]), update))
            if args.apply:
                assignments = ", ".join(f"{column} = ?" for column in update)
                conn.execute(
                    f"UPDATE operaciones_inmobiliarias SET {assignments} WHERE id = ?",
                    (*update.values(), op["id"]),
                )

    if args.apply:
        conn.commit()

    print(
        {
            "year": args.year,
            "operations": len(operations),
            "updated": len(changes),
            "sample": changes[:8],
            "applied": bool(args.apply),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
