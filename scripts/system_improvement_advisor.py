#!/usr/bin/env python3
"""Propone mejoras estructuradas a partir de auditorías, incidentes y memoria del sistema."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import system_supervisor


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DEFAULT_IMPROVEMENTS_PATH = DOCS / "improvement_opportunities.jsonl"
DEFAULT_HISTORY_PATH = ROOT / "reports" / "system_audit" / "system-audit-history.jsonl"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_jsonl(path: Path, limit: int = 50) -> list[dict]:
    items = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            try:
                items.append(json.loads(raw))
            except Exception:
                continue
    except Exception:
        return []
    return items[-limit:]


def _load_report(path: Path) -> dict:
    return _load_json(path)


def _history_entries(report_path: Path) -> list[dict]:
    history_path = Path(report_path).parent / "system-audit-history.jsonl"
    if history_path.exists():
        return _load_jsonl(history_path)
    return _load_jsonl(DEFAULT_HISTORY_PATH)


def _recent_incidents(memory: dict) -> list[dict]:
    return _load_jsonl(DOCS / "incidents.jsonl")


def _existing_improvements() -> list[dict]:
    return _load_jsonl(DEFAULT_IMPROVEMENTS_PATH)


def _slug(text: str) -> str:
    return (
        str(text or "")
        .strip()
        .lower()
        .replace(" ", "-")
        .replace("/", "-")
        .replace("_", "-")
    )


def _dedupe_key(item: dict) -> str:
    return str(item.get("improvement_id") or f"{item.get('category')}:{item.get('title')}")


def _recent_api_errors(report: dict) -> list[dict]:
    for step in report.get("steps") or []:
        js = step.get("json_summary") or {}
        if js.get("kind") == "prod_auth_drift_audit":
            continue
    return []


def _build_proposals(report: dict, memory: dict, history: list[dict], incidents: list[dict], existing: list[dict]) -> list[dict]:
    proposals = []
    seen = {_dedupe_key(item) for item in existing}
    trend = report.get("trend") or {}
    module_alerts = (trend.get("module_alerts") or {}).get("repeated_modules") or []
    processes = (((memory.get("process_catalog") or {}).get("processes")) or [])
    recent_errors = ((((report.get("steps") or [])[-1:] or [{}])[0].get("json_summary") or {}).get("recent_api_errors") or [])

    for module in module_alerts:
        process_ids = [str(item.get("id") or "") for item in processes if str(item.get("module") or "") == str(module)]
        proposal = {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "improvement_id": f"IMP-REPEATED-{_slug(module)}",
            "category": "test_gap",
            "priority": "high",
            "title": f"Endurecer verificadores del módulo {module}",
            "evidence": [f"repeated_module_warning:{module}", *process_ids[:3]],
            "proposal": f"Añadir smoke más fino, reconciliación y tests de regresión del módulo {module} para cortar alertas repetidas.",
            "expected_benefit": "Reduce regresiones silenciosas y acelera el diagnóstico.",
            "risk": "low",
            "target_files": ["scripts/prod_process_smoke.py", "scripts/system_business_reconciliation.py", "docs/process_catalog.json"],
            "suggested_tests": ["tests/test_ollama_automation_tools.py"],
        }
        key = _dedupe_key(proposal)
        if key not in seen:
            seen.add(key)
            proposals.append(proposal)

    for incident in incidents[-8:]:
        module = str(incident.get("module") or "")
        proposal = {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "improvement_id": f"IMP-LEARN-{_slug(incident.get('incident_id') or module)}",
            "category": "technical_debt",
            "priority": "medium",
            "title": f"Convertir {incident.get('incident_id')} en guardarraíl más específico",
            "evidence": [incident.get("incident_id"), incident.get("symptom")],
            "proposal": "Extraer un verificador específico, un test de regresión y una regla de impacto de cambio para este patrón ya ocurrido.",
            "expected_benefit": "Hace acumulativo el aprendizaje operativo del sistema.",
            "risk": "low",
            "target_files": (incident.get("tests_or_audits") or [])[:4],
            "suggested_tests": (incident.get("tests_or_audits") or [])[:3],
        }
        key = _dedupe_key(proposal)
        if key not in seen:
            seen.add(key)
            proposals.append(proposal)

    build_info_errors = []
    for step in report.get("steps") or []:
        js = step.get("json_summary") or {}
        if js.get("kind") == "prod_api_monitor":
            for item in js.get("checks") or []:
                if item.get("name") == "health" and "backend=postgres" not in str(item.get("detail") or ""):
                    build_info_errors.append("health_not_postgres")
        if js.get("kind") == "system_business_reconciliation":
            for item in js.get("results") or []:
                if item.get("status") == "failed":
                    proposals.append(
                        {
                            "date": datetime.now(timezone.utc).date().isoformat(),
                            "improvement_id": f"IMP-BUSINESS-{_slug(item.get('id'))}",
                            "category": "business_rule",
                            "priority": "high",
                            "title": f"Profundizar reconciliación de negocio en {item.get('module')}",
                            "evidence": [item.get("id"), *(item.get("failed_subchecks") or [])],
                            "proposal": f"Desglosar el check {item.get('id')} en subchecks más específicos y añadir shadow calculations independientes.",
                            "expected_benefit": "Permite detectar antes cálculos erróneos que no rompen el endpoint.",
                            "risk": "medium",
                            "target_files": ["scripts/system_business_reconciliation.py", "docs/reconciliation_checks.json", "web/server.py"],
                            "suggested_tests": ["tests/test_ollama_automation_tools.py"],
                        }
                    )
    if build_info_errors:
        proposal = {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "improvement_id": "IMP-RENDER-RUNTIME-CONFIG-GUARD",
            "category": "security",
            "priority": "high",
            "title": "Blindar la propagación de configuración crítica en Render",
            "evidence": build_info_errors,
            "proposal": "Comprobar en cada cron que el proceso web expone el backend y el origen de DSN esperados, y bloquear cuarentena si la propia contención puede dañar configuración.",
            "expected_benefit": "Evita que el sistema de protección degrade el runtime operativo.",
            "risk": "medium",
            "target_files": ["scripts/render_env_sync.py", "scripts/auto_quarantine_guard.py", "scripts/prod_auth_drift_audit.py"],
            "suggested_tests": ["tests/test_ollama_automation_tools.py"],
        }
        key = _dedupe_key(proposal)
        if key not in seen:
            seen.add(key)
            proposals.append(proposal)

    for err in recent_errors[:3]:
        title = str(err.get("path") or "recent_api_error")
        proposal = {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "improvement_id": f"IMP-API-ERROR-{_slug(title)}",
            "category": "technical_debt",
            "priority": "high",
            "title": f"Corregir fragilidad detectada en {title}",
            "evidence": [title, err.get("message")],
            "proposal": "Aislar la consulta o función con error repetido y añadir test dirigido con el mismo patrón de parámetros.",
            "expected_benefit": "Reduce errores 500 o cálculos parciales en producción.",
            "risk": "medium",
            "target_files": ["web/server.py"],
            "suggested_tests": ["tests/test_ollama_automation_tools.py"],
        }
        key = _dedupe_key(proposal)
        if key not in seen:
            seen.add(key)
            proposals.append(proposal)

    ranked = {"high": 0, "medium": 1, "low": 2}
    proposals.sort(key=lambda item: (ranked.get(str(item.get("priority") or "medium"), 9), str(item.get("title") or "")))
    return proposals[:12]


def _append_new(path: Path, proposals: list[dict], existing: list[dict]) -> int:
    existing_keys = {_dedupe_key(item) for item in existing}
    new_rows = [item for item in proposals if _dedupe_key(item) not in existing_keys]
    if not new_rows:
        return 0
    with path.open("a", encoding="utf-8") as fh:
        for row in new_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(new_rows)


def run(report_path: Path, *, persist: bool = True) -> dict:
    report = _load_report(report_path)
    memory = system_supervisor.load_supervisor_memory()
    history = _history_entries(report_path)
    incidents = _recent_incidents(memory)
    existing = _existing_improvements()
    proposals = _build_proposals(report, memory, history, incidents, existing)
    appended = _append_new(DEFAULT_IMPROVEMENTS_PATH, proposals, existing) if persist else 0
    return {
        "kind": "system_improvement_advisor",
        "status": "passed",
        "proposals_total": len(proposals),
        "appended_total": appended,
        "proposals": proposals,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Asesor de mejoras estructuradas del sistema.")
    parser.add_argument("report_path", help="Ruta al reporte de auditoría.")
    parser.add_argument("--no-persist", action="store_true", help="No guarda propuestas en improvement_opportunities.jsonl.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON.")
    args = parser.parse_args()
    result = run(Path(args.report_path).resolve(), persist=not args.no_persist)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
