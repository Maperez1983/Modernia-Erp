#!/usr/bin/env python3
"""
Normaliza usuarios y memberships de workspaces para el entorno Modernia.

Objetivo:
- Asegurar que cada usuario pertenece SOLO a su workspace objetivo (Modernia o Modernia Centro)
- Marcar usuarios como activos
- Ajustar el campo `servicio` (string) según lo solicitado
- Ajustar rol dentro de `workspace_miembros` (Owner/Miembro) para admins del workspace

Uso (Render/producción):
  python3 scripts/fix_modernia_workspaces_users.py --dry-run
  python3 scripts/fix_modernia_workspaces_users.py --apply --confirm APLICAR

Requiere:
  POSTGRES_URL o DATABASE_URL en env.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import psycopg


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm_login(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def norm_ws(value: str) -> str:
    # Compatible con normalize_workspace_slug (aprox.)
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


@dataclass(frozen=True)
class UserSpec:
    login: str
    workspace_key: str  # "modernia" | "modernia-centro"
    services: List[str]
    is_owner: bool = False


def build_specs() -> List[UserSpec]:
    # IMPORTANT: estos valores vienen del mensaje del usuario.
    # Los "login" se comparan por normalización (quitando puntos/espacios).
    return [
        UserSpec("S.Lallana", "modernia", ["Inmobiliaria"]),
        UserSpec("DGarcia", "modernia", ["Inmobiliaria"]),
        UserSpec("Icanamero", "modernia", ["Administración"], is_owner=True),
        UserSpec("DGallardo", "modernia", ["Fincas", "Gestoría"]),
        UserSpec("Rmiera", "modernia", ["Seguros", "Gestoría"]),
        UserSpec("Tramos", "modernia", ["Gestoría"]),
        UserSpec("AMostazo", "modernia", ["Gestoría"]),
        UserSpec("Gbartha", "modernia", ["Registro horario"]),
        UserSpec("LDianez", "modernia", ["Inmobiliaria"]),
        UserSpec("Bsalazar", "modernia", ["Seguros", "Inmobiliaria"]),
        UserSpec("AMelgar", "modernia", ["Gestoría"]),
        UserSpec("JBernal", "modernia", ["Financiaciones"]),
        UserSpec("S.sanchez", "modernia-centro", ["Administración"], is_owner=True),
        UserSpec("C.anca", "modernia-centro", ["Administración"], is_owner=True),
    ]


def resolve_workspace_ids(conn) -> Dict[str, str]:
    rows = conn.execute("SELECT id, nombre, slug FROM workspaces").fetchall()
    by_key: Dict[str, str] = {}
    for row in rows:
        ws_id = str(row[0] or "").strip()
        nombre = str(row[1] or "").strip()
        slug = str(row[2] or "").strip()
        key = norm_ws(slug or nombre)
        if key:
            by_key[key] = ws_id
    # Fallbacks
    if "modernia-centro" not in by_key and "modernia-centro" in {norm_ws("Modernia Centro")}:
        # no-op, aquí solo para claridad
        pass
    return by_key


def fetch_users(conn) -> Dict[str, Dict[str, str]]:
    rows = conn.execute("SELECT id, usuario, email FROM usuarios").fetchall()
    out: Dict[str, Dict[str, str]] = {}
    for row in rows:
        uid = str(row[0] or "").strip()
        usuario = str(row[1] or "").strip()
        email = str(row[2] or "").strip()
        # Index por usuario normalizado y por local-part del email (si existe).
        keys = set()
        if usuario:
            keys.add(norm_login(usuario))
        if email and "@" in email:
            keys.add(norm_login(email.split("@", 1)[0]))
        keys = {k for k in keys if k}
        for key in keys:
            # Si hay duplicados, preferimos el que tenga email.
            if key in out and out[key].get("email"):
                continue
            out[key] = {"id": uid, "usuario": usuario, "email": email}
    return out


def tokens_for_login(login: str) -> List[str]:
    base = norm_login(login)
    tokens = []
    if base:
        tokens.append(base)
        if len(base) >= 4:
            tokens.append(base[1:])
        if len(base) >= 5:
            tokens.append(base[2:])
    # orden: más específico primero, sin duplicados
    seen = set()
    ordered = []
    for tok in sorted(tokens, key=lambda x: (-len(x), x)):
        if tok and tok not in seen:
            seen.add(tok)
            ordered.append(tok)
    return ordered


def resolve_user_id(conn, users_index: Dict[str, Dict[str, str]], login: str) -> Tuple[Optional[str], List[dict]]:
    """
    Devuelve (user_id, candidates). Si no puede resolver unívocamente, user_id=None y candidates contiene sugerencias.
    """
    key = norm_login(login)
    direct = users_index.get(key)
    if direct:
        return str(direct["id"]), []
    # Intento por tokens (dgarcia -> garcia, sllallana -> lallana, etc.)
    all_candidates: Dict[str, dict] = {}
    for tok in tokens_for_login(login):
        pattern = f"%{tok}%"
        try:
            rows = conn.execute(
                """
                SELECT id, usuario, email, nombre, apellido, activo
                FROM usuarios
                WHERE LOWER(COALESCE(usuario,'')) LIKE LOWER(%s)
                   OR LOWER(COALESCE(email,'')) LIKE LOWER(%s)
                   OR LOWER(COALESCE(nombre,'')) LIKE LOWER(%s)
                   OR LOWER(COALESCE(apellido,'')) LIKE LOWER(%s)
                ORDER BY COALESCE(activo, 1) DESC, COALESCE(updated_at, created_at) DESC NULLS LAST
                LIMIT 8
                """,
                (pattern, pattern, pattern, pattern),
            ).fetchall()
        except Exception:
            rows = []
        for row in rows or []:
            rid = str(row[0] or "").strip()
            if not rid:
                continue
            if rid not in all_candidates:
                all_candidates[rid] = {
                    "id": rid,
                    "usuario": str(row[1] or "").strip(),
                    "email": str(row[2] or "").strip(),
                    "nombre": str(row[3] or "").strip(),
                    "apellido": str(row[4] or "").strip(),
                    "activo": int(row[5] or 0) if row[5] is not None else 0,
                }
        if len(all_candidates) == 1:
            # resolución unívoca temprana
            only_id = next(iter(all_candidates.keys()))
            return only_id, []
    candidates = list(all_candidates.values())
    if len(candidates) == 1:
        return candidates[0]["id"], []
    return None, candidates[:8]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="No escribe cambios (por defecto si no hay --apply).")
    ap.add_argument("--apply", action="store_true", help="Aplica cambios en BD.")
    ap.add_argument("--confirm", default="", help="Debe ser APLICAR cuando uses --apply.")
    args = ap.parse_args()

    apply_changes = bool(args.apply)
    if apply_changes and str(args.confirm or "").strip().upper() != "APLICAR":
        raise SystemExit("Falta confirmación: usa --confirm APLICAR")
    if not apply_changes:
        args.dry_run = True

    dsn = (os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not dsn:
        raise SystemExit("POSTGRES_URL/DATABASE_URL no configurado.")

    specs = build_specs()

    with psycopg.connect(dsn) as conn:
        conn.autocommit = False
        ws_map = resolve_workspace_ids(conn)
        users_map = fetch_users(conn)

        # Resolve workspace ids needed.
        wanted_ws = {"modernia", "modernia-centro"}
        missing_ws = [k for k in wanted_ws if k not in ws_map]
        if missing_ws:
            raise SystemExit(f"No encuentro workspaces: {missing_ws}. Slugs disponibles: {sorted(ws_map.keys())[:30]}")

        prepared: List[Tuple[UserSpec, str, str]] = []
        missing_users: List[str] = []
        ambiguous_users: Dict[str, List[dict]] = {}
        for spec in specs:
            user_id, candidates = resolve_user_id(conn, users_map, spec.login)
            if not user_id:
                if candidates:
                    ambiguous_users[spec.login] = candidates
                else:
                    missing_users.append(spec.login)
                continue
            ws_id = ws_map[spec.workspace_key]
            prepared.append((spec, user_id, ws_id))

        if missing_users:
            print("Usuarios NO encontrados (revisa login exacto):")
            for u in missing_users:
                print(f" - {u}")
            print("")
        if ambiguous_users:
            print("Usuarios ambiguos (varios candidatos, el script no elige para no liarla):")
            for login, rows in ambiguous_users.items():
                print(f" - {login}:")
                for row in rows:
                    label = f"{row.get('usuario') or '-'} · {row.get('email') or '-'} · {row.get('nombre') or '-'} {row.get('apellido') or '-'}".strip()
                    print(f"    - {row.get('id')} :: {label}")
            print("")

        changes = []
        for spec, user_id, ws_id in prepared:
            servicio = ", ".join(spec.services)
            role = "Owner" if spec.is_owner else "Miembro"
            changes.append((spec.login, user_id, ws_id, role, servicio))

        print(f"Modo: {'APLICAR' if apply_changes else 'DRY-RUN'}")
        print("Cambios previstos:")
        for login, user_id, ws_id, role, servicio in changes:
            print(f" - {login} ({user_id}) -> ws={ws_id} role={role} servicio={servicio}")
        print("")

        if args.dry_run:
            return 0

        ts = now_iso()
        try:
            for _, user_id, ws_id, role, servicio in changes:
                # 1) activar usuario + set servicio
                conn.execute(
                    """
                    UPDATE usuarios
                    SET activo = 1,
                        servicio = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (servicio, ts, user_id),
                )
                # 2) eliminar memberships en otros workspaces (single-workspace)
                conn.execute(
                    "DELETE FROM workspace_miembros WHERE usuario_id = %s AND workspace_id <> %s",
                    (user_id, ws_id),
                )
                # 3) upsert membership en workspace destino
                conn.execute(
                    """
                    INSERT INTO workspace_miembros (id, workspace_id, usuario_id, rol, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (workspace_id, usuario_id)
                    DO UPDATE SET rol = EXCLUDED.rol, updated_at = EXCLUDED.updated_at
                    """,
                    (secrets.token_hex(16), ws_id, user_id, role, ts, ts),
                )

            conn.commit()
            print("OK: cambios aplicados.")
            return 0
        except Exception as exc:
            conn.rollback()
            raise


if __name__ == "__main__":
    raise SystemExit(main())
