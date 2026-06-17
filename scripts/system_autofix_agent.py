#!/usr/bin/env python3
"""Prepara diagnosticos y planes de reparacion a partir de auditorias fallidas.

Este agente no despliega ni modifica produccion. Su primera responsabilidad es
convertir un fallo en una ruta de reparacion concreta: modulo, ficheros, tests y
riesgo. Puede ejecutar tests locales relacionados si se solicita.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ollama_json import generate_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "reports" / "system_audit"
DEFAULT_KNOWLEDGE_PATH = ROOT / "docs" / "system_knowledge.json"
DEFAULT_EXPECTED_BEHAVIORS_PATH = ROOT / "docs" / "expected_behaviors.json"
DEFAULT_INCIDENTS_PATH = ROOT / "docs" / "incidents.jsonl"
DEFAULT_PLAYBOOKS_PATH = ROOT / "docs" / "repair_playbooks.json"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run(cmd: list[str], timeout: int = 900) -> dict:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return {
            "command": cmd,
            "status": "passed" if proc.returncode == 0 else "failed",
            "returncode": proc.returncode,
            "duration_seconds": round(time.monotonic() - started, 2),
            "output_tail": (proc.stdout or "")[-12000:],
        }
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return {
            "command": cmd,
            "status": "timeout",
            "returncode": None,
            "duration_seconds": round(time.monotonic() - started, 2),
            "output_tail": (output or "")[-12000:],
        }


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _latest_report(report_dir: Path) -> Path:
    candidates = sorted(report_dir.glob("system-audit-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No hay reportes en {report_dir}")
    return candidates[0]


def _compact_report(report: dict) -> dict:
    steps = []
    for step in report.get("steps") or []:
        if not isinstance(step, dict):
            continue
        steps.append(
            {
                "name": step.get("name"),
                "status": step.get("status"),
                "returncode": step.get("returncode"),
                "duration_seconds": step.get("duration_seconds"),
                "json_summary": step.get("json_summary"),
                "output_tail": (step.get("output_tail") or "")[-3000:],
            }
        )
    return {
        "run_id": report.get("run_id"),
        "status": report.get("status"),
        "failed_steps": report.get("failed_steps"),
        "steps": steps,
    }


def _compact_knowledge(knowledge: dict) -> dict:
    modules = {}
    for name, data in (knowledge.get("modules") or {}).items():
        if not isinstance(data, dict):
            continue
        modules[name] = {
            "expectations": data.get("expectations"),
            "tests": data.get("tests"),
            "endpoints_sample": data.get("endpoints_sample"),
            "frontend_functions_sample": data.get("frontend_functions_sample"),
        }
    return {
        "generated_at": knowledge.get("generated_at"),
        "git": knowledge.get("git"),
        "entrypoints": knowledge.get("entrypoints"),
        "operational_memory": knowledge.get("operational_memory"),
        "modules": modules,
        "diagnostic_rules": knowledge.get("diagnostic_rules"),
    }


def _load_operational_inputs() -> dict:
    expected = {}
    incidents = []
    playbooks = {}
    try:
        expected = _load_json(Path(os.environ.get("CRM_EXPECTED_BEHAVIORS_PATH") or DEFAULT_EXPECTED_BEHAVIORS_PATH))
    except Exception:
        expected = {}
    try:
        incidents = _load_jsonl(Path(os.environ.get("CRM_INCIDENTS_PATH") or DEFAULT_INCIDENTS_PATH))
    except Exception:
        incidents = []
    try:
        playbooks = _load_json(Path(os.environ.get("CRM_REPAIR_PLAYBOOKS_PATH") or DEFAULT_PLAYBOOKS_PATH))
    except Exception:
        playbooks = {}
    return {
        "expected_behaviors": expected.get("modules") or {},
        "recent_incidents": incidents,
        "repair_playbooks": playbooks.get("playbooks") or [],
    }


def _heuristic_plan(report: dict, knowledge: dict) -> dict:
    failed_steps = report.get("failed_steps") or []
    text = json.dumps(report, ensure_ascii=False).lower()
    modules = knowledge.get("modules") or {}
    selected = []
    for name in modules:
        if name.lower() in text:
            selected.append(name)
    if "agenda" in text or "acciones" in text or "cita" in text:
        selected.insert(0, "agenda")
    if "403" in text or "permiso" in text or "usuario" in text:
        selected.append("usuarios_permisos")
    if not selected:
        selected = ["core"]
    ordered = []
    for item in selected:
        if item not in ordered:
            ordered.append(item)
    tests = []
    files = []
    for module in ordered:
        data = modules.get(module) or {}
        tests.extend(data.get("tests") or [])
        for endpoint in data.get("endpoints_sample") or []:
            if isinstance(endpoint, dict) and endpoint.get("path"):
                files.append(f"web/server.py:{endpoint.get('line')}")
    entrypoints = knowledge.get("entrypoints") or {}
    for group in ("backend", "frontend", "auditoria"):
        files.extend(entrypoints.get(group) or [])
    dedup_tests = []
    for test in tests:
        if test not in dedup_tests:
            dedup_tests.append(test)
    dedup_files = []
    for file in files:
        if file not in dedup_files:
            dedup_files.append(file)
    return {
        "source": "heuristic",
        "status": "needs_human_or_llm_patch",
        "risk_level": "medium",
        "probable_modules": ordered[:4],
        "probable_files": dedup_files[:20],
        "probable_tests": dedup_tests[:20],
        "failed_steps": failed_steps,
        "diagnosis": "Plan heuristico generado desde el reporte y la base de conocimiento.",
        "repair_strategy": [
            "Reproducir el fallo con los tests relacionados o crear una regresion minima.",
            "Inspeccionar el endpoint/funcion indicado por el modulo afectado.",
            "Aplicar cambio pequeno y verificar con tests + auditoria de produccion no destructiva.",
        ],
        "operational_memory_hits": _operational_memory_hits(knowledge, ordered, text),
        "regression_test_outline": _regression_outline(ordered, text),
        "autofix_allowed": False,
    }


def _operational_memory_hits(knowledge: dict, modules: list[str], report_text: str) -> dict:
    memory = (knowledge.get("operational_memory") or {}) if isinstance(knowledge, dict) else {}
    expected = memory.get("expected_behaviors") or {}
    incidents = memory.get("recent_incidents") or []
    playbooks = memory.get("repair_playbooks") or []
    expected_hits = {name: expected.get(name) for name in modules if expected.get(name)}
    incident_hits = []
    for item in incidents:
        haystack = json.dumps(item, ensure_ascii=False).lower()
        if any(module.lower() in haystack for module in modules) or any(token in haystack for token in report_text.split()[:80]):
            incident_hits.append(item)
    playbook_hits = []
    for item in playbooks:
        haystack = json.dumps(item, ensure_ascii=False).lower()
        if any(module.lower() in haystack for module in modules) or any(trigger in report_text for trigger in (item.get("triggers") or [])):
            playbook_hits.append(item)
    return {
        "expected_behaviors": expected_hits,
        "incidents": incident_hits[:5],
        "repair_playbooks": playbook_hits[:5],
    }


def _regression_outline(modules: list[str], report_text: str) -> dict:
    primary = modules[0] if modules else "core"
    if primary == "agenda" or "acciones" in report_text or "cita" in report_text:
        return {
            "target_file": "tests/test_agenda_frontend_regressions.py",
            "goal": "Cubrir que admin y no admin ven agenda del mismo workspace y que el modal de cita no hereda campos residuales.",
            "cases": [
                "Simular apertura de nueva cita tras editar otra y comprobar cliente/tipo/responsable vacios o valores por defecto.",
                "Validar que /api/acciones con workspace_id y range=all devuelve filas para usuario miembro no admin.",
            ],
            "commands": [["python3", "-m", "pytest", "-q", "tests/test_agenda_frontend_regressions.py", "tests/test_api_usuarios_scoping.py"]],
        }
    if primary == "usuarios_permisos" or "403" in report_text:
        return {
            "target_file": "tests/test_api_usuarios_scoping.py",
            "goal": "Cubrir diferencias esperadas entre permisos correctos y perdida accidental de datos por scoping.",
            "cases": [
                "Usuario no privilegiado solo ve usuarios/workspaces donde es miembro.",
                "403 de modulo sin servicio se mantiene controlado y no se convierte en 5xx.",
            ],
            "commands": [["python3", "-m", "pytest", "-q", "tests/test_api_usuarios_scoping.py", "tests/test_workspace_membership_autojoin.py"]],
        }
    return {
        "target_file": "tests/test_frontend_smoke.py",
        "goal": "Crear una regresion minima alrededor del endpoint o flujo que aparece en failed_steps/output_tail.",
        "cases": [
            "Reproducir el endpoint fallido con parametros minimos.",
            "Verificar que responde 2xx o error 4xx controlado, nunca 5xx.",
        ],
        "commands": [["python3", "-m", "pytest", "-q", "tests/test_frontend_smoke.py"]],
    }


def _ollama_plan(report: dict, knowledge: dict) -> dict:
    base_url = (os.environ.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL).strip().rstrip("/")
    model = os.environ.get("OLLAMA_AUTOFIX_MODEL") or os.environ.get("OLLAMA_AUDIT_MODEL") or "qwen2.5-coder:7b"
    prompt = (
        "Responde solo JSON valido, sin markdown. Eres un agente senior de reparacion del CRM Modernia. "
        "No inventes ficheros. No propongas tocar produccion directamente. "
        "A partir del reporte fallido y la base de conocimiento, devuelve este esquema exacto: "
        "{"
        "\"source\":\"ollama\","
        "\"status\":\"needs_patch|needs_more_data|no_action\","
        "\"risk_level\":\"low|medium|high\","
        "\"probable_modules\":[\"...\"],"
        "\"probable_files\":[\"...\"],"
        "\"probable_tests\":[\"...\"],"
        "\"diagnosis\":\"...\","
        "\"repair_strategy\":[\"...\"],"
        "\"regression_test_outline\":{\"target_file\":\"tests/test_x.py\",\"goal\":\"...\",\"cases\":[\"...\"],\"commands\":[[\"python3\",\"-m\",\"pytest\",\"-q\",\"tests/test_x.py\"]]},"
        "\"patch_outline\":[\"...\"],"
        "\"verification_commands\":[[\"python3\",\"-m\",\"pytest\",\"-q\",\"tests/test_x.py\"]],"
        "\"autofix_allowed\":false"
        "}. "
        "El campo autofix_allowed solo puede ser true si el cambio es trivial, de bajo riesgo y hay test directo; por defecto false.\n\n"
        + json.dumps({"report": _compact_report(report), "knowledge": _compact_knowledge(knowledge)}, ensure_ascii=False, indent=2)
    )
    valid_statuses = {"needs_patch", "needs_more_data", "no_action"}
    required = {"status", "risk_level", "probable_modules", "probable_files", "probable_tests", "diagnosis", "repair_strategy"}
    parsed = generate_json(
        base_url=base_url,
        model=model,
        prompt=prompt,
        required_keys=required,
        valid_statuses=valid_statuses,
        retries=1,
    )
    parsed.setdefault("source", "ollama")
    return parsed


def _safe_test_paths(paths: list[str]) -> list[str]:
    safe = []
    allow_e2e = (os.environ.get("RUN_AUTOFIX_E2E") or "").strip().lower() in {"1", "true", "yes", "si", "sí", "on"}
    for item in paths:
        value = str(item or "").strip()
        if not value or not value.startswith("tests/") or ".." in value:
            continue
        if "e2e" in value.lower() and not allow_e2e:
            continue
        if (ROOT / value).exists() and value not in safe:
            safe.append(value)
    return safe


def _git_dirty() -> list[str]:
    result = _run(["git", "status", "--short"], timeout=30)
    return [line for line in (result.get("output_tail") or "").splitlines() if line.strip()]


def _current_branch() -> str:
    result = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=30)
    return (result.get("output_tail") or "").strip()


def _write_prompt_artifact(plan: dict, report_path: Path, output_dir: Path) -> Path:
    prompt_path = output_dir / "codex_repair_prompt.md"
    lines = [
        "# CRM Repair Prompt",
        "",
        f"Report: {report_path}",
        f"Generated: {_utc_now()}",
        "",
        "## Diagnosis",
        "",
        str(plan.get("diagnosis") or ""),
        "",
        "## Probable Modules",
        "",
        "\n".join(f"- {item}" for item in plan.get("probable_modules") or []),
        "",
        "## Probable Files",
        "",
        "\n".join(f"- {item}" for item in plan.get("probable_files") or []),
        "",
        "## Probable Tests",
        "",
        "\n".join(f"- {item}" for item in plan.get("probable_tests") or []),
        "",
        "## Repair Strategy",
        "",
        "\n".join(f"- {item}" for item in plan.get("repair_strategy") or []),
        "",
        "## Regression Test Outline",
        "",
        json.dumps(plan.get("regression_test_outline") or {}, ensure_ascii=False, indent=2),
        "",
        "## Patch Outline",
        "",
        "\n".join(f"- {item}" for item in plan.get("patch_outline") or []),
    ]
    prompt_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return prompt_path


def _write_regression_artifact(plan: dict, output_dir: Path) -> Path:
    outline = plan.get("regression_test_outline") or {}
    target = str(outline.get("target_file") or "tests/test_regression_from_audit.py")
    artifact_path = output_dir / "proposed_regression_test.py"
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = outline.get("cases") or []
    content = [
        '"""Regresion propuesta por system_autofix_agent.',
        "",
        f"Destino sugerido: {target}",
        f"Objetivo: {outline.get('goal') or ''}",
        '"""',
        "",
        "import unittest",
        "",
        "",
        "class ProposedAuditRegression(unittest.TestCase):",
    ]
    if cases:
        for idx, case in enumerate(cases, start=1):
            content.extend(
                [
                    f"    def test_case_{idx}(self):",
                    f"        # TODO: {case}",
                    "        self.skipTest('Regresion propuesta; implementar con fixtures del modulo afectado')",
                    "",
                ]
            )
    else:
        content.extend(
            [
                "    def test_regression_placeholder(self):",
                "        self.skipTest('Regresion propuesta; completar con el fallo reproducible')",
                "",
            ]
        )
    content.extend(["", "if __name__ == '__main__':", "    unittest.main()", ""])
    artifact_path.write_text("\n".join(content), encoding="utf-8")
    return artifact_path


def _materialize_regression_test(plan: dict, output_dir: Path) -> dict:
    outline = plan.get("regression_test_outline") or {}
    target = str(outline.get("target_file") or "").strip()
    if not target.startswith("tests/") or ".." in target:
        return {
            "created": False,
            "path": "",
            "reason": "Ruta de test no segura o no definida.",
        }
    destination = ROOT / target
    if destination.exists():
        return {
            "created": False,
            "path": str(destination),
            "reason": "El test sugerido ya existe; no se sobreescribe automaticamente.",
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    artifact_path = _write_regression_artifact(plan, output_dir)
    content = artifact_path.read_text(encoding="utf-8")
    destination.write_text(content, encoding="utf-8")
    return {
        "created": True,
        "path": str(destination),
        "reason": "Se ha materializado un test base pendiente de implementar.",
    }


def _prepare_branch_artifact(plan: dict, report: dict, output_dir: Path, *, create_branch: bool) -> dict:
    run_id = str(report.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    branch = "autofix/" + re.sub(r"[^A-Za-z0-9_.-]+", "-", run_id).strip("-")
    info = {
        "branch": branch,
        "current_branch": _current_branch(),
        "created": False,
        "command": ["git", "switch", "-c", branch],
        "reason": "Modo preparacion: no se crea rama salvo --prepare-branch.",
    }
    dirty = _git_dirty()
    if create_branch:
        if dirty:
            info["reason"] = "No se crea rama porque hay cambios locales pendientes."
        else:
            result = _run(["git", "switch", "-c", branch], timeout=60)
            info["created"] = result.get("status") == "passed"
            info["result"] = result
            info["reason"] = "Rama creada para preparar parche." if info["created"] else "No se pudo crear la rama."
    (output_dir / "branch_plan.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return info


def run_agent(
    report_path: Path,
    knowledge_path: Path,
    output_dir: Path,
    *,
    run_tests: bool,
    use_ollama: bool,
    prepare_branch: bool = False,
    materialize_test: bool = False,
) -> dict:
    report = _load_json(report_path)
    knowledge = _load_json(knowledge_path)
    if not knowledge.get("operational_memory"):
        knowledge["operational_memory"] = _load_operational_inputs()
    output_dir.mkdir(parents=True, exist_ok=True)

    if report.get("status") != "failed":
        plan = {
            "source": "system_autofix_agent",
            "status": "no_action",
            "risk_level": "low",
            "diagnosis": "La auditoria no esta fallando; no se prepara reparacion.",
            "autofix_allowed": False,
        }
    else:
        plan = _heuristic_plan(report, knowledge)
        if use_ollama:
            try:
                ollama_plan = _ollama_plan(report, knowledge)
                if ollama_plan:
                    plan.update({k: v for k, v in ollama_plan.items() if v not in (None, "", [])})
            except Exception as exc:
                plan["ollama_error"] = str(exc)

    tests_run = []
    if run_tests and plan.get("status") != "no_action":
        test_paths = _safe_test_paths(plan.get("probable_tests") or [])
        if test_paths:
            tests_run.append(_run([sys.executable, "-m", "pytest", "-q", *test_paths], timeout=1200))
        else:
            tests_run.append({"status": "skipped", "detail": "No hay tests seguros detectados"})

    prompt_path = _write_prompt_artifact(plan, report_path, output_dir)
    regression_path = _write_regression_artifact(plan, output_dir)
    materialized_test = {"created": False, "path": "", "reason": "Modo solo plan; no se materializa test."}
    if materialize_test and plan.get("status") != "no_action":
        materialized_test = _materialize_regression_test(plan, output_dir)
    branch_plan = _prepare_branch_artifact(plan, report, output_dir, create_branch=prepare_branch)
    result = {
        "kind": "system_autofix_agent",
        "generated_at": _utc_now(),
        "report_path": str(report_path),
        "knowledge_path": str(knowledge_path),
        "git_dirty": _git_dirty(),
        "plan": plan,
        "tests_run": tests_run,
        "artifacts": {
            "repair_prompt": str(prompt_path),
            "proposed_regression_test": str(regression_path),
            "branch_plan": str(output_dir / "branch_plan.json"),
        },
        "materialized_test": materialized_test,
        "branch_plan": branch_plan,
        "safety": {
            "edits_applied": bool(materialized_test.get("created")),
            "production_touched": False,
            "reason": (
                "Diagnostica y prepara plan; puede crear rama y materializar un test base local. "
                "No modifica produccion ni despliega."
            ),
        },
    }
    output_path = output_dir / "autofix_plan.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["artifacts"]["plan_json"] = str(output_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Agente seguro de preparacion de reparaciones del CRM.")
    parser.add_argument("report", nargs="?", help="Ruta a system-audit-*.json. Si se omite, usa el ultimo reporte.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Directorio de reportes si no se pasa report.")
    parser.add_argument("--knowledge", default=str(DEFAULT_KNOWLEDGE_PATH), help="Base de conocimiento JSON.")
    parser.add_argument("--output-dir", default="", help="Directorio donde guardar el plan.")
    parser.add_argument("--run-tests", action="store_true", help="Ejecuta tests seguros relacionados con el diagnostico.")
    parser.add_argument("--prepare-branch", action="store_true", help="Crea rama autofix/<run_id> solo si el arbol git esta limpio.")
    parser.add_argument("--materialize-test", action="store_true", help="Crea el test sugerido solo si la ruta no existe todavia.")
    parser.add_argument("--no-ollama", action="store_true", help="Usa solo heuristica local, sin consultar Ollama.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo.")
    args = parser.parse_args()

    report_path = Path(args.report).resolve() if args.report else _latest_report(Path(args.report_dir).resolve())
    knowledge_path = Path(args.knowledge).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else report_path.with_suffix("").parent / f"{report_path.stem}-autofix"

    if not args.no_ollama and not shutil.which("ollama") and not os.environ.get("OLLAMA_BASE_URL"):
        use_ollama = False
    else:
        use_ollama = not args.no_ollama

    result = run_agent(
        report_path,
        knowledge_path,
        output_dir,
        run_tests=args.run_tests,
        use_ollama=use_ollama,
        prepare_branch=args.prepare_branch,
        materialize_test=args.materialize_test,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
