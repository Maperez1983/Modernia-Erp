#!/usr/bin/env python3
"""Audita deriva de accesos y contrasenas compartidas en produccion."""

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
from pathlib import Path


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    metrics: dict | None = None

    def as_dict(self) -> dict:
        payload = {"name": self.name, "status": self.status}
        if self.detail:
            payload["detail"] = self.detail
        if self.metrics:
            payload["metrics"] = self.metrics
        return payload


class HttpResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IDENTITY_POLICY_PATH = ROOT / "docs" / "audit_identity_policy.json"


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.environ.get(name) or default).strip())
    except Exception:
        return default


def _base_url() -> str:
    value = (os.environ.get("CRM_BASE_URL") or os.environ.get("CRM_E2E_URL") or "https://modernia-erp-2.onrender.com").strip()
    return value.split("?", 1)[0].rstrip("/")


def _csv_env(name: str) -> list[str]:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _make_session():
    return build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _open(session, request: Request, timeout: int) -> HttpResponse:
    with session.open(request, timeout=timeout) as resp:
        return HttpResponse(resp.getcode(), resp.read().decode("utf-8", "replace"))


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


def _health_backend(base_url: str, timeout: int) -> tuple[str, dict]:
    try:
        with urlopen(f"{base_url}/api/build_info", timeout=timeout) as raw:
            text = raw.read().decode("utf-8", "replace")
        data = json.loads(text or "{}")
    except Exception:
        return "", {}
    return str(data.get("backend") or "").strip().lower(), data if isinstance(data, dict) else {}


def _login(base_url: str, username: str, password: str, timeout: int):
    session = _make_session()
    started = time.monotonic()
    try:
        resp = _post_json(session, f"{base_url}/api/login", {"usuario": username, "password": password}, timeout)
        try:
            data = json.loads(resp.text or "{}")
        except Exception:
            data = {}
        ok = resp.status_code == 200 and bool(data.get("ok"))
        return session, data, CheckResult(
            f"login:{username}",
            "passed" if ok else "failed",
            detail="" if ok else f"HTTP {resp.status_code} {str(data)[:300]}",
            metrics={"http_status": resp.status_code, "duration_seconds": round(time.monotonic() - started, 2)},
        )
    except Exception as exc:
        return session, {}, CheckResult(f"login:{username}", "failed", detail=f"{type(exc).__name__}: {exc}")


def _admin_lookup(base_url: str, session, login: str, timeout: int) -> tuple[dict | None, CheckResult]:
    started = time.monotonic()
    try:
        resp, data = _get_json(session, f"{base_url}/api/admin_user_lookup?{urlencode({'login': login})}", timeout)
        items = data.get("items") if isinstance(data, dict) else []
        items = items if isinstance(items, list) else []
        item = items[0] if items else None
        status = "passed" if resp.status_code == 200 and item else "failed"
        return item, CheckResult(
            f"admin_lookup:{login}",
            status,
            detail="" if status == "passed" else f"HTTP {resp.status_code} items={len(items)}",
            metrics={
                "http_status": resp.status_code,
                "duration_seconds": round(time.monotonic() - started, 2),
                "items": len(items),
                "has_password": bool((item or {}).get("has_password")),
                "password_scheme": (item or {}).get("password_scheme"),
                "memberships": len((item or {}).get("memberships") or []),
            },
        )
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        return None, CheckResult(f"admin_lookup:{login}", "failed", detail=f"HTTP {exc.code} {detail[:300]}")
    except Exception as exc:
        return None, CheckResult(f"admin_lookup:{login}", "failed", detail=f"{type(exc).__name__}: {exc}")


def _shared_login_users() -> list[str]:
    policy = _identity_policy()
    shared_policy = policy.get("shared_password_users") or []
    if shared_policy:
        return [str(item).strip() for item in shared_policy if str(item).strip()]
    explicit = _csv_env("CRM_AUDIT_SHARED_LOGIN_USERS")
    if explicit:
        return explicit
    users = []
    for key in ("CRM_INMO_USER", "CRM_SHARED_TEST_USERS"):
        users.extend(_csv_env(key))
    if not users:
        user = str(os.environ.get("CRM_INMO_USER") or "").strip()
        if user:
            users.append(user)
    return sorted({user for user in users if user})


def _shared_password() -> str:
    return str(os.environ.get("CRM_AUDIT_SHARED_PASSWORD") or os.environ.get("CRM_INMO_PASSWORD") or "").strip()


def _identity_policy() -> dict:
    path = Path(os.environ.get("CRM_AUDIT_IDENTITY_POLICY_PATH") or DEFAULT_IDENTITY_POLICY_PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def run() -> dict:
    base_url = _base_url()
    timeout = _env_int("CRM_AUDIT_HTTP_TIMEOUT", 45)
    results: list[CheckResult] = []
    users: dict[str, dict] = {}
    failed_checks: list[str] = []
    warnings: list[str] = []

    expected_backend = str(os.environ.get("CRM_EXPECTED_BACKEND") or "postgres").strip().lower()
    backend, build_info = _health_backend(base_url, timeout)
    backend_status = "passed" if backend and backend == expected_backend else "failed"
    results.append(
        CheckResult(
            "backend_mode",
            backend_status,
            detail="" if backend_status == "passed" else f"backend={backend or 'unknown'} expected={expected_backend}",
            metrics={"backend": backend, "expected_backend": expected_backend, "commit": build_info.get("commit")},
        )
    )
    if backend_status != "passed":
        failed_checks.append("backend_mode")

    admin_user = str(os.environ.get("CRM_ADMIN_USER") or "").strip()
    admin_password = str(os.environ.get("CRM_ADMIN_PASSWORD") or "")
    if not admin_user or not admin_password:
        results.append(CheckResult("admin_credentials", "skipped", detail="Faltan CRM_ADMIN_USER/CRM_ADMIN_PASSWORD"))
        return {
            "kind": "prod_auth_drift_audit",
            "base_url": base_url,
            "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "status": "skipped",
            "failed_checks": failed_checks,
            "warnings": warnings,
            "checks": [item.as_dict() for item in results],
            "users": users,
        }

    session, login_data, login_result = _login(base_url, admin_user, admin_password, timeout)
    results.append(login_result)
    if login_result.status != "passed":
        failed_checks.append(login_result.name)
        return {
            "kind": "prod_auth_drift_audit",
            "base_url": base_url,
            "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "status": "failed",
            "failed_checks": failed_checks,
            "warnings": warnings,
            "checks": [item.as_dict() for item in results],
            "users": users,
        }

    shared_users = _shared_login_users()
    shared_password = _shared_password()
    if not shared_users or not shared_password:
        results.append(CheckResult("shared_password_policy", "skipped", detail="Faltan CRM_AUDIT_SHARED_LOGIN_USERS/CRM_AUDIT_SHARED_PASSWORD"))
    else:
        for username in shared_users:
            item, lookup_result = _admin_lookup(base_url, session, username, timeout)
            results.append(lookup_result)
            user_result = {
                "username": username,
                "lookup_ok": lookup_result.status == "passed",
                "login_with_shared_password": False,
                "memberships": (item or {}).get("memberships") or [],
                "password_scheme": (item or {}).get("password_scheme") or "",
                "has_password": bool((item or {}).get("has_password")),
            }
            if lookup_result.status != "passed":
                failed_checks.append(lookup_result.name)
                users[username] = user_result
                continue
            _, _, shared_login = _login(base_url, username, shared_password, timeout)
            shared_login.name = f"shared_password_login:{username}"
            results.append(shared_login)
            user_result["login_with_shared_password"] = shared_login.status == "passed"
            if shared_login.status != "passed":
                failed_checks.append(shared_login.name)
            if not user_result["memberships"]:
                warnings.append(f"no_membership:{username}")
            users[username] = user_result

    status = "failed" if failed_checks else ("passed_with_warnings" if warnings else "passed")
    return {
        "kind": "prod_auth_drift_audit",
        "base_url": base_url,
        "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "failed_checks": failed_checks,
        "warnings": warnings,
        "checks": [item.as_dict() for item in results],
        "users": users,
        "shared_policy": {
            "expected_backend": expected_backend,
            "shared_login_users": shared_users,
            "shared_password_configured": bool(shared_password),
        },
        "identity_policy": _identity_policy(),
        "admin_user": (login_data.get("user") or {}) if isinstance(login_data, dict) else {},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita deriva de accesos en produccion.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo.")
    args = parser.parse_args()
    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
