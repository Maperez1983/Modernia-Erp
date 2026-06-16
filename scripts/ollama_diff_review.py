#!/usr/bin/env python3
"""Revisa cambios locales con la base de conocimiento del CRM y Ollama.

No modifica ficheros. Sirve como pre-push/pre-commit manual para detectar zonas
sensibles sin tests y riesgos funcionales antes de subir cambios.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KNOWLEDGE_PATH = ROOT / "docs" / "system_knowledge.json"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return proc.returncode, proc.stdout or ""
    except Exception as exc:
        return 1, f"{type(exc).__name__}: {exc}"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _json_from_text(text: str) -> dict:
    text = (text or "").strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _changed_files(staged: bool) -> list[str]:
    cmd = ["git", "diff", "--cached", "--name-only"] if staged else ["git", "diff", "--name-only"]
    _, out = _run(cmd)
    files = [line.strip() for line in out.splitlines() if line.strip()]
    if staged:
        return files
    _, status = _run(["git", "status", "--short"])
    for line in status.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if path and path not in files:
            files.append(path)
    return files


def _diff_text(staged: bool, max_chars: int) -> str:
    cmd = ["git", "diff", "--cached", "--"] if staged else ["git", "diff", "--"]
    _, out = _run(cmd, timeout=120)
    if not staged:
        _, untracked = _run(["git", "ls-files", "--others", "--exclude-standard"])
        extras = []
        for file in [x.strip() for x in untracked.splitlines() if x.strip()]:
            path = ROOT / file
            if path.is_file() and path.stat().st_size <= 120_000:
                try:
                    extras.append(f"\n--- untracked: {file} ---\n" + path.read_text(encoding="utf-8", errors="replace")[:20_000])
                except Exception:
                    pass
        out += "\n".join(extras)
    return out[-max_chars:]


def _module_hints(files: list[str], knowledge: dict) -> dict:
    modules = knowledge.get("modules") or {}
    touched = {}
    haystack = "\n".join(files).lower()
    for name, data in modules.items():
        endpoints = data.get("endpoints_sample") or []
        tests = data.get("tests") or []
        functions = data.get("frontend_functions_sample") or []
        score = 0
        if name.lower() in haystack:
            score += 2
        for endpoint in endpoints:
            if isinstance(endpoint, dict) and str(endpoint.get("path") or "").strip("/") in haystack:
                score += 2
        for test in tests:
            if test in files:
                score += 3
        if any(fn.lower() in haystack for fn in functions):
            score += 1
        if score:
            touched[name] = {
                "score": score,
                "expectations": data.get("expectations"),
                "tests": tests,
            }
    if any(file in {"web/app.js", "web/index.html", "web/styles.css"} for file in files):
        touched.setdefault("frontend", {"score": 1, "expectations": ["Revisar que no se rompan flujos existentes ni estados de modales."], "tests": ["tests/test_frontend_smoke.py"]})
    if "web/server.py" in files:
        touched.setdefault("backend", {"score": 1, "expectations": ["Revisar scoping workspace/empresa y errores 4xx controlados."], "tests": ["tests/test_frontend_smoke.py"]})
    return touched


def _heuristic_review(files: list[str], knowledge: dict) -> dict:
    hints = _module_hints(files, knowledge)
    tests = []
    expectations = []
    for data in hints.values():
        for test in data.get("tests") or []:
            if test not in tests:
                tests.append(test)
        for exp in data.get("expectations") or []:
            if exp not in expectations:
                expectations.append(exp)
    findings = []
    if files and not any(file.startswith("tests/") for file in files):
        findings.append(
            {
                "severity": "medium",
                "title": "Cambio sin tests modificados",
                "detail": "El diff toca codigo o configuracion pero no incluye tests. Ejecutar o añadir tests relacionados antes de push.",
            }
        )
    sensitive = {"web/server.py", "web/app.js", "web/index.html", "schema.sql"}
    touched_sensitive = [file for file in files if file in sensitive]
    if touched_sensitive:
        findings.append(
            {
                "severity": "medium",
                "title": "Zona sensible modificada",
                "detail": f"Ficheros sensibles: {', '.join(touched_sensitive)}. Revisar invariantes de workspace, permisos y agenda.",
            }
        )
    return {
        "source": "heuristic",
        "status": "review_required" if findings else "passed",
        "changed_files": files,
        "module_hints": hints,
        "findings": findings,
        "recommended_tests": tests[:30],
        "expectations_to_check": expectations[:30],
    }


def _ollama_review(diff: str, heuristic: dict, knowledge: dict) -> dict:
    base_url = (os.environ.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL).strip().rstrip("/")
    model = os.environ.get("OLLAMA_REVIEW_MODEL") or os.environ.get("OLLAMA_AUDIT_MODEL") or "qwen2.5-coder:7b"
    compact_knowledge = {
        "modules": {
            name: {
                "expectations": data.get("expectations"),
                "tests": data.get("tests"),
                "endpoints_sample": data.get("endpoints_sample"),
            }
            for name, data in (knowledge.get("modules") or {}).items()
        },
        "diagnostic_rules": knowledge.get("diagnostic_rules"),
    }
    prompt = (
        "Responde solo JSON valido, sin markdown. Eres revisor senior del CRM Modernia. "
        "Revisa el diff contra la base de conocimiento y devuelve: "
        "{\"status\":\"passed|review_required|blocked\","
        "\"findings\":[{\"severity\":\"low|medium|high\",\"title\":\"...\",\"file\":\"...\",\"detail\":\"...\"}],"
        "\"recommended_tests\":[\"tests/test_x.py\"],"
        "\"risk_summary\":\"...\"}. "
        "No inventes ficheros. Si el diff es insuficiente, usa findings de severidad medium.\n\n"
        + json.dumps({"heuristic": heuristic, "knowledge": compact_knowledge, "diff": diff}, ensure_ascii=False)
    )
    if model.lower().startswith("qwen3:"):
        prompt = "/no_think\n" + prompt
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    request = Request(f"{base_url}/api/generate", data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=240) as response:
            data = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"No se puede conectar con Ollama: {exc}") from exc
    parsed = _json_from_text(str(data.get("response") or ""))
    if parsed.get("status") not in {"passed", "review_required", "blocked"} or not isinstance(parsed.get("findings"), list):
        raise RuntimeError("Ollama no devolvio un JSON de revision valido")
    parsed["source"] = "ollama"
    return parsed


def run_review(*, staged: bool, no_ollama: bool, max_diff_chars: int, output: Path | None) -> dict:
    knowledge = _load_json(DEFAULT_KNOWLEDGE_PATH)
    files = _changed_files(staged)
    diff = _diff_text(staged, max_diff_chars)
    heuristic = _heuristic_review(files, knowledge)
    result = {
        "kind": "ollama_diff_review",
        "generated_at": _utc_now(),
        "staged": staged,
        "heuristic": heuristic,
        "ollama": None,
        "status": heuristic["status"],
    }
    if not no_ollama and (os.environ.get("OLLAMA_BASE_URL") or shutil_which("ollama")) and diff.strip():
        try:
            result["ollama"] = _ollama_review(diff, heuristic, knowledge)
            if result["ollama"].get("status") in {"blocked", "review_required"}:
                result["status"] = result["ollama"]["status"]
        except Exception as exc:
            result["ollama_error"] = str(exc)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def shutil_which(binary: str) -> str | None:
    _, out = _run(["which", binary], timeout=10)
    value = out.strip()
    return value or None


def main() -> int:
    parser = argparse.ArgumentParser(description="Revision local de diff con Ollama y memoria del CRM.")
    parser.add_argument("--staged", action="store_true", help="Revisa solo cambios staged.")
    parser.add_argument("--no-ollama", action="store_true", help="Usa solo heuristica local.")
    parser.add_argument("--max-diff-chars", type=int, default=50000, help="Maximo de caracteres de diff para Ollama.")
    parser.add_argument("--output", default="", help="Ruta donde guardar JSON de revision.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo.")
    parser.add_argument("--fail-on-review", action="store_true", help="Devuelve codigo 1 si hay review_required/blocked.")
    args = parser.parse_args()
    output = Path(args.output).resolve() if args.output else None
    result = run_review(staged=args.staged, no_ollama=args.no_ollama, max_diff_chars=args.max_diff_chars, output=output)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    if args.fail_on_review and result.get("status") in {"review_required", "blocked"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
