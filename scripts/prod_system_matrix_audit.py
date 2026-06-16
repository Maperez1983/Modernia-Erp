#!/usr/bin/env python3
"""Auditoria amplia, no destructiva, del CRM en produccion.

Comprueba usuarios configurados, workspaces visibles y endpoints principales por
workspace/modulo. No crea, modifica ni borra datos.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name) or default).strip())
    except Exception:
        return default


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _base_url() -> str:
    value = (os.environ.get("CRM_BASE_URL") or os.environ.get("CRM_E2E_URL") or "https://modernia-erp-2.onrender.com").strip()
    return value.split("?", 1)[0].rstrip("/")


@dataclass
class EndpointSpec:
    name: str
    path: str
    module: str
    params: dict[str, str]
    requires_workspace: bool = True


ENDPOINTS = [
    EndpointSpec("workspace_health", "/api/workspace_health", "core", {}),
    EndpointSpec("workspace_service_desks", "/api/workspace_service_desks", "core", {}),
    EndpointSpec("workspace_clientes", "/api/workspace_clientes", "core", {"limit": "20"}),
    EndpointSpec("clientes_list", "/api/clientes_list", "crm", {"servicio": "inmobiliaria", "limit": "20"}),
    EndpointSpec("agenda_inmobiliaria", "/api/acciones", "inmobiliaria", {"servicio": "inmobiliaria", "range": "all", "limit": "100", "order": "desc"}),
    EndpointSpec("inmuebles", "/api/inmuebles", "inmobiliaria", {"limit": "20"}),
    EndpointSpec("visitas", "/api/visitas", "inmobiliaria", {"limit": "20"}),
    EndpointSpec("demandas", "/api/demandas", "inmobiliaria", {"limit": "20"}),
    EndpointSpec("compraventas", "/api/compraventas", "inmobiliaria", {"limit": "20"}),
    EndpointSpec("seguros_overview", "/api/workspace_seguros_overview", "seguros", {}),
    EndpointSpec("seguros_kpis", "/api/seguros_kpis", "seguros", {}),
    EndpointSpec("seguros_recibos_summary", "/api/seguros_recibos_summary", "seguros", {}),
    EndpointSpec("gestoria_overview", "/api/workspace_gestoria_overview", "gestoria", {}),
    EndpointSpec("gestoria_dashboard", "/api/gestoria_dashboard", "gestoria", {}),
    EndpointSpec("gestoria_modelos", "/api/gestoria_modelos", "gestoria", {"limit": "20"}),
    EndpointSpec("fin_overview", "/api/workspace_fin_overview", "financiero", {}),
    EndpointSpec("fin_kpis", "/api/fin_kpis", "financiero", {}),
    EndpointSpec("fin_alertas", "/api/fin_alertas", "financiero", {"limit": "20"}),
    EndpointSpec("fincas_comunidades", "/api/workspace_fincas_comunidades", "fincas", {"limit": "20"}),
    EndpointSpec("rrhh_personal", "/api/workspace_registro_personal", "rrhh", {"limit": "20"}),
]


class HttpResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


def _make_session():
    jar = http.cookiejar.CookieJar()
    return build_opener(HTTPCookieProcessor(jar))


def _open(session, request: Request, timeout: int) -> HttpResponse:
    try:
        with session.open(request, timeout=timeout) as resp:
            return HttpResponse(resp.getcode(), resp.read().decode("utf-8", "replace"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return HttpResponse(exc.code, body)


def _post_json(session, url: str, payload: dict, timeout: int) -> tuple[HttpResponse, dict]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    resp = _open(session, request, timeout)
    return resp, _parse_json(resp.text)


def _get_json(session, url: str, timeout: int) -> tuple[HttpResponse, dict | list]:
    resp = _open(session, Request(url, method="GET"), timeout)
    return resp, _parse_json(resp.text)


def _parse_json(text: str) -> dict | list:
    try:
        data = json.loads(text or "{}")
        return data if isinstance(data, (dict, list)) else {}
    except Exception:
        return {}


def _extract_rows(data: dict | list) -> list:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    rows = data.get("rows")
    if isinstance(rows, list):
        return rows
    for key in ("items", "data", "results"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _credentials() -> list[dict[str, str]]:
    raw = (os.environ.get("CRM_AUDIT_USER_CREDENTIALS_JSON") or "").strip()
    items: list[dict[str, str]] = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    user = str(item.get("user") or item.get("usuario") or "").strip()
                    password = str(item.get("password") or item.get("pass") or "")
                    label = str(item.get("label") or user or "user").strip()
                    if user and password:
                        items.append({"label": label, "user": user, "password": password})
        except Exception:
            pass
    defaults = [
        {"label": "admin", "user": os.environ.get("CRM_ADMIN_USER") or "", "password": os.environ.get("CRM_ADMIN_PASSWORD") or ""},
        {"label": "non_admin", "user": os.environ.get("CRM_INMO_USER") or "", "password": os.environ.get("CRM_INMO_PASSWORD") or ""},
    ]
    known = {item["user"].lower() for item in items}
    for item in defaults:
        user = item["user"].strip()
        password = item["password"]
        if user and password and user.lower() not in known:
            items.append({"label": item["label"], "user": user, "password": password})
            known.add(user.lower())
    return items


def _request_url(base_url: str, spec: EndpointSpec, workspace_id: str) -> str:
    params = dict(spec.params)
    if spec.requires_workspace:
        params["workspace_id"] = workspace_id
    query = urlencode(params)
    return f"{base_url}{spec.path}" + (f"?{query}" if query else "")


def _status_for_http(status_code: int, rows: int | None = None) -> str:
    if 200 <= status_code < 300:
        return "passed"
    if status_code in {401, 403, 404}:
        return "warning"
    if status_code == 400 and rows == 0:
        return "warning"
    return "failed"


def _health(base_url: str, timeout: int) -> dict:
    started = time.monotonic()
    try:
        with urlopen(f"{base_url}/api/health", timeout=timeout) as raw:
            text = raw.read().decode("utf-8", "replace")
            status_code = raw.getcode()
    except Exception as exc:
        return {
            "name": "health",
            "status": "failed",
            "detail": f"{type(exc).__name__}: {exc}",
            "duration_seconds": round(time.monotonic() - started, 2),
        }
    return {
        "name": "health",
        "status": "passed" if status_code == 200 and text.strip().startswith("ok") else "failed",
        "http_status": status_code,
        "detail": text.strip()[:300],
        "duration_seconds": round(time.monotonic() - started, 2),
    }


def _login(base_url: str, username: str, password: str, timeout: int) -> tuple[object, dict, dict]:
    session = _make_session()
    started = time.monotonic()
    try:
        resp, data = _post_json(session, f"{base_url}/api/login", {"usuario": username, "password": password}, timeout)
    except Exception as exc:
        return session, {}, {
            "name": f"login:{username}",
            "status": "failed",
            "detail": f"{type(exc).__name__}: {exc}",
            "duration_seconds": round(time.monotonic() - started, 2),
        }
    ok = resp.status_code == 200 and isinstance(data, dict) and bool(data.get("ok"))
    user = data.get("user") if isinstance(data, dict) else {}
    safe_user = {
        key: user.get(key)
        for key in ("id", "usuario", "email", "servicio", "rol", "nombre", "apellido")
        if isinstance(user, dict) and user.get(key)
    }
    return session, data if isinstance(data, dict) else {}, {
        "name": f"login:{username}",
        "status": "passed" if ok else "failed",
        "http_status": resp.status_code,
        "user": safe_user,
        "duration_seconds": round(time.monotonic() - started, 2),
        "detail": "" if ok else str(data)[:500],
    }


def _fetch_workspaces(base_url: str, session, label: str, timeout: int) -> tuple[list[dict], dict]:
    started = time.monotonic()
    try:
        resp, data = _get_json(session, f"{base_url}/api/workspaces", timeout)
    except Exception as exc:
        return [], {
            "name": f"workspaces:{label}",
            "status": "failed",
            "detail": f"{type(exc).__name__}: {exc}",
            "duration_seconds": round(time.monotonic() - started, 2),
        }
    rows = _extract_rows(data)
    rows = [row for row in rows if isinstance(row, dict)]
    return rows, {
        "name": f"workspaces:{label}",
        "status": "passed" if resp.status_code == 200 and rows else "failed",
        "http_status": resp.status_code,
        "workspaces_total": len(rows),
        "duration_seconds": round(time.monotonic() - started, 2),
    }


def _fetch_workspace_users(base_url: str, session, workspace: dict, timeout: int) -> dict:
    ws_id = str(workspace.get("id") or "").strip()
    started = time.monotonic()
    url = f"{base_url}/api/usuarios?{urlencode({'workspace_id': ws_id})}"
    try:
        resp, data = _get_json(session, url, timeout)
    except Exception as exc:
        return {
            "workspace_id": ws_id,
            "workspace_nombre": workspace.get("nombre"),
            "status": "failed",
            "detail": f"{type(exc).__name__}: {exc}",
            "duration_seconds": round(time.monotonic() - started, 2),
        }
    rows = [row for row in _extract_rows(data) if isinstance(row, dict)]
    active = [row for row in rows if int(row.get("activo") or 0) == 1]
    return {
        "workspace_id": ws_id,
        "workspace_nombre": workspace.get("nombre"),
        "status": _status_for_http(resp.status_code),
        "http_status": resp.status_code,
        "users_total": len(rows),
        "users_active": len(active),
        "users_sample": [
            {
                "usuario": row.get("usuario"),
                "nombre": row.get("nombre"),
                "apellido": row.get("apellido"),
                "servicio": row.get("servicio"),
                "rol": row.get("rol"),
                "activo": row.get("activo"),
            }
            for row in rows[:20]
        ],
        "duration_seconds": round(time.monotonic() - started, 2),
    }


def _check_endpoint(base_url: str, session, user_label: str, workspace: dict, spec: EndpointSpec, timeout: int) -> dict:
    ws_id = str(workspace.get("id") or "").strip()
    started = time.monotonic()
    url = _request_url(base_url, spec, ws_id)
    try:
        resp, data = _get_json(session, url, timeout)
        rows = _extract_rows(data)
        status = _status_for_http(resp.status_code, len(rows))
        return {
            "user_label": user_label,
            "workspace_id": ws_id,
            "workspace_nombre": workspace.get("nombre"),
            "module": spec.module,
            "endpoint": spec.name,
            "path": spec.path,
            "status": status,
            "http_status": resp.status_code,
            "rows": len(rows),
            "duration_seconds": round(time.monotonic() - started, 2),
            "detail": "" if status == "passed" else str(data)[:500],
        }
    except Exception as exc:
        return {
            "user_label": user_label,
            "workspace_id": ws_id,
            "workspace_nombre": workspace.get("nombre"),
            "module": spec.module,
            "endpoint": spec.name,
            "path": spec.path,
            "status": "failed",
            "detail": f"{type(exc).__name__}: {exc}",
            "duration_seconds": round(time.monotonic() - started, 2),
        }


def run() -> dict:
    base_url = _base_url()
    timeout = _env_int("CRM_AUDIT_HTTP_TIMEOUT", 45)
    strict_forbidden = _env_flag("CRM_AUDIT_STRICT_FORBIDDEN")
    health = _health(base_url, timeout)
    checks: list[dict] = [health]
    users: list[dict] = []
    workspaces_by_user: dict[str, list[dict]] = {}
    workspace_user_inventory: list[dict] = []
    endpoint_matrix: list[dict] = []

    credentials = _credentials()
    if not credentials:
        checks.append({"name": "credentials", "status": "failed", "detail": "No hay credenciales configuradas"})

    for cred in credentials:
        label = cred["label"]
        username = cred["user"]
        session, login_data, login_check = _login(base_url, username, cred["password"], timeout)
        checks.append(login_check)
        users.append({"label": label, "username": username, "login_status": login_check["status"], "user": login_check.get("user", {})})
        if login_check["status"] != "passed":
            continue

        workspaces, workspace_check = _fetch_workspaces(base_url, session, label, timeout)
        checks.append(workspace_check)
        workspaces_by_user[label] = [
            {"id": row.get("id"), "nombre": row.get("nombre"), "slug": row.get("slug"), "modulos_activos": row.get("modulos_activos")}
            for row in workspaces
        ]

        for workspace in workspaces:
            if not workspace.get("id"):
                continue
            if label == "admin":
                workspace_user_inventory.append(_fetch_workspace_users(base_url, session, workspace, timeout))
            for spec in ENDPOINTS:
                endpoint_matrix.append(_check_endpoint(base_url, session, label, workspace, spec, timeout))

    failed_statuses = {"failed"}
    if strict_forbidden:
        failed_statuses.add("warning")
    failed_checks = [item.get("name") or item.get("endpoint") for item in checks + endpoint_matrix + workspace_user_inventory if item.get("status") in failed_statuses]
    warning_checks = [item.get("name") or item.get("endpoint") for item in checks + endpoint_matrix + workspace_user_inventory if item.get("status") == "warning"]
    by_module: dict[str, dict[str, int]] = {}
    for item in endpoint_matrix:
        module = str(item.get("module") or "unknown")
        status = str(item.get("status") or "unknown")
        by_module.setdefault(module, {})
        by_module[module][status] = by_module[module].get(status, 0) + 1

    return {
        "kind": "prod_system_matrix_audit",
        "base_url": base_url,
        "started_at": _utc_now(),
        "finished_at": _utc_now(),
        "status": "failed" if failed_checks else "passed",
        "failed_checks": failed_checks,
        "warning_checks": warning_checks,
        "strict_forbidden": strict_forbidden,
        "summary": {
            "credentialed_users": len(credentials),
            "workspaces_checked": sum(len(rows) for rows in workspaces_by_user.values()),
            "workspace_user_inventories": len(workspace_user_inventory),
            "endpoint_checks": len(endpoint_matrix),
            "endpoint_status_by_module": by_module,
        },
        "checks": checks,
        "users": users,
        "workspaces_by_user": workspaces_by_user,
        "workspace_user_inventory": workspace_user_inventory,
        "endpoint_matrix": endpoint_matrix,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoria matricial de produccion del CRM.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo.")
    args = parser.parse_args()
    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
