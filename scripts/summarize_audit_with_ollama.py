#!/usr/bin/env python3
"""Resume un reporte de auditoria usando Ollama local."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


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
                "output_tail": output[-5000:],
            }
        )
    return {
        "run_id": report.get("run_id"),
        "status": report.get("status"),
        "started_at": report.get("started_at"),
        "finished_at": report.get("finished_at"),
        "failed_steps": report.get("failed_steps"),
        "steps": compact_steps,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: summarize_audit_with_ollama.py reports/system_audit/system-audit-....json", file=sys.stderr)
        return 2

    if not shutil.which("ollama"):
        print("Ollama no esta instalado o no esta en PATH; se omite el resumen local.")
        return 0

    report_path = Path(sys.argv[1]).resolve()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    model = os.environ.get("OLLAMA_AUDIT_MODEL") or "qwen2.5-coder:7b"
    prompt = (
        "Eres un auditor tecnico de un CRM. Resume este reporte en castellano con: "
        "1) estado global, 2) fallos concretos, 3) causa probable si se puede inferir, "
        "4) siguiente accion recomendada. No inventes datos que no esten en el JSON.\n\n"
        + json.dumps(_compact_report(report), ensure_ascii=False, indent=2)
    )
    proc = subprocess.run(
        ["ollama", "run", model],
        input=prompt,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=240,
    )
    summary_path = report_path.with_suffix(".ollama.md")
    summary_path.write_text(proc.stdout.strip() + "\n", encoding="utf-8")
    print(f"Resumen Ollama: {summary_path}")
    if proc.returncode != 0:
        print(proc.stdout, file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
