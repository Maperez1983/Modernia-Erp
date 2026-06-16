#!/usr/bin/env python3
"""Construye la base de conocimiento estable para auditorias con Ollama."""

from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
KNOWLEDGE_JSON = DOCS_DIR / "system_knowledge.json"
KNOWLEDGE_MD = DOCS_DIR / "system_knowledge.md"


MODULE_RULES = [
    ("agenda", ("acciones", "agenda", "cita")),
    ("usuarios_permisos", ("usuarios", "workspace_miembros", "membership", "privilege", "permiso")),
    ("rrhh", ("registro_horario", "workspace_registro", "rrhh", "nomina", "personal")),
    ("workspaces", ("workspace", "tenant")),
    ("inmobiliaria", ("inmobiliaria", "inmueble", "demanda", "visita", "compraventa", "matching", "encargo")),
    ("seguros", ("seguro", "poliza", "recibo", "siniestro", "idd")),
    ("gestoria", ("gestoria", "renta", "modelo", "asiento", "factura")),
    ("financiacion", ("fin_", "hipoteca", "financiacion")),
    ("fincas", ("fincas", "comunidad", "junta", "vecino")),
]

MODULE_EXPECTATIONS = {
    "agenda": [
        "Los usuarios de un workspace deben ver sus citas nuevas y antiguas si pertenecen al workspace.",
        "El comportamiento de lectura de agenda debe ser equivalente entre admin y no admin dentro del mismo workspace permitido.",
        "Al crear o editar citas no se deben heredar cliente, tipo de cita, responsable, fechas ni campos de una cita anterior.",
        "Los filtros de agenda deben acotarse por workspace/servicio, no por estado modal residual del frontend.",
    ],
    "usuarios_permisos": [
        "Un usuario no privilegiado solo puede ver datos de workspaces donde es miembro.",
        "Un admin puede auditar usuarios por workspace, pero no debe mezclar tenants sin workspace_id.",
        "Las diferencias de permisos deben producir 401/403 controlados, nunca 5xx.",
    ],
    "workspaces": [
        "Toda consulta operativa debe resolver workspace_id de forma explicita o desde la sesion.",
        "Los endpoints compartidos deben mantener aislamiento entre workspaces.",
    ],
    "inmobiliaria": [
        "La informacion de inmuebles, demandas, visitas, compraventas y matching debe estar filtrada por workspace.",
        "Las vistas de no admin deben devolver datos permitidos, no listas vacias por error de scoping.",
    ],
    "seguros": [
        "Los endpoints de seguros deben devolver datos o 403 controlado si el usuario no tiene servicio.",
        "Los KPIs no deben romper por falta de datos; si falta empresa_id debe responder 400 claro.",
    ],
    "gestoria": [
        "Los endpoints de gestoria deben respetar permisos de servicio y workspace.",
        "La importacion y consulta documental no debe cruzar clientes entre workspaces.",
    ],
    "financiacion": [
        "Las alertas/KPIs financieros deben responder con datos o errores 400/403 controlados.",
    ],
    "fincas": [
        "Las comunidades, incidencias, proveedores y documentos deben acotarse por workspace.",
    ],
    "rrhh": [
        "El registro horario y personal deben estar acotados por usuario/workspace.",
    ],
}

MODULE_ENTRYPOINTS = {
    "backend": ["web/server.py", "web/db_backend.py", "web/schema_support.py"],
    "frontend": ["web/app.js", "web/index.html", "web/styles.css"],
    "auditoria": [
        "scripts/run_system_audit.py",
        "scripts/prod_api_monitor.py",
        "scripts/prod_system_matrix_audit.py",
        "scripts/summarize_audit_with_ollama.py",
    ],
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run(cmd: list[str], timeout: int = 30) -> str:
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return proc.stdout.strip()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _extract_endpoints(server_text: str) -> list[dict]:
    items = []
    for match in re.finditer(r'if\s+path\s*==\s*["\'](/api/[^"\']+)["\']', server_text):
        line = server_text[: match.start()].count("\n") + 1
        path = match.group(1)
        items.append({"path": path, "line": line, "module": _classify(path)})
    unique = {}
    for item in items:
        unique.setdefault(item["path"], item)
    return sorted(unique.values(), key=lambda item: item["path"])


def _extract_frontend_api_map(app_text: str) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = defaultdict(list)
    lines = app_text.splitlines()
    for idx, line in enumerate(lines, start=1):
        for match in re.finditer(r'["\'](/api/[^"\']+)["\']', line):
            endpoint = match.group(1)
            start = max(0, idx - 6)
            context = "\n".join(lines[start:idx])
            fn_match = re.findall(r"\b(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(|\bconst\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(", context)
            names = []
            for a, b in fn_match:
                if a:
                    names.append(a)
                if b:
                    names.append(b)
            if not names:
                names = [f"line:{idx}"]
            for name in names[-3:]:
                if name not in mapping[endpoint]:
                    mapping[endpoint].append(name)
    return dict(sorted(mapping.items()))


def _classify(text: str) -> str:
    lower = text.lower()
    for module, needles in MODULE_RULES:
        if any(needle in lower for needle in needles):
            return module
    return "core"


def _tests_by_module() -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        module = _classify(path.name)
        result[module].append(str(path.relative_to(ROOT)))
    return dict(sorted(result.items()))


def build_knowledge() -> dict:
    server_text = _read(ROOT / "web" / "server.py")
    app_text = _read(ROOT / "web" / "app.js")
    endpoints = _extract_endpoints(server_text)
    endpoint_counts: dict[str, int] = defaultdict(int)
    for item in endpoints:
        endpoint_counts[item["module"]] += 1
    frontend_functions: dict[str, list[str]] = defaultdict(list)
    for match in re.finditer(r"\b(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(", app_text):
        name = match.group(1)
        frontend_functions[_classify(name)].append(name)
    for match in re.finditer(r"\bconst\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(", app_text):
        name = match.group(1)
        frontend_functions[_classify(name)].append(name)
    frontend_api_map = _extract_frontend_api_map(app_text)
    return {
        "kind": "modernia_system_knowledge",
        "generated_at": _utc_now(),
        "git": {
            "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
            "commit": _run(["git", "rev-parse", "HEAD"]),
            "recent_commits": _run(["git", "log", "--oneline", "-8"]).splitlines(),
        },
        "purpose": (
            "Memoria estable para que Ollama relacione fallos de produccion con el modulo, "
            "endpoint, frontend, test y expectativa funcional correspondiente."
        ),
        "entrypoints": MODULE_ENTRYPOINTS,
        "frontend_api_map": frontend_api_map,
        "modules": {
            module: {
                "expectations": expectations,
                "endpoint_count": endpoint_counts.get(module, 0),
                "endpoints_sample": [item for item in endpoints if item["module"] == module][:40],
                "tests": _tests_by_module().get(module, []),
                "frontend_functions_sample": sorted(set(frontend_functions.get(module, [])))[:60],
                "frontend_endpoint_links": [
                    {
                        "path": item["path"],
                        "frontend_functions": frontend_api_map.get(item["path"], []),
                    }
                    for item in endpoints
                    if item["module"] == module and frontend_api_map.get(item["path"])
                ][:40],
            }
            for module, expectations in MODULE_EXPECTATIONS.items()
        },
        "all_api_endpoints_total": len(endpoints),
        "diagnostic_rules": [
            {
                "symptom": "Un usuario no admin no ve citas o ve menos que admin en el mismo workspace.",
                "module": "agenda",
                "look_at": [
                    "scripts/prod_system_matrix_audit.py endpoint agenda_inmobiliaria",
                    "web/server.py /api/acciones",
                    "fetch_api_usuarios y enforce_workspace_membership",
                    "web/app.js estado modal/filtros de agenda",
                    "tests/test_agenda_frontend_regressions.py",
                    "tests/test_api_usuarios_scoping.py",
                ],
            },
            {
                "symptom": "Despues de editar/crear una cita se heredan cliente, tipo o responsable.",
                "module": "agenda",
                "look_at": [
                    "web/app.js apertura/reset del modal de agenda",
                    "web/app.js serializacion del formulario de cita",
                    "tests/test_agenda_frontend_regressions.py",
                ],
            },
            {
                "symptom": "Aparecen 500/timeout en endpoints de produccion.",
                "module": "core",
                "look_at": [
                    "output_tail del paso fallido",
                    "endpoint exacto en web/server.py",
                    "tests relacionados por nombre de modulo",
                    "schema.sql si el error menciona columna/tabla",
                ],
            },
            {
                "symptom": "Un endpoint responde 403 a no admin.",
                "module": "usuarios_permisos",
                "look_at": [
                    "servicio/rol del usuario en /api/login",
                    "workspace_user_inventory",
                    "controles has_service_access/enforce_workspace_membership",
                ],
                "note": "Puede ser correcto si el usuario no tiene ese servicio; no debe considerarse caida si es esperado.",
            },
        ],
    }


def write_markdown(knowledge: dict) -> None:
    lines = [
        "# Modernia CRM System Knowledge",
        "",
        f"Generated: {knowledge['generated_at']}",
        f"Commit: {knowledge['git']['commit']}",
        "",
        knowledge["purpose"],
        "",
        "## Modules",
    ]
    for module, data in knowledge["modules"].items():
        lines.extend(["", f"### {module}", "", f"- API endpoints: {data['endpoint_count']}"])
        if data["tests"]:
            lines.append(f"- Tests: {', '.join(data['tests'][:12])}")
        lines.append("- Expectations:")
        for expectation in data["expectations"]:
            lines.append(f"  - {expectation}")
    lines.extend(["", "## Diagnostic Rules"])
    for rule in knowledge["diagnostic_rules"]:
        lines.extend(["", f"### {rule['symptom']}", f"- Module: {rule['module']}", "- Look at:"])
        for item in rule["look_at"]:
            lines.append(f"  - {item}")
        if rule.get("note"):
            lines.append(f"- Note: {rule['note']}")
    KNOWLEDGE_MD.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def main() -> int:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    knowledge = build_knowledge()
    KNOWLEDGE_JSON.write_text(json.dumps(knowledge, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(knowledge)
    print(f"Knowledge JSON: {KNOWLEDGE_JSON}")
    print(f"Knowledge MD: {KNOWLEDGE_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
