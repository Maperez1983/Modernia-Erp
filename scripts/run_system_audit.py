#!/usr/bin/env python3
"""Ejecuta una auditoria reproducible del CRM y guarda resultados en JSON."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
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
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[audit] reporte: {report_path}")

    if args.ollama:
        summary = _run_step(
            "ollama_summary",
            [sys.executable, "scripts/summarize_audit_with_ollama.py", str(report_path)],
            timeout=240,
        )
        report["steps"].append(summary)
        report["ollama_summary_status"] = summary["status"]
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
