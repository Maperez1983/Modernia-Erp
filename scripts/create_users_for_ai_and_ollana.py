#!/usr/bin/env python3
"""Crear/actualizar un par de usuarios base para IA y Ollana."""

import argparse
import os
import secrets
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.auth_security import hash_password  # noqa: E402
from web.db_backend import is_postgres_enabled, open_db_conn  # noqa: E402
from web.server import ensure_usuarios_schema, ensure_workspace_core_tables  # noqa: E402


def _default_db_path() -> Path:
    configured = os.environ.get("DB_PATH") or os.environ.get("DATABASE_PATH") or ""
    if configured.strip():
        return Path(configured).expanduser()
    return ROOT / "data" / "erp_import2.sqlite"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _random_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#_-"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(16))
        if (
            any(c.islower() for c in pw)
            and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw)
            and any(c in "!@#_-" for c in pw)
        ):
            return pw


def _fetch_workspace_id(conn, workspace_id: str = "", workspace_slug: str = "") -> str:
    if workspace_id:
        row = conn.execute("SELECT id FROM workspaces WHERE id = ? LIMIT 1", (workspace_id,)).fetchone()
        if row:
            return str(row[0])

    if workspace_slug:
        row = conn.execute(
            """
            SELECT id FROM workspaces
            WHERE LOWER(TRIM(COALESCE(slug, ''))) = LOWER(TRIM(?))
               OR LOWER(TRIM(COALESCE(nombre, ''))) = LOWER(TRIM(?))
            LIMIT 1
            """,
            (workspace_slug, workspace_slug),
        ).fetchone()
        if row:
            return str(row[0])

    row = conn.execute("SELECT id FROM workspaces ORDER BY nombre ASC LIMIT 1").fetchone()
    if row:
        return str(row[0])

    raise SystemExit("No existe ninguna workspace en la base de datos.")


def _find_user(conn, usuario: str, email: str):
    rows = conn.execute(
        """
        SELECT id, nombre, apellido, usuario, email, rol, servicio, activo, password_hash
        FROM usuarios
        WHERE LOWER(TRIM(COALESCE(usuario, ''))) = LOWER(TRIM(?))
           OR LOWER(TRIM(COALESCE(email, ''))) = LOWER(TRIM(?))
        LIMIT 10
        """,
        (usuario, email),
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise SystemExit(f"Login ambiguo para {usuario!r} / {email!r} (hay más de un usuario).")
    return rows[0]


def _upsert_user(
    conn,
    *,
    usuario: str,
    email: str,
    nombre: str,
    apellido: str,
    rol: str,
    servicio: str,
    password: str,
    reset_password: bool,
    workspace_id: str,
    workspace_role: str,
) -> dict:
    now = _now_iso()
    row = _find_user(conn, usuario, email)

    if row is None:
        user_id = os.urandom(16).hex()
        conn.execute(
            """
            INSERT INTO usuarios
            (id, nombre, apellido, usuario, email, servicio, rol, registro_horario_activo, password_hash, activo, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                nombre,
                apellido,
                usuario,
                email,
                servicio,
                rol,
                1,
                hash_password(password),
                1,
                now,
                now,
            ),
        )
        created = True
    else:
        user_id = str(row[0])
        updates = [
            "nombre = ?",
            "apellido = ?",
            "usuario = ?",
            "email = ?",
            "servicio = ?",
            "rol = ?",
            "activo = 1",
        ]
        values = [nombre, apellido, usuario, email, servicio, rol]
        if reset_password or not str(row[8] or "").strip():
            updates.append("password_hash = ?")
            updates.append("updated_at = ?")
            values.extend([hash_password(password), now])
        else:
            updates.append("updated_at = ?")
            values.append(now)

        conn.execute(
            f"UPDATE usuarios SET {', '.join(updates)} WHERE id = ?",
            (*values, user_id),
        )
        created = False

    membership_row = conn.execute(
        "SELECT id FROM workspace_miembros WHERE workspace_id = ? AND usuario_id = ? LIMIT 1",
        (workspace_id, user_id),
    ).fetchone()
    if membership_row:
        conn.execute(
            "UPDATE workspace_miembros SET rol = ?, updated_at = ? WHERE id = ?",
            (workspace_role, now, membership_row[0]),
        )
    else:
        conn.execute(
            """
            INSERT INTO workspace_miembros
            (id, workspace_id, usuario_id, rol, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (os.urandom(16).hex(), workspace_id, user_id, workspace_role, now, now),
        )

    return {
        "usuario": usuario,
        "email": email,
        "id": user_id,
        "created": created,
        "password": password,
        "workspace_role": workspace_role,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea/actualiza una cuenta para IA y otra para Ollana.")
    parser.add_argument("--db", default=str(_default_db_path()), help="Ruta a sqlite local (si no hay DB_URL).")
    parser.add_argument("--workspace-id", default="", help="Workspace destino por ID.")
    parser.add_argument("--workspace-slug", default="", help="Workspace destino por slug o nombre.")
    parser.add_argument("--me-user", default="ia_admin", help="Login de tu cuenta IA.")
    parser.add_argument("--me-email", default="ia_admin@verifika2.local", help="Email de tu cuenta IA.")
    parser.add_argument("--ollana-user", default="ollana", help="Login de Ollana.")
    parser.add_argument("--ollana-email", default="ollana@verifika2.local", help="Email de Ollana.")
    parser.add_argument("--me-password", default="", help="Contraseña de tu cuenta (opcional).")
    parser.add_argument("--ollana-password", default="", help="Contraseña de Ollana (opcional).")
    parser.add_argument("--reset-passwords", action="store_true", help="Reescribe contraseña aunque ya exista.")
    parser.add_argument("--dry-run", action="store_true", help="No escribe cambios.")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not is_postgres_enabled() and not db_path.exists():
        raise SystemExit(f"DB no encontrada: {db_path}")

    conn = open_db_conn(str(db_path), with_row_factory=False)
    try:
        ensure_usuarios_schema(conn)
        ensure_workspace_core_tables(conn)

        workspace_id = _fetch_workspace_id(conn, workspace_id=args.workspace_id, workspace_slug=args.workspace_slug)
        print(f"[ok] Workspace objetivo: {workspace_id}")

        me_password = args.me_password.strip() or _random_password()
        ollana_password = args.ollana_password.strip() or _random_password()

        if args.dry_run:
            conn.rollback()
            print("[dry-run] No se escribirá nada.")
            return

        me_user = _upsert_user(
            conn,
            usuario=args.me_user.strip(),
            email=args.me_email.strip(),
            nombre="Asistente",
            apellido="IA",
            rol="Administrador",
            servicio="Administración,Inmobiliaria,Fincas,Seguros,Gestoría,Financiaciones",
            password=me_password,
            reset_password=args.reset_passwords,
            workspace_id=workspace_id,
            workspace_role="Owner",
        )
        ollana_user = _upsert_user(
            conn,
            usuario=args.ollana_user.strip(),
            email=args.ollana_email.strip(),
            nombre="Ollana",
            apellido="Asistente",
            rol="Lectura",
            servicio="Inmobiliaria",
            password=ollana_password,
            reset_password=args.reset_passwords,
            workspace_id=workspace_id,
            workspace_role="Miembro",
        )

        conn.commit()

        for item in (me_user, ollana_user):
            action = "creado" if item["created"] else "actualizado"
            print(f"- {item['usuario']} ({item['email']}) {action}")
            print(f"  id: {item['id']} | workspace: {workspace_id} ({item['workspace_role']})")
            print(f"  contraseña: {item['password']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
