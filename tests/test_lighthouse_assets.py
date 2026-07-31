from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_lighthouse_shell_assets_are_consistent() -> None:
    index_html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "web" / "manifest.webmanifest").read_text(encoding="utf-8"))
    sw_js = (ROOT / "web" / "sw.js").read_text(encoding="utf-8")
    server_py = (ROOT / "web" / "server.py").read_text(encoding="utf-8")

    assert '<meta name="description"' in index_html
    assert "verifika2_wordmark_dark.svg" in index_html
    assert "verifika2_wordmark_traced_dark.svg" not in app_js
    assert 'manifest.webmanifest?v=18' in index_html
    assert 'sw.js?v=383' in index_html

    assert 'CURRENT_ICON_VERSION = 28' in server_py
    assert 'manifest.webmanifest?v=18' in sw_js
    assert '/icons/ios/v28/icon-192.png' in sw_js
    assert '/icons/ios/v28/icon-512.png' in sw_js

    assert manifest["name"] == "Verifika² · CRM"
    assert manifest["short_name"] == "Verifika²"
    assert manifest["start_url"] == "/?source=pwa"
    assert manifest["display"] == "standalone"

    for icon in manifest["icons"]:
        src = str(icon.get("src") or "")
        assert src.startswith("/icons/ios/v28/")
        assert (ROOT / "web" / src.lstrip("/")).exists()


def test_service_worker_shell_matches_index_asset_versions() -> None:
    """El shell precacheado tiene que pedir los mismos bundles que `index.html`.

    Cuando se desfasa, el SW sirve una versión distinta de la que carga la página:
    eso es lo que dejó cachés rotas y obligó a desactivarlo en producción.
    """
    index_html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    sw_js = (ROOT / "web" / "sw.js").read_text(encoding="utf-8")

    shell_block = re.search(r"const SHELL_URLS = \[(.*?)\];", sw_js, re.S)
    assert shell_block, "No se encontró SHELL_URLS en web/sw.js"

    versioned = re.findall(r'"/([A-Za-z0-9_.-]+)\?v=(\d+)"', shell_block.group(1))
    assert versioned, "SHELL_URLS no tiene ningún asset versionado"

    for filename, sw_version in versioned:
        index_versions = set(
            re.findall(rf'{re.escape(filename)}\?v=(\d+)', index_html)
        )
        assert index_versions, f"{filename} no aparece versionado en index.html"
        assert index_versions == {sw_version}, (
            f"sw.js precachea {filename}?v={sw_version} pero index.html pide "
            f"{sorted(index_versions)}"
        )


def test_service_worker_shell_urls_exist_on_disk() -> None:
    """Todo lo que precachea el SW tiene que existir.

    `install` cachea la lista entera; si un recurso no está, la instalación falla
    y el service worker no llega a activarse nunca.
    """
    sw_js = (ROOT / "web" / "sw.js").read_text(encoding="utf-8")

    shell_block = re.search(r"const SHELL_URLS = \[(.*?)\];", sw_js, re.S)
    assert shell_block, "No se encontró SHELL_URLS en web/sw.js"

    missing = []
    for entry in re.findall(r'"([^"]+)"', shell_block.group(1)):
        path = entry.split("?", 1)[0]
        if path == "/":
            path = "/index.html"
        relative = path.lstrip("/")
        # La SPA vive en `web/` pero `/assets/` se sirve desde la raíz del repo.
        if not ((ROOT / "web" / relative).exists() or (ROOT / relative).exists()):
            missing.append(entry)

    assert not missing, f"SHELL_URLS apunta a recursos que no existen: {missing}"
