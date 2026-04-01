#!/usr/bin/env python3
import argparse
import os
import sys
from getpass import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.db_backend import is_postgres_enabled, open_db_conn  # noqa: E402

from web.auth_security import hash_password  # noqa: E402


def _default_db_path():
    configured = os.environ.get("DB_PATH") or os.environ.get("DATABASE_PATH") or ""
    if configured.strip():
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / "data" / "erp_import2.sqlite"


def find_users(conn, login):
    value = str(login or "").strip()
    if not value:
        return []
    return conn.execute(
        """
        SELECT id, nombre, apellido, usuario, email, servicio, rol, activo
        FROM usuarios
        WHERE LOWER(TRIM(COALESCE(usuario, ''))) = LOWER(TRIM(?))
           OR LOWER(TRIM(COALESCE(email, ''))) = LOWER(TRIM(?))
        """,
        (value, value),
    ).fetchall()


def main():
    parser = argparse.ArgumentParser(description="Resetea la contraseña de un usuario (por usuario o email).")
    parser.add_argument("--db", default=str(_default_db_path()), help="Ruta al sqlite principal.")
    parser.add_argument("--login", required=True, help="Usuario o email para localizar la cuenta.")
    parser.add_argument("--activate", action="store_true", help="Marca la cuenta como activa antes del reset.")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not is_postgres_enabled() and not db_path.exists():
        raise SystemExit(f"DB no encontrada: {db_path}")

    conn = open_db_conn(str(db_path), with_row_factory=True)
    try:
        try:
            conn.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone()
        except Exception:
            raise SystemExit("Tabla usuarios no existe o DB no inicializada.")

        matches = find_users(conn, args.login)
        if not matches:
            raise SystemExit("No se encontró ningún usuario con ese login (usuario/email).")
        if len(matches) > 1:
            print("Login ambiguo: hay más de un usuario con ese mismo usuario/email (case/trim-insensitive).")
            for row in matches:
                full_name = " ".join(x for x in [row["nombre"] or "", row["apellido"] or ""] if x).strip()
                print(
                    f"- id={row['id']} usuario={row['usuario']!r} email={row['email']!r} activo={row['activo']} nombre={full_name!r}"
                )
            print("Solución: corrige duplicados (renombra `usuario` o cambia `email`) y reintenta.")
            raise SystemExit(2)

        user = matches[0]
        full_name = " ".join(x for x in [user["nombre"] or "", user["apellido"] or ""] if x).strip()
        print(f"Encontrado: id={user['id']} usuario={user['usuario']!r} email={user['email']!r} activo={user['activo']} nombre={full_name!r}")

        if args.activate and int(user["activo"] or 0) != 1:
            conn.execute("UPDATE usuarios SET activo = 1, updated_at = datetime('now') WHERE id = ?", (user["id"],))
            conn.commit()
            print("Cuenta activada (activo=1).")

        while True:
            pw1 = getpass("Nueva contraseña (mín 8): ")
            if not pw1 or len(pw1) < 8:
                print("La contraseña debe tener al menos 8 caracteres.")
                continue
            pw2 = getpass("Repite la contraseña: ")
            if pw1 != pw2:
                print("No coincide. Reintenta.")
                continue
            break

        pw_hash = hash_password(pw1)
        conn.execute(
            """
            UPDATE usuarios
            SET password_hash = ?, invite_token = NULL, invite_expires_at = NULL, updated_at = datetime('now')
            WHERE id = ?
            """,
            (pw_hash, user["id"]),
        )
        conn.commit()
        print("Contraseña actualizada. Ya puedes iniciar sesión.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
