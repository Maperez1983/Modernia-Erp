#!/usr/bin/env python3
"""Audita la postura operativa de seguridad del CRM en produccion."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import prod_auth_drift_audit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVARIANTS_PATH = ROOT / "docs" / "security_invariants.json"


def _load_invariants() -> list[dict]:
    path = Path(os.environ.get("CRM_SECURITY_INVARIANTS_PATH") or DEFAULT_INVARIANTS_PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = data.get("invariants")
    return items if isinstance(items, list) else []


def _severity_rank(value: str) -> int:
    return {"critical": 3, "high": 2, "medium": 1, "low": 0}.get(str(value or "").lower(), 0)


def run() -> dict:
    auth = prod_auth_drift_audit.run()
    invariants = _load_invariants()
    findings = []
    summary = {"critical": 0, "high": 0, "medium": 0, "low": 0}

    backend = (((auth.get("checks") or [None])[0] or {}).get("metrics") or {}).get("backend")
    if backend != (auth.get("shared_policy") or {}).get("expected_backend"):
        findings.append(
            {
                "id": "backend-postgres-production",
                "severity": "critical",
                "status": "failed",
                "detail": f"backend={backend} expected={(auth.get('shared_policy') or {}).get('expected_backend')}",
            }
        )

    lookup_failed = [item for item in (auth.get("checks") or []) if str(item.get("name") or "").startswith("admin_lookup:") and item.get("status") != "passed"]
    if lookup_failed:
        findings.append(
            {
                "id": "admin-lookup-available",
                "severity": "high",
                "status": "failed",
                "detail": f"fallos={len(lookup_failed)}",
            }
        )

    shared_failed = [item for item in (auth.get("checks") or []) if str(item.get("name") or "").startswith("shared_password_login:") and item.get("status") != "passed"]
    if shared_failed:
        findings.append(
            {
                "id": "shared-test-password-cohort",
                "severity": "high",
                "status": "failed",
                "detail": f"fallos={len(shared_failed)}",
            }
        )

    no_membership_users = sorted(
        username
        for username, data in (auth.get("users") or {}).items()
        if not (data.get("memberships") or [])
    )
    if no_membership_users:
        findings.append(
            {
                "id": "no-active-user-without-signal",
                "severity": "medium",
                "status": "warning",
                "detail": ", ".join(no_membership_users[:20]),
            }
        )

    for item in findings:
        sev = str(item.get("severity") or "low").lower()
        summary[sev] = summary.get(sev, 0) + 1

    status = "failed" if any(item.get("status") == "failed" and _severity_rank(item.get("severity")) >= 2 for item in findings) else ("passed_with_warnings" if findings else "passed")
    return {
        "kind": "prod_security_posture_audit",
        "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": status,
        "failed_checks": [item["id"] for item in findings if item.get("status") == "failed"],
        "warnings": [item["id"] for item in findings if item.get("status") == "warning"],
        "invariants_total": len(invariants),
        "findings": findings,
        "summary": summary,
        "auth_drift_status": auth.get("status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audita postura de seguridad operativa en produccion.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo.")
    args = parser.parse_args()
    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
