#!/usr/bin/env python3
"""Verificadores de negocio contra producción para detectar cálculos o agregados incoherentes."""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import prod_auth_drift_audit


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DEFAULT_CHECKS_PATH = DOCS / "reconciliation_checks.json"


def _load_checks() -> list[dict]:
    try:
        data = json.loads(Path(os.environ.get("RUN_SYSTEM_AUDIT_RECONCILIATION_PATH") or DEFAULT_CHECKS_PATH).read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return (data if isinstance(data, dict) else {}).get("checks") or []


def _base_url() -> str:
    return prod_auth_drift_audit._base_url()


def _timeout() -> int:
    return prod_auth_drift_audit._env_int("CRM_AUDIT_HTTP_TIMEOUT", 45)


def _admin_session() -> tuple[object | None, dict, str]:
    user = str(os.environ.get("CRM_ADMIN_USER") or "").strip()
    password = str(os.environ.get("CRM_ADMIN_PASSWORD") or "")
    if not user or not password:
        return None, {}, "missing_admin_credentials"
    session, login_data, login_result = prod_auth_drift_audit._login(_base_url(), user, password, _timeout())
    if login_result.status != "passed":
        return None, {}, login_result.detail or "admin_login_failed"
    return session, login_data, ""


def _get_json(session, path: str) -> tuple[int, dict]:
    resp, data = prod_auth_drift_audit._get_json(session, f"{_base_url()}{path}", _timeout())
    return int(resp.status_code), data if isinstance(data, dict) else {}


def _pick_workspace(session) -> dict:
    status, data = _get_json(session, "/api/workspaces")
    if status != 200:
        return {}
    rows = data.get("rows")
    rows = rows if isinstance(rows, list) else []
    preferred = (os.environ.get("CRM_AUDIT_WORKSPACE") or "verifika").strip().lower()
    for row in rows:
        haystack = " ".join(str(row.get(k) or "") for k in ("id", "nombre", "slug")).lower()
        if preferred and preferred in haystack:
            return row
    return rows[0] if rows else {}


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _safe_float(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _workspace_query(workspace: dict, extra: dict | None = None) -> str:
    params = {"workspace_id": str(workspace.get("id") or "")}
    if workspace.get("empresa_id"):
        params["empresa_id"] = str(workspace.get("empresa_id"))
    if extra:
        params.update({key: str(value) for key, value in extra.items() if value not in {None, ""}})
    parts = [f"{key}={value}" for key, value in params.items() if value]
    return "&".join(parts)


def _check_seguros_dashboard(session, workspace: dict) -> dict:
    query = _workspace_query(workspace)
    overview_status, overview = _get_json(session, f"/api/workspace_seguros_overview?{query}")
    recibos_status, recibos = _get_json(session, f"/api/seguros_recibos_summary?{query}")
    counts = (overview.get("counts") or {}) if overview_status == 200 else {}
    checks = []
    total = _safe_int(counts.get("total"))
    en_vigor = _safe_int(counts.get("en_vigor"))
    renovaciones = _safe_int(counts.get("renovaciones_30d"))
    prima_total = _safe_float(counts.get("prima_total"))
    checks.append({"name": "en_vigor_lte_total", "ok": en_vigor <= total, "detail": f"{en_vigor}<={total}"})
    checks.append({"name": "renovaciones_non_negative", "ok": renovaciones >= 0, "detail": str(renovaciones)})
    checks.append({"name": "prima_total_non_negative", "ok": prima_total >= 0, "detail": str(prima_total)})
    summary = (recibos.get("summary") or {}) if recibos_status == 200 else {}
    checks.append({"name": "recibos_total_non_negative", "ok": _safe_int(summary.get("total")) >= 0, "detail": str(summary.get("total"))})
    failed = [item for item in checks if not item["ok"]]
    return {
        "id": "seguros_dashboard_consistency",
        "module": "seguros",
        "status": "failed" if failed or overview_status != 200 or recibos_status != 200 else "passed",
        "failed_subchecks": [item["name"] for item in failed],
        "detail": {
            "overview_status": overview_status,
            "recibos_status": recibos_status,
            "counts": {"total": total, "en_vigor": en_vigor, "renovaciones_30d": renovaciones, "prima_total": prima_total},
            "subchecks": checks,
        },
    }


def _check_gestoria_dashboard(session, workspace: dict) -> dict:
    query = _workspace_query(workspace)
    overview_status, overview = _get_json(session, f"/api/workspace_gestoria_overview?{query}")
    dashboard_status, dashboard = _get_json(session, f"/api/gestoria_dashboard?{query}")
    overview_counts = (overview.get("counts") or {}) if overview_status == 200 else {}
    dashboard_counts = (dashboard.get("counts") or {}) if dashboard_status == 200 else {}
    checks = []
    rentas_total = _safe_int(dashboard_counts.get("rentas_total_ejercicio"))
    rentas_pend = _safe_int(dashboard_counts.get("rentas_pendientes_presentar"))
    modelos_mes = _safe_int(dashboard_counts.get("modelos_mes"))
    checks.append({"name": "rentas_pending_lte_total", "ok": rentas_pend <= max(rentas_total, rentas_pend), "detail": f"{rentas_pend}<={rentas_total}"})
    checks.append({"name": "modelos_mes_non_negative", "ok": modelos_mes >= 0, "detail": str(modelos_mes)})
    checks.append(
        {
            "name": "overview_vs_dashboard_rentas_pending",
            "ok": abs(rentas_pend - _safe_int(overview_counts.get("rentas_pendientes_presentar"))) <= 5,
            "detail": f"dashboard={rentas_pend} overview={_safe_int(overview_counts.get('rentas_pendientes_presentar'))}",
        }
    )
    failed = [item for item in checks if not item["ok"]]
    return {
        "id": "gestoria_rentas_import",
        "module": "gestoria",
        "status": "failed" if failed or overview_status != 200 or dashboard_status != 200 else "passed",
        "failed_subchecks": [item["name"] for item in failed],
        "detail": {
            "overview_status": overview_status,
            "dashboard_status": dashboard_status,
            "counts": {"rentas_total_ejercicio": rentas_total, "rentas_pendientes_presentar": rentas_pend, "modelos_mes": modelos_mes},
            "subchecks": checks,
        },
    }


def _check_gestoria_accounting(session, workspace: dict) -> dict:
    query = _workspace_query(workspace)
    status, data = _get_json(session, f"/api/gestoria_contabilidad?{query}")
    summary = (data.get("summary") or {}) if status == 200 else {}
    ingresos = _safe_float(summary.get("ingresos"))
    gastos = _safe_float(summary.get("gastos"))
    resultado = _safe_float(summary.get("resultado"))
    checks = [
        {"name": "resultado_matches_ingresos_minus_gastos", "ok": math.isclose(resultado, ingresos - gastos, rel_tol=0, abs_tol=1.5), "detail": f"{resultado}~={ingresos - gastos}"},
        {"name": "total_rows_non_negative", "ok": _safe_int(data.get("total_rows")) >= 0, "detail": str(data.get("total_rows"))},
    ]
    failed = [item for item in checks if not item["ok"]]
    return {
        "id": "gestoria_facturas_accounting",
        "module": "gestoria",
        "status": "failed" if failed or status != 200 else "passed",
        "failed_subchecks": [item["name"] for item in failed],
        "detail": {"http_status": status, "summary": summary, "subchecks": checks},
    }


def _check_fin_dashboard(session, workspace: dict) -> dict:
    query = _workspace_query(workspace)
    status, data = _get_json(session, f"/api/workspace_fin_overview?{query}")
    counts = (data.get("counts") or {}) if status == 200 else {}
    total = _safe_int(counts.get("total"))
    firmadas = _safe_int(counts.get("firmadas"))
    comision = _safe_float(counts.get("comision_total"))
    checks = [
        {"name": "firmadas_lte_total", "ok": firmadas <= total, "detail": f"{firmadas}<={total}"},
        {"name": "comision_non_negative", "ok": comision >= 0, "detail": str(comision)},
    ]
    failed = [item for item in checks if not item["ok"]]
    return {
        "id": "fin_dashboard_consistency",
        "module": "financiacion",
        "status": "failed" if failed or status != 200 else "passed",
        "failed_subchecks": [item["name"] for item in failed],
        "detail": {"http_status": status, "counts": counts, "subchecks": checks},
    }


CHECK_RUNNERS = {
    "seguros_dashboard_consistency": _check_seguros_dashboard,
    "gestoria_rentas_import": _check_gestoria_dashboard,
    "gestoria_facturas_accounting": _check_gestoria_accounting,
    "fin_dashboard_consistency": _check_fin_dashboard,
}


def run() -> dict:
    session, _, error = _admin_session()
    if not session:
        return {
            "kind": "system_business_reconciliation",
            "status": "failed",
            "failed_checks": ["admin_session"],
            "results": [],
            "detail": error,
        }
    workspace = _pick_workspace(session)
    if not workspace.get("id"):
        return {
            "kind": "system_business_reconciliation",
            "status": "failed",
            "failed_checks": ["workspace_resolution"],
            "results": [],
            "detail": "No se pudo resolver un workspace de auditoría.",
        }
    results = []
    for item in _load_checks():
        runner = CHECK_RUNNERS.get(str(item.get("id") or ""))
        if not runner:
            continue
        results.append(runner(session, workspace))
    failed = [item["id"] for item in results if item.get("status") != "passed"]
    return {
        "kind": "system_business_reconciliation",
        "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "failed" if failed else "passed",
        "failed_checks": failed,
        "workspace": {"id": workspace.get("id"), "nombre": workspace.get("nombre"), "slug": workspace.get("slug")},
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verificadores de negocio en producción.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON.")
    args = parser.parse_args()
    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.json else None))
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())

