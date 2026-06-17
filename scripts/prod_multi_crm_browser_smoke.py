#!/usr/bin/env python3
"""Smoke Playwright multi-CRM sobre la navegacion real de produccion."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlencode

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None


DEFAULT_BASE_URL = "https://crm.verifika2.com"
DEFAULT_WORKSPACE_HINT = "verifika"
DEFAULT_TIMEOUT_MS = 60000

MODULE_SPECS = {
    "inmobiliaria": {
        "query": {"crm": "inmo", "tab": "crm"},
        "wait_for": "#crmSection:not(.hidden)",
        "ready_js": "(() => !!document.querySelector('#crmSection:not(.hidden)'))()",
    },
    "gestoria": {
        "query": {"crm": "gestoria", "tab": "gestoria-crm"},
        "wait_for": "#gestoriaCrmSection:not(.hidden)",
        "ready_js": "(() => !!document.querySelector('#gestoriaCrmSection:not(.hidden)') && !!document.getElementById('gestoriaCrmTable'))()",
    },
    "seguros": {
        "query": {"crm": "seguros", "tab": "seguros-crm"},
        "wait_for": "#segurosCrmSection:not(.hidden)",
        "ready_js": "(() => !!document.querySelector('#segurosCrmSection:not(.hidden)') && !!document.getElementById('segurosKpis'))()",
    },
    "financiero": {
        "query": {"crm": "fin", "tab": "fin-crm"},
        "wait_for": "#finDashboardSection:not(.hidden), #finCrmSection:not(.hidden)",
        "ready_js": "(() => !!document.querySelector('#finDashboardSection:not(.hidden), #finCrmSection:not(.hidden)') && (!!document.getElementById('finDashboardKpis') || !!document.getElementById('finCrmTable')))()",
    },
    "fincas": {
        "query": {"view": "fincas"},
        "wait_for": "[data-workspace-view=\"fincas\"]:not(.hidden)",
        "ready_js": "(() => !!document.querySelector('[data-workspace-view=\"fincas\"]:not(.hidden)') && !!document.getElementById('workspaceFincasCommunityList'))()",
    },
    "rrhh": {
        "query": {"view": "rrhh"},
        "wait_for": "[data-workspace-view=\"rrhh\"]:not(.hidden)",
        "ready_js": "(() => !!document.querySelector('[data-workspace-view=\"rrhh\"]:not(.hidden)') && !!document.getElementById('workspaceRrhhHub'))()",
    },
}


def _base_origin() -> str:
    value = (os.environ.get("CRM_E2E_URL") or os.environ.get("CRM_BASE_URL") or DEFAULT_BASE_URL).strip()
    return value.split("?", 1)[0].rstrip("/")


def _workspace_hint() -> str:
    return (os.environ.get("CRM_AUDIT_WORKSPACE") or DEFAULT_WORKSPACE_HINT).strip().lower()


def _credential_specs() -> list[dict]:
    specs = []
    admin_user = (os.environ.get("CRM_ADMIN_USER") or "").strip()
    admin_password = os.environ.get("CRM_ADMIN_PASSWORD") or ""
    if admin_user and admin_password:
        specs.append({"label": "admin", "user": admin_user, "password": admin_password, "modules": list(MODULE_SPECS)})
    non_admin_user = (os.environ.get("CRM_INMO_USER") or "").strip()
    non_admin_password = os.environ.get("CRM_INMO_PASSWORD") or ""
    if non_admin_user and non_admin_password:
        specs.append({"label": "non_admin", "user": non_admin_user, "password": non_admin_password, "modules": ["inmobiliaria"]})
    return specs


def _pick_workspace(rows: list[dict]) -> dict:
    if not rows:
        return {}
    preferred = _workspace_hint()
    for row in rows:
        haystack = " ".join(str(row.get(k) or "") for k in ("id", "nombre", "slug")).lower()
        if preferred and preferred in haystack:
            return row
    return rows[0]


def _route_for(workspace_token: str, module_key: str) -> str:
    params = {"holding": "1", "mode": "tenant", "workspace": workspace_token, "nosw": "1", "swcleared": "1"}
    params.update(MODULE_SPECS[module_key]["query"])
    return f"/?{urlencode(params)}"


def _login(page, base_url: str, user: str, password: str) -> tuple[dict, dict]:
    page.goto(f"{base_url}/?nosw=1&swcleared=1", wait_until="domcontentloaded")
    page.wait_for_selector("#authLoginUser", timeout=DEFAULT_TIMEOUT_MS)
    page.fill("#authLoginUser", user)
    page.fill("#authLoginPass", password)
    with page.expect_response(lambda r: r.url.endswith("/api/login")) as login_info:
        page.click('#authLoginForm button[type="submit"]')
    login_resp = login_info.value
    login_data = login_resp.json()
    if not login_resp.ok or not login_data.get("ok"):
        raise RuntimeError(f"login_failed http={login_resp.status} data={login_data}")
    page.wait_for_function("() => !document.body.classList.contains('auth-locked')", timeout=DEFAULT_TIMEOUT_MS)
    with page.expect_response(lambda r: r.url.endswith("/api/workspaces")) as ws_info:
        page.evaluate("() => fetch('/api/workspaces').then((r) => r.json()).catch(() => ({}))")
    workspaces = ws_info.value
    ws_data = workspaces.json() if workspaces.ok else {}
    rows = ws_data.get("rows") if isinstance(ws_data, dict) else []
    return login_data, _pick_workspace(rows if isinstance(rows, list) else [])


def _module_metrics(page, module_key: str) -> dict:
    js = """
      (moduleKey) => {
        const chars = (selector) => {
          const el = document.querySelector(selector);
          return el ? String(el.innerText || el.textContent || '').trim().length : 0;
        };
        if (moduleKey === 'inmobiliaria') return { visible: !!document.querySelector('#crmSection:not(.hidden)'), chars: chars('#crmSection') };
        if (moduleKey === 'gestoria') return { visible: !!document.querySelector('#gestoriaCrmSection:not(.hidden)'), chars: chars('#gestoriaCrmTable') };
        if (moduleKey === 'seguros') return { visible: !!document.querySelector('#segurosCrmSection:not(.hidden)'), chars: chars('#segurosKpis') };
        if (moduleKey === 'financiero') return { visible: !!document.querySelector('#finDashboardSection:not(.hidden), #finCrmSection:not(.hidden)'), chars: chars('#finDashboardKpis') + chars('#finCrmTable') };
        if (moduleKey === 'fincas') return { visible: !!document.querySelector('[data-workspace-view=\"fincas\"]:not(.hidden)'), chars: chars('#workspaceFincasCommunityList') };
        if (moduleKey === 'rrhh') return { visible: !!document.querySelector('[data-workspace-view=\"rrhh\"]:not(.hidden)'), chars: chars('#workspaceRrhhHub') };
        return { visible: false, chars: 0 };
      }
    """
    return page.evaluate(js, module_key)


def run() -> dict:
    if sync_playwright is None:
        return {"kind": "prod_multi_crm_browser_smoke", "status": "skipped", "detail": "Playwright no disponible", "results": [], "failed_checks": [], "warnings": []}

    credential_specs = _credential_specs()
    if not credential_specs:
        return {"kind": "prod_multi_crm_browser_smoke", "status": "skipped", "detail": "Faltan credenciales", "results": [], "failed_checks": [], "warnings": []}

    base_url = _base_origin()
    results = []
    failed_checks = []
    warnings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for spec in credential_specs:
            context = browser.new_context(ignore_https_errors=True, service_workers="block")
            page = context.new_page()
            page.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS * 2)
            try:
                login_data, workspace = _login(page, base_url, spec["user"], spec["password"])
                workspace_token = str(workspace.get("slug") or workspace.get("id") or "").strip()
                if not workspace_token:
                    raise RuntimeError("workspace_not_found")
                for module_key in spec["modules"]:
                    module_spec = MODULE_SPECS[module_key]
                    route = _route_for(workspace_token, module_key)
                    page.goto(f"{base_url}{route}", wait_until="domcontentloaded")
                    page.wait_for_selector(module_spec["wait_for"], timeout=DEFAULT_TIMEOUT_MS)
                    page.wait_for_function(module_spec["ready_js"], timeout=DEFAULT_TIMEOUT_MS)
                    metrics = _module_metrics(page, module_key)
                    status = "passed" if metrics.get("visible") else "failed"
                    if status == "passed" and int(metrics.get("chars") or 0) == 0:
                        status = "warning"
                        warnings.append(f"{spec['label']}:{module_key}")
                    elif status == "failed":
                        failed_checks.append(f"{spec['label']}:{module_key}")
                    results.append(
                        {
                            "user_label": spec["label"],
                            "module": module_key,
                            "status": status,
                            "workspace_nombre": workspace.get("nombre"),
                            "workspace_slug": workspace.get("slug"),
                            "route": route,
                            "metrics": {
                                "chars": int(metrics.get("chars") or 0),
                                "visible": bool(metrics.get("visible")),
                                "user": (login_data.get("user") or {}).get("usuario"),
                            },
                        }
                    )
            except Exception as exc:
                failed_checks.append(spec["label"])
                results.append({"user_label": spec["label"], "module": "session", "status": "failed", "detail": f"{type(exc).__name__}: {exc}", "route": "", "metrics": {}})
            finally:
                context.close()
        browser.close()

    status = "failed" if failed_checks else ("passed_with_warnings" if warnings else "passed")
    return {
        "kind": "prod_multi_crm_browser_smoke",
        "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "base_url": base_url,
        "failed_checks": failed_checks,
        "warnings": warnings,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke Playwright multi-CRM.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON.")
    args = parser.parse_args()
    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
