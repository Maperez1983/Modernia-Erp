#!/usr/bin/env python3
"""Sincroniza variables de entorno de Render sin pisar claves no incluidas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen


def _api_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _normalize_env_list(payload: object) -> list[dict]:
    rows = payload if isinstance(payload, list) else []
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        if not key:
            continue
        value = row.get("value")
        if value is None:
            value = row.get("previewValue") or ""
        normalized.append({"key": key, "value": str(value)})
    return normalized


def _fetch_env_vars(api_key: str, service_id: str) -> list[dict]:
    req = Request(
        f"https://api.render.com/v1/services/{service_id}/env-vars",
        headers=_api_headers(api_key),
        method="GET",
    )
    with urlopen(req, timeout=30) as resp:
        return _normalize_env_list(json.loads(resp.read().decode("utf-8")))


def _merge_env_vars(current_rows: list[dict], updates: dict[str, str]) -> list[dict]:
    merged = {str(row["key"]): str(row.get("value") or "") for row in current_rows if row.get("key")}
    for key, value in updates.items():
        merged[str(key)] = str(value)
    return [{"key": key, "value": merged[key]} for key in sorted(merged)]


def sync_env_vars(api_key: str, service_id: str, updates: dict[str, str], *, dry_run: bool = False) -> dict:
    current = _fetch_env_vars(api_key, service_id)
    payload_rows = _merge_env_vars(current, updates)
    if dry_run:
        return {
            "kind": "render_env_sync",
            "status": "dry_run",
            "current_total": len(current),
            "updated_keys": sorted(updates),
            "payload_total": len(payload_rows),
            "payload": payload_rows,
        }
    req = Request(
        f"https://api.render.com/v1/services/{service_id}/env-vars",
        data=json.dumps(payload_rows).encode("utf-8"),
        headers=_api_headers(api_key),
        method="PUT",
    )
    with urlopen(req, timeout=30) as resp:
        response_rows = _normalize_env_list(json.loads(resp.read().decode("utf-8")))
    return {
        "kind": "render_env_sync",
        "status": "passed",
        "current_total": len(current),
        "updated_keys": sorted(updates),
        "payload_total": len(payload_rows),
        "result_total": len(response_rows),
    }


def _load_updates(args: argparse.Namespace) -> dict[str, str]:
    if args.json_file:
        data = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("El JSON de variables debe ser un objeto clave/valor.")
        return {str(key): str(value) for key, value in data.items()}
    updates = {}
    for item in args.set or []:
        if "=" not in item:
            raise ValueError(f"Variable invalida: {item}")
        key, value = item.split("=", 1)
        updates[key.strip()] = value
    return updates


def main() -> int:
    parser = argparse.ArgumentParser(description="Sincroniza variables de entorno de Render sin borrar el resto.")
    parser.add_argument("--api-key", required=True, help="API key de Render.")
    parser.add_argument("--service-id", required=True, help="Service ID de Render.")
    parser.add_argument("--set", action="append", default=[], help="Par clave=valor a sincronizar.")
    parser.add_argument("--json-file", default="", help="JSON con pares clave/valor.")
    parser.add_argument("--dry-run", action="store_true", help="No aplica el PUT final.")
    parser.add_argument("--json", action="store_true", help="Imprime JSON formateado.")
    args = parser.parse_args()
    updates = _load_updates(args)
    result = sync_env_vars(args.api_key, args.service_id, updates, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

