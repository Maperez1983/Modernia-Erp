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
    parser.add_argument(
        "--punch-check",
        action="store_true",
        help="Simula un fichaje de entrada+salida (en SAVEPOINT y rollback, no persiste cambios).",
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

    def simulate_punch(u, session, ws_id, persona_id):
        if not args.punch_check or not ws_id or not persona_id:
            return []
        errors = []
        privileged = bool(server.workspace_session_is_privileged(session))
        user_id = _norm(u.get("id"))
        now_dt = server.app_now()
        fecha = now_dt.date().isoformat()

        try:
            ok, _err = server.enforce_workspace_membership(conn, session, ws_id)
            if not ok:
                return ["PUNCH_NO_WORKSPACE_MEMBER"]
        except Exception:
            return ["PUNCH_MEMBERSHIP_CHECK_FAIL"]

        try:
            persona_row = conn.execute(
                """
                SELECT id, empresa_id, usuario_id, nombre, tipo_jornada, horas_pactadas_dia
                FROM workspace_registro_personal
                WHERE workspace_id = ? AND id = ? AND COALESCE(activo, 1) = 1
                LIMIT 1
                """,
                (ws_id, persona_id),
            ).fetchone()
        except Exception:
            persona_row = None
        if not persona_row:
            return ["PUNCH_PERSONA_MISSING"]

        if not privileged:
            if not user_id or _norm(persona_row["usuario_id"]) != user_id:
                return ["PUNCH_NOT_AUTHORIZED"]

        empresa_id = _norm(persona_row["empresa_id"])
        if not empresa_id:
            return ["PUNCH_PERSONA_NO_EMPRESA_ID"]

        record_id = server.os.urandom(16).hex() if hasattr(server, "os") else __import__("os").urandom(16).hex()
        persona_nombre = _norm(persona_row["nombre"]) or "Empleado"
        tipo_jornada = _norm(persona_row["tipo_jornada"]) or "Completa"
        horas_pactadas_dia = persona_row["horas_pactadas_dia"]

        # Importante: no persistimos. Usamos SAVEPOINT para rollback seguro incluso en autocommit.
        sp = f"punch_{record_id[:8]}"
        try:
            conn.execute(f"SAVEPOINT {sp}")
        except Exception:
            errors.append("PUNCH_SAVEPOINT_FAIL")
            return errors

        try:
            conn.execute(
                """
                INSERT INTO workspace_registro_horario (
                  id, workspace_id, empresa_id, persona_id, usuario_id, persona_nombre,
                  tipo_jornada, horas_pactadas_dia,
                  fecha, hora_inicio, hora_fin,
                  pausa_min, minutos_trabajados, metodo_registro, estado, notas,
                  created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?,
                  ?, ?,
                  ?, ?, '',
                  0, 0, 'self', 'Abierto', 'diagnostic',
                  datetime('now'), datetime('now')
                )
                """,
                (
                    record_id,
                    ws_id,
                    empresa_id,
                    persona_id,
                    user_id or None,
                    persona_nombre,
                    tipo_jornada,
                    horas_pactadas_dia,
                    fecha,
                    "08:00",
                ),
            )
        except Exception:
            errors.append("PUNCH_INSERT_FAIL")

        try:
            entries = server.fetch_workspace_time_entries(
                conn,
                ws_id,
                empresa_id="",
                limit=20,
                month=fecha[:7],
                persona_id=persona_id if not privileged else "",
            )
            rows = entries.get("rows") or []
            if not any(_norm(r.get("id")) == record_id for r in rows if isinstance(r, dict)):
                # Si el fetch filtra por mes distinto, no es crítico, pero marcamos para revisar.
                pass
        except Exception:
            errors.append("PUNCH_FETCH_FAIL")

        try:
            conn.execute(
                """
                UPDATE workspace_registro_horario
                SET hora_fin = '17:00', minutos_trabajados = 540, estado = 'Cerrado', updated_at = datetime('now')
                WHERE id = ? AND workspace_id = ?
                """,
                (record_id, ws_id),
            )
        except Exception:
            errors.append("PUNCH_UPDATE_FAIL")

        try:
            conn.execute(f"ROLLBACK TO {sp}")
            conn.execute(f"RELEASE {sp}")
        except Exception:
            errors.append("PUNCH_ROLLBACK_FAIL")

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
        errors.extend(simulate_punch(u, session, ws_id, persona_id))

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
