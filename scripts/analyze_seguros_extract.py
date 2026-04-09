#!/usr/bin/env python3
"""
Analiza un CSV generado por `scripts/extract_seguros_pdfs_local.py`.

Genera:
  - CSV con pólizas únicas (mejor candidato por (poliza_numero_norm, compania_norm))
  - CSV con filas de póliza con campos mínimos incompletos
  - JSON resumen (counts, duplicados, totales)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REQUIRED_KEYS = ("tomador", "poliza_numero", "compania", "fecha_efecto")


def parse_float_eu(value: str) -> float | None:
    s = str(value or "").strip()
    if not s:
        return None
    s = s.replace("€", "").replace("%", "").strip()
    # Normaliza miles/decimales en formato ES
    if re.fullmatch(r"-?[0-9]{1,3}(\.[0-9]{3})*,[0-9]+", s):
        s = s.replace(".", "").replace(",", ".")
    # Normaliza "1234,56"
    elif re.fullmatch(r"-?[0-9]+,[0-9]+", s):
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def year_from_date(value: str) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    # Caso típico: YYYY-MM-DD
    m = re.match(r"^(\d{4})-\d{2}-\d{2}$", s)
    if m:
        return m.group(1)
    # Fallback: intenta extraer año
    m = re.search(r"\b(19\d{2}|20\d{2})\b", s)
    return m.group(1) if m else ""


@dataclass(frozen=True)
class PolicyKey:
    poliza_norm: str
    compania_norm: str

    def as_str(self) -> str:
        return f"{self.poliza_norm}|{self.compania_norm}"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        out_path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = list(rows[0].keys())
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def score_row(row: dict[str, str]) -> tuple[int, int, float, int]:
    # Orden: required_filled, required_valid, confidence, ok
    rf = int(float((row.get("required_filled") or "0").strip() or 0))
    rv = int(float((row.get("required_valid") or "0").strip() or 0))
    conf = float((row.get("confidence") or "0").strip() or 0.0)
    ok = int(float((row.get("ok") or "0").strip() or 0))
    return (rf, rv, conf, ok)


def is_missing_required(row: dict[str, str], required_keys: Iterable[str]) -> bool:
    return any(not str(row.get(k) or "").strip() for k in required_keys)


def main() -> None:
    ap = argparse.ArgumentParser(description="Analiza el CSV de extracción masiva de seguros.")
    ap.add_argument("--csv", required=True, help="Ruta del CSV `seguros_extract_*.csv`.")
    ap.add_argument("--out-dir", default="", help="Directorio de salida (por defecto, directorio del CSV).")
    ap.add_argument("--doc-kind", default="poliza", help="Doc kind a analizar (por defecto: poliza).")
    args = ap.parse_args()

    csv_path = Path(args.csv).expanduser().resolve()
    if not csv_path.exists():
        raise SystemExit(f"No existe: {csv_path}")

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else csv_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = read_csv(csv_path)
    kind = str(args.doc_kind or "").strip() or "poliza"
    kind_counts = Counter(r.get("doc_kind") or "" for r in rows)
    poliza_rows = [r for r in rows if (r.get("doc_kind") or "") == kind]

    grouped: dict[PolicyKey, list[dict[str, str]]] = defaultdict(list)
    for r in poliza_rows:
        poliza_norm = str(r.get("poliza_numero_norm") or "").strip()
        compania_norm = str(r.get("compania_norm") or "").strip()
        if not poliza_norm:
            continue
        grouped[PolicyKey(poliza_norm=poliza_norm, compania_norm=compania_norm)].append(r)

    chosen: list[dict[str, str]] = []
    duplicates: dict[str, list[str]] = {}
    for k, group in grouped.items():
        group_sorted = sorted(group, key=score_row, reverse=True)
        chosen.append(group_sorted[0])
        if len(group) > 1:
            duplicates[k.as_str()] = [g.get("path") or "" for g in group_sorted]

    missing_rows = [r for r in poliza_rows if is_missing_required(r, REQUIRED_KEYS)]
    missing_counts = Counter()
    for r in poliza_rows:
        for k in REQUIRED_KEYS:
            if not str(r.get(k) or "").strip():
                missing_counts[k] += 1

    top_companies = Counter(r.get("compania_norm") or "" for r in chosen if str(r.get("compania_norm") or "").strip())
    top_ramos = Counter(r.get("ramo") or "" for r in chosen if str(r.get("ramo") or "").strip())
    by_year = Counter(year_from_date(r.get("fecha_efecto") or "") for r in chosen if year_from_date(r.get("fecha_efecto") or ""))

    # Totales numéricos (solo sobre chosen/unique)
    tot_prima_total = 0.0
    tot_prima_neta = 0.0
    tot_comision = 0.0
    num_prima_total = 0
    num_prima_neta = 0
    num_comision = 0
    for r in chosen:
        v = parse_float_eu(r.get("prima_total") or "")
        if v is not None:
            tot_prima_total += v
            num_prima_total += 1
        v = parse_float_eu(r.get("prima_neta") or "")
        if v is not None:
            tot_prima_neta += v
            num_prima_neta += 1
        v = parse_float_eu(r.get("comision") or "")
        if v is not None:
            tot_comision += v
            num_comision += 1

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = csv_path.stem.replace("seguros_extract_", "seguros_analyze_")
    summary_path = out_dir / f"{base}_{ts}_summary.json"
    unique_path = out_dir / f"{base}_{ts}_unique.csv"
    missing_path = out_dir / f"{base}_{ts}_missing.csv"

    write_csv(chosen, unique_path)
    write_csv(missing_rows, missing_path)

    summary = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "input_csv": str(csv_path),
        "doc_kind_analyzed": kind,
        "rows_total": len(rows),
        "rows_kind": len(poliza_rows),
        "kind_counts": dict(kind_counts),
        "unique_policies": len(chosen),
        "duplicate_groups": duplicates,
        "missing_required_counts_in_kind": dict(missing_counts),
        "missing_rows_in_kind": len(missing_rows),
        "top_companies_unique": top_companies.most_common(20),
        "top_ramos_unique": top_ramos.most_common(30),
        "by_year_unique": by_year.most_common(),
        "totals_unique": {
            "prima_total_sum": round(tot_prima_total, 2),
            "prima_total_count": num_prima_total,
            "prima_neta_sum": round(tot_prima_neta, 2),
            "prima_neta_count": num_prima_neta,
            "comision_sum": round(tot_comision, 2),
            "comision_count": num_comision,
        },
        "outputs": {
            "unique_csv": str(unique_path),
            "missing_csv": str(missing_path),
            "summary_json": str(summary_path),
        },
    }

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

