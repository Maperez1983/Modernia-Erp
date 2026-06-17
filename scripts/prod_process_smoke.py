#!/usr/bin/env python3
"""Smoke por procesos críticos a partir de señales reales de producción."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import prod_module_smoke
from scripts import prod_multi_crm_browser_smoke
from scripts import system_business_reconciliation
from scripts import system_supervisor


PROCESS_STATUSES_OK = {"passed", "passed_with_warnings"}


def _index_by_module(items: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for item in items:
        result.setdefault(str(item.get("module") or "unknown"), []).append(item)
    return result


def run() -> dict:
    memory = system_supervisor.load_supervisor_memory()
    processes = (memory.get("process_catalog") or {}).get("processes") or []
    module_smoke = prod_module_smoke.run()
    browser_smoke = prod_multi_crm_browser_smoke.run()
    reconciliation = system_business_reconciliation.run()
    module_index = _index_by_module(module_smoke.get("results") or [])
    browser_index = _index_by_module(browser_smoke.get("results") or [])
    reconciliation_index = {str(item.get("id") or ""): item for item in (reconciliation.get("results") or [])}

    results = []
    failed_checks = []
    warnings = []
    for process in processes:
        process_id = str(process.get("id") or "")
        module = str(process.get("module") or "unknown")
        reasons = []
        status = "passed"
        module_rows = module_index.get(module, [])
        browser_rows = browser_index.get(module, [])
        recon = reconciliation_index.get(process_id)
        if module_rows and not any(item.get("status") == "passed" for item in module_rows):
            status = "failed"
            reasons.append("module_smoke")
        elif any(item.get("status") == "warning" for item in module_rows):
            status = "warning"
            reasons.append("module_smoke_warning")
        if browser_rows and not any(item.get("status") == "passed" for item in browser_rows):
            status = "failed"
            reasons.append("browser_smoke")
        elif status == "passed" and any(item.get("status") == "warning" for item in browser_rows):
            status = "warning"
            reasons.append("browser_smoke_warning")
        if recon and recon.get("status") not in PROCESS_STATUSES_OK:
            status = "failed"
            reasons.append("business_reconciliation")
        elif recon and recon.get("status") == "passed":
            reasons.append("business_reconciliation")

        row = {
            "process_id": process_id,
            "module": module,
            "criticality": process.get("criticality"),
            "status": status,
            "reasons": reasons,
            "checks": process.get("checks") or [],
        }
        results.append(row)
        if status == "failed":
            failed_checks.append(process_id)
        elif status == "warning":
            warnings.append(process_id)

    return {
        "kind": "prod_process_smoke",
        "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "failed" if failed_checks else ("passed_with_warnings" if warnings else "passed"),
        "failed_checks": failed_checks,
        "warnings": warnings,
        "results": results,
        "sources": {
            "module_smoke_status": module_smoke.get("status"),
            "browser_smoke_status": browser_smoke.get("status"),
            "business_reconciliation_status": reconciliation.get("status"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke por procesos críticos.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON.")
    args = parser.parse_args()
    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
