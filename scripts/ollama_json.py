#!/usr/bin/env python3
"""Cliente minimo para obtener JSON estricto desde Ollama."""

from __future__ import annotations

import json
import re
from urllib.error import URLError
from urllib.request import Request, urlopen


def json_from_text(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {}
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


def generate_json(
    *,
    base_url: str,
    model: str,
    prompt: str,
    required_keys: set[str] | None = None,
    valid_statuses: set[str] | None = None,
    timeout: int = 240,
    retries: int = 1,
) -> dict:
    last_response = ""
    last_error = ""
    for attempt in range(retries + 1):
        strict_prompt = prompt
        if attempt:
            strict_prompt = (
                "Tu respuesta anterior no fue JSON valido o no cumplio el esquema. "
                "Responde ahora SOLO con un objeto JSON valido, sin explicaciones, sin markdown.\n\n"
                + prompt
            )
        if model.lower().startswith("qwen3:"):
            strict_prompt = "/no_think\n" + strict_prompt
        payload = json.dumps({"model": model, "prompt": strict_prompt, "stream": False}).encode("utf-8")
        request = Request(
            f"{base_url.rstrip('/')}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except URLError as exc:
            raise RuntimeError(f"No se puede conectar con Ollama: {exc}") from exc
        last_response = str(data.get("response") or "").strip()
        parsed = json_from_text(last_response)
        if not parsed:
            last_error = "respuesta sin JSON"
            continue
        if required_keys and not required_keys.issubset(parsed.keys()):
            last_error = f"faltan claves: {sorted(required_keys - set(parsed.keys()))}"
            continue
        if valid_statuses and parsed.get("status") not in valid_statuses:
            last_error = f"status invalido: {parsed.get('status')}"
            continue
        parsed["raw_response_tail"] = last_response[-2000:]
        return parsed
    raise RuntimeError(f"Ollama no devolvio JSON valido ({last_error}): {last_response[-1000:]}")
