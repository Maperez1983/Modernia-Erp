#!/usr/bin/env python3
"""Supervisor estructurado del sistema: procesos, impacto de cambios e incidencias."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PROCESS_CATALOG = DOCS / "process_catalog.json"
BUSINESS_RULES = DOCS / "business_rules.json"
SYSTEM_INVARIANTS = DOCS / "system_invariants.json"
CHANGE_IMPACT_MAP = DOCS / "change_impact_map.json"
RECONCILIATION_CHECKS = DOCS / "reconciliation_checks.json"
CANONICAL_SCENARIOS = DOCS / "canonical_scenarios.json"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_supervisor_memory() -> dict:
    return {
        "process_catalog": _load_json(PROCESS_CATALOG),
        "business_rules": _load_json(BUSINESS_RULES),
        "system_invariants": _load_json(SYSTEM_INVARIANTS),
        "change_impact_map": _load_json(CHANGE_IMPACT_MAP),
        "reconciliation_checks": _load_json(RECONCILIATION_CHECKS),
        "canonical_scenarios": _load_json(CANONICAL_SCENARIOS),
    }


def impacted_processes(changed_files: list[str], memory: dict | None = None) -> dict:
    memory = memory or load_supervisor_memory()
    rules = (memory.get("change_impact_map") or {}).get("rules") or []
    process_meta = {item.get("id"): item for item in ((memory.get("process_catalog") or {}).get("processes") or [])}
    matched = {}
    haystack = "\n".join(changed_files).lower()
    for rule in rules:
        patterns = [str(item).lower() for item in (rule.get("match_any") or [])]
        if not patterns or not any(pattern in haystack for pattern in patterns):
            continue
        for process_id in rule.get("processes") or []:
            bucket = matched.setdefault(
                process_id,
                {
                    "process": process_meta.get(process_id, {"id": process_id}),
                    "risk": rule.get("risk") or "medium",
                    "required_checks": [],
                    "required_tests": [],
                    "matched_patterns": [],
                },
            )
            for item in rule.get("required_checks") or []:
                if item not in bucket["required_checks"]:
                    bucket["required_checks"].append(item)
            for item in rule.get("required_tests") or []:
                if item not in bucket["required_tests"]:
                    bucket["required_tests"].append(item)
            for pattern in patterns:
                if pattern in haystack and pattern not in bucket["matched_patterns"]:
                    bucket["matched_patterns"].append(pattern)
            if bucket["risk"] != "critical" and rule.get("risk") == "critical":
                bucket["risk"] = "critical"
    return {"changed_files": changed_files, "processes": list(matched.values())}


def process_health_from_report(report: dict, memory: dict | None = None) -> dict:
    memory = memory or load_supervisor_memory()
    processes = (memory.get("process_catalog") or {}).get("processes") or []
    alerts = report.get("alerts") or []
    alerts_text = json.dumps(alerts, ensure_ascii=False).lower()
    failed_steps = set(report.get("failed_steps") or [])
    result = []
    for process in processes:
        module = str(process.get("module") or "").lower()
        status = "passed"
        reasons = []
        if any(check in failed_steps for check in (process.get("checks") or [])):
            status = "failed"
            reasons.append("check_failed")
        if module and module in alerts_text:
            if status != "failed":
                status = "warning"
            reasons.append("alert_linked")
        result.append(
            {
                "process_id": process.get("id"),
                "module": process.get("module"),
                "criticality": process.get("criticality"),
                "status": status,
                "reasons": reasons,
                "checks": process.get("checks") or [],
            }
        )
    return {"kind": "system_supervisor_health", "processes": result}


def build_snapshot(*, changed_files: list[str] | None = None, report: dict | None = None) -> dict:
    memory = load_supervisor_memory()
    snapshot = {
        "kind": "system_supervisor_snapshot",
        "processes_total": len((memory.get("process_catalog") or {}).get("processes") or []),
        "business_rules_total": len((memory.get("business_rules") or {}).get("rules") or []),
        "global_invariants_total": len((memory.get("system_invariants") or {}).get("global_invariants") or []),
        "reconciliation_checks_total": len((memory.get("reconciliation_checks") or {}).get("checks") or []),
        "canonical_scenarios_total": len((memory.get("canonical_scenarios") or {}).get("scenarios") or []),
    }
    if changed_files is not None:
        snapshot["impact"] = impacted_processes(changed_files, memory=memory)
    if report is not None:
        snapshot["process_health"] = process_health_from_report(report, memory=memory)
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Supervisor estructurado del sistema.")
    parser.add_argument("--changed-file", action="append", default=[], help="Fichero tocado para calcular impacto.")
    parser.add_argument("--report", default="", help="Ruta a reporte de auditoria para resumir salud por proceso.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo.")
    args = parser.parse_args()
    report = _load_json(Path(args.report).resolve()) if args.report else None
    snapshot = build_snapshot(changed_files=args.changed_file or None, report=report)
    print(json.dumps(snapshot, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
