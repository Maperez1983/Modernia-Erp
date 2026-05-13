#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Finding:
    file: str
    line: int
    kind: str
    snippet: str


def load_text(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def scan_server(lines: list[str], rel: str) -> list[Finding]:
    findings: list[Finding] = []
    in_handler = False
    for idx, line in enumerate(lines, start=1):
        if "def do_POST" in line or "def do_GET" in line:
            in_handler = True
        if not in_handler:
            continue

        if 'empresa["id"]' in line:
            findings.append(Finding(rel, idx, "server_empresa_dict_id", line.strip()))
        if re.search(r"\bempresa_id\s*=\s*str\(payload\.get\(\"empresa_id\"\)", line):
            findings.append(Finding(rel, idx, "server_payload_empresa_id", line.strip()))
        if "workspace_company_id" in line and "payload.get" in line:
            findings.append(Finding(rel, idx, "server_payload_workspace_company_id", line.strip()))
        if "resolve_empresa_id_for_request" in line:
            findings.append(Finding(rel, idx, "server_resolve_empresa_id_for_request", line.strip()))
        if "resolve_legacy_empresa_id_from_workspace_company" in line:
            findings.append(
                Finding(rel, idx, "server_resolve_legacy_empresa_id_from_workspace_company", line.strip())
            )
    return findings


def scan_app(lines: list[str], rel: str) -> list[Finding]:
    findings: list[Finding] = []
    for idx, line in enumerate(lines, start=1):
        if re.search(r"\bempresa\.id\b", line):
            findings.append(Finding(rel, idx, "app_empresa_dot_id", line.strip()))
        if "legacy_empresa_id" in line:
            findings.append(Finding(rel, idx, "app_legacy_empresa_id", line.strip()))
        if "workspace_company_id" in line:
            findings.append(Finding(rel, idx, "app_workspace_company_id", line.strip()))
        if "isTenantWorkspaceMode" in line:
            findings.append(Finding(rel, idx, "app_is_tenant_workspace_mode", line.strip()))
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audita uso de empresa_id/empresa[\"id\"] y compat tenant (workspace_company_id)."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Ruta raíz del repo (default: .)",
    )
    parser.add_argument("--format", default="text", choices=("text", "json"))
    parser.add_argument(
        "--only-suspicious",
        action="store_true",
        help="Solo reporta patrones típicamente problemáticos (empresa[\"id\"] y empresa.id sin legacy fallback).",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    server = root / "web" / "server.py"
    app = root / "web" / "app.js"
    if not server.exists():
        raise SystemExit(f"No existe {server}")
    if not app.exists():
        raise SystemExit(f"No existe {app}")

    server_lines = load_text(server)
    app_lines = load_text(app)

    findings = []
    findings.extend(scan_server(server_lines, "web/server.py"))
    findings.extend(scan_app(app_lines, "web/app.js"))

    if args.only_suspicious:
        filtered: list[Finding] = []
        for f in findings:
            if f.kind == "server_empresa_dict_id":
                filtered.append(f)
            elif f.kind == "app_empresa_dot_id":
                # Deja solo líneas donde se use empresa.id sin mencionar legacy_empresa_id.
                if "legacy_empresa_id" not in f.snippet:
                    filtered.append(f)
        findings = filtered

    out = {
        "root": str(root),
        "counts": {},
        "findings": [f.__dict__ for f in findings],
    }
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    out["counts"] = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    if args.format == "json":
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print(f"Repo: {root}")
    for kind, n in out["counts"].items():
        print(f"- {kind}: {n}")
    print("")
    for f in out["findings"][:250]:
        print(f"{f['file']}:{f['line']} {f['kind']} :: {f['snippet']}")
    if len(out["findings"]) > 250:
        print(f"... ({len(out['findings'])-250} más)")


if __name__ == "__main__":
    main()

