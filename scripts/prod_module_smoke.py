#!/usr/bin/env python3
"""Smoke funcional por modulos con usuarios reales de produccion."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import prod_system_matrix_audit


MODULE_TARGETS = {
    "inmobiliaria": {"agenda_inmobiliaria", "inmuebles", "demandas", "visitas", "compraventas"},
    "seguros": {"seguros_overview", "seguros_kpis", "seguros_recibos_summary"},
    "gestoria": {"gestoria_overview", "gestoria_dashboard", "gestoria_modelos"},
    "financiero": {"fin_overview", "fin_kpis", "fin_alertas"},
    "fincas": {"fincas_comunidades"},
    "rrhh": {"rrhh_personal"},
    "core": {"workspace_health", "workspace_service_desks", "workspace_clientes", "clientes_list"},
}

DEFAULT_EXPECTATIONS_PATH = Path(__file__).resolve().parents[1] / "docs" / "module_smoke_expectations.json"
NON_ACTIONABLE_WARNING_CLASSES = {"expected_permission_denied", "not_applicable"}


def _load_expectations() -> dict:
    path = Path(os.environ.get("RUN_SYSTEM_AUDIT_MODULE_EXPECTATIONS_PATH") or DEFAULT_EXPECTATIONS_PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def run() -> dict:
    matrix = prod_system_matrix_audit.run()
    expectations = _load_expectations()
    endpoint_matrix = matrix.get("endpoint_matrix") or []
    by_user_module: dict[str, dict[str, list[dict]]] = {}
    for item in endpoint_matrix:
        label = str(item.get("user_label") or "unknown")
        module = str(item.get("module") or "unknown")
        by_user_module.setdefault(label, {}).setdefault(module, []).append(item)

    results = []
    failed_checks = []
    warning_checks = []
    for label, module_map in by_user_module.items():
        for module, target_endpoints in MODULE_TARGETS.items():
            rows = [item for item in module_map.get(module, []) if str(item.get("endpoint") or "") in target_endpoints]
            if not rows:
                continue
            passed = [item for item in rows if item.get("status") == "passed"]
            warnings = [item for item in rows if item.get("status") == "warning"]
            failed = [item for item in rows if item.get("status") == "failed"]
            warning_classes = {str(item.get("class") or "").strip() for item in warnings if str(item.get("class") or "").strip()}
            only_non_actionable_warnings = bool(warnings) and warning_classes.issubset(NON_ACTIONABLE_WARNING_CLASSES) and not failed and not passed
            rows_total = sum(int(item.get("rows") or 0) for item in rows)
            key = f"{label}:{module}"
            min_rows = int(
                ((expectations.get("by_user_module") or {}).get(key, {}) or {}).get(
                    "min_rows_total",
                    ((expectations.get("by_module") or {}).get(module, {}) or {}).get(
                        "min_rows_total",
                        (expectations.get("defaults") or {}).get("min_rows_total", 1),
                    ),
                )
            )
            status = "passed" if passed else ("warning" if warnings and not failed else "failed")
            if only_non_actionable_warnings:
                status = "skipped"
            if status == "passed" and rows_total < min_rows:
                status = "warning"
            sample = rows[0]
            results.append(
                {
                    "user_label": label,
                    "module": module,
                    "status": status,
                    "workspace_nombre": sample.get("workspace_nombre"),
                    "rows_total": rows_total,
                    "min_rows_total": min_rows,
                    "endpoints_checked": len(rows),
                    "passed_endpoints": len(passed),
                    "warning_endpoints": len(warnings),
                    "failed_endpoints": len(failed),
                    "warning_classes": sorted(warning_classes),
                }
            )
            if status == "failed":
                failed_checks.append(f"{label}:{module}")
            elif status == "warning":
                warning_checks.append(f"{label}:{module}")

    return {
        "kind": "prod_module_smoke",
        "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "failed" if failed_checks else ("passed_with_warnings" if warning_checks else "passed"),
        "failed_checks": failed_checks,
        "warnings": warning_checks,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke funcional por modulos en produccion.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo.")
    args = parser.parse_args()
    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
