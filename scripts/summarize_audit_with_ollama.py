#!/usr/bin/env python3
"""Resume un reporte de auditoria usando Ollama local."""

from __future__ import annotations

import json
import os
import shutil
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from pathlib import Path


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_KNOWLEDGE_PATH = Path(__file__).resolve().parents[1] / "docs" / "system_knowledge.json"
DEFAULT_EXPECTED_BEHAVIORS_PATH = Path(__file__).resolve().parents[1] / "docs" / "expected_behaviors.json"
DEFAULT_INCIDENTS_PATH = Path(__file__).resolve().parents[1] / "docs" / "incidents.jsonl"
DEFAULT_PLAYBOOKS_PATH = Path(__file__).resolve().parents[1] / "docs" / "repair_playbooks.json"


def _load_system_knowledge() -> dict:
    path = Path(os.environ.get("CRM_SYSTEM_KNOWLEDGE_PATH") or DEFAULT_KNOWLEDGE_PATH).resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "path": str(path)}
    modules = data.get("modules") if isinstance(data, dict) else {}
    compact_modules = {}
    if isinstance(modules, dict):
        for name, module in modules.items():
            if not isinstance(module, dict):
                continue
            compact_modules[name] = {
                "expectations": module.get("expectations"),
                "endpoint_count": module.get("endpoint_count"),
                "endpoints_sample": module.get("endpoints_sample"),
                "tests": module.get("tests"),
                "frontend_functions_sample": module.get("frontend_functions_sample"),
            }
    return {
        "available": True,
        "path": str(path),
        "generated_at": data.get("generated_at"),
        "git": data.get("git"),
        "entrypoints": data.get("entrypoints"),
        "modules": compact_modules,
        "diagnostic_rules": data.get("diagnostic_rules"),
    }


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_jsonl(path: Path, limit: int = 20) -> list[dict]:
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


def _load_operational_memory() -> dict:
    expected = _load_json(Path(os.environ.get("CRM_EXPECTED_BEHAVIORS_PATH") or DEFAULT_EXPECTED_BEHAVIORS_PATH))
    incidents = _load_jsonl(Path(os.environ.get("CRM_INCIDENTS_PATH") or DEFAULT_INCIDENTS_PATH))
    playbooks = _load_json(Path(os.environ.get("CRM_REPAIR_PLAYBOOKS_PATH") or DEFAULT_PLAYBOOKS_PATH))
    return {
        "expected_behaviors": expected.get("modules") or {},
        "recent_incidents": incidents,
        "repair_playbooks": playbooks.get("playbooks") or [],
    }


def _compact_report(report: dict) -> dict:
    compact_steps = []
    for step in report.get("steps", []):
        output = step.get("output_tail") or ""
        compact_steps.append(
            {
                "name": step.get("name"),
                "status": step.get("status"),
                "returncode": step.get("returncode"),
                "duration_seconds": step.get("duration_seconds"),
                "skip_reason": step.get("skip_reason"),
                "json_summary": step.get("json_summary"),
                "output_tail": output[-1500:] if not step.get("json_summary") else "",
            }
        )
    return {
        "run_id": report.get("run_id"),
        "status": report.get("status"),
        "started_at": report.get("started_at"),
        "finished_at": report.get("finished_at"),
        "failed_steps": report.get("failed_steps"),
        "system_knowledge": _load_system_knowledge(),
        "operational_memory": _load_operational_memory(),
        "steps": compact_steps,
    }


def _deterministic_summary(compact: dict) -> str:
    lines = [
        "# Resumen auditoria CRM",
        "",
        f"- Estado global: {compact.get('status') or 'desconocido'}",
        f"- Run ID: {compact.get('run_id') or ''}",
        f"- Inicio: {compact.get('started_at') or ''}",
        f"- Fin: {compact.get('finished_at') or ''}",
        f"- Fallos: {', '.join(compact.get('failed_steps') or []) if compact.get('failed_steps') else 'ninguno'}",
        "",
        "## Base de conocimiento",
    ]
    knowledge = compact.get("system_knowledge") or {}
    if knowledge.get("available"):
        lines.extend(
            [
                f"- Archivo: {knowledge.get('path')}",
                f"- Generada: {knowledge.get('generated_at')}",
                f"- Commit conocido: {(knowledge.get('git') or {}).get('commit')}",
                f"- Modulos conocidos: {', '.join((knowledge.get('modules') or {}).keys())}",
                "",
            ]
        )
    else:
        lines.extend([f"- No disponible: {knowledge.get('path')}", ""])
    lines.extend([
        "## Pasos",
    ])
    for step in compact.get("steps") or []:
        name = step.get("name") or "paso"
        status = step.get("status") or "desconocido"
        duration = step.get("duration_seconds")
        lines.append(f"- {name}: {status} ({duration}s)")
        js = step.get("json_summary") or {}
        if not isinstance(js, dict):
            continue
        kind = js.get("kind")
        if kind == "prod_api_monitor":
            users = js.get("users") or {}
            lines.append(f"  API produccion: {js.get('base_url')}; fallos={js.get('failed_checks') or []}; usuarios={list(users.keys())}")
        elif kind == "prod_system_matrix_audit":
            summary = js.get("summary") or {}
            warnings = js.get("warning_checks") or []
            lines.append(
                "  Matriz sistema: "
                f"usuarios con login={summary.get('credentialed_users')}; "
                f"workspaces={summary.get('workspaces_checked')}; "
                f"endpoints={summary.get('endpoint_checks')}; "
                f"avisos={len(warnings)}"
            )
            lines.append(f"  Modulos: {summary.get('endpoint_status_by_module') or {}}")
        elif kind == "codebase_inventory_for_ollama":
            backend = js.get("backend") or {}
            frontend = js.get("frontend") or {}
            tests = js.get("tests") or {}
            lines.append(
                "  Inventario codigo: "
                f"endpoints_api={backend.get('api_endpoints_total')}; "
                f"funciones_frontend={frontend.get('function_count')}; "
                f"tests={tests.get('total')}"
            )
    op_memory = compact.get("operational_memory") or {}
    incidents = op_memory.get("recent_incidents") or []
    if incidents:
        lines.extend(["", "## Incidentes conocidos"])
        for item in incidents[:5]:
            lines.append(f"- {item.get('incident_id')}: {item.get('symptom')}")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: summarize_audit_with_ollama.py reports/system_audit/system-audit-....json", file=sys.stderr)
        return 2

    if not shutil.which("ollama"):
        base_url = (os.environ.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL).strip().rstrip("/")
        if base_url == DEFAULT_OLLAMA_BASE_URL:
            print("Ollama no esta instalado o no esta en PATH; se omite el resumen local.")
            return 0

    report_path = Path(sys.argv[1]).resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    compact = _compact_report(report)
    deterministic = _deterministic_summary(compact)
    model = os.environ.get("OLLAMA_AUDIT_MODEL") or "qwen2.5-coder:7b"
    base_url = (os.environ.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL).strip().rstrip("/")
    prompt = (
        "Responde solo en castellano. Eres un auditor tecnico de un CRM. "
        "Usa la base de conocimiento incluida para relacionar sintomas con modulos, endpoints, tests y expectativas. "
        "Resume este reporte con: "
        "1) estado global, 2) fallos concretos, 3) causa probable si se puede inferir, "
        "4) donde mirar primero en el codigo, 5) siguiente accion recomendada. Usa solo el JSON recibido; si no hay fallos, dilo claramente. "
        "No menciones pruebas, despliegues ni fallos que no aparezcan literalmente en el JSON.\n\n"
        + json.dumps(compact, ensure_ascii=False, indent=2)
    )
    if model.lower().startswith("qwen3:"):
        prompt = "/no_think\n" + prompt
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    request = Request(
        f"{base_url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=240) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            summary_path = report_path.with_suffix(".ollama.md")
            content = deterministic + "\n## Analisis Ollama\n\nOllama no disponible: modelo o endpoint no encontrado (HTTP 404).\n"
            summary_path.write_text(content, encoding="utf-8")
            print(f"Resumen Ollama degradado: {summary_path}")
            return 0
        print(f"Ollama devolvio HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"No se puede conectar con Ollama local: {exc}", file=sys.stderr)
        return 1

    summary = str(data.get("response") or "").strip()
    if not summary:
        print(f"Ollama no devolvio resumen: {data}", file=sys.stderr)
        return 1

    summary_path = report_path.with_suffix(".ollama.md")
    content = deterministic + "\n## Analisis Ollama\n\n" + summary + "\n"
    summary_path.write_text(content, encoding="utf-8")
    print(f"Resumen Ollama: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
