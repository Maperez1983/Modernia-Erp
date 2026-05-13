#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path


def compact_spaces(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_email(value: object) -> str:
    return compact_spaces(value).lower()


def normalize_full_name(nombre: object, apellido: object = "") -> str:
    full = " ".join([compact_spaces(nombre), compact_spaces(apellido)]).strip()
    return compact_spaces(full).lower()


def parse_service_tokens(servicio: object) -> set[str]:
    raw = compact_spaces(servicio)
    if not raw:
        return set()
    tokens: list[str] = []
    for part in raw.replace(",", ";").split(";"):
        part = compact_spaces(part)
        if part:
            tokens.append(part.upper())
    return set(tokens)


@dataclass
class Db:
    kind: str  # "sqlite" | "postgres"
    conn: object
    placeholder: str  # "?" | "%s"

    def execute(self, sql: str, params: tuple = ()):
        return self.conn.execute(sql, params)

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


def open_db(db_arg: str) -> Db:
    db_arg = str(db_arg or "").strip()
    if not db_arg:
        raise SystemExit("--db vacío")

    if db_arg.startswith("postgres://") or db_arg.startswith("postgresql://"):
        try:
            import psycopg  # type: ignore
        except Exception as e:
            raise SystemExit(f"psycopg no disponible: {e}")
        conn = psycopg.connect(db_arg)
        return Db(kind="postgres", conn=conn, placeholder="%s")

    if db_arg.startswith("sqlite://"):
        db_arg = db_arg[len("sqlite://") :]

    db_path = Path(db_arg).expanduser()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return Db(kind="sqlite", conn=conn, placeholder="?")


def load_workspaces(db: Db, *, workspace_id: str = "") -> list[dict]:
    if workspace_id:
        row = db.execute(
            f"SELECT id, COALESCE(nombre,'') AS nombre, COALESCE(slug,'') AS slug FROM workspaces WHERE id = {db.placeholder} LIMIT 1",
            (workspace_id,),
        ).fetchone()
        return [dict(row)] if row else []
    rows = db.execute(
        "SELECT id, COALESCE(nombre,'') AS nombre, COALESCE(slug,'') AS slug FROM workspaces ORDER BY nombre, id"
    ).fetchall()
    return [dict(r) for r in rows]


def load_workspace_members(db: Db, ws_id: str) -> list[dict]:
    rows = db.execute(
        f"""
        SELECT
          mem.workspace_id,
          mem.usuario_id,
          COALESCE(mem.rol, '') AS member_role,
          COALESCE(u.activo, 1) AS activo,
          COALESCE(u.nombre, '') AS nombre,
          COALESCE(u.apellido, '') AS apellido,
          COALESCE(u.usuario, '') AS usuario,
          COALESCE(u.email, '') AS email,
          COALESCE(u.servicio, '') AS servicio
        FROM workspace_miembros mem
        LEFT JOIN usuarios u ON u.id = mem.usuario_id
        WHERE mem.workspace_id = {db.placeholder}
        ORDER BY COALESCE(u.nombre,''), COALESCE(u.apellido,''), mem.usuario_id
        """,
        (ws_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def load_user_workspace_memberships(db: Db) -> dict[str, list[str]]:
    rows = db.execute("SELECT usuario_id, workspace_id FROM workspace_miembros").fetchall()
    by_user: dict[str, list[str]] = {}
    for r in rows or []:
        try:
            uid = compact_spaces(r["usuario_id"])  # sqlite Row / psycopg dict-row
            ws_id = compact_spaces(r["workspace_id"])
        except Exception:
            uid = compact_spaces(r[0] if len(r) > 0 else "")
            ws_id = compact_spaces(r[1] if len(r) > 1 else "")
        if not uid or not ws_id:
            continue
        by_user.setdefault(uid, [])
        if ws_id not in by_user[uid]:
            by_user[uid].append(ws_id)
    return by_user


def persona_evidence(db: Db, ws_id: str, *, uid: str, email: str, full_name: str) -> dict:
    result = {"by_usuario_id": False, "by_email": False, "by_name": False}
    if not ws_id:
        return result

    if uid:
        row = db.execute(
            f"""
            SELECT 1
            FROM workspace_registro_personal
            WHERE workspace_id = {db.placeholder}
              AND COALESCE(activo, 1) = 1
              AND usuario_id = {db.placeholder}
            LIMIT 1
            """,
            (ws_id, uid),
        ).fetchone()
        result["by_usuario_id"] = bool(row)

    if (not result["by_usuario_id"]) and email:
        row = db.execute(
            f"""
            SELECT 1
            FROM workspace_registro_personal
            WHERE workspace_id = {db.placeholder}
              AND COALESCE(activo, 1) = 1
              AND LOWER(TRIM(COALESCE(email, ''))) = LOWER(TRIM({db.placeholder}))
            LIMIT 1
            """,
            (ws_id, email),
        ).fetchone()
        result["by_email"] = bool(row)

    if (not result["by_usuario_id"]) and (not result["by_email"]) and full_name:
        row = db.execute(
            f"""
            SELECT 1
            FROM workspace_registro_personal
            WHERE workspace_id = {db.placeholder}
              AND COALESCE(activo, 1) = 1
              AND LOWER(TRIM(COALESCE(nombre, ''))) = LOWER(TRIM({db.placeholder}))
            LIMIT 1
            """,
            (ws_id, full_name),
        ).fetchone()
        result["by_name"] = bool(row)

    return result


def is_owner_admin(member_role: str) -> bool:
    role = compact_spaces(member_role).lower()
    return role in {"owner", "admin"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audita `workspace_miembros` para detectar contaminación entre workspaces y exportar SQL de limpieza."
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("POSTGRES_URL") or "data/erp_import2.sqlite",
        help="SQLite path o URL Postgres (default: $POSTGRES_URL o data/erp_import2.sqlite)",
    )
    parser.add_argument("--workspace-id", default="", help="Auditar solo un workspace_id")
    parser.add_argument("--format", default="text", choices=("text", "json"))
    parser.add_argument(
        "--export-sql",
        default="",
        help="Ruta donde escribir DELETEs sugeridos (dry-run). No ejecuta cambios.",
    )
    parser.add_argument(
        "--suggest-remove-no-evidence",
        action="store_true",
        help="Sugiere borrar miembros sin evidencia (no owner/admin y sin ficha/registro en ese workspace).",
    )
    args = parser.parse_args()

    # Allow importing sibling package when executed as a script.
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    db = open_db(str(args.db))
    try:
        workspaces = load_workspaces(db, workspace_id=compact_spaces(args.workspace_id))
        memberships_by_user = load_user_workspace_memberships(db)

        report: dict = {"db": db.kind, "workspaces": [], "summary": {"workspaces": len(workspaces), "flagged": 0}}
        delete_sql: list[str] = []

        for ws in workspaces:
            ws_id = compact_spaces(ws.get("id"))
            members = load_workspace_members(db, ws_id)
            flagged = []
            for m in members:
                uid = compact_spaces(m.get("usuario_id"))
                email = normalize_email(m.get("email"))
                full_name = normalize_full_name(m.get("nombre"), m.get("apellido"))
                services = parse_service_tokens(m.get("servicio"))
                evidence = persona_evidence(db, ws_id, uid=uid, email=email, full_name=full_name)

                in_multiple = len(memberships_by_user.get(uid, [])) > 1 if uid else False
                missing_user = not compact_spaces(m.get("nombre")) and not compact_spaces(m.get("usuario")) and not compact_spaces(m.get("email"))
                inactive_user = int(m.get("activo") or 0) == 0
                has_evidence = bool(evidence["by_usuario_id"] or evidence["by_email"] or evidence["by_name"])
                role = compact_spaces(m.get("member_role"))
                owner_admin = is_owner_admin(role)
                gestoria_staff = "GESTORIA" in services

                no_evidence_flag = (not has_evidence) and (not owner_admin) and (not gestoria_staff)

                flags = []
                if missing_user:
                    flags.append("missing_user_row")
                if inactive_user:
                    flags.append("inactive_user")
                if in_multiple:
                    flags.append("multi_workspace")
                if no_evidence_flag:
                    flags.append("no_evidence")

                if flags:
                    item = {
                        "workspace_id": ws_id,
                        "usuario_id": uid,
                        "usuario": compact_spaces(m.get("usuario")),
                        "nombre": compact_spaces(m.get("nombre")),
                        "apellido": compact_spaces(m.get("apellido")),
                        "email": email,
                        "member_role": role,
                        "servicio": compact_spaces(m.get("servicio")),
                        "evidence": evidence,
                        "user_workspaces": memberships_by_user.get(uid, []) if uid else [],
                        "flags": flags,
                    }
                    flagged.append(item)

                    if args.suggest_remove_no_evidence and ("no_evidence" in flags) and ws_id and uid:
                        delete_sql.append(
                            f"DELETE FROM workspace_miembros WHERE workspace_id = '{ws_id}' AND usuario_id = '{uid}';"
                        )

            report["workspaces"].append(
                {
                    "id": ws_id,
                    "nombre": compact_spaces(ws.get("nombre")),
                    "slug": compact_spaces(ws.get("slug")),
                    "members_total": len(members),
                    "flagged_total": len(flagged),
                    "flagged": flagged,
                }
            )
            report["summary"]["flagged"] += len(flagged)

        if args.export_sql:
            out = Path(args.export_sql).expanduser()
            out.write_text("\n".join(delete_sql) + ("\n" if delete_sql else ""), encoding="utf-8")

        if args.format == "json":
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return

        # Text output
        print(f"DB: {db.kind}")
        print(f"Workspaces: {report['summary']['workspaces']} | Flagged: {report['summary']['flagged']}")
        if args.export_sql:
            print(f"SQL sugerido: {args.export_sql} ({len(delete_sql)} DELETEs)")
        for ws in report["workspaces"]:
            print(
                f"\n- Workspace {ws['id']} · {ws['nombre'] or ws['slug'] or ''} · miembros={ws['members_total']} · flags={ws['flagged_total']}"
            )
            for item in ws["flagged"]:
                flags = ",".join(item["flags"])
                who = (item["usuario"] or item["email"] or item["usuario_id"])[:64]
                print(
                    f"  - {who} · {flags} · role={item['member_role'] or '-'} · servicios={item['servicio'] or '-'}"
                )
        return
    finally:
        db.close()


if __name__ == "__main__":
    main()
