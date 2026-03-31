#!/usr/bin/env python3
import argparse
import os
import sqlite3
from pathlib import Path


def _default_db_path():
    configured = os.environ.get("DB_PATH") or os.environ.get("DATABASE_PATH") or ""
    if configured.strip():
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / "data" / "erp_import2.sqlite"


def main():
    parser = argparse.ArgumentParser(description="Audita duplicados en tabla usuarios.")
    parser.add_argument("--db", default=str(_default_db_path()), help="Ruta al sqlite principal (por defecto data/erp_import2.sqlite)")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        raise SystemExit(f"DB no encontrada: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'usuarios' LIMIT 1"
        ).fetchone()
        if not has_table:
            raise SystemExit("Tabla usuarios no existe en esta DB.")

        users = conn.execute(
            """
            SELECT id, nombre, apellido, usuario, email, servicio, rol, activo, created_at, updated_at
            FROM usuarios
            ORDER BY created_at ASC
            """
        ).fetchall()

        by_usuario = {}
        by_email = {}
        whitespace_issues = []
        for row in users:
            usuario = str(row["usuario"] or "")
            email = str(row["email"] or "")
            usuario_key = usuario.strip().lower()
            email_key = email.strip().lower()
            if usuario and usuario != usuario.strip():
                whitespace_issues.append(("usuario", row["id"], usuario))
            if email and email != email.strip():
                whitespace_issues.append(("email", row["id"], email))
            if usuario_key:
                by_usuario.setdefault(usuario_key, []).append(row)
            if email_key:
                by_email.setdefault(email_key, []).append(row)

        dup_usuario = {k: v for k, v in by_usuario.items() if len(v) > 1}
        dup_email = {k: v for k, v in by_email.items() if len(v) > 1}

        print(f"DB: {db_path}")
        print(f"Total usuarios: {len(users)}")
        print()

        if whitespace_issues:
            print("Campos con espacios al inicio/fin:")
            for field, user_id, value in whitespace_issues:
                print(f"- {field}: id={user_id} value={value!r}")
            print()

        if dup_usuario:
            print("Duplicados por usuario (case/trim-insensitive):")
            for key, rows in sorted(dup_usuario.items(), key=lambda kv: kv[0]):
                print(f"- usuario_key={key!r} ({len(rows)} registros)")
                for r in rows:
                    nombre = f"{r['nombre'] or ''} {r['apellido'] or ''}".strip()
                    print(f"  - id={r['id']} usuario={r['usuario']!r} email={r['email']!r} activo={r['activo']} nombre={nombre!r}")
            print()
        else:
            print("Sin duplicados por usuario (case/trim-insensitive).")
            print()

        if dup_email:
            print("Duplicados por email (case/trim-insensitive):")
            for key, rows in sorted(dup_email.items(), key=lambda kv: kv[0]):
                print(f"- email_key={key!r} ({len(rows)} registros)")
                for r in rows:
                    nombre = f"{r['nombre'] or ''} {r['apellido'] or ''}".strip()
                    print(f"  - id={r['id']} usuario={r['usuario']!r} email={r['email']!r} activo={r['activo']} nombre={nombre!r}")
            print()
        else:
            print("Sin duplicados por email (case/trim-insensitive).")
            print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()

