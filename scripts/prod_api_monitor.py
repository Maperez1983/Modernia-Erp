#!/usr/bin/env python3
"""Checks HTTP/API de produccion para el CRM.

No modifica datos. Valida salud, login, workspaces visibles y agenda por API.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import http.cookiejar
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    metrics: dict | None = None

    def as_dict(self) -> dict:
        data = {"name": self.name, "status": self.status}
        if self.detail:
            data["detail"] = self.detail
        if self.metrics:
            data["metrics"] = self.metrics
        return data


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name) or default).strip())
    except Exception:
        return default


def _base_url() -> str:
    value = (os.environ.get("CRM_BASE_URL") or os.environ.get("CRM_E2E_URL") or "https://modernia-erp-2.onrender.com").strip()
    return value.split("?", 1)[0].rstrip("/")


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
    except Exception as exc:
        # HTTPError tambien contiene cuerpo/status, pero para el monitor basta con propagar.
        raise exc


def _post_json(session, url: str, payload: dict, timeout: int) -> HttpResponse:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    return _open(session, request, timeout)


def _get_json(session, url: str, timeout: int) -> tuple[HttpResponse, dict]:
    resp = _open(session, Request(url, method="GET"), timeout)
    try:
        data = json.loads(resp.text or "{}")
    except Exception:
        data = {}
    return resp, data


def _check_health(base_url: str, timeout: int) -> CheckResult:
    started = time.monotonic()
    try:
        with urlopen(f"{base_url}/api/health", timeout=timeout) as raw:
            resp = HttpResponse(raw.getcode(), raw.read().decode("utf-8", "replace"))
        text = (resp.text or "").strip()[:300]
        status = "passed" if resp.status_code == 200 and text.startswith("ok") else "failed"
        return CheckResult(
            "health",
            status,
            detail=text,
            metrics={"http_status": resp.status_code, "duration_seconds": round(time.monotonic() - started, 2)},
        )
    except Exception as exc:
        return CheckResult("health", "failed", detail=f"{type(exc).__name__}: {exc}")


def _login(base_url: str, username: str, password: str, timeout: int) -> tuple[requests.Session, dict, CheckResult]:
    session = _make_session()
    started = time.monotonic()
    try:
        resp = _post_json(session, f"{base_url}/api/login", {"usuario": username, "password": password}, timeout)
        data = {}
        try:
            data = json.loads(resp.text or "{}")
        except Exception:
            data = {}
        ok = resp.status_code == 200 and bool(data.get("ok"))
        safe_user = {
            key: (data.get("user") or {}).get(key)
            for key in ("usuario", "email", "servicio", "rol", "nombre", "apellido")
            if (data.get("user") or {}).get(key)
        }
        return (
            session,
            data,
            CheckResult(
                f"login:{username}",
                "passed" if ok else "failed",
                detail="" if ok else f"HTTP {resp.status_code} {str(data)[:300]}",
                metrics={"http_status": resp.status_code, "duration_seconds": round(time.monotonic() - started, 2), "user": safe_user},
            ),
        )
    except Exception as exc:
        return session, {}, CheckResult(f"login:{username}", "failed", detail=f"{type(exc).__name__}: {exc}")


def _choose_workspace(rows: list[dict]) -> dict:
    if not rows:
        return {}
    preferred = (os.environ.get("CRM_AUDIT_WORKSPACE") or "modernia").strip().lower()
    for row in rows:
        haystack = " ".join(str(row.get(k) or "") for k in ("id", "nombre", "slug")).lower()
        if preferred and preferred in haystack:
            return row
    return rows[0]


def _check_workspaces(base_url: str, session: requests.Session, label: str, timeout: int) -> tuple[dict, CheckResult]:
    started = time.monotonic()
    resp, data = _get_json(session, f"{base_url}/api/workspaces", timeout)
    rows = data.get("rows") if isinstance(data, dict) else []
    rows = rows if isinstance(rows, list) else []
    workspace = _choose_workspace(rows)
    status = "passed" if resp.status_code == 200 and workspace.get("id") else "failed"
    return (
        workspace,
        CheckResult(
            f"workspaces:{label}",
            status,
            detail="" if status == "passed" else f"HTTP {resp.status_code} rows={len(rows)}",
            metrics={
                "http_status": resp.status_code,
                "duration_seconds": round(time.monotonic() - started, 2),
                "workspaces_total": len(rows),
                "workspace_id": workspace.get("id"),
                "workspace_nombre": workspace.get("nombre"),
                "workspace_slug": workspace.get("slug"),
            },
        ),
    )


def _check_agenda(base_url: str, session: requests.Session, label: str, workspace_id: str, timeout: int) -> CheckResult:
    started = time.monotonic()
    params = {
        "servicio": "inmobiliaria",
        "workspace_id": workspace_id,
        "range": "all",
        "limit": str(_env_int("CRM_AUDIT_AGENDA_LIMIT", 5000)),
        "order": "desc",
    }
    url = f"{base_url}/api/acciones?{urlencode(params)}"
    resp, data = _get_json(session, url, timeout)
    rows = data.get("rows") if isinstance(data, dict) else []
    rows = rows if isinstance(rows, list) else []
    min_rows = _env_int("CRM_AUDIT_MIN_AGENDA_ROWS", 1)
    status = "passed" if resp.status_code == 200 and len(rows) >= min_rows else "failed"
    sample = []
    for row in rows[:5]:
        sample.append(
            {
                "fecha": row.get("fecha"),
                "hora": row.get("hora"),
                "asunto": row.get("asunto"),
                "tipo": row.get("tipo"),
                "responsable": row.get("responsable"),
                "cliente": row.get("cliente"),
            }
        )
    return CheckResult(
        f"agenda:{label}",
        status,
        detail="" if status == "passed" else f"HTTP {resp.status_code} rows={len(rows)} min={min_rows}",
        metrics={
            "http_status": resp.status_code,
            "duration_seconds": round(time.monotonic() - started, 2),
            "rows": len(rows),
            "returned": data.get("returned") if isinstance(data, dict) else None,
            "truncated": data.get("truncated") if isinstance(data, dict) else None,
            "sample": sample,
        },
    )


def _user_specs() -> list[tuple[str, str, str]]:
    specs = [
        ("admin", os.environ.get("CRM_ADMIN_USER") or "", os.environ.get("CRM_ADMIN_PASSWORD") or ""),
        ("non_admin", os.environ.get("CRM_INMO_USER") or "", os.environ.get("CRM_INMO_PASSWORD") or ""),
    ]
    return [(label, user.strip(), password) for label, user, password in specs if user.strip() and password]


def run() -> dict:
    base_url = _base_url()
    timeout = _env_int("CRM_AUDIT_HTTP_TIMEOUT", 45)
    results: list[CheckResult] = [_check_health(base_url, timeout)]
    user_summaries = {}
    warnings = []
    critical_failures = []
    for label, username, password in _user_specs():
        session, login_data, login_result = _login(base_url, username, password, timeout)
        results.append(login_result)
        if login_result.status != "passed":
            if label == "admin":
                warnings.append(login_result.name)
            else:
                critical_failures.append(login_result.name)
            continue
        workspace, workspace_result = _check_workspaces(base_url, session, label, timeout)
        results.append(workspace_result)
        if workspace_result.status != "passed":
            if label == "admin":
                warnings.append(workspace_result.name)
            else:
                critical_failures.append(workspace_result.name)
        if workspace.get("id"):
            agenda_result = _check_agenda(base_url, session, label, str(workspace["id"]), timeout)
            results.append(agenda_result)
            if agenda_result.status != "passed":
                if label == "admin":
                    warnings.append(agenda_result.name)
                else:
                    critical_failures.append(agenda_result.name)
            user_summaries[label] = {
                "username": username,
                "workspace_id": workspace.get("id"),
                "agenda_rows": (agenda_result.metrics or {}).get("rows"),
                "user": (login_data.get("user") or {}) if isinstance(login_data, dict) else {},
            }
    if not _user_specs():
        results.append(CheckResult("credentials", "skipped", detail="Faltan CRM_ADMIN_USER/CRM_ADMIN_PASSWORD y CRM_INMO_USER/CRM_INMO_PASSWORD"))

    failed = [item for item in results if item.status == "failed"]
    health_failed = any(item.name == "health" and item.status == "failed" for item in results)
    report_status = "failed" if health_failed or critical_failures else ("passed_with_warnings" if warnings else "passed")
    return {
        "kind": "prod_api_monitor",
        "base_url": base_url,
        "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": report_status,
        "failed_checks": [item.name for item in failed],
        "critical_failures": critical_failures,
        "warnings": warnings,
        "checks": [item.as_dict() for item in results],
        "users": user_summaries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor HTTP/API de produccion del CRM.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo.")
    args = parser.parse_args()
    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
