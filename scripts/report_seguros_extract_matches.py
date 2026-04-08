#!/usr/bin/env python3
"""
Reporte: cruza extract de pólizas (CSV) con clientes y seguros del CRM.

No escribe en BD. Solo genera un CSV con el estado del cruce.
"""

from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.server import DB_CONFIGURED, normalize_company_key, normalize_poliza_key  # noqa: E402


def norm_nif(value: Any) -> str:
    return (
        str(value or "")
        .strip()
        .upper()
        .replace(" ", "")
        .replace("-", "")
        .replace(".", "")
        .replace("/", "")
    )


@dataclass(frozen=True)
class PolicyKey:
    poliza_norm: str
    compania_norm: str


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(rows: list[dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        out_path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def open_sqlite(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def main() -> None:
    ap = argparse.ArgumentParser(description="Reporte: cruce extract pólizas vs clientes/seguros CRM.")
    ap.add_argument("--csv", required=True, help="CSV del extract (o *_unique.csv).")
    ap.add_argument("--empresa-id", required=True, help="empresa_id (UUID).")
    ap.add_argument("--out-dir", default=str(ROOT / "reports"), help="Directorio de salida.")
    ap.add_argument("--only-poliza", action="store_true", help="Si el CSV tiene doc_kind, filtra a doc_kind=poliza.")
    args = ap.parse_args()

    csv_path = Path(args.csv).expanduser().resolve()
    if not csv_path.exists():
        raise SystemExit(f"No existe: {csv_path}")

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_csv = out_dir / f"seguros_extract_match_{ts}.csv"

    db_path = DB_CONFIGURED
    if not db_path.exists():
        raise SystemExit(f"No existe DB SQLite: {db_path}")

    conn = open_sqlite(db_path)
    try:
        empresa_id = str(args.empresa_id).strip()

        # Clientes asociados a empresa (directo o via clientes_empresas)
        clientes_rows = conn.execute(
            """
            SELECT DISTINCT c.id, c.nombre, c.nif
            FROM clientes c
            LEFT JOIN clientes_empresas ce ON ce.cliente_id=c.id AND ce.empresa_id=?
            WHERE c.empresa_id=? OR ce.empresa_id=?
            """,
            (empresa_id, empresa_id, empresa_id),
        ).fetchall()
        clientes_by_nif: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for r in clientes_rows:
            n = norm_nif(r["nif"])
            if n:
                clientes_by_nif[n].append(r)

        # Seguros por policy key
        seguros_rows = conn.execute(
            """
            SELECT id, cliente_id, tomador, compania, poliza_numero, fecha_efecto
            FROM seguros
            WHERE empresa_id=?
            """,
            (empresa_id,),
        ).fetchall()
        seguros_by_key: dict[PolicyKey, list[sqlite3.Row]] = defaultdict(list)
        seguros_by_client_company: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
        for s in seguros_rows:
            pol = normalize_poliza_key(str(s["poliza_numero"] or ""))
            comp = normalize_company_key(str(s["compania"] or ""))
            if pol:
                seguros_by_key[PolicyKey(pol, comp)].append(s)
            cid = str(s["cliente_id"] or "").strip()
            if cid and comp:
                seguros_by_client_company[(cid, comp)].append(s)

        rows = read_csv(csv_path)
        if args.only_poliza and rows and "doc_kind" in rows[0]:
            rows = [r for r in rows if (r.get("doc_kind") or "") == "poliza"]

        out_rows: list[dict[str, Any]] = []
        stats = Counter()

        for r in rows:
            pol_raw = str(r.get("poliza_numero") or "").strip()
            comp_raw = str(r.get("compania") or "").strip()
            pol = normalize_poliza_key(pol_raw)
            comp = normalize_company_key(comp_raw)
            nif = norm_nif(r.get("nif") or r.get("dni") or "")

            client_candidates = clientes_by_nif.get(nif, []) if nif else []
            client_id = str(client_candidates[0]["id"]) if len(client_candidates) == 1 else ""
            client_nombre = str(client_candidates[0]["nombre"]) if len(client_candidates) == 1 else ""

            seguro_candidates = seguros_by_key.get(PolicyKey(pol, comp), []) if pol else []
            seguro_id = str(seguro_candidates[0]["id"]) if len(seguro_candidates) == 1 else ""

            match_type = "none"
            if seguro_id:
                match_type = "policy_key"
                stats["match_policy_key"] += 1
            elif client_id and comp:
                # existe algún seguro del cliente con esa compañía (aunque no coincida póliza)
                candidates = seguros_by_client_company.get((client_id, comp), [])
                if candidates:
                    match_type = "client_company"
                    stats["match_client_company"] += 1

            if nif:
                stats["with_nif"] += 1
            if client_candidates:
                stats["client_found_by_nif"] += 1
                if len(client_candidates) > 1:
                    stats["client_ambiguous_nif"] += 1
            if pol:
                stats["with_poliza"] += 1

            out_rows.append(
                {
                    "poliza_numero": pol_raw,
                    "poliza_numero_norm": pol,
                    "compania": comp_raw,
                    "compania_norm": comp,
                    "tomador": str(r.get("tomador") or "").strip(),
                    "nif": nif,
                    "cliente_id": client_id,
                    "cliente_nombre": client_nombre,
                    "cliente_candidates": len(client_candidates),
                    "seguro_id": seguro_id,
                    "seguro_candidates": len(seguro_candidates),
                    "match_type": match_type,
                    "path": str(r.get("path") or "").strip(),
                }
            )

        write_csv(out_rows, out_csv)
        summary = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "db": str(db_path),
            "empresa_id": empresa_id,
            "input_csv": str(csv_path),
            "rows": len(rows),
            "stats": dict(stats),
            "output_csv": str(out_csv),
        }
        print(summary)
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

