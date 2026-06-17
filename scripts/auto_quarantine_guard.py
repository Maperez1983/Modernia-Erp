#!/usr/bin/env python3
"""Activa o limpia cuarentena operativa en Render segun el ultimo reporte."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

if __package__ in {None, ""}:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import render_env_sync


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _quarantine_decision(report: dict) -> dict:
    alerts = report.get("alerts") or []
    quarantine_types = {"auth_drift", "security_posture", "new_failure", "step_failed"}
    read_only_types = {"module_smoke", "browser_smoke", "module_volume_drop", "user_module_volume_drop"}
    strongest = {"mode": "off", "scope": "", "reason": ""}
    for item in alerts:
        alert_type = str(item.get("type") or "").strip().lower()
        severity = str(item.get("severity") or "").strip().lower()
        title = str(item.get("title") or item.get("type") or "incident").strip()
        scope = str(item.get("module") or item.get("workspace") or "global").strip() or "global"
        if alert_type in quarantine_types or severity == "critical":
            return {"mode": "quarantine", "scope": scope, "reason": title}
        if strongest["mode"] == "off" and (alert_type in read_only_types or severity == "high"):
            strongest = {"mode": "read_only", "scope": scope, "reason": title}
    return strongest


def _render_env_update(api_key: str, service_id: str, pairs: dict[str, str]) -> dict:
    return render_env_sync.sync_env_vars(api_key, service_id, pairs, dry_run=False)


def run(report_path: Path) -> dict:
    report = _load_json(report_path)
    api_key = str(os.environ.get("RENDER_API_KEY") or "").strip()
    service_id = str(os.environ.get("RENDER_WEB_SERVICE_ID") or "").strip()
    if not api_key or not service_id:
        return {"kind": "auto_quarantine_guard", "status": "skipped", "detail": "Faltan RENDER_API_KEY/RENDER_WEB_SERVICE_ID"}
    decision = _quarantine_decision(report)
    if decision["mode"] != "off":
        payload = {
            "APP_EMERGENCY_MODE": decision["mode"],
            "APP_EMERGENCY_SCOPE": decision["scope"][:180],
            "APP_EMERGENCY_REASON": decision["reason"][:180],
        }
        _render_env_update(api_key, service_id, payload)
        return {
            "kind": "auto_quarantine_guard",
            "status": "passed",
            "quarantined": True,
            "mode": decision["mode"],
            "scope": decision["scope"],
            "reason": decision["reason"],
        }
    if (os.environ.get("RUN_SYSTEM_AUDIT_AUTO_CLEAR_QUARANTINE") or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}:
        payload = {
            "APP_EMERGENCY_MODE": "off",
            "APP_EMERGENCY_SCOPE": "",
            "APP_EMERGENCY_REASON": "",
        }
        _render_env_update(api_key, service_id, payload)
        return {"kind": "auto_quarantine_guard", "status": "passed", "quarantined": False, "mode": "off", "scope": "", "reason": "cleared"}
    return {"kind": "auto_quarantine_guard", "status": "passed", "quarantined": False, "mode": "off", "scope": "", "reason": "not_required"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Activa cuarentena operativa segun auditoria.")
    parser.add_argument("report_path", help="Ruta al reporte JSON de auditoria.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON.")
    args = parser.parse_args()
    result = run(Path(args.report_path).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
