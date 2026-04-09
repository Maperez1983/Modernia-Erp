#!/usr/bin/env python3
"""
Busca PDFs de pólizas (en el CSV de extracción) por NIF/DNI y, si se indica,
intenta enlazar con registros ya existentes en la tabla `seguros`.

Uso:
  python3 scripts/find_seguros_pdf_by_nif.py --nif 12345678Z
  python3 scripts/find_seguros_pdf_by_nif.py --csv reports/seguros_extract_*.csv --nif B12345678
  python3 scripts/find_seguros_pdf_by_nif.py --nif 12345678Z --empresa-id <uuid>

Notas:
  - No toca la base de datos.
  - Solo imprime rutas locales de los PDFs detectados en el CSV.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _norm_id(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper().strip() if ch.isalnum())


def _latest_extract_csv(reports_dir: Path) -> Path | None:
    if not reports_dir.exists():
        return None
    candidates = sorted(reports_dir.glob("seguros_extract_*.csv"), key=lambda p: p.name, reverse=True)
    return candidates[0] if candidates else None


@dataclass(frozen=True)
class Key:
    poliza_norm: str
    compania_norm: str

    def as_str(self) -> str:
        return f"{self.poliza_norm}|{self.compania_norm}"


def _normalize_poliza_key(value: Any) -> str:
    import re

    text = re.sub(r"\s+", "", str(value or "").upper())
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text


def _normalize_company_key(value: Any) -> str:
    import re

    text = str(value or "").upper()
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _open_sqlite() -> sqlite3.Connection:
    db_path = ROOT / "data" / "erp_import2.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _build_crm_index(conn: sqlite3.Connection, empresa_id: str) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        "SELECT id, empresa_id, cliente_id, compania, poliza_numero, tomador FROM seguros WHERE empresa_id = ?",
        (empresa_id,),
    ).fetchall()
    out: dict[str, sqlite3.Row] = {}
    for r in rows:
        k = Key(
            poliza_norm=_normalize_poliza_key(r["poliza_numero"]),
            compania_norm=_normalize_company_key(r["compania"]),
        ).as_str()
        if k and k not in out:
            out[k] = r
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Localiza PDFs (CSV de extracción) por NIF/DNI.")
    ap.add_argument("--nif", required=True, help="NIF/DNI/CIF del tomador (ej: 12345678Z o B12345678).")
    ap.add_argument("--csv", default="", help="CSV de extracción `seguros_extract_*.csv` (por defecto usa el último en reports/).")
    ap.add_argument("--only-poliza", action="store_true", help="Filtra solo doc_kind=poliza (recomendado).")
    ap.add_argument("--empresa-id", default="", help="Si se indica, intenta casar con tabla `seguros` (solo SQLite local).")
    args = ap.parse_args()

    target = _norm_id(args.nif)
    if not target:
        raise SystemExit("NIF vacío.")

    csv_path = Path(args.csv).expanduser() if str(args.csv or "").strip() else (_latest_extract_csv(ROOT / "reports") or Path())
    if not csv_path or not csv_path.exists():
        raise SystemExit("No encuentro el CSV. Pasa --csv o genera uno con scripts/extract_seguros_pdfs_local.py.")

    rows = _read_csv(csv_path)
    filtered = []
    for r in rows:
        if args.only_poliza and (r.get("doc_kind") or "").strip() != "poliza":
            continue
        nif = _norm_id(r.get("nif") or r.get("dni") or "")
        if nif == target:
            filtered.append(r)

    if not filtered:
        print("Sin resultados.")
        return

    crm_index: dict[str, sqlite3.Row] = {}
    if str(args.empresa_id or "").strip():
        try:
            conn = _open_sqlite()
            crm_index = _build_crm_index(conn, str(args.empresa_id).strip())
        except Exception:
            crm_index = {}

    # salida compacta
    for r in filtered:
        poliza = (r.get("poliza_numero") or "").strip()
        compania = (r.get("compania") or "").strip()
        key = Key(_normalize_poliza_key(poliza), _normalize_company_key(compania)).as_str()
        crm = crm_index.get(key)
        crm_id = (crm["id"] if crm else "")
        print(f"- {Path(r.get('path') or '').name} :: {compania} :: {poliza} :: crm_id={crm_id}")
        print(f"  {r.get('path')}")


if __name__ == "__main__":
    main()

