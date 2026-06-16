#!/usr/bin/env python3
"""Audita invariantes de acceso del home frontend.

Detecta regresiones donde una card CRM pueda mostrarse pero quedar bloqueada al
hacer click por guards inconsistentes de permisos.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "web" / "app.js"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_app() -> str:
    return APP_JS.read_text(encoding="utf-8", errors="replace")


def _check(app_js: str, *, name: str, snippet: str, detail: str) -> dict:
    ok = snippet in app_js
    return {
        "name": name,
        "status": "passed" if ok else "failed",
        "detail": "" if ok else detail,
    }


def run() -> dict:
    app_js = _read_app()
    checks = [
        _check(
            app_js,
            name="admin_wide_access_helper",
            snippet="const hasAdminWideAccess = (user) => {",
            detail="Falta helper centralizado para acceso amplio de administracion.",
        ),
        _check(
            app_js,
            name="shared_home_modules_follow_admin_wide_access",
            snippet="const canAccessSharedHomeModules = (user) => hasAdminWideAccess(user);",
            detail="Las cards compartidas del home no siguen el criterio de acceso amplio.",
        ),
        _check(
            app_js,
            name="service_access_follows_admin_wide_access",
            snippet="if (hasAdminWideAccess(user)) return true;",
            detail="Los guards de apertura CRM no reconocen acceso amplio por rol/servicio.",
        ),
        _check(
            app_js,
            name="core_cards_click_handler_present",
            snippet='coreCards.addEventListener("click", (event) => {',
            detail="No existe manejador central de click para las cards del home.",
        ),
        _check(
            app_js,
            name="core_cards_have_fallback_href_navigation",
            snippet="const fallbackNavigate = () => {",
            detail="Las cards no tienen navegacion de respaldo mediante href.",
        ),
    ]

    for service_key, action, opener in (
        ("inmobiliaria", "crm-inmo", "openCrmInmobiliario"),
        ("gestoria", "crm-gestoria", "openCrmGestoria"),
        ("seguros", "crm-seguros", "openCrmSeguros"),
        ("financiaciones", "crm-fin", "openCrmFinanciaciones"),
    ):
        checks.append(
            _check(
                app_js,
                name=f"service_card_{service_key}_action",
                snippet=f'card.dataset.action = "{action}";',
                detail=f"La card de {service_key} no define data-action consistente.",
            )
        )
        checks.append(
            _check(
                app_js,
                name=f"service_card_{service_key}_anchor",
                snippet=f'data-action="{action}"',
                detail=f"La card de {service_key} no define link navegable consistente.",
            )
        )
        checks.append(
            _check(
                app_js,
                name=f"service_card_{service_key}_guard",
                snippet=f'if (!userCanAccessService("{service_key}")) return;',
                detail=f"La apertura de {opener} no protege ni documenta el guard esperado.",
            )
        )

    failed = [item["name"] for item in checks if item["status"] == "failed"]
    actionable = [
        {
            "module": "frontend_home",
            "check": item["name"],
            "detail": item["detail"],
        }
        for item in checks
        if item["status"] == "failed"
    ]
    return {
        "kind": "frontend_home_access_audit",
        "generated_at": _utc_now(),
        "status": "failed" if failed else "passed",
        "failed_checks": failed,
        "summary": {
            "checks_total": len(checks),
            "failed_checks": len(failed),
            "actionable_warnings": len(actionable),
        },
        "actionable_warnings": actionable,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita invariantes de acceso del home frontend.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo.")
    args = parser.parse_args()
    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
