#!/usr/bin/env python3
import argparse
import os
from web.db_backend import open_db_conn
from pathlib import Path


def _default_db_path():
    configured = os.environ.get("DB_PATH") or os.environ.get("DATABASE_PATH") or ""
    if configured.strip():
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / "data" / "erp_import2.sqlite"


def main():
    parser = argparse.ArgumentParser(description="Busca usuarios por texto (nombre/apellido/usuario/email).")
    parser.add_argument("--db", default=str(_default_db_path()), help="Ruta al sqlite principal.")
    parser.add_argument("--q", required=True, help="Texto a buscar (parcial).")
    parser.add_argument("--limit", type=int, default=20, help="Máximo de resultados.")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        raise SystemExit(f"DB no encontrada: {db_path}")

    q = str(args.q or "").strip()
    if not q:
        raise SystemExit("--q vacío.")

    limit = max(1, min(int(args.limit or 20), 200))

    conn = open_db_conn(str(db_path), with_row_factory=True)
    try:
        try:
            conn.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone()
        except Exception:
            raise SystemExit("Tabla usuarios no existe o DB no inicializada.")

        like = f"%{q}%"
        rows = conn.execute(
            """
            SELECT id, nombre, apellido, usuario, email, activo
            FROM usuarios
            WHERE LOWER(COALESCE(nombre, '')) LIKE LOWER(?)
               OR LOWER(COALESCE(apellido, '')) LIKE LOWER(?)
               OR LOWER(COALESCE(usuario, '')) LIKE LOWER(?)
               OR LOWER(COALESCE(email, '')) LIKE LOWER(?)
            ORDER BY COALESCE(activo, 1) DESC, nombre COLLATE NOCASE ASC, apellido COLLATE NOCASE ASC
            LIMIT ?
            """,
            (like, like, like, like, limit),
        ).fetchall()

        if not rows:
            print("Sin resultados.")
            return

        for row in rows:
            full_name = " ".join(x for x in [row["nombre"] or "", row["apellido"] or ""] if x).strip()
            print(f"- id={row['id']} activo={row['activo']} usuario={row['usuario']!r} email={row['email']!r} nombre={full_name!r}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
