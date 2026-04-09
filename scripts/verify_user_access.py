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
    parser = argparse.ArgumentParser(description="Verifica acceso y ficha RRHH por usuario (sin levantar servidor).")
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta a la base de datos SQLite")
    parser.add_argument("--limit", type=int, default=0, help="Limita nº de usuarios procesados (0 = todos)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from web import server

    db_path = args.db
    server.ensure_tables(db_path)
    conn = server.open_sqlite_conn(db_path, with_row_factory=True)

    workspaces = [dict(r) for r in (conn.execute("SELECT id, slug, nombre FROM workspaces ORDER BY nombre COLLATE NOCASE ASC").fetchall() or [])]
    workspace_ids = [str(r.get("id") or "").strip() for r in (workspaces or []) if str(r.get("id") or "").strip()]

    users = [dict(r) for r in (conn.execute(
        """
        SELECT id, usuario, nombre, apellido, rol, servicio, email, registro_horario_activo
        FROM usuarios
        WHERE COALESCE(activo, 1) = 1
          AND COALESCE(usuario, '') != 'workspace'
        ORDER BY LOWER(COALESCE(usuario, '')) ASC
        """
    ).fetchall() or [])]
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

    def resolve_persona(u, session):
        # Escoge el primer workspace visible donde podamos resolver una persona (o autocrearla si procede).
        # Esto aproxima el comportamiento de home + workspace_boot sin depender del HTTP server.
        for ws_id in workspace_ids:
            persona_id = server.workspace_persona_id_for_user(conn, ws_id, _norm(u.get("id")))
            if not persona_id:
                persona_id = server.ensure_workspace_persona_for_self(conn, ws_id, session)
            if persona_id:
                return ws_id, persona_id, "ok"
        return "", "", "no_persona"

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

        # Ficha detalle
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

        # Reglas: si hay persona, debería estar activa y vinculada al usuario. Empresa_id es necesario para fichar.
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
