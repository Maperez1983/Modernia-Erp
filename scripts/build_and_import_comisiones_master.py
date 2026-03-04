#!/usr/bin/env python3
import csv
import hashlib
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "comisiones_companias_extraidas.csv"
MASTER = ROOT / "data" / "comisiones_companias_master.csv"
DB = ROOT / "data" / "erp_import2.sqlite"


def expand_tipo(tipo: str, pct: str):
    t = (tipo or "").strip().lower()
    if t == "np/cartera":
        return [("Nueva producción", pct), ("Cartera", pct)]
    if t == "primer año":
        return [("Nueva producción", pct)]
    if t in {"años sucesivos", "anos sucesivos"}:
        return [("Cartera", pct)]
    if t == "nueva producción":
        return [("Nueva producción", pct)]
    if t == "cartera":
        return [("Cartera", pct)]
    if t == "sobre prima neta":
        return [("General", pct)]
    if t == "variable":
        return [("Variable", pct)]
    if tipo:
        return [(tipo, pct)]
    return [("General", pct)]


def normalize_ramo(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "General"
    return " ".join(raw.replace("\n", " ").split())


def make_id(compania: str, ramo: str, tipo: str, porcentaje: str, notas: str) -> str:
    blob = f"{compania}|{ramo}|{tipo}|{porcentaje}|{notas}".encode("utf-8")
    return hashlib.md5(blob).hexdigest()


def build_master_rows():
    rows = []
    with INPUT.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            compania = (row.get("compania") or "").strip()
            archivo = (row.get("archivo") or "").strip()
            ramo = normalize_ramo(row.get("producto_ramo"))
            tipo = (row.get("tipo") or "").strip()
            pct = (row.get("comision_pct") or "").strip()
            condiciones = (row.get("condiciones") or "").strip()
            confidence = (row.get("confidence") or "").strip()
            for tipo_exp, pct_exp in expand_tipo(tipo, pct):
                notas = f"origen={archivo}; tipo_origen={tipo}; confianza={confidence}; condiciones={condiciones}"
                rows.append(
                    {
                        "id": make_id(compania, ramo, tipo_exp, pct_exp, notas),
                        "compania": compania,
                        "ramo": ramo,
                        "tipo_comision": tipo_exp,
                        "porcentaje": pct_exp,
                        "vigencia_desde": "",
                        "vigencia_hasta": "",
                        "notas": notas,
                        "origen_archivo": archivo,
                    }
                )
    return rows


def write_master_csv(rows):
    fields = [
        "id",
        "compania",
        "ramo",
        "tipo_comision",
        "porcentaje",
        "vigencia_desde",
        "vigencia_hasta",
        "notas",
        "origen_archivo",
    ]
    with MASTER.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def import_into_sqlite(rows):
    conn = sqlite3.connect(DB)
    try:
        conn.execute("DELETE FROM seguros_comisiones")
        now = "now"
        for row in rows:
            conn.execute(
                """
                INSERT INTO seguros_comisiones (
                  id, compania, ramo, porcentaje, vigencia_desde, vigencia_hasta, notas, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    row["id"],
                    row["compania"],
                    f"{row['ramo']} [{row['tipo_comision']}]",
                    float(row["porcentaje"] or 0),
                    row["vigencia_desde"] or None,
                    row["vigencia_hasta"] or None,
                    row["notas"],
                    now,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def main():
    rows = build_master_rows()
    write_master_csv(rows)
    import_into_sqlite(rows)
    print(f"master_rows={len(rows)}")


if __name__ == "__main__":
    main()
