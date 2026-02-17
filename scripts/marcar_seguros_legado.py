#!/usr/bin/env python3
import argparse
import sqlite3
from pathlib import Path


LEGACY_STATUS = "Migrado legado"


def resolve_empresa_id(conn, empresa_id, empresa_nombre_like):
    if empresa_id:
        return empresa_id
    if not empresa_nombre_like:
        raise SystemExit("Debes indicar --empresa-id o --empresa-nombre-like")
    row = conn.execute(
        "SELECT id, nombre FROM empresas WHERE UPPER(nombre) LIKE UPPER(?) LIMIT 1",
        (f"%{empresa_nombre_like}%",),
    ).fetchone()
    if not row:
        raise SystemExit(f"No se encontró empresa con LIKE '{empresa_nombre_like}'")
    print(f"empresa_id={row['id']} nombre={row['nombre']}")
    return row["id"]


def main():
    parser = argparse.ArgumentParser(
        description="Marca pólizas de seguros como legado para excluirlas del operativo actual."
    )
    parser.add_argument("--db", required=True, help="Ruta sqlite")
    parser.add_argument("--empresa-id", default="", help="Empresa ID")
    parser.add_argument("--empresa-nombre-like", default="", help="Resolver empresa por nombre")
    parser.add_argument(
        "--scope",
        choices=["no-doc", "all"],
        default="no-doc",
        help="no-doc: solo pólizas sin poliza_key/poliza_url. all: todas las pólizas de la empresa.",
    )
    parser.add_argument("--apply", action="store_true", help="Aplicar cambios (por defecto dry-run)")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"No existe DB: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        empresa_id = resolve_empresa_id(conn, args.empresa_id.strip(), args.empresa_nombre_like.strip())
        where = [
            "empresa_id = ?",
            "(estado IS NULL OR TRIM(estado) = '' OR LOWER(TRIM(estado)) NOT LIKE '%legado%')",
        ]
        params = [empresa_id]
        if args.scope == "no-doc":
            where.append("(poliza_key IS NULL OR TRIM(poliza_key) = '')")
            where.append("(poliza_url IS NULL OR TRIM(poliza_url) = '')")
        sql_where = " AND ".join(where)
        rows = conn.execute(
            f"""
            SELECT id, tomador, compania, poliza_numero, estado, poliza_key, poliza_url
            FROM seguros
            WHERE {sql_where}
            ORDER BY created_at, id
            """,
            params,
        ).fetchall()
        print(f"candidatas={len(rows)} scope={args.scope}")
        for row in rows[:15]:
            print(
                f"- {row['id']} | {row['tomador'] or ''} | {row['compania'] or ''} | "
                f"{row['poliza_numero'] or ''} | estado={row['estado'] or ''}"
            )
        if not args.apply:
            print("dry-run: añade --apply para ejecutar UPDATE")
            return
        conn.execute(
            f"UPDATE seguros SET estado = ?, updated_at = datetime('now') WHERE {sql_where}",
            [LEGACY_STATUS, *params],
        )
        conn.commit()
        print(f"rows_updated={conn.total_changes}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
