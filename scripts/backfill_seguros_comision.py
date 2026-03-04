#!/usr/bin/env python3
import argparse
import sqlite3
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "erp_import2.sqlite"


def norm(value: str) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def tipo_from_produccion(produccion: str) -> str:
    p = norm(produccion)
    if "cambio" in p:
        return "cartera"
    return "nueva produccion"


def parse_ramo_tipo(ramo_value: str):
    raw = str(ramo_value or "").strip()
    if raw.endswith("]") and "[" in raw:
        left, right = raw.rsplit("[", 1)
        return norm(left), norm(right[:-1])
    return norm(raw), ""


def score(rule, compania, ramo, tipo):
    row_comp = norm(rule["compania"])
    if not row_comp or row_comp != compania:
        return -1
    row_ramo, row_tipo = parse_ramo_tipo(rule["ramo"])
    s = 10
    if row_ramo and ramo:
        if row_ramo == ramo:
            s += 60
        elif ramo in row_ramo or row_ramo in ramo:
            s += 35
        else:
            s -= 20
    if row_tipo == tipo:
        s += 30
    elif "general" in row_tipo:
        s += 10
    elif "variable" in row_tipo:
        s += 5
    elif row_tipo:
        s -= 10
    return s


def best_pct(rules, compania, ramo, produccion):
    c = norm(compania)
    if not c:
        return None
    r = norm(ramo)
    t = tipo_from_produccion(produccion)
    best = None
    best_score = -1
    for rule in rules:
        s = score(rule, c, r, t)
        if s > best_score:
            best_score = s
            best = rule
    if not best or best_score < 20:
        return None
    try:
        return float(best["porcentaje"] or 0)
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Persistir cambios en DB")
    args = parser.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        rules = conn.execute(
            "SELECT compania, ramo, porcentaje FROM seguros_comisiones WHERE porcentaje IS NOT NULL"
        ).fetchall()
        seguros = conn.execute(
            "SELECT id, compania, ramo, produccion, prima_total, comision FROM seguros"
        ).fetchall()

        scanned = 0
        candidates = 0
        updates = []
        for row in seguros:
            scanned += 1
            try:
                prima_total = float(row["prima_total"] or 0)
            except Exception:
                prima_total = 0.0
            if prima_total <= 0:
                continue
            pct = best_pct(rules, row["compania"], row["ramo"], row["produccion"])
            if pct is None:
                continue
            candidates += 1
            new_commission = round((prima_total * pct) / 100.0, 2)
            old = row["comision"]
            old_num = float(old) if old not in (None, "") else None
            if old_num is None or abs(old_num - new_commission) > 0.009:
                updates.append((new_commission, row["id"]))

        if args.apply and updates:
            conn.executemany(
                "UPDATE seguros SET comision = ?, updated_at = datetime('now') WHERE id = ?",
                updates,
            )
            conn.commit()

        print(f"scanned={scanned}")
        print(f"rules={len(rules)}")
        print(f"candidates={candidates}")
        print(f"updates={len(updates)}")
        print(f"mode={'apply' if args.apply else 'dry-run'}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
