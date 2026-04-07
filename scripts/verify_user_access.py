#!/usr/bin/env python3
import argparse
from dataclasses import dataclass
import sys
from pathlib import Path


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _norm(value):
    return str(value or "").strip()


@dataclass
class UserRow:
    id: str
    usuario: str
    nombre: str
    apellido: str
    rol: str
    servicio: str
    email: str
    registro_horario_activo: int


def main():
    parser = argparse.ArgumentParser(
        description="Verifica acceso, membership y ficha RRHH por usuario (sin levantar servidor)."
    )
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta a la base de datos SQLite")
    parser.add_argument("--limit", type=int, default=0, help="Limita nº de usuarios procesados (0 = todos)")
    parser.add_argument(
        "--boot-check",
        action="store_true",
        help="Simula checks de /api/home_time_status y /api/workspace_boot (detecta 500 típicos).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from web import server

    db_path = args.db
    server.ensure_tables(db_path)
    conn = server.open_sqlite_conn(db_path, with_row_factory=True)

    workspaces = [
        dict(r)
        for r in (
            conn.execute("SELECT id, slug, nombre FROM workspaces ORDER BY nombre COLLATE NOCASE ASC").fetchall()
            or []
        )
    ]
    workspace_ids = [str(r.get("id") or "").strip() for r in (workspaces or []) if str(r.get("id") or "").strip()]

    users = [
        dict(r)
        for r in (
            conn.execute(
                """
                SELECT id, usuario, nombre, apellido, rol, servicio, email, registro_horario_activo
                FROM usuarios
                WHERE COALESCE(activo, 1) = 1
                  AND COALESCE(usuario, '') != 'workspace'
                ORDER BY LOWER(COALESCE(usuario, '')) ASC
                """
            ).fetchall()
            or []
        )
    ]
    if args.limit and args.limit > 0:
        users = list(users)[: args.limit]

    def session_for(u):
        return {
            "user_id": _norm(u.get("id")),
            "usuario": _norm(u.get("usuario")),
            "nombre": _norm(u.get("nombre")),
            "apellido": _norm(u.get("apellido")),
            "rol": _norm(u.get("rol")),
            "servicio": _norm(u.get("servicio")),
            "email": _norm(u.get("email")),
        }

    def visible_workspaces(session):
        try:
            rows = server.fetch_workspace_rows_for_user(conn, session) or []
        except Exception:
            rows = []
        ids = [str(r.get("id") or "").strip() for r in rows if str(r.get("id") or "").strip()]
        return ids or list(workspace_ids)

    def resolve_persona(u, session):
        # Escoge el primer workspace visible donde podamos resolver una persona (o autocrearla si procede).
        # Aproxima /api/home_time_status y /api/workspace_boot sin levantar servidor.
        user_id = _norm(u.get("id"))
        for ws_id in visible_workspaces(session):
            ok, _err = server.enforce_workspace_membership(conn, session, ws_id)
            if not ok:
                continue
            persona_id = server.workspace_persona_id_for_user(conn, ws_id, user_id)
            if not persona_id:
                persona_id = server.ensure_workspace_persona_for_self(conn, ws_id, session)
            if persona_id:
                return ws_id, persona_id, "ok"
        return "", "", "no_persona"

    def simulate_boot(u, session, ws_id, persona_id):
        """
        Replica parte de /api/workspace_boot + /api/home_time_status para detectar errores de schema/queries
        que en el front se traducen en cards bloqueadas o 'sin ficha'.
        """
        if not args.boot_check or not ws_id:
            return []
        errors = []
        privileged = bool(server.workspace_session_is_privileged(session))
        user_id = _norm(u.get("id"))

        try:
            ok, _err = server.enforce_workspace_membership(conn, session, ws_id)
            if not ok:
                errors.append("BOOT_NO_WORKSPACE_MEMBER")
                return errors
        except Exception:
            errors.append("BOOT_MEMBERSHIP_CHECK_FAIL")
            return errors

        # 1) Time entries query (si falla aquí, /api/workspace_boot suele dar 500).
        try:
            server.fetch_workspace_time_entries(
                conn,
                ws_id,
                empresa_id="",
                limit=50,
                month="",
                persona_id=(persona_id if (user_id and not privileged) else ""),
            )
        except Exception:
            errors.append("BOOT_TIME_ENTRIES_FAIL")

        # 2) Employees query (no-priv debería recibir su ficha).
        if user_id and not privileged:
            try:
                row = conn.execute(
                    """
                    SELECT p.id
                    FROM workspace_registro_personal p
                    WHERE p.workspace_id = ? AND p.usuario_id = ? AND COALESCE(p.activo, 1) = 1
                    ORDER BY COALESCE(p.usuario_manual, 0) DESC, COALESCE(p.updated_at, p.created_at) DESC
                    LIMIT 1
                    """,
                    (ws_id, user_id),
                ).fetchone()
                if not row:
                    errors.append("BOOT_TIME_EMPLOYEE_MISSING")
            except Exception:
                errors.append("BOOT_TIME_EMPLOYEE_QUERY_FAIL")

        # 3) Workspace health (front lo pide al cargar el holding).
        try:
            server.fetch_workspace_health(conn, ws_id)
        except Exception:
            errors.append("BOOT_HEALTH_FAIL")

        return errors

    total = len(users)
    ok = 0
    problems = []
    print(f"DB: {db_path}")
    print(f"Workspaces: {len(workspace_ids)}")
    for u in users:
        user = UserRow(
            id=_norm(u.get("id")),
            usuario=_norm(u.get("usuario")),
            nombre=_norm(u.get("nombre")),
            apellido=_norm(u.get("apellido")),
            rol=_norm(u.get("rol")),
            servicio=_norm(u.get("servicio")),
            email=_norm(u.get("email")),
            registro_horario_activo=_safe_int(u.get("registro_horario_activo"), 0),
        )
        session = session_for(u)
        ws_id, persona_id, status = resolve_persona(u, session)

        member = None
        if ws_id:
            try:
                member = server.fetch_workspace_member(conn, ws_id, user.id)
            except Exception:
                member = None

        persona_row = None
        if ws_id and persona_id:
            try:
                row = conn.execute(
                    """
                    SELECT id, workspace_id, empresa_id, COALESCE(usuario_id, '') AS usuario_id,
                           COALESCE(usuario_manual, 0) AS usuario_manual, COALESCE(activo, 1) AS activo,
                           COALESCE(email, '') AS email, COALESCE(nombre, '') AS nombre
                    FROM workspace_registro_personal
                    WHERE workspace_id = ? AND id = ?
                    LIMIT 1
                    """,
                    (ws_id, persona_id),
                ).fetchone()
                persona_row = dict(row) if row else None
            except Exception:
                persona_row = None

        errors = []
        if status != "ok":
            errors.append("NO_PERSONA")
        if ws_id and not member:
            errors.append("NO_WORKSPACE_MEMBER")
        if persona_row:
            if _norm(persona_row.get("usuario_id")) != user.id:
                errors.append("PERSONA_NOT_LINKED")
            if _safe_int(persona_row.get("activo"), 1) != 1:
                errors.append("PERSONA_INACTIVE")
            if not _norm(persona_row.get("empresa_id")):
                errors.append("PERSONA_NO_EMPRESA_ID")
        else:
            if ws_id and persona_id:
                errors.append("PERSONA_ROW_MISSING")

        errors.extend(simulate_boot(u, session, ws_id, persona_id))

        if errors:
            problems.append((user.usuario or user.email or user.id[:8], ",".join(errors)))
        else:
            ok += 1

        print(
            f"- {user.usuario:12} | ws={ws_id[:8] if ws_id else '-':8} | persona={persona_id[:8] if persona_id else '-':8} | member={'Y' if member else 'N'} | rh={user.registro_horario_activo} | servicio={user.servicio or '-'}"
        )

    print("")
    print(f"OK: {ok}/{total}")
    if problems:
        print("Problemas:")
        for label, err in problems:
            print(f"  - {label}: {err}")


if __name__ == "__main__":
    main()

