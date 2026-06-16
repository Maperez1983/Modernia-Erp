#!/usr/bin/env python3
"""Ejecuta una auditoria reproducible del CRM y guarda resultados en JSON."""

from __future__ import annotations

import argparse
import html
import json
import os
import shlex
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "reports" / "system_audit"

FAST_PYTESTS = [
    "tests/test_frontend_smoke.py",
    "tests/test_agenda_frontend_regressions.py",
    "tests/test_api_usuarios_scoping.py",
    "tests/test_workspace_membership_autojoin.py",
    "tests/test_workspace_scope_empresa_ids.py",
    "tests/test_inmobiliaria_crm_smoke.py",
    "tests/test_cliente_ficha.py",
    "tests/test_seguros_activation.py",
    "tests/test_fin_workflow.py",
    "tests/test_gestoria_import_backend.py",
]

E2E_PYTESTS = [
    "tests/test_inmobiliaria_e2e_playwright.py",
    "tests/test_seguros_e2e_playwright.py",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def _summarize_json_output(output: str) -> dict | None:
    try:
        data = json.loads(output or "{}")
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    kind = data.get("kind")
    if kind == "prod_api_monitor":
        return {
            "kind": kind,
            "status": data.get("status"),
            "base_url": data.get("base_url"),
            "failed_checks": data.get("failed_checks"),
            "checks": [
                {
                    "name": item.get("name"),
                    "status": item.get("status"),
                    "detail": item.get("detail"),
                    "metrics": item.get("metrics"),
                }
                for item in (data.get("checks") or [])
                if isinstance(item, dict)
            ],
            "users": data.get("users"),
        }
    if kind == "prod_system_matrix_audit":
        return {
            "kind": kind,
            "status": data.get("status"),
            "base_url": data.get("base_url"),
            "failed_checks": data.get("failed_checks"),
            "warning_checks": (data.get("warning_checks") or [])[:80],
            "summary": data.get("summary"),
            "actionable_warnings": data.get("actionable_warnings"),
            "users": data.get("users"),
            "workspaces_by_user": data.get("workspaces_by_user"),
            "workspace_user_inventory": [
                {
                    "workspace_id": item.get("workspace_id"),
                    "workspace_nombre": item.get("workspace_nombre"),
                    "status": item.get("status"),
                    "users_total": item.get("users_total"),
                    "users_active": item.get("users_active"),
                    "users_sample": item.get("users_sample"),
                }
                for item in (data.get("workspace_user_inventory") or [])
                if isinstance(item, dict)
            ],
        }
    if kind == "codebase_inventory_for_ollama":
        return {
            "kind": kind,
            "git": data.get("git"),
            "files": data.get("files"),
            "backend": data.get("backend"),
            "frontend": {
                "function_count": (data.get("frontend") or {}).get("function_count"),
                "event_handlers": (data.get("frontend") or {}).get("event_handlers"),
                "sample_functions": ((data.get("frontend") or {}).get("sample_functions") or [])[:80],
            },
            "tests": data.get("tests"),
            "risk_markers_sample": (data.get("risk_markers") or [])[:80],
        }
    return {
        "kind": kind,
        "status": data.get("status"),
        "failed_checks": data.get("failed_checks"),
        "summary": data.get("summary"),
    }


def _build_alerts(report: dict) -> list[dict]:
    alerts = []
    for step in report.get("steps", []):
        name = step.get("name")
        status = step.get("status")
        if status not in {"passed", "skipped"}:
            alerts.append(
                {
                    "severity": "high",
                    "type": "step_failed",
                    "title": f"Fallo en {name}",
                    "detail": (step.get("output_tail") or "")[-1000:],
                }
            )
        js = step.get("json_summary") or {}
        if js.get("kind") == "prod_system_matrix_audit":
            for item in js.get("actionable_warnings") or []:
                classification = item.get("classification") or {}
                alerts.append(
                    {
                        "severity": classification.get("severity") or "medium",
                        "type": classification.get("class") or "matrix_warning",
                        "title": f"{item.get('module')}/{item.get('endpoint')} requiere revision",
                        "detail": item.get("detail") or "",
                        "workspace": item.get("workspace_nombre"),
                        "user_label": item.get("user_label"),
                    }
                )
    return alerts


def _load_history(report_dir: Path, limit: int = 20) -> list[dict]:
    history_path = report_dir / "system-audit-history.jsonl"
    if not history_path.exists():
        return []
    entries = []
    try:
        with history_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return entries[-limit:]


def _matrix_summary_from_report(report: dict) -> dict:
    for step in report.get("steps", []):
        js = step.get("json_summary") or {}
        if js.get("kind") == "prod_system_matrix_audit":
            summary = dict(js.get("summary") or {})
            summary["actionable_warnings_total"] = len(js.get("actionable_warnings") or [])
            return summary
    return {}


def _build_trend_data(report: dict, previous_entries: list[dict]) -> dict:
    latest_prev = previous_entries[-1] if previous_entries else {}
    current_failed = set(report.get("failed_steps") or [])
    previous_failed = set(latest_prev.get("failed_steps") or [])
    current_matrix = _matrix_summary_from_report(report)
    previous_matrix = {}
    for step in latest_prev.get("steps") or []:
        js = step.get("json_summary") or {}
        if js.get("kind") == "prod_system_matrix_audit":
            previous_matrix = dict(js.get("summary") or {})
            previous_matrix["actionable_warnings_total"] = js.get("actionable_warnings_total") or 0
            break

    repeated_failures = sorted(current_failed & previous_failed)
    recovered_failures = sorted(previous_failed - current_failed)
    new_failures = sorted(current_failed - previous_failed)
    consecutive_failed_runs = 0
    if report.get("status") == "failed":
        for entry in reversed(previous_entries):
            if entry.get("status") != "failed":
                break
            consecutive_failed_runs += 1
        consecutive_failed_runs += 1

    classification_counts = current_matrix.get("endpoint_classification_counts") or {}
    previous_classification_counts = previous_matrix.get("endpoint_classification_counts") or {}
    changed_classes = {}
    all_classes = set(classification_counts) | set(previous_classification_counts)
    for key in sorted(all_classes):
        delta = int(classification_counts.get(key, 0)) - int(previous_classification_counts.get(key, 0))
        if delta:
            changed_classes[key] = delta

    recent_status_counts = Counter(entry.get("status") or "unknown" for entry in previous_entries[-9:])
    recent_status_counts[report.get("status") or "unknown"] += 1
    return {
        "previous_run_id": latest_prev.get("run_id"),
        "previous_status": latest_prev.get("status"),
        "repeated_failures": repeated_failures,
        "new_failures": new_failures,
        "recovered_failures": recovered_failures,
        "consecutive_failed_runs": consecutive_failed_runs,
        "recent_status_counts": dict(recent_status_counts),
        "matrix": {
            "current": current_matrix,
            "previous": previous_matrix,
            "changed_classifications": changed_classes,
        },
    }


def _build_trend_alerts(report: dict, trend: dict) -> list[dict]:
    alerts = []
    repeated = trend.get("repeated_failures") or []
    new_failures = trend.get("new_failures") or []
    recovered = trend.get("recovered_failures") or []
    consecutive_failed_runs = int(trend.get("consecutive_failed_runs") or 0)
    matrix = trend.get("matrix") or {}
    current_matrix = matrix.get("current") or {}
    previous_matrix = matrix.get("previous") or {}
    current_actionable = int(current_matrix.get("actionable_warnings_total") or 0)
    previous_actionable = int(previous_matrix.get("actionable_warnings_total") or 0)

    if repeated:
        alerts.append(
            {
                "severity": "medium" if report.get("status") == "passed" else "high",
                "type": "repeated_failure",
                "title": f"Fallo repetido: {', '.join(repeated[:4])}",
                "detail": f"El mismo fallo aparece en la ejecucion anterior. Rachas fallidas consecutivas: {consecutive_failed_runs or 1}.",
            }
        )
    if new_failures:
        alerts.append(
            {
                "severity": "high",
                "type": "new_failure",
                "title": f"Nuevos fallos detectados: {', '.join(new_failures[:4])}",
                "detail": "Hay pasos fallidos que no estaban presentes en la ejecucion anterior.",
            }
        )
    if current_actionable > previous_actionable:
        alerts.append(
            {
                "severity": "high" if current_actionable else "medium",
                "type": "actionable_warning_increase",
                "title": "Han aumentado los avisos accionables",
                "detail": f"Antes: {previous_actionable}. Ahora: {current_actionable}.",
            }
        )
    if recovered and report.get("status") == "passed":
        alerts.append(
            {
                "severity": "low",
                "type": "recovered_failure",
                "title": f"Recuperado respecto a la ejecucion anterior: {', '.join(recovered[:4])}",
                "detail": "La auditoria actual ya no reproduce algunos fallos previos.",
            }
        )
    return alerts


def _append_history(report_dir: Path, report: dict) -> None:
    history_path = report_dir / "system-audit-history.jsonl"
    matrix_summary = _matrix_summary_from_report(report)
    summary = {
        "run_id": report.get("run_id"),
        "started_at": report.get("started_at"),
        "finished_at": report.get("finished_at"),
        "status": report.get("status"),
        "failed_steps": report.get("failed_steps"),
        "alerts_total": len(report.get("alerts") or []),
        "trend": {
            "previous_run_id": (report.get("trend") or {}).get("previous_run_id"),
            "previous_status": (report.get("trend") or {}).get("previous_status"),
            "repeated_failures": (report.get("trend") or {}).get("repeated_failures"),
            "new_failures": (report.get("trend") or {}).get("new_failures"),
            "recovered_failures": (report.get("trend") or {}).get("recovered_failures"),
            "consecutive_failed_runs": (report.get("trend") or {}).get("consecutive_failed_runs"),
        },
        "matrix_summary": matrix_summary,
        "steps": [
            {
                "name": step.get("name"),
                "status": step.get("status"),
                "duration_seconds": step.get("duration_seconds"),
                "json_summary": {
                    "kind": (step.get("json_summary") or {}).get("kind"),
                    "summary": (step.get("json_summary") or {}).get("summary"),
                    "failed_checks": (step.get("json_summary") or {}).get("failed_checks"),
                    "actionable_warnings_total": len(((step.get("json_summary") or {}).get("actionable_warnings") or [])),
                }
                if step.get("json_summary")
                else None,
            }
            for step in report.get("steps", [])
        ],
    }
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")


def _write_dashboard(report_dir: Path, report: dict) -> None:
    latest_json = report_dir / "latest-system-audit.json"
    latest_html = report_dir / "latest-system-audit.html"
    latest_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    alerts = report.get("alerts") or []
    trend = report.get("trend") or {}
    history_entries = _load_history(report_dir, limit=10)
    matrix = (trend.get("matrix") or {}).get("current") or {}
    changed_classes = ((trend.get("matrix") or {}).get("changed_classifications") or {})
    step_rows = []
    for step in report.get("steps", []):
        step_rows.append(
            "<tr>"
            f"<td>{html.escape(str(step.get('name') or ''))}</td>"
            f"<td>{html.escape(str(step.get('status') or ''))}</td>"
            f"<td>{html.escape(str(step.get('duration_seconds') or ''))}</td>"
            "</tr>"
        )
    history_rows = []
    for entry in reversed(history_entries):
        history_rows.append(
            "<tr>"
            f"<td>{html.escape(str(entry.get('started_at') or ''))}</td>"
            f"<td>{html.escape(str(entry.get('status') or ''))}</td>"
            f"<td>{html.escape(str(entry.get('alerts_total') or 0))}</td>"
            f"<td>{html.escape(', '.join(entry.get('failed_steps') or []))}</td>"
            "</tr>"
        )
    alert_items = "\n".join(
        f"<li><strong>{html.escape(str(item.get('severity') or ''))}</strong> "
        f"{html.escape(str(item.get('title') or ''))} "
        f"<span>{html.escape(str(item.get('detail') or ''))[:300]}</span></li>"
        for item in alerts
    )
    trend_items = [
        f"<li>Run previo: {html.escape(str(trend.get('previous_run_id') or 'n/a'))} ({html.escape(str(trend.get('previous_status') or 'n/a'))})</li>",
        f"<li>Fallos repetidos: {html.escape(', '.join(trend.get('repeated_failures') or []) or 'ninguno')}</li>",
        f"<li>Nuevos fallos: {html.escape(', '.join(trend.get('new_failures') or []) or 'ninguno')}</li>",
        f"<li>Recuperados: {html.escape(', '.join(trend.get('recovered_failures') or []) or 'ninguno')}</li>",
        f"<li>Racha de fallos: {html.escape(str(trend.get('consecutive_failed_runs') or 0))}</li>",
        f"<li>Avisos accionables actuales: {html.escape(str(matrix.get('actionable_warnings_total') or 0))}</li>",
        f"<li>Cambios de clasificacion: {html.escape(json.dumps(changed_classes, ensure_ascii=False) if changed_classes else 'sin cambios')}</li>",
    ]
    latest_html.write_text(
        """<!doctype html>
<html lang="es">
<meta charset="utf-8">
<title>Modernia CRM System Health</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:32px;line-height:1.35;color:#1f2933}
table{border-collapse:collapse;width:100%;margin-top:16px}td,th{border:1px solid #d9e2ec;padding:8px;text-align:left}
.status{font-size:22px;font-weight:700}.passed{color:#0f7b4f}.failed{color:#b42318}.alerts li{margin:8px 0}
</style>
<h1>Modernia CRM System Health</h1>
"""
        + f"<p class=\"status {html.escape(str(report.get('status') or ''))}\">Estado: {html.escape(str(report.get('status') or ''))}</p>"
        + f"<p>Run ID: {html.escape(str(report.get('run_id') or ''))}<br>Inicio: {html.escape(str(report.get('started_at') or ''))}<br>Fin: {html.escape(str(report.get('finished_at') or ''))}</p>"
        + f"<h2>Alertas ({len(alerts)})</h2><ul class=\"alerts\">{alert_items or '<li>Sin alertas accionables</li>'}</ul>"
        + f"<h2>Tendencia</h2><ul>{''.join(trend_items)}</ul>"
        + "<h2>Pasos</h2><table><thead><tr><th>Paso</th><th>Estado</th><th>Segundos</th></tr></thead><tbody>"
        + "\n".join(step_rows)
        + "</tbody></table>"
        + "<h2>Historial reciente</h2><table><thead><tr><th>Inicio</th><th>Estado</th><th>Alertas</th><th>Fallos</th></tr></thead><tbody>"
        + "\n".join(history_rows)
        + "</tbody></table></html>\n",
        encoding="utf-8",
    )


def _run_step(name: str, cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 900) -> dict:
    started = time.monotonic()
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    print(f"[audit] {name}: {shlex.join(cmd)}", flush=True)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        output = proc.stdout or ""
        status = "passed" if proc.returncode == 0 else "failed"
        result = {
            "name": name,
            "status": status,
            "returncode": proc.returncode,
            "duration_seconds": round(time.monotonic() - started, 2),
            "command": cmd,
            "output_tail": output[-12000:],
        }
        json_summary = _summarize_json_output(output)
        if json_summary:
            result["json_summary"] = json_summary
        return result
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return {
            "name": name,
            "status": "timeout",
            "returncode": None,
            "duration_seconds": round(time.monotonic() - started, 2),
            "command": cmd,
            "output_tail": output[-12000:],
        }


def _existing(paths: list[str]) -> list[str]:
    return [path for path in paths if (ROOT / path).exists()]


def _production_smoke_steps() -> list[tuple[str, list[str], dict[str, str]]]:
    base_url = os.environ.get("CRM_E2E_URL") or os.environ.get("CRM_BASE_URL") or "https://crm.verifika2.com/?swcleared=1"
    pairs = [
        ("production_admin_smoke", "CRM_ADMIN_USER", "CRM_ADMIN_PASSWORD"),
        ("production_non_admin_smoke", "CRM_INMO_USER", "CRM_INMO_PASSWORD"),
    ]
    steps = []
    for name, user_key, pass_key in pairs:
        user = (os.environ.get(user_key) or "").strip()
        password = os.environ.get(pass_key) or ""
        if not user or not password:
            steps.append((name, [], {"skip_reason": f"faltan {user_key}/{pass_key}"}))
            continue
        steps.append(
            (
                name,
                [sys.executable, "scripts/prod_inmo_smoke.py"],
                {
                    "CRM_E2E_URL": base_url,
                    "CRM_E2E_USER": user,
                    "CRM_E2E_PASS": password,
                },
            )
        )
    return steps


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoria automatica del sistema CRM.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Directorio donde guardar el JSON.")
    parser.add_argument("--skip-local", action="store_true", help="Omite checks locales de sintaxis/pytest.")
    parser.add_argument("--include-e2e", action="store_true", help="Ejecuta E2E Playwright locales.")
    parser.add_argument("--include-production", action="store_true", help="Ejecuta smoke tests contra CRM_BASE_URL/CRM_E2E_URL.")
    parser.add_argument("--include-production-api", action="store_true", help="Ejecuta checks HTTP/API contra produccion sin navegador.")
    parser.add_argument("--include-system-matrix", action="store_true", help="Ejecuta matriz amplia de usuarios/workspaces/modulos en produccion.")
    parser.add_argument("--include-code-inventory", action="store_true", help="Genera inventario compacto del codigo para Ollama.")
    parser.add_argument("--ollama", action="store_true", help="Genera resumen local con Ollama si esta disponible.")
    parser.add_argument("--fail-fast", action="store_true", help="Detiene la auditoria en el primer fallo.")
    args = parser.parse_args()

    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"system-audit-{run_id}.json"

    report = {
        "run_id": run_id,
        "started_at": _utc_now(),
        "root": str(ROOT),
        "include_e2e": bool(args.include_e2e),
        "include_production": bool(args.include_production),
        "steps": [],
    }
    previous_entries = _load_history(report_dir)

    steps: list[tuple[str, list[str], dict[str, str] | None, int]] = []
    if not args.skip_local:
        steps.extend(
            [
                ("python_syntax_web_server", [sys.executable, "-m", "py_compile", "web/server.py"], None, 120),
                ("javascript_syntax_app", ["node", "--check", "web/app.js"], None, 120),
                ("pytest_fast_core", [sys.executable, "-m", "pytest", "-q", *_existing(FAST_PYTESTS)], None, 1200),
            ]
        )
    if not args.skip_local and (args.include_e2e or _env_flag("RUN_SYSTEM_AUDIT_E2E")):
        steps.append(
            (
                "pytest_playwright_e2e",
                [sys.executable, "-m", "pytest", "-q", *_existing(E2E_PYTESTS)],
                {"RUN_PLAYWRIGHT_E2E": "1"},
                1800,
            )
        )
    if args.include_production_api or _env_flag("RUN_SYSTEM_AUDIT_PRODUCTION_API"):
        steps.append(("production_api_monitor", [sys.executable, "scripts/prod_api_monitor.py", "--json"], None, 300))
    if args.include_system_matrix or _env_flag("RUN_SYSTEM_AUDIT_SYSTEM_MATRIX"):
        steps.append(("production_system_matrix", [sys.executable, "scripts/prod_system_matrix_audit.py", "--json"], None, 900))
    if args.include_code_inventory or _env_flag("RUN_SYSTEM_AUDIT_CODE_INVENTORY"):
        steps.append(("codebase_inventory", [sys.executable, "scripts/codebase_inventory_for_ollama.py", "--json"], None, 180))
    if _env_flag("RUN_SYSTEM_AUDIT_BUILD_KNOWLEDGE"):
        steps.append(("build_system_knowledge", [sys.executable, "scripts/build_system_knowledge.py"], None, 180))

    for name, cmd, env, timeout in steps:
        result = _run_step(name, cmd, env=env, timeout=timeout)
        report["steps"].append(result)
        if args.fail_fast and result["status"] != "passed":
            break

    if args.include_production or _env_flag("RUN_SYSTEM_AUDIT_PRODUCTION"):
        for name, cmd, env in _production_smoke_steps():
            if not cmd:
                report["steps"].append({"name": name, "status": "skipped", **env})
                continue
            result = _run_step(name, cmd, env=env, timeout=240)
            report["steps"].append(result)
            if args.fail_fast and result["status"] != "passed":
                break

    failed = [step for step in report["steps"] if step.get("status") not in {"passed", "skipped"}]
    report["finished_at"] = _utc_now()
    report["status"] = "failed" if failed else "passed"
    report["failed_steps"] = [step.get("name") for step in failed]
    report["alerts"] = _build_alerts(report)
    report["trend"] = _build_trend_data(report, previous_entries)
    report["alerts"].extend(_build_trend_alerts(report, report["trend"]))
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _append_history(report_dir, report)
    _write_dashboard(report_dir, report)
    print(f"[audit] reporte: {report_path}")

    if args.ollama:
        summary = _run_step(
            "ollama_summary",
            [sys.executable, "scripts/summarize_audit_with_ollama.py", str(report_path)],
            timeout=240,
        )
        report["steps"].append(summary)
        report["ollama_summary_status"] = summary["status"]
        report["alerts"] = _build_alerts(report)
        report["trend"] = _build_trend_data(report, previous_entries)
        report["alerts"].extend(_build_trend_alerts(report, report["trend"]))
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _write_dashboard(report_dir, report)

    if failed and _env_flag("RUN_SYSTEM_AUDIT_AUTOFIX"):
        autofix_cmd = [sys.executable, "scripts/system_autofix_agent.py", str(report_path), "--json"]
        if _env_flag("RUN_SYSTEM_AUDIT_AUTOFIX_TESTS"):
            autofix_cmd.append("--run-tests")
        autofix = _run_step("autofix_plan", autofix_cmd, timeout=900)
        report["steps"].append(autofix)
        report["autofix_plan_status"] = autofix["status"]
        report["alerts"] = _build_alerts(report)
        report["trend"] = _build_trend_data(report, previous_entries)
        report["alerts"].extend(_build_trend_alerts(report, report["trend"]))
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _write_dashboard(report_dir, report)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
