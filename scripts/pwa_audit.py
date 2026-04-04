#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def extract_const(pattern: str, text: str, label: str) -> str:
    m = re.search(pattern, text)
    if not m:
        raise ValueError(f"No se encontró {label}.")
    return str(m.group(1))


def assert_icon(path: Path, size: tuple[int, int]) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Falta icono: {path}")
    img = Image.open(path)
    if img.size != size:
        raise ValueError(f"Icono {path} tamaño {img.size}, esperado {size}.")


def main() -> int:
    sw_text = read_text(WEB / "sw.js")
    app_text = read_text(WEB / "app.js")
    index_text = read_text(WEB / "index.html")

    cache_version = extract_const(r'const\s+CACHE_VERSION\s*=\s*"([^"]+)"', sw_text, "CACHE_VERSION en sw.js")
    app_sw_version = extract_const(r'const\s+APP_SW_VERSION\s*=\s*"([^"]+)"', app_text, "APP_SW_VERSION en app.js")
    register_version = extract_const(
        r'register\("/sw\.js\?v=([0-9]+)"\)', index_text, "versión de registro del SW en index.html"
    )

    if cache_version != app_sw_version:
        raise ValueError(f"Versiones no alineadas: sw.js={cache_version} app.js={app_sw_version}")
    if cache_version.lstrip("v") != register_version:
        raise ValueError(
            f"Registro de SW no alineado: index.html=v{register_version} sw.js={cache_version}"
        )

    manifest_path = WEB / "manifest.webmanifest"
    manifest = json.loads(read_text(manifest_path))
    if manifest.get("display") != "standalone":
        raise ValueError("El manifest no usa display=standalone.")
    icons = manifest.get("icons") or []
    if not icons:
        raise ValueError("El manifest no tiene iconos.")

    # Validar iconos del manifest.
    for icon in icons:
        src = str(icon.get("src") or "").strip()
        sizes = str(icon.get("sizes") or "").strip()
        if not src or not sizes:
            continue
        if not src.startswith("/icons/"):
            continue
        try:
            w_str, h_str = sizes.lower().split("x", 1)
            size = (int(w_str), int(h_str))
        except Exception:
            continue
        assert_icon(WEB / src.lstrip("/"), size)

    # Validar apple-touch-icon del HTML.
    m = re.search(r'<link\s+rel="apple-touch-icon"\s+href="([^"]+)"\s*/?>', index_text)
    if not m:
        raise ValueError("No se encontró link apple-touch-icon en index.html.")
    touch_href = str(m.group(1)).strip()
    if not touch_href.startswith("/icons/"):
        raise ValueError("apple-touch-icon no apunta a /icons/.")
    assert_icon(WEB / touch_href.lstrip("/"), (180, 180))

    print("OK: PWA/Icons/SW coherentes.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as err:
        print(f"ERROR: {err}", file=sys.stderr)
        raise SystemExit(1)
