#!/usr/bin/env python3
"""Genera un inventario compacto del repo para resumen/auditoria con Ollama."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IGNORE_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "reports", "dist", "build"}
TEXT_SUFFIXES = {".py", ".js", ".css", ".html", ".sql", ".md", ".json", ".sh", ".yml", ".yaml", ".toml", ".txt"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return proc.returncode, proc.stdout or ""
    except Exception as exc:
        return 1, f"{type(exc).__name__}: {exc}"


def _iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(ROOT).parts
        if any(part in IGNORE_DIRS for part in rel_parts):
            continue
        files.append(path)
    return files


def _read_text(path: Path, limit: int = 6_000_000) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _git_info() -> dict:
    _, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    _, commit = _run(["git", "rev-parse", "HEAD"])
    _, status = _run(["git", "status", "--short"])
    _, recent = _run(["git", "log", "--oneline", "-8"])
    return {
        "branch": branch.strip(),
        "commit": commit.strip(),
        "dirty_files": [line.strip() for line in status.splitlines() if line.strip()],
        "recent_commits": [line.strip() for line in recent.splitlines() if line.strip()],
    }


def _extract_api_endpoints(server_text: str) -> list[dict]:
    endpoints = []
    for match in re.finditer(r'if\s+path\s*==\s*["\'](/api/[^"\']+)["\']', server_text):
        line = server_text[: match.start()].count("\n") + 1
        endpoints.append({"path": match.group(1), "line": line})
    unique = {}
    for item in endpoints:
        unique.setdefault(item["path"], item)
    return sorted(unique.values(), key=lambda item: item["path"])


def _extract_js_functions(app_text: str) -> dict:
    functions = re.findall(r"\b(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(", app_text)
    const_functions = re.findall(r"\bconst\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(", app_text)
    event_handlers = re.findall(r"\.addEventListener\s*\(\s*['\"]([^'\"]+)['\"]", app_text)
    return {
        "function_count": len(functions) + len(const_functions),
        "sample_functions": sorted(set(functions + const_functions))[:120],
        "event_handlers": dict(Counter(event_handlers).most_common()),
    }


def _scan_risk_markers(files: list[Path]) -> list[dict]:
    markers = []
    pattern = re.compile(r"\b(TODO|FIXME|HACK|XXX|pass\s*#|console\.error|alert\(|except\s+Exception)\b", re.IGNORECASE)
    for path in files:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = _read_text(path, limit=6_000_000)
        if not text:
            continue
        rel = str(path.relative_to(ROOT))
        for idx, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                markers.append({"file": rel, "line": idx, "text": line.strip()[:220]})
                if len(markers) >= 500:
                    return markers
    return markers


def build_inventory() -> dict:
    files = _iter_files()
    suffix_counts = Counter(path.suffix.lower() or "<none>" for path in files)
    largest = sorted(
        [{"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size} for path in files],
        key=lambda item: item["bytes"],
        reverse=True,
    )[:40]
    tests = sorted(str(path.relative_to(ROOT)) for path in files if path.name.startswith("test_") or "/tests/" in str(path.relative_to(ROOT)))
    server_text = _read_text(ROOT / "web" / "server.py")
    app_text = _read_text(ROOT / "web" / "app.js")
    return {
        "kind": "codebase_inventory_for_ollama",
        "generated_at": _utc_now(),
        "root": str(ROOT),
        "git": _git_info(),
        "files": {
            "total": len(files),
            "suffix_counts": dict(suffix_counts.most_common()),
            "largest": largest,
        },
        "backend": {
            "api_endpoints_total": len(_extract_api_endpoints(server_text)),
            "api_endpoints": _extract_api_endpoints(server_text),
        },
        "frontend": _extract_js_functions(app_text),
        "tests": {
            "total": len(tests),
            "files": tests[:300],
        },
        "risk_markers": _scan_risk_markers(files),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventario compacto del repo para Ollama.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON completo.")
    args = parser.parse_args()
    inventory = build_inventory()
    print(json.dumps(inventory, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
