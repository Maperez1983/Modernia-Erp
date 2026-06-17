#!/usr/bin/env python3
"""Genera acciones de remediacion segura y no destructiva desde el reporte."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _step_summary(report: dict, kind: str) -> dict:
    for step in report.get("steps") or []:
        js = step.get("json_summary") or {}
        if js.get("kind") == kind:
            return js
    return {}


def run(report_path: Path) -> dict:
    report = _load_report(report_path)
    actions = []
    auth = _step_summary(report, "prod_auth_drift_audit")
    browser = _step_summary(report, "prod_multi_crm_browser_smoke")
    module_smoke = _step_summary(report, "prod_module_smoke")
    quarantine = _step_summary(report, "auto_quarantine_guard")

    for item in auth.get("checks") or []:
        if item.get("status") != "failed":
            continue
        name = str(item.get("name") or "")
        if name.startswith("shared_password_login:"):
            user = name.split(":", 1)[1]
            actions.append({
                "id": f"auth-shared-password-{user}",
                "type": "credential_review",
                "scope": "audit_identity",
                "apply": False,
                "title": f"Revisar credencial compartida de {user}",
                "detail": item.get("detail") or "",
            })
        elif name == "backend_mode":
            actions.append({
                "id": "backend-source-review",
                "type": "backend_guard",
                "scope": "production_backend",
                "apply": False,
                "title": "Revisar backend efectivo de producción",
                "detail": item.get("detail") or "",
            })

    for item in browser.get("results") or []:
        if item.get("status") not in {"failed", "warning"}:
            continue
        actions.append({
            "id": f"browser-{item.get('user_label')}:{item.get('module')}",
            "type": "browser_validation",
            "scope": item.get("module"),
            "apply": False,
            "title": f"Revisar navegación de {item.get('module')} ({item.get('user_label')})",
            "detail": item.get("detail") or item.get("route") or "",
        })

    for item in module_smoke.get("results") or []:
        if item.get("status") not in {"failed", "warning"}:
            continue
        actions.append({
            "id": f"module-{item.get('user_label')}:{item.get('module')}",
            "type": "module_validation",
            "scope": item.get("module"),
            "apply": False,
            "title": f"Revisar smoke de {item.get('module')} ({item.get('user_label')})",
            "detail": f"rows_total={item.get('rows_total')} min_rows_total={item.get('min_rows_total')}",
        })

    if quarantine.get("quarantined"):
        actions.insert(0, {
            "id": "containment-active",
            "type": "containment",
            "scope": quarantine.get("scope") or "global",
            "apply": True,
            "title": f"Cuarentena activa en modo {quarantine.get('mode') or 'quarantine'}",
            "detail": quarantine.get("reason") or "",
        })

    return {
        "kind": "safe_auto_remediation",
        "status": "passed" if not actions else "passed_with_actions",
        "actions_total": len(actions),
        "actions": actions[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera remediacion segura.")
    parser.add_argument("report_path", help="Ruta al reporte JSON.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON.")
    args = parser.parse_args()
    result = run(Path(args.report_path).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
