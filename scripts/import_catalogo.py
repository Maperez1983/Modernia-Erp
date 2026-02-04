#!/usr/bin/env python3
import argparse
import csv
import sqlite3
from pathlib import Path


def detect_delimiter(sample):
    for delim in (";", ",", "\t", "|"):
        if delim in sample:
            return delim
    return ","


def load_csv_rows(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    delim = detect_delimiter(text[:2000])
    rows = []
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        reader = csv.reader(fh, delimiter=delim)
        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue
            rows.append(row)
    return rows


def infer_columns(rows):
    header = [c.strip().lower() for c in rows[0]]
    if "codigo" in header and "descripcion" in header:
        return header.index("codigo"), header.index("descripcion"), True
    return 0, 1 if len(rows[0]) > 1 else 0, False


def main():
    parser = argparse.ArgumentParser(description="Importar catálogo CNAE/IAE a SQLite")
    parser.add_argument("--db", required=True, help="Ruta a la base de datos SQLite")
    parser.add_argument("--tipo", required=True, choices=["cnae", "iae"], help="Tipo de catálogo")
    parser.add_argument("--file", required=True, help="CSV con columnas codigo, descripcion")
    args = parser.parse_args()

    db_path = Path(args.db)
    file_path = Path(args.file)
    if not db_path.exists():
        raise SystemExit("DB no encontrada")
    if not file_path.exists():
        raise SystemExit("CSV no encontrado")

    rows = load_csv_rows(file_path)
    if not rows:
        raise SystemExit("CSV vacío")

    idx_codigo, idx_desc, has_header = infer_columns(rows)
    if has_header:
        rows = rows[1:]

    table = "cnae_catalogo" if args.tipo == "cnae" else "iae_catalogo"
    conn = sqlite3.connect(db_path)
    conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (codigo TEXT PRIMARY KEY, descripcion TEXT NOT NULL)")
    conn.execute(f"DELETE FROM {table}")
    to_insert = []
    for row in rows:
        if len(row) <= max(idx_codigo, idx_desc):
            continue
        codigo = row[idx_codigo].strip()
        descripcion = row[idx_desc].strip()
        if not codigo or not descripcion:
            continue
        to_insert.append((codigo, descripcion))
    conn.executemany(
        f"INSERT OR REPLACE INTO {table} (codigo, descripcion) VALUES (?, ?)",
        to_insert,
    )
    conn.commit()
    conn.close()
    print(f"Importados {len(to_insert)} registros en {table}")


if __name__ == "__main__":
    main()
