#!/usr/bin/env python3
"""
Reconciliación (dry-run por defecto) entre el CRM (tabla `seguros`) y un extract CSV.

Uso típico:
  1) Extraer PDFs a CSV: scripts/extract_seguros_pdfs_local.py
  2) (Opcional) generar unique CSV: scripts/analyze_seguros_extract.py
  3) Reconciliar con DB del CRM:
       python3 scripts/reconcile_seguros_with_extract.py --csv reports/..._unique.csv --empresa-id <uuid>

Objetivos:
  - Medir cobertura: cuántas pólizas del extract casan con CRM
  - Proponer updates de campos vacíos en CRM con datos extraídos
  - (Opcional) aplicar updates con --apply

Soporta SQLite (local) y Postgres (si hay POSTGRES_URL/DATABASE_URL).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from web.server import (  # noqa: E402
    DB_CONFIGURED,
    normalize_company_key,
    normalize_poliza_key,
)


PLACEHOLDER_VALUES = {"poliza_key", "poliza_url", "doc_key", "doc_url"}


@dataclass(frozen=True)
class Key:
    poliza_norm: str
    compania_norm: str

    def as_str(self) -> str:
        return f"{self.poliza_norm}|{self.compania_norm}"


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


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


def is_postgres_enabled() -> bool:
    return bool((os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or "").strip())


def open_sqlite(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def open_postgres():
    import psycopg
    from psycopg.rows import dict_row

    dsn = (os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not dsn:
        raise RuntimeError("No hay POSTGRES_URL/DATABASE_URL")
    return psycopg.connect(dsn, row_factory=dict_row)


def list_empresas(conn) -> list[dict[str, Any]]:
    sql = "SELECT id, nombre FROM empresas ORDER BY nombre"
    cur = conn.execute(sql) if hasattr(conn, "execute") else conn.cursor().execute(sql)  # type: ignore
    rows = cur.fetchall()
    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
        else:
            out.append({"id": r["id"], "nombre": r["nombre"]})
    return out


def fetch_seguros(conn, empresa_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT
          id, empresa_id,
          tomador, compania, ramo, poliza_numero,
          fecha_efecto, fecha_vencimiento,
          prima_neta, prima_total, comision,
          produccion, colaborador,
          estado, estado_poliza,
          poliza_key, poliza_url,
          cliente_id,
          (SELECT nif FROM clientes WHERE clientes.id = seguros.cliente_id) AS cliente_nif,
          created_at, updated_at
        FROM seguros
        WHERE empresa_id = %s
    """
    if isinstance(conn, sqlite3.Connection):
        sql = sql.replace("%s", "?")
    cur = conn.execute(sql, (empresa_id,))
    rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
        else:
            out.append(dict(r))
    return out


def clean_text(v: Any) -> str:
    s = str(v or "").strip()
    return s


def normalize_nif(value: Any) -> str:
    return clean_text(value).upper().replace(" ", "").replace("-", "").replace(".", "")


def normalize_date(value: Any) -> str:
    s = clean_text(value)
    if not s:
        return ""
    # YYYY-MM-DD
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    # DD/MM/YYYY o DD-MM-YYYY
    for sep in ("/", "-"):
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 3 and len(parts[2]) == 4:
                dd, mm, yy = parts[0].zfill(2), parts[1].zfill(2), parts[2]
                if dd.isdigit() and mm.isdigit() and yy.isdigit():
                    return f"{yy}-{mm}-{dd}"
    return s


def normalize_key(poliza: str, compania: str) -> Key:
    return Key(
        poliza_norm=normalize_poliza_key(clean_text(poliza)),
        compania_norm=normalize_company_key(clean_text(compania)),
    )


def should_fill(old: Any, new: Any) -> bool:
    old_s = clean_text(old)
    new_s = clean_text(new)
    if not new_s:
        return False
    if not old_s:
        return True
    if old_s.strip().lower() in PLACEHOLDER_VALUES:
        return True
    return False


def build_updates(db_row: dict[str, Any], extract_row: dict[str, str]) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    # Campos de texto
    for k in ("tomador", "compania", "ramo", "fecha_efecto", "fecha_vencimiento", "produccion", "colaborador", "estado", "estado_poliza"):
        if should_fill(db_row.get(k), extract_row.get(k)):
            updates[k] = clean_text(extract_row.get(k))
    # poliza_numero: solo si está vacío en DB y hay algo en extract
    if should_fill(db_row.get("poliza_numero"), extract_row.get("poliza_numero")):
        updates["poliza_numero"] = clean_text(extract_row.get("poliza_numero"))

    # numéricos (si DB está vacío/0 y extract tiene valor parseable)
    def _parse_float(v: str) -> float | None:
        s = clean_text(v).replace("€", "").strip()
        if not s:
            return None
        # ES format
        s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except Exception:
            return None

    for k in ("prima_neta", "prima_total", "comision"):
        old = db_row.get(k)
        new = _parse_float(extract_row.get(k) or "")
        if new is None:
            continue
        try:
            old_f = float(old or 0.0)
        except Exception:
            old_f = 0.0
        if old is None or old_f == 0.0:
            updates[k] = new

    return updates


def apply_update(conn, seguro_id: str, updates: dict[str, Any]) -> None:
    if not updates:
        return
    cols = list(updates.keys())
    set_sql = ", ".join([f"{c} = %s" for c in cols] + ["updated_at = %s"])
    params = [updates[c] for c in cols] + [datetime.now(timezone.utc).isoformat(), seguro_id]
    sql = f"UPDATE seguros SET {set_sql} WHERE id = %s"
    if isinstance(conn, sqlite3.Connection):
        sql = sql.replace("%s", "?")
    conn.execute(sql, params)


def main() -> None:
    ap = argparse.ArgumentParser(description="Reconciliar tabla `seguros` con CSV de extracción.")
    ap.add_argument("--csv", required=True, help="CSV de extract (idealmente el *_unique.csv).")
    ap.add_argument("--empresa-id", default="", help="empresa_id a reconciliar (UUID/text).")
    ap.add_argument("--list-empresas", action="store_true", help="Lista empresas en la DB y sale.")
    ap.add_argument("--out-dir", default=str(ROOT / "reports"), help="Directorio de salida.")
    ap.add_argument("--apply", action="store_true", help="Aplica updates en DB (PELIGRO).")
    args = ap.parse_args()

    csv_path = Path(args.csv).expanduser().resolve()
    if not csv_path.exists():
        raise SystemExit(f"No existe: {csv_path}")

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = _now_ts()
    base = f"seguros_reconcile_{ts}"
    summary_path = out_dir / f"{base}_summary.json"
    updates_path = out_dir / f"{base}_updates.csv"
    missing_in_crm_path = out_dir / f"{base}_missing_in_crm.csv"
    unmatched_in_extract_path = out_dir / f"{base}_unmatched_in_extract.csv"

    # Open DB
    if is_postgres_enabled():
        conn = open_postgres()
        db_kind = "postgres"
        db_ref = "env:POSTGRES_URL|DATABASE_URL"
    else:
        db_path = DB_CONFIGURED
        if not db_path.exists():
            raise SystemExit(f"No existe DB SQLite: {db_path}")
        conn = open_sqlite(db_path)
        db_kind = "sqlite"
        db_ref = str(db_path)

    try:
        if args.list_empresas:
            empresas = list_empresas(conn)
            print(json.dumps({"db": {"kind": db_kind, "ref": db_ref}, "empresas": empresas}, ensure_ascii=False, indent=2))
            return

        empresa_id = clean_text(args.empresa_id)
        if not empresa_id:
            raise SystemExit("Falta --empresa-id (o usa --list-empresas).")

        seguros = fetch_seguros(conn, empresa_id)
        seguros_by_key: dict[Key, dict[str, Any]] = {}
        seguros_by_nif_company: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for s in seguros:
            k = normalize_key(s.get("poliza_numero") or "", s.get("compania") or "")
            if not k.poliza_norm:
                # index por NIF+compañía para fallback si hay cliente vinculado
                nif_norm = normalize_nif(s.get("cliente_nif") or "")
                comp_norm = normalize_company_key(clean_text(s.get("compania") or ""))
                if nif_norm and comp_norm:
                    seguros_by_nif_company.setdefault((nif_norm, comp_norm), []).append(s)
                continue
            # Si hay colisión, nos quedamos con el que tenga más datos (heurística simple)
            prev = seguros_by_key.get(k)
            if not prev:
                seguros_by_key[k] = s
            else:
                prev_score = sum(1 for f in ("tomador", "fecha_efecto", "fecha_vencimiento", "ramo") if clean_text(prev.get(f)))
                s_score = sum(1 for f in ("tomador", "fecha_efecto", "fecha_vencimiento", "ramo") if clean_text(s.get(f)))
                if s_score > prev_score:
                    seguros_by_key[k] = s

        extract_rows = read_csv(csv_path)
        # Si viene del analyze unique, no hay doc_kind; si viene del extract sí.
        if extract_rows and "doc_kind" in extract_rows[0]:
            # Por defecto, nos quedamos con pólizas (si el CSV tiene doc_kind)
            extract_rows = [r for r in extract_rows if (r.get("doc_kind") or "") == "poliza"]

        matched = 0
        matched_by_policy = 0
        matched_by_nif_fallback = 0
        update_rows: list[dict[str, Any]] = []
        missing_in_crm: list[dict[str, Any]] = []
        used_db_ids: set[str] = set()
        ambiguous_fallback: list[dict[str, Any]] = []

        for r in extract_rows:
            pol = clean_text(r.get("poliza_numero") or "")
            comp = clean_text(r.get("compania") or "")
            k = normalize_key(pol, comp)
            if not k.poliza_norm:
                continue
            db_row = seguros_by_key.get(k)
            matched_via_fallback = False
            if not db_row:
                # fallback: si el CSV tiene nif/dni, intenta casar con seguros sin poliza_numero vía cliente_nif+compañía
                nif_norm = normalize_nif(r.get("nif") or r.get("dni") or "")
                comp_norm = normalize_company_key(comp)
                candidates = seguros_by_nif_company.get((nif_norm, comp_norm), []) if (nif_norm and comp_norm) else []
                if candidates:
                    # Prioriza: póliza vacía + fecha_efecto más parecida
                    eff = normalize_date(r.get("fecha_efecto") or "")
                    ranked = []
                    for c in candidates:
                        c_pol = clean_text(c.get("poliza_numero") or "")
                        c_eff = normalize_date(c.get("fecha_efecto") or "")
                        score = 0
                        if not c_pol:
                            score += 10
                        if eff and c_eff and eff == c_eff:
                            score += 5
                        ranked.append((score, c))
                    ranked.sort(key=lambda t: t[0], reverse=True)
                    # Si el mejor candidato es claramente único (score estrictamente mayor)
                    if len(ranked) == 1 or ranked[0][0] > ranked[1][0]:
                        db_row = ranked[0][1]
                        matched_by_nif_fallback += 1
                        matched_via_fallback = True
                    else:
                        ambiguous_fallback.append(
                            {
                                "poliza_numero": pol,
                                "compania": comp,
                                "nif": nif_norm,
                                "fecha_efecto": eff,
                                "candidates": [clean_text(x.get("id") or "") for _s, x in ranked[:6]],
                            }
                        )

            if not db_row:
                missing_in_crm.append(
                    {
                        "poliza_numero": pol,
                        "poliza_numero_norm": k.poliza_norm,
                        "compania": comp,
                        "compania_norm": k.compania_norm,
                        "tomador": clean_text(r.get("tomador") or ""),
                        "fecha_efecto": clean_text(r.get("fecha_efecto") or ""),
                        "fecha_vencimiento": clean_text(r.get("fecha_vencimiento") or ""),
                        "path": clean_text(r.get("path") or ""),
                    }
                )
                continue

            matched += 1
            if not matched_via_fallback:
                matched_by_policy += 1
            used_db_ids.add(clean_text(db_row.get("id") or ""))
            updates = build_updates(db_row, r)
            if updates:
                update_rows.append(
                    {
                        "seguro_id": clean_text(db_row.get("id") or ""),
                        "poliza_key": k.as_str(),
                        "updates_json": json.dumps(updates, ensure_ascii=False),
                    }
                )
                if args.apply:
                    apply_update(conn, clean_text(db_row.get("id") or ""), updates)

        if args.apply:
            conn.commit()

        unmatched_in_extract = []
        for s in seguros:
            sid = clean_text(s.get("id") or "")
            if sid and sid not in used_db_ids:
                unmatched_in_extract.append(
                    {
                        "seguro_id": sid,
                        "poliza_numero": clean_text(s.get("poliza_numero") or ""),
                        "compania": clean_text(s.get("compania") or ""),
                        "tomador": clean_text(s.get("tomador") or ""),
                        "fecha_efecto": clean_text(s.get("fecha_efecto") or ""),
                        "fecha_vencimiento": clean_text(s.get("fecha_vencimiento") or ""),
                    }
                )

        summary = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "db": {"kind": db_kind, "ref": db_ref},
            "empresa_id": empresa_id,
            "input_csv": str(csv_path),
            "extract_rows_total": len(read_csv(csv_path)),
            "extract_rows_used": len(extract_rows),
            "crm_seguros_total": len(seguros),
            "crm_seguros_indexed_by_poliza": len(seguros_by_key),
            "matched_by_poliza_compania": matched,
            "matched_by_policy_key": matched_by_policy,
            "matched_by_nif_fallback": matched_by_nif_fallback,
            "ambiguous_nif_fallback": len(ambiguous_fallback),
            "missing_in_crm": len(missing_in_crm),
            "unmatched_in_extract": len(unmatched_in_extract),
            "updates_proposed": len(update_rows),
            "apply": bool(args.apply),
            "outputs": {
                "updates_csv": str(updates_path),
                "missing_in_crm_csv": str(missing_in_crm_path),
                "unmatched_in_extract_csv": str(unmatched_in_extract_path),
                "ambiguous_fallback_json": str(out_dir / f"{base}_ambiguous_fallback.json"),
                "summary_json": str(summary_path),
            },
        }

        write_csv(update_rows, updates_path)
        write_csv(missing_in_crm, missing_in_crm_path)
        write_csv(unmatched_in_extract, unmatched_in_extract_path)
        (out_dir / f"{base}_ambiguous_fallback.json").write_text(
            json.dumps(ambiguous_fallback, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
