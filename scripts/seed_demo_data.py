#!/usr/bin/env python3
import argparse
import hashlib
import os
import secrets
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.auth_security import hash_password  # noqa: E402
from web.db_backend import open_db_conn  # noqa: E402
from web.server import ensure_tables  # noqa: E402


def _default_db_path():
    configured = os.environ.get("DB_PATH") or os.environ.get("DATABASE_PATH") or ""
    if configured.strip():
        return Path(configured).expanduser()
    return ROOT / "data" / "erp_import2.sqlite"


def stable_id(*parts: str) -> str:
    raw = "|".join(str(p) for p in parts if p is not None)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_workspace(conn, *, slug: str, name: str) -> str:
    row = conn.execute("SELECT id FROM workspaces WHERE slug = ? LIMIT 1", (slug,)).fetchone()
    if row:
        return str(row["id"])
    now = utc_now_iso()
    ws_id = stable_id("workspace", slug)
    conn.execute(
        """
        INSERT INTO workspaces (id, nombre, slug, estado, plan, descripcion, primary_color, accent_color, created_at, updated_at)
        VALUES (?, ?, ?, 'Activo', 'Enterprise', ?, '#3C6E71', '#5F7A61', ?, ?)
        """,
        (ws_id, name, slug, "Workspace demo para pruebas en Render.", now, now),
    )
    return ws_id


def ensure_empresa(conn, *, nombre: str) -> str:
    row = conn.execute("SELECT id FROM empresas WHERE nombre = ? LIMIT 1", (nombre,)).fetchone()
    if row:
        return str(row["id"])
    now = utc_now_iso()
    emp_id = stable_id("empresa", nombre.lower())
    conn.execute(
        "INSERT INTO empresas (id, nombre, activo, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
        (emp_id, nombre, now, now),
    )
    return emp_id


def link_workspace_empresa(conn, *, workspace_id: str, empresa_id: str, rol: str = "Activa") -> None:
    now = utc_now_iso()
    row = conn.execute(
        "SELECT id FROM workspace_empresas WHERE workspace_id = ? AND empresa_id = ? LIMIT 1",
        (workspace_id, empresa_id),
    ).fetchone()
    if row:
        return
    record_id = stable_id("workspace_empresa", workspace_id, empresa_id)
    conn.execute(
        """
        INSERT INTO workspace_empresas (id, workspace_id, empresa_id, rol, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (record_id, workspace_id, empresa_id, rol, now, now),
    )


def enable_workspace_modules(conn, *, workspace_id: str, module_keys: list[str]) -> None:
    now = utc_now_iso()
    for idx, key in enumerate(module_keys):
        key = str(key).strip()
        if not key:
            continue
        row = conn.execute(
            "SELECT id FROM workspace_modulos WHERE workspace_id = ? AND modulo_key = ? LIMIT 1",
            (workspace_id, key),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE workspace_modulos SET enabled = 1, sort_order = ?, updated_at = ? WHERE id = ?",
                (idx, now, row["id"]),
            )
            continue
        record_id = stable_id("workspace_modulo", workspace_id, key)
        conn.execute(
            """
            INSERT INTO workspace_modulos (id, workspace_id, modulo_key, modulo_nombre, categoria, enabled, sort_order, config_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'seed', 1, ?, NULL, ?, ?)
            """,
            (record_id, workspace_id, key, key, idx, now, now),
        )


def ensure_user(
    conn,
    *,
    usuario: str,
    email: str,
    nombre: str,
    apellido: str,
    rol: str,
    servicio: str,
    activo: int = 1,
    registro_horario_activo: int = 1,
    password: Optional[str] = None,
    reset_password: bool = False,
) -> Tuple[str, Optional[str]]:
    usuario = str(usuario or "").strip()
    email = str(email or "").strip()
    row = conn.execute(
        """
        SELECT id, usuario, email, activo
        FROM usuarios
        WHERE LOWER(TRIM(COALESCE(usuario, ''))) = LOWER(TRIM(?))
           OR LOWER(TRIM(COALESCE(email, ''))) = LOWER(TRIM(?))
        LIMIT 1
        """,
        (usuario, email),
    ).fetchone()
    now = utc_now_iso()
    created_password = None
    if password is None and (reset_password or not row):
        created_password = secrets.token_urlsafe(12)
        password = created_password

    if row:
        user_id = str(row["id"])
        conn.execute(
            """
            UPDATE usuarios
            SET nombre = ?, apellido = ?, usuario = ?, email = ?, servicio = ?, rol = ?,
                registro_horario_activo = ?, activo = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (nombre, apellido, usuario, email, servicio, rol, int(registro_horario_activo), int(activo), user_id),
        )
        if reset_password and password:
            conn.execute(
                "UPDATE usuarios SET password_hash = ?, updated_at = datetime('now') WHERE id = ?",
                (hash_password(password), user_id),
            )
        return user_id, created_password

    user_id = stable_id("user", usuario.lower() or email.lower())
    password_hash = hash_password(password or secrets.token_urlsafe(16))
    conn.execute(
        """
        INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, registro_horario_activo, password_hash, activo, created_at, updated_at)
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
            int(registro_horario_activo),
            password_hash,
            int(activo),
            now,
            now,
        ),
    )
    return user_id, created_password


def ensure_persona(
    conn,
    *,
    workspace_id: str,
    empresa_id: str,
    usuario_id: str,
    nombre: str,
    nif: str,
    email: str,
    telefono: str,
    tipo_jornada: str = "Completa",
    horas_pactadas_dia: float = 8.0,
    fecha_alta: Optional[str] = None,
) -> str:
    now = utc_now_iso()
    persona_id = stable_id("persona", workspace_id, usuario_id)
    if fecha_alta is None:
        fecha_alta = date.today().isoformat()
    row = conn.execute(
        "SELECT id FROM workspace_registro_personal WHERE workspace_id = ? AND id = ? LIMIT 1",
        (workspace_id, persona_id),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE workspace_registro_personal
            SET empresa_id = ?, usuario_id = ?, usuario_manual = 1, source = 'manual',
                nombre = ?, nif = ?, email = ?, telefono = ?, tipo_jornada = ?, horas_pactadas_dia = ?,
                fecha_alta = ?, activo = 1, updated_at = datetime('now')
            WHERE workspace_id = ? AND id = ?
            """,
            (
                empresa_id,
                usuario_id,
                nombre,
                nif,
                email,
                telefono,
                tipo_jornada,
                float(horas_pactadas_dia),
                fecha_alta,
                workspace_id,
                persona_id,
            ),
        )
        return persona_id
    conn.execute(
        """
        INSERT INTO workspace_registro_personal (
          id, workspace_id, empresa_id, empresa_manual, usuario_id, usuario_manual, source,
          nombre, nif, email, telefono, tipo_contrato, tipo_jornada, horas_pactadas_dia,
          fecha_alta, activo, notas, created_at, updated_at
        ) VALUES (?, ?, ?, 0, ?, 1, 'manual', ?, ?, ?, ?, 'INDEFINIDO', ?, ?, ?, 1, ?, ?, ?)
        """,
        (
            persona_id,
            workspace_id,
            empresa_id,
            usuario_id,
            nombre,
            nif,
            email,
            telefono,
            tipo_jornada,
            float(horas_pactadas_dia),
            fecha_alta,
            "Seed demo (Render).",
            now,
            now,
        ),
    )
    return persona_id


def ensure_pending_vacation(conn, *, workspace_id: str, empresa_id: str, persona_id: str) -> str:
    today = date.today()
    # Próximo lunes
    days_until_monday = (7 - today.weekday()) % 7
    start = today + timedelta(days=days_until_monday or 7)
    end = start + timedelta(days=4)
    record_id = stable_id("ausencia", workspace_id, persona_id, start.isoformat(), end.isoformat())
    row = conn.execute(
        "SELECT id FROM workspace_rrhh_ausencias WHERE workspace_id = ? AND id = ? LIMIT 1",
        (workspace_id, record_id),
    ).fetchone()
    if row:
        return str(row["id"])
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO workspace_rrhh_ausencias (
          id, workspace_id, empresa_id, persona_id, tipo, fecha_inicio, fecha_fin, estado,
          motivo, comentario, aprobado_por, aprobado_at, rechazado_at, cancelado_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'Vacaciones', ?, ?, 'Solicitada', ?, ?, NULL, NULL, NULL, NULL, ?, ?)
        """,
        (
            record_id,
            workspace_id,
            empresa_id,
            persona_id,
            start.isoformat(),
            end.isoformat(),
            "Seed demo",
            "Solicitud pendiente para validar (demo).",
            now,
            now,
        ),
    )
    return record_id


def main():
    parser = argparse.ArgumentParser(description="Seed reproducible de datos demo (sin PII) para Render.")
    parser.add_argument("--db", default=str(_default_db_path()), help="Ruta a la sqlite (por defecto DB_PATH o data/erp_import2.sqlite).")
    parser.add_argument("--workspace-slug", default="modernia", help="Slug del workspace.")
    parser.add_argument("--workspace-name", default="Grupo Modernia (Demo)", help="Nombre del workspace.")
    parser.add_argument("--reset-passwords", action="store_true", help="Regenera contraseñas de usuarios demo (las imprime).")
    parser.add_argument("--yes", action="store_true", help="Confirma que quieres escribir en la DB.")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not args.yes:
        raise SystemExit("Aborta: añade --yes para confirmar el seed.")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    ensure_tables(str(db_path))

    conn = open_db_conn(str(db_path), with_row_factory=True)
    try:
        workspace_id = ensure_workspace(conn, slug=str(args.workspace_slug).strip(), name=str(args.workspace_name).strip())
        empresa_a = ensure_empresa(conn, nombre="Modernia Demo SL")
        empresa_b = ensure_empresa(conn, nombre="Modernia Fincas Demo SL")
        link_workspace_empresa(conn, workspace_id=workspace_id, empresa_id=empresa_a, rol="Activa")
        link_workspace_empresa(conn, workspace_id=workspace_id, empresa_id=empresa_b, rol="Activa")
        enable_workspace_modules(
            conn,
            workspace_id=workspace_id,
            module_keys=[
                "crm360",
                "documental",
                "facturacion",
                "portal_cliente",
                "registro_horario",
                "rrhh",
                "automatizaciones",
            ],
        )

        # Servicios visibles (para UI): lista amplia.
        servicios_admin = "Gestoría, Seguros, Inmobiliaria, Financiaciones, Administración Fincas, Dirección"

        admin_id, admin_pw = ensure_user(
            conn,
            usuario="admin",
            email="admin@demo.local",
            nombre="Admin",
            apellido="Demo",
            rol="Administrador",
            servicio=servicios_admin,
            registro_horario_activo=1,
            reset_password=bool(args.reset_passwords),
        )

        worker_id, worker_pw = ensure_user(
            conn,
            usuario="empleado",
            email="empleado@demo.local",
            nombre="Empleado",
            apellido="Demo",
            rol="Lectura",
            servicio="RRHH",
            registro_horario_activo=1,
            reset_password=bool(args.reset_passwords),
        )

        admin_persona = ensure_persona(
            conn,
            workspace_id=workspace_id,
            empresa_id=empresa_a,
            usuario_id=admin_id,
            nombre="Admin Demo",
            nif="00000000T",
            email="admin@demo.local",
            telefono="600000000",
            tipo_jornada="Completa",
            horas_pactadas_dia=8.0,
        )

        worker_persona = ensure_persona(
            conn,
            workspace_id=workspace_id,
            empresa_id=empresa_b,
            usuario_id=worker_id,
            nombre="Empleado Demo",
            nif="00000001R",
            email="empleado@demo.local",
            telefono="600000001",
            tipo_jornada="Completa",
            horas_pactadas_dia=8.0,
        )

        ausencia_id = ensure_pending_vacation(conn, workspace_id=workspace_id, empresa_id=empresa_b, persona_id=worker_persona)

        conn.commit()

        print(f"OK seed demo en: {db_path}")
        print(f"- workspace_id={workspace_id} slug={args.workspace_slug}")
        print(f"- empresa_a={empresa_a} empresa_b={empresa_b}")
        print(f"- admin_user=admin id={admin_id} persona={admin_persona}")
        if admin_pw:
            print(f"  password={admin_pw}")
        print(f"- worker_user=empleado id={worker_id} persona={worker_persona}")
        if worker_pw:
            print(f"  password={worker_pw}")
        print(f"- ausencia_demo_pendiente id={ausencia_id}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
