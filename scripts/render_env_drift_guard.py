#!/usr/bin/env python3
"""Verifica que una variable crítica de Render no haya desaparecido y la restaura si hace falta."""

from __future__ import annotations

import argparse
import json
import os
import sys

from render_env_sync import sync_env_vars


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Comprueba y (opcionalmente) reestablece variables críticas en Render."
    )
    parser.add_argument("--api-key", required=True, help="API key de Render.")
    parser.add_argument("--service-id", required=True, help="ID del servicio Render.")
    parser.add_argument(
        "--required",
        nargs="+",
        default=[
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_REGION",
            "AWS_S3_BUCKET",
        ],
        help="Variables requeridas (separadas por espacio).",
    )
    parser.add_argument(
        "--remediate",
        action="store_true",
        help=(
            "Si una variable falta o está vacía, intenta restaurarla leyendo el mismo nombre "
            "de variable en el entorno local de este proceso."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Salida en JSON.",
    )
    return parser.parse_args()


def _fetch_current(api_key: str, service_id: str) -> dict[str, str]:
    # fetch + normalize en una sola pasada para evitar dependencias fuertes con la forma interna de render_env_sync.
    rows = []
    cursor = ""
    import json as _json
    from urllib.request import Request, urlopen

    while True:
        url = f"https://api.render.com/v1/services/{service_id}/env-vars"
        if cursor:
            url += f"?cursor={cursor}"
        req = Request(url, headers={"Authorization": f"Bearer {api_key}"})
        with urlopen(req, timeout=30) as resp:
            payload = _json.loads(resp.read().decode("utf-8"))
        if not isinstance(payload, list) or not payload:
            break
        for row in payload:
            if not isinstance(row, dict):
                continue
            row = row.get("envVar") or row
            key = str(row.get("key") or "").strip()
            if not key:
                continue
            rows.append((key, str(row.get("value") or row.get("previewValue") or "")))
        last = payload[-1] if payload else {}
        next_cursor = str(last.get("cursor") or "").strip()
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return {key: value for key, value in rows}


def run(api_key: str, service_id: str, required: list[str], remediate: bool, as_json: bool) -> int:
    current = _fetch_current(api_key, service_id)
    required = [item.strip() for item in required if str(item or "").strip()]
    missing = []
    empty = []
    for key in required:
        if key not in current:
            missing.append(key)
            continue
        if not str(current.get(key, "") or "").strip():
            empty.append(key)

    if not missing and not empty:
        payload = {"status": "passed", "missing": [], "empty": [], "updates": {}}
        if as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("OK: vars críticas de Render presentes.")
        return 0

    if not remediate:
        payload = {
            "status": "failed",
            "missing": missing,
            "empty": empty,
            "updates": {},
            "detail": "Setea --remediate o sincroniza manualmente en Render.",
        }
        if as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if missing:
                print(f"Faltan: {', '.join(missing)}")
            if empty:
                print(f"Vacías: {', '.join(empty)}")
            print("Añade --remediate (con valores en el entorno local) o corrígelo en Render.")
        return 2

    updates: dict[str, str] = {}
    for key in (missing + empty):
        value = os.environ.get(key)
        if value is None or not str(value).strip():
            continue
        updates[key] = str(value)

    unresolved = [key for key in (missing + empty) if key not in updates]
    if unresolved:
        payload = {
            "status": "failed",
            "missing": missing,
            "empty": empty,
            "updates": updates,
            "unresolved": unresolved,
            "detail": "No hay valor local para reestablecer estas claves; exporta en entorno local primero.",
        }
        if as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"No se pudo auto-restaurar: {', '.join(unresolved)}")
            print("Exporta localmente: " + ", ".join(f"{k}=..." for k in unresolved))
        return 2

    sync_env_vars(api_key, service_id, updates, dry_run=False)
    refreshed = _fetch_current(api_key, service_id)
    unresolved_after = [key for key in updates if not (str(refreshed.get(key, "") or "").strip())]
    if unresolved_after:
        payload = {
            "status": "failed",
            "missing": missing,
            "empty": empty,
            "updates": updates,
            "unresolved": unresolved_after,
            "detail": "Render respondió con valores vacíos después de sync.",
        }
        if as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"No quedaron persistidas en Render: {', '.join(unresolved_after)}")
        return 2

    payload = {
        "status": "remediated",
        "missing": [],
        "empty": [],
        "updates": updates,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"OK: reestablecidas {', '.join(sorted(updates))}.")
    return 0


def main() -> int:
    args = parse_args()
    return run(
        api_key=args.api_key,
        service_id=args.service_id,
        required=list(args.required),
        remediate=args.remediate,
        as_json=args.json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
