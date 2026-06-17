#!/usr/bin/env python3
"""Activa o limpia cuarentena operativa en Render segun el ultimo reporte."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _should_quarantine(report: dict) -> tuple[bool, str]:
    critical_types = {"auth_drift", "security_posture", "module_smoke", "module_volume_drop", "user_module_volume_drop", "new_failure"}
    alerts = report.get("alerts") or []
    hits = [item for item in alerts if str(item.get("type") or "") in critical_types or str(item.get("severity") or "").lower() == "critical"]
    if hits:
        top = hits[0]
        return True, str(top.get("title") or top.get("type") or "critical_incident")
    return False, ""


def _render_env_update(api_key: str, service_id: str, pairs: dict[str, str]) -> dict:
    body = json.dumps([{"key": key, "value": value} for key, value in pairs.items()]).encode("utf-8")
    req = Request(
        f"https://api.render.com/v1/services/{service_id}/env-vars",
        data=body,
        method="PUT",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run(report_path: Path) -> dict:
    report = _load_json(report_path)
    api_key = str(os.environ.get("RENDER_API_KEY") or "").strip()
    service_id = str(os.environ.get("RENDER_WEB_SERVICE_ID") or "").strip()
    if not api_key or not service_id:
        return {"kind": "auto_quarantine_guard", "status": "skipped", "detail": "Faltan RENDER_API_KEY/RENDER_WEB_SERVICE_ID"}
    quarantine, reason = _should_quarantine(report)
    if quarantine:
        payload = {
            "APP_EMERGENCY_MODE": "1",
            "APP_EMERGENCY_REASON": reason[:180],
        }
        _render_env_update(api_key, service_id, payload)
        return {"kind": "auto_quarantine_guard", "status": "passed", "quarantined": True, "reason": reason}
    if (os.environ.get("RUN_SYSTEM_AUDIT_AUTO_CLEAR_QUARANTINE") or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}:
        payload = {
            "APP_EMERGENCY_MODE": "0",
            "APP_EMERGENCY_REASON": "",
        }
        _render_env_update(api_key, service_id, payload)
        return {"kind": "auto_quarantine_guard", "status": "passed", "quarantined": False, "reason": "cleared"}
    return {"kind": "auto_quarantine_guard", "status": "passed", "quarantined": False, "reason": "not_required"}


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
