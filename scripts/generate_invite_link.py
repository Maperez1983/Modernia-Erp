#!/usr/bin/env python3
import argparse
import os
import secrets
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.db_backend import is_postgres_enabled, open_db_conn  # noqa: E402


def _default_db_path():
    configured = os.environ.get("DB_PATH") or os.environ.get("DATABASE_PATH") or ""
    if configured.strip():
        return Path(configured).expanduser()
    return ROOT / "data" / "erp_import2.sqlite"


def _default_base_url():
    configured = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
    return configured or "http://localhost:8000"


def _invite_ttl_seconds():
    raw = str(os.environ.get("AUTH_INVITE_TTL_SECONDS") or "172800").strip()
    try:
        return max(1800, int(raw))
    except Exception:
        return 172800


def find_users(conn, login):
    value = str(login or "").strip()
    if not value:
        return []
    return conn.execute(
        """
        SELECT id, nombre, apellido, usuario, email, activo
        FROM usuarios
        WHERE LOWER(TRIM(COALESCE(usuario, ''))) = LOWER(TRIM(?))
           OR LOWER(TRIM(COALESCE(email, ''))) = LOWER(TRIM(?))
        """,
        (value, value),
    ).fetchall()


def main():
    parser = argparse.ArgumentParser(description="Genera (o renueva) un enlace de activación para definir contraseña.")
    parser.add_argument("--db", default=str(_default_db_path()), help="Ruta al sqlite principal.")
    parser.add_argument("--login", required=True, help="Usuario o email para localizar la cuenta.")
    parser.add_argument("--base-url", default=_default_base_url(), help="Base URL pública (por defecto APP_BASE_URL o http://localhost:8000).")
    parser.add_argument("--activate", action="store_true", help="Marca la cuenta como activa antes de generar el enlace.")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not is_postgres_enabled() and not db_path.exists():
        raise SystemExit(f"DB no encontrada: {db_path}")

    base_url = str(args.base_url or "").strip().rstrip("/")
    if not base_url:
        raise SystemExit("base-url vacío.")

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
                print(f"- id={row['id']} usuario={row['usuario']!r} email={row['email']!r} activo={row['activo']} nombre={full_name!r}")
            raise SystemExit(2)

        user = matches[0]
        if args.activate and int(user["activo"] or 0) != 1:
            conn.execute("UPDATE usuarios SET activo = 1, updated_at = datetime('now') WHERE id = ?", (user["id"],))
            conn.commit()

        ttl_seconds = _invite_ttl_seconds()
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
        conn.execute(
            """
            UPDATE usuarios
            SET invite_token = ?, invite_expires_at = ?, invite_sent_at = datetime('now'), updated_at = datetime('now')
            WHERE id = ?
            """,
            (token, expires_at, user["id"]),
        )
        conn.commit()

        invite_link = f"{base_url}/?activar_token={urllib.parse.quote(token)}"
        hours = int(round(ttl_seconds / 3600))
        print(invite_link)
        print(f"(Caduca en ~{hours}h; expires_at={expires_at})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
