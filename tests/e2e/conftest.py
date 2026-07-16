from __future__ import annotations

import html
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import urlopen

import pytest
from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from web.auth_security import hash_password


ROOT = Path(__file__).resolve().parents[2]
SCREENSHOTS_DIR = ROOT / "screenshots"
TRACES_DIR = ROOT / "traces"
VIDEOS_DIR = ROOT / "videos"
REPORT_DIR = ROOT / "playwright-report"
RESULTS_DIR = ROOT / "test-results"

for directory in (SCREENSHOTS_DIR, TRACES_DIR, VIDEOS_DIR, REPORT_DIR, RESULTS_DIR):
    directory.mkdir(parents=True, exist_ok=True)


_SERVER_PORT_RE = re.compile(r"E2E_PORT:(\d+)")
_BROWSER_PORT_RE = re.compile(r"DevTools listening on ws://127\.0\.0\.1:(\d+)/")


LEAFLET_STUB = r"""
(function () {
  if (window.L) return;
  function noop() { return this; }
  function point(lat, lng) {
    return { lat: Number(lat), lng: Number(lng) };
  }
  function map() {
    return {
      addLayer: noop,
      removeLayer: noop,
      setView: noop,
      panTo: noop,
      invalidateSize: noop,
      remove: noop,
      on: noop,
      fitBounds: noop,
      getZoom: function () { return 16; },
    };
  }
  function tileLayer() {
    return {
      addTo: noop,
      remove: noop,
    };
  }
  function marker(latlng) {
    var current = Array.isArray(latlng) ? point(latlng[0], latlng[1]) : point(0, 0);
    return {
      addTo: noop,
      on: noop,
      setLatLng: function (next) {
        if (Array.isArray(next)) {
          current = point(next[0], next[1]);
        }
        return this;
      },
      getLatLng: function () {
        return current;
      },
      dragging: {
        enable: noop,
        disable: noop,
      },
    };
  }
  window.L = {
    map: map,
    tileLayer: tileLayer,
    marker: marker,
    control: {
      zoom: function () {
        return { addTo: noop };
      },
    },
    latLng: point,
    latLngBounds: function () {
      return {};
    },
    divIcon: function () {
      return {};
    },
    icon: function () {
      return {};
    },
  };
})();
""".strip()


def _bool_env(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "si", "sí", "on"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _future_iso(days: int = 30) -> str:
    return (_utc_now() + timedelta(days=days)).isoformat()


def _sanitize_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)([?&](?:token|activar_token|portal_token|firma_inmo|access_token|password|passwd)=)([^&\s]+)", r"\1***", text)
    text = re.sub(r"(?i)(\b(?:token|activar_token|portal_token|firma_inmo|access_token|password|passwd)\s*[:=]\s*)([^\s,;]+)", r"\1***", text)
    text = re.sub(r"(?i)(\bcrm_session\s*=\s*)([^\s;]+)", r"\1***", text)
    return text


def _sanitize_filename(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip())
    text = text.strip("-_.")
    return text or "test"


def _strip_query(url: str) -> str:
    parsed = urlparse(str(url or ""))
    query_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        query_items.append(
            (
                key,
                "***"
                if key.lower() in {"token", "activar_token", "portal_token", "firma_inmo", "access_token", "password", "passwd"}
                else value,
            )
        )
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query_items), parsed.fragment))


def _is_critical_response(response) -> bool:
    try:
        resource_type = str(response.request.resource_type or "")
    except Exception:
        resource_type = ""
    try:
        parsed = urlparse(response.url)
        basename = Path(parsed.path).name
    except Exception:
        basename = ""
    if resource_type == "document":
        return True
    return basename in {
        "index.html",
        "manifest.webmanifest",
        "app_shared.js",
        "app-auth.js",
        "app-routing.js",
        "app.js",
        "ui-foundation.js",
        "icon-192.png",
        "icon-512.png",
        "apple-touch-icon-180.png",
        "apple-touch-icon-167.png",
        "apple-touch-icon-152.png",
        "apple-touch-icon-120.png",
        "verifika2_wordmark_dark.svg",
    }


def _table_info(conn: sqlite3.Connection, table: str) -> dict[str, dict[str, Any]]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not rows:
        raise RuntimeError(f"La tabla {table} no existe en la base temporal.")
    info: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row[1])
        info[name] = {
            "notnull": bool(row[3]),
            "default": row[4],
        }
    return info


def _insert_row(conn: sqlite3.Connection, table: str, data: dict[str, Any]) -> None:
    info = _table_info(conn, table)
    payload = {key: value for key, value in data.items() if key in info}
    missing = [
        name
        for name, meta in info.items()
        if meta["notnull"] and meta["default"] is None and name not in payload
    ]
    if missing:
        raise RuntimeError(f"Faltan columnas obligatorias en {table}: {', '.join(sorted(missing))}")
    if not payload:
        raise RuntimeError(f"No hay columnas compatibles para insertar en {table}.")
    columns = ", ".join(payload.keys())
    placeholders = ", ".join(["?"] * len(payload))
    conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
        list(payload.values()),
    )


def _connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _bootstrap_minimal_schema(db_path: Path) -> None:
    conn = _connect_db(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS empresas (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              activo INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS clientes (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              nif TEXT,
              telefono TEXT,
              email TEXT
            );
            CREATE TABLE IF NOT EXISTS acciones (
              id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS inmueble_docs (
              id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS inmuebles (
              id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS captaciones (
              id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS gestoria (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
              fecha TEXT,
              cuota REAL,
              precio REAL,
              tipo TEXT,
              perfil TEXT,
              estado TEXT,
              fecha_baja TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS inversores (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS inversure_operaciones (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS seguros (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              tomador TEXT,
              compania TEXT,
              ramo TEXT,
              poliza_numero TEXT,
              prima_total REAL,
              comision REAL,
              porcentaje REAL,
              estado TEXT,
              fecha_efecto TEXT,
              fecha_vencimiento TEXT,
              poliza_url TEXT,
              poliza_key TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS seguros_renovaciones (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              poliza_id TEXT,
              poliza_key TEXT,
              fecha_vencimiento TEXT,
              estado TEXT,
              proxima_accion_fecha TEXT,
              ultimo_contacto_fecha TEXT,
              notas TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS auth_invites (
              token TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              expires_at TEXT,
              created_at TEXT NOT NULL,
              sent_at TEXT,
              used_at TEXT,
              revoked_at TEXT,
              notes TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


@dataclass
class E2EData:
    admin_username: str = "e2e_admin"
    admin_email: str = "e2e_admin@example.test"
    admin_password: str = "Playwright!23"
    normal_username: str = "e2e_user"
    normal_email: str = "e2e_user@example.test"
    normal_password: str = "Playwright!24"
    invite_username: str = "e2e_invited"
    invite_email: str = "e2e_invited@example.test"
    invite_password: str = "Playwright!25"
    invite_token: str = "e2e-public-invite-token"
    workspace_id: str = "ws-e2e-playwright"
    workspace_slug: str = "e2e-playwright"
    workspace_name: str = "Workspace Playwright E2E"
    company_id: str = "emp-e2e-playwright"
    company_name: str = "Empresa Playwright E2E"


@dataclass
class E2EApp:
    base_url: str
    db_path: Path
    ocr_db_path: Path
    uploads_dir: Path
    server_log_path: Path
    server_process: subprocess.Popen[str]
    data: E2EData = field(default_factory=E2EData)

    def url(self, path: str = "/", params: dict[str, str] | None = None, *, include_swcleared: bool = True) -> str:
        target = path if str(path or "").startswith("http") else f"{self.base_url}{path if str(path or '').startswith('/') else '/' + str(path or '')}"
        parsed = urlparse(target)
        query_items = list(parse_qsl(parsed.query, keep_blank_values=True))
        if params:
            query_items.extend([(str(key), str(value)) for key, value in params.items() if str(value).strip() != ""])
        if include_swcleared and not any(key == "swcleared" for key, _ in query_items):
            query_items.append(("swcleared", "1"))
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query_items), parsed.fragment))

    def goto(self, page: Page, path: str = "/", params: dict[str, str] | None = None, *, wait_until: str = "domcontentloaded") -> None:
        page.goto(self.url(path, params=params), wait_until=wait_until)

    def api_get(self, page: Page, path: str) -> tuple[int, Any]:
        payload = page.evaluate(
            """
            async (url) => {
              const res = await fetch(url, { cache: "no-store", credentials: "same-origin" });
              let body = null;
              try {
                body = await res.json();
              } catch {
                try {
                  body = await res.text();
                } catch {
                  body = null;
                }
              }
              return { status: res.status, body };
            }
            """,
            path,
        )
        return int(payload["status"]), payload["body"]

    def session_user(self, page: Page) -> Any:
        status, body = self.api_get(page, "/api/me")
        if status != 200:
            return None
        return (body or {}).get("user")

    def logout(self, page: Page) -> None:
        page.evaluate(
            """
            async () => {
              try {
                await fetch("/api/logout", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  credentials: "same-origin",
                  body: "{}",
                });
              } catch {}
            }
            """
        )

    def login(self, page: Page, username: str, password: str) -> None:
        self.goto(page, "/")
        page.locator("#authLoginForm").wait_for(state="visible")
        page.locator("#authLoginUser").fill(username)
        page.locator("#authLoginPass").fill(password)
        page.locator("#authLoginForm button[type='submit']").click()

    def seed_database(self) -> None:
        conn = _connect_db(self.db_path)
        try:
            now = _iso_now()
            password_hash = hash_password(self.data.admin_password)
            normal_hash = hash_password(self.data.normal_password)

            _insert_row(
                conn,
                "empresas",
                {
                    "id": self.data.company_id,
                    "nombre": self.data.company_name,
                    "razon_social": self.data.company_name,
                    "activo": 1,
                    "nif": "B12345678",
                    "direccion": "Calle Playwright 1",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            _insert_row(
                conn,
                "usuarios",
                {
                    "id": "user-e2e-admin",
                    "nombre": "Admin",
                    "apellido": "E2E",
                    "usuario": self.data.admin_username,
                    "email": self.data.admin_email,
                    "servicio": "Administración",
                    "rol": "Administrador",
                    "registro_horario_activo": 0,
                    "password_hash": password_hash,
                    "activo": 1,
                    "invite_token": None,
                    "invite_expires_at": None,
                    "invite_sent_at": None,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            _insert_row(
                conn,
                "usuarios",
                {
                    "id": "user-e2e-normal",
                    "nombre": "Usuario",
                    "apellido": "E2E",
                    "usuario": self.data.normal_username,
                    "email": self.data.normal_email,
                    "servicio": "Gestoria, Seguros",
                    "rol": "Miembro",
                    "registro_horario_activo": 0,
                    "password_hash": normal_hash,
                    "activo": 1,
                    "invite_token": None,
                    "invite_expires_at": None,
                    "invite_sent_at": None,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            _insert_row(
                conn,
                "usuarios",
                {
                    "id": "user-e2e-invite",
                    "nombre": "Invitado",
                    "apellido": "E2E",
                    "usuario": self.data.invite_username,
                    "email": self.data.invite_email,
                    "servicio": "Gestoria, Seguros",
                    "rol": "Miembro",
                    "registro_horario_activo": 0,
                    "password_hash": None,
                    "activo": 1,
                    "invite_token": self.data.invite_token,
                    "invite_expires_at": _future_iso(14),
                    "invite_sent_at": now,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            _insert_row(
                conn,
                "workspaces",
                {
                    "id": self.data.workspace_id,
                    "nombre": self.data.workspace_name,
                    "slug": self.data.workspace_slug,
                    "estado": "Activo",
                    "plan": "Enterprise",
                    "kind": "Directo",
                    "descripcion": "Workspace temporal de pruebas Playwright.",
                    "logo_url": "",
                    "primary_color": "#0B1D33",
                    "accent_color": "#F2C14E",
                    "kiosk_pin_hash": None,
                    "kiosk_pin_required": 0,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            _insert_row(
                conn,
                "workspace_empresas",
                {
                    "id": "workspace-company-link-e2e",
                    "workspace_id": self.data.workspace_id,
                    "empresa_id": self.data.company_id,
                    "rol": "operativa",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            _insert_row(
                conn,
                "workspace_companies",
                {
                    "id": "workspace-company-e2e",
                    "workspace_id": self.data.workspace_id,
                    "legacy_empresa_id": self.data.company_id,
                    "nombre": self.data.company_name,
                    "nif": "B12345678",
                    "direccion": "Calle Playwright 1",
                    "logo_url": "",
                    "primary_color": "#0B1D33",
                    "accent_color": "#F2C14E",
                    "activo": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            for idx, module in enumerate(
                (
                    ("gestoria", "Gestoría", "CRM"),
                    ("seguros", "Seguros", "CRM"),
                ),
                start=1,
            ):
                _insert_row(
                    conn,
                    "workspace_modulos",
                    {
                        "id": f"workspace-module-e2e-{idx}",
                        "workspace_id": self.data.workspace_id,
                        "modulo_key": module[0],
                        "modulo_nombre": module[1],
                        "categoria": module[2],
                        "enabled": 1,
                        "sort_order": idx,
                        "config_json": "{}",
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            _insert_row(
                conn,
                "workspace_miembros",
                {
                    "id": "workspace-member-admin-e2e",
                    "workspace_id": self.data.workspace_id,
                    "usuario_id": "user-e2e-admin",
                    "rol": "Owner",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            _insert_row(
                conn,
                "workspace_miembros",
                {
                    "id": "workspace-member-normal-e2e",
                    "workspace_id": self.data.workspace_id,
                    "usuario_id": "user-e2e-normal",
                    "rol": "Miembro",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            _insert_row(
                conn,
                "auth_invites",
                {
                    "token": self.data.invite_token,
                    "user_id": "user-e2e-invite",
                    "expires_at": _future_iso(14),
                    "created_at": now,
                    "sent_at": now,
                    "used_at": None,
                    "revoked_at": None,
                    "notes": "e2e",
                },
            )
            conn.execute(
                """
                UPDATE usuarios
                SET invite_token = ?, invite_expires_at = ?, invite_sent_at = ?, password_hash = NULL, updated_at = ?
                WHERE id = ?
                """,
                (self.data.invite_token, _future_iso(14), now, now, "user-e2e-invite"),
            )
            conn.commit()
        finally:
            conn.close()

    def stop(self) -> None:
        proc = self.server_process
        if proc.poll() is None:
            try:
                if hasattr(signal, "SIGTERM"):
                    proc.terminate()
                else:
                    proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=15)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=15)
                except Exception:
                    pass


@dataclass
class BrowserIssues:
    console: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    request_failures: list[str] = field(default_factory=list)
    critical_responses: list[str] = field(default_factory=list)
    all_responses: list[str] = field(default_factory=list)

    def on_console(self, message) -> None:
        self.console.append(f"[{message.type}] {_sanitize_text(message.text)}")

    def on_pageerror(self, error: Exception) -> None:
        self.page_errors.append(_sanitize_text(error))

    def on_requestfailed(self, request) -> None:
        failure_info: Any = None
        try:
            failure_attr = getattr(request, "failure", None)
            failure_info = failure_attr() if callable(failure_attr) else failure_attr
        except Exception:
            failure_info = None
        if isinstance(failure_info, dict):
            reason = str(failure_info.get("error_text") or failure_info.get("errorText") or "requestfailed")
        else:
            reason = str(failure_info or "requestfailed")
        if "aborted" in reason.lower() or "canceled" in reason.lower() or "cancelled" in reason.lower():
            return
        self.request_failures.append(f"{request.resource_type} {_sanitize_text(_strip_query(request.url))} :: {_sanitize_text(reason)}")

    def on_response(self, response) -> None:
        text = f"{response.status} {_sanitize_text(_strip_query(response.url))}"
        self.all_responses.append(text)
        if response.status >= 500:
            self.critical_responses.append(text)
            return
        if response.status == 404 and _is_critical_response(response):
            self.critical_responses.append(text)

    def has_failures(self) -> bool:
        return bool(self.page_errors or self.request_failures or self.critical_responses)

    def summary(self) -> str:
        parts: list[str] = []
        if self.page_errors:
            parts.append("pageerror: " + " | ".join(self.page_errors))
        if self.request_failures:
            parts.append("requestfailed: " + " | ".join(self.request_failures))
        if self.critical_responses:
            parts.append("critical response: " + " | ".join(self.critical_responses))
        return "\n".join(parts).strip()


def _wait_until_server_ready(base_url: str, server_log_path: Path, timeout_seconds: int = 120) -> None:
    deadline = time.time() + timeout_seconds
    last_error = ""
    health_url = f"{base_url}/api/health"
    while time.time() < deadline:
        try:
            with urlopen(health_url, timeout=5) as response:
                status = getattr(response, "status", response.getcode())
                if int(status) == 200:
                    return
                last_error = f"HTTP {status}"
        except HTTPError as exc:
            if exc.code == 200:
                return
            last_error = f"HTTP {exc.code}"
        except URLError as exc:
            last_error = str(exc.reason or exc)
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.5)
    log_tail = ""
    try:
        log_tail = server_log_path.read_text(encoding="utf-8", errors="replace")[-8000:]
    except Exception:
        log_tail = ""
    raise RuntimeError(
        f"El servidor Playwright no estuvo listo a tiempo. Ultimo error: {last_error}\n"
        f"Log del servidor:\n{log_tail}"
    )


def _wait_for_log_port(log_path: Path, pattern: re.Pattern[str], timeout_seconds: int, label: str) -> int:
    deadline = time.time() + timeout_seconds
    last_text = ""
    while time.time() < deadline:
        try:
            last_text = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            last_text = ""
        match = pattern.search(last_text)
        if match:
            return int(match.group(1))
        time.sleep(0.25)
    tail = ""
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-8000:]
    except Exception:
        tail = last_text[-8000:]
    raise RuntimeError(f"No se pudo determinar el puerto de {label} a tiempo.\nLog:\n{tail}")


@dataclass
class BrowserLaunch:
    browser: Browser
    home_dir: Path


def _browser_executable_candidates(playwright: Playwright | None = None) -> list[str]:
    candidates: list[str] = []
    env_candidate = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "").strip()
    if env_candidate:
        candidates.append(env_candidate)
    if playwright is not None:
        try:
            managed_candidate = str(getattr(playwright.chromium, "executable_path", "") or "").strip()
        except Exception:
            managed_candidate = ""
        if managed_candidate:
            candidates.append(managed_candidate)
    candidates.extend(
        [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    )
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    unique_candidates: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique_candidates:
            unique_candidates.append(candidate)
    return unique_candidates


def _resolve_browser_executable(playwright: Playwright) -> str:
    tried: list[str] = []
    for candidate in _browser_executable_candidates(playwright):
        tried.append(candidate)
        if Path(candidate).exists():
            return candidate
    raise RuntimeError("No se encontró un binario de Chromium/Chrome utilizable.\n" + "\n".join(tried or ["- ninguno"]))


def _wait_until_browser_ready(endpoint_url: str, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    last_error = ""
    version_url = endpoint_url.rstrip("/") + "/json/version"
    while time.time() < deadline:
        try:
            with urlopen(version_url, timeout=5) as response:
                status = getattr(response, "status", response.getcode())
                if int(status) == 200:
                    return
                last_error = f"HTTP {status}"
        except HTTPError as exc:
            if exc.code == 200:
                return
            last_error = f"HTTP {exc.code}"
        except URLError as exc:
            last_error = str(exc.reason or exc)
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"El navegador no respondió en tiempo. Ultimo error: {last_error}")


def _terminate_browser_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        if hasattr(signal, "SIGTERM"):
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        proc.wait(timeout=15)
    except Exception:
        try:
            if hasattr(signal, "SIGKILL"):
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.wait(timeout=15)
        except Exception:
            pass


def _launch_browser(playwright: Playwright, headless: bool) -> Browser:
    home_dir = Path(tempfile.mkdtemp(prefix="playwright-home-"))
    launch_args = [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--disable-breakpad",
        "--disable-crash-reporter",
        "--disable-crashpad-for-testing",
        "--disable-client-side-phishing-detection",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-popup-blocking",
        "--disable-renderer-backgrounding",
        "--mute-audio",
    ]
    if _bool_env("PLAYWRIGHT_NO_SANDBOX", False):
        launch_args.append("--no-sandbox")
    executable_path = _resolve_browser_executable(playwright)
    launch_env = os.environ.copy()
    launch_env.update(
        {
            "HOME": str(home_dir),
            "XDG_CONFIG_HOME": str(home_dir / ".config"),
            "XDG_CACHE_HOME": str(home_dir / ".cache"),
        }
    )
    launch_kwargs: dict[str, Any] = {
        "headless": headless,
        "args": launch_args,
        "env": launch_env,
    }
    if executable_path:
        launch_kwargs["executable_path"] = executable_path
    browser = playwright.chromium.launch(**launch_kwargs)
    return BrowserLaunch(browser=browser, home_dir=home_dir)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _route_external_request(route) -> None:
    url = str(route.request.url or "")
    if "fonts.googleapis.com" in url:
        route.fulfill(status=200, content_type="text/css", body="/* test font css */")
        return
    if "unpkg.com/leaflet@1.9.4/dist/leaflet.js" in url:
        route.fulfill(status=200, content_type="text/javascript", body=LEAFLET_STUB)
        return
    if "unpkg.com/leaflet@1.9.4/dist/leaflet.css" in url:
        route.fulfill(status=200, content_type="text/css", body="/* leaflet css */")
        return
    if "www.google.com/maps" in url:
        route.fulfill(status=200, content_type="text/html", body="<!doctype html><html><body></body></html>")
        return
    if "fonts.gstatic.com" in url or "tile.openstreetmap.org" in url or "server.arcgisonline.com" in url:
        route.fulfill(status=204)
        return
    route.continue_()


RESULTS: list[dict[str, Any]] = []


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture(scope="session")
def playwright_instance() -> Playwright:
    instance = sync_playwright().start()
    yield instance
    instance.stop()


@pytest.fixture(scope="session")
def browser(playwright_instance: Playwright) -> Browser:
    launch = _launch_browser(playwright_instance, _bool_env("PLAYWRIGHT_HEADLESS", True))
    try:
        yield launch.browser
    finally:
        try:
            launch.browser.close()
        except Exception:
            pass
        try:
            shutil.rmtree(launch.home_dir, ignore_errors=True)
        except Exception:
            pass


@pytest.fixture
def e2e_app(tmp_path) -> E2EApp:
    data = E2EData()
    db_path = tmp_path / "e2e.sqlite"
    ocr_db_path = tmp_path / "ocr.sqlite"
    uploads_dir = tmp_path / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    db_path.touch(exist_ok=True)
    ocr_db_path.touch(exist_ok=True)
    _bootstrap_minimal_schema(db_path)

    env = os.environ.copy()
    env.update(
        {
            "APP_DB_BACKEND": "sqlite",
            "DB_PATH": str(db_path),
            "OCR_DB_PATH": str(ocr_db_path),
            "UPLOADS_DIR": str(uploads_dir),
            "APP_SUPERADMIN_USERNAMES": data.admin_username,
            "APP_SUPERADMIN_ENFORCE": "0",
            "WORKSPACE_TIME_SWEEP_ENABLED": "0",
            "LEGAL_RADAR_AUTO_SCAN_ENABLED": "0",
            "LEGAL_RADAR_AUTO_IMPORT_ENABLED": "0",
            "APP_PERFORMANCE_LOGGING": "0",
            "APP_HTTP_COMPRESSION": "1",
            "APP_WORKSPACE_MEMBERSHIP_ENFORCE": "0",
            "APP_S3_SCOPE_ENFORCE": "0",
            "OCR_WORKERS": "1",
        }
    )
    server_log_path = RESULTS_DIR / f"server-{os.getpid()}-{int(time.time() * 1000)}.log"
    server_log = server_log_path.open("w", encoding="utf-8")
    server_script = (
        "import sys\n"
        "from web import server as app_server\n"
        "\n"
        "class RecordingThreadingHTTPServer(app_server.ThreadingHTTPServer):\n"
        "    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):\n"
        "        super().__init__(server_address, RequestHandlerClass, bind_and_activate=bind_and_activate)\n"
        "        print(f'E2E_PORT:{self.server_address[1]}', flush=True)\n"
        "\n"
        "app_server.ThreadingHTTPServer = RecordingThreadingHTTPServer\n"
        "sys.argv = [\n"
        "    'web.server',\n"
        "    '--host', '127.0.0.1',\n"
        "    '--port', '0',\n"
        "    '--db', " + json.dumps(str(db_path)) + ",\n"
        "    '--ocr-db', " + json.dumps(str(ocr_db_path)) + ",\n"
        "    '--ocr-workers', '1',\n"
        "]\n"
        "app_server.main()\n"
    )
    server_process = subprocess.Popen(
        [sys.executable, "-c", server_script],
        cwd=str(ROOT),
        env=env,
        stdout=server_log,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    app: E2EApp | None = None
    try:
        port = _wait_for_log_port(server_log_path, _SERVER_PORT_RE, timeout_seconds=60, label="servidor E2E")
        base_url = f"http://127.0.0.1:{port}"
        app = E2EApp(
            base_url=base_url,
            db_path=db_path,
            ocr_db_path=ocr_db_path,
            uploads_dir=uploads_dir,
            server_log_path=server_log_path,
            server_process=server_process,
            data=data,
        )
        _wait_until_server_ready(base_url, server_log_path)
        app.seed_database()
        yield app
    finally:
        try:
            if app is not None:
                app.stop()
            else:
                if server_process.poll() is None:
                    try:
                        if hasattr(signal, "SIGTERM"):
                            os.killpg(server_process.pid, signal.SIGTERM)
                        else:
                            server_process.terminate()
                    except Exception:
                        try:
                            server_process.terminate()
                        except Exception:
                            pass
                    try:
                        server_process.wait(timeout=15)
                    except Exception:
                        try:
                            server_process.kill()
                        except Exception:
                            pass
        finally:
            try:
                server_log.close()
            except Exception:
                pass


@pytest.fixture
def tracked_page(browser: Browser, e2e_app: E2EApp, request: pytest.FixtureRequest):
    context = browser.new_context(
        base_url=e2e_app.base_url,
        viewport={"width": 1440, "height": 1200},
        locale="es-ES",
        timezone_id="Europe/Madrid",
        color_scheme="light",
    )
    context.set_default_timeout(15000)
    context.set_default_navigation_timeout(30000)
    context.tracing.start(screenshots=True, snapshots=True, sources=True)

    issues = BrowserIssues()
    context.on("page", lambda page: page.on("console", issues.on_console))
    context.on("page", lambda page: page.on("pageerror", issues.on_pageerror))
    context.on("page", lambda page: page.on("requestfailed", issues.on_requestfailed))
    context.on("page", lambda page: page.on("response", issues.on_response))

    context.route("**/*", _route_external_request)

    page = context.new_page()
    page.add_init_script(
        """
        (() => {
          try {
            window.__PLAYWRIGHT_E2E__ = true;
          } catch {}
        })();
        """
    )

    started = time.perf_counter()
    yield page

    failed_call = bool(getattr(request.node, "rep_call", None) and request.node.rep_call.failed)
    failed_setup = bool(getattr(request.node, "rep_setup", None) and request.node.rep_setup.failed)
    failed_teardown = bool(getattr(request.node, "rep_teardown", None) and request.node.rep_teardown.failed)
    failed = failed_call or failed_setup or failed_teardown or issues.has_failures()
    final_url = _sanitize_text(page.url)
    if failed:
        safe_name = _sanitize_filename(request.node.name)
        screenshot_path = SCREENSHOTS_DIR / f"{safe_name}.png"
        trace_path = TRACES_DIR / f"{safe_name}.zip"
        log_path = RESULTS_DIR / f"{safe_name}.log"
        report_path = RESULTS_DIR / f"{safe_name}.json"
        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            pass
        try:
            context.tracing.stop(path=str(trace_path))
        except Exception:
            pass
        payload = {
            "nodeid": request.node.nodeid,
            "failed": True,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "page_errors": issues.page_errors,
            "request_failures": issues.request_failures,
            "critical_responses": issues.critical_responses,
            "console": issues.console,
            "url": final_url,
            "artifacts": {
                "screenshot": str(screenshot_path.relative_to(ROOT)) if screenshot_path.exists() else "",
                "trace": str(trace_path.relative_to(ROOT)) if trace_path.exists() else "",
            },
        }
        page_errors = [f"- {item}" for item in issues.page_errors] or ["- none"]
        request_failures = [f"- {item}" for item in issues.request_failures] or ["- none"]
        critical_responses = [f"- {item}" for item in issues.critical_responses] or ["- none"]
        console_lines = [f"- {item}" for item in issues.console] or ["- none"]
        log_text = "\n".join(
            [
                f"nodeid: {request.node.nodeid}",
                f"url: {final_url}",
                "",
                "page_errors:",
                *page_errors,
                "",
                "request_failures:",
                *request_failures,
                "",
                "critical_responses:",
                *critical_responses,
                "",
                "console:",
                *console_lines,
            ]
        )
        log_path.write_text(log_text, encoding="utf-8")
        _write_json(report_path, payload)
    else:
        try:
            context.tracing.stop()
        except Exception:
            pass

    try:
        context.close()
    finally:
        RESULTS.append(
            {
                "nodeid": request.node.nodeid,
                "status": "failed" if failed else "passed",
                "duration_seconds": round(time.perf_counter() - started, 3),
                "page_errors": issues.page_errors,
                "request_failures": issues.request_failures,
                "critical_responses": issues.critical_responses,
                "console": issues.console[:20],
                "screenshot": str((SCREENSHOTS_DIR / f"{_sanitize_filename(request.node.name)}.png").relative_to(ROOT))
                if (SCREENSHOTS_DIR / f"{_sanitize_filename(request.node.name)}.png").exists()
                else "",
                "trace": str((TRACES_DIR / f"{_sanitize_filename(request.node.name)}.zip").relative_to(ROOT))
                if (TRACES_DIR / f"{_sanitize_filename(request.node.name)}.zip").exists()
                else "",
                "url": final_url,
            }
        )
    if failed and issues.has_failures() and not failed_call and not failed_setup and not failed_teardown:
        raise AssertionError(issues.summary() or "Browser issues detected.")


@pytest.fixture
def page(tracked_page: Page) -> Page:
    return tracked_page


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    rows = []
    for item in RESULTS:
        rows.append(
            f"""
            <tr class="{html.escape(item['status'])}">
              <td>{html.escape(item['nodeid'])}</td>
              <td>{html.escape(item['status'])}</td>
              <td>{html.escape(str(item['duration_seconds']))}</td>
              <td>{html.escape(item['url'])}</td>
              <td>{html.escape(item['screenshot'] or '-')}</td>
              <td>{html.escape(item['trace'] or '-')}</td>
            </tr>
            """
        )
    summary = {
        "total": len(RESULTS),
        "passed": sum(1 for item in RESULTS if item["status"] == "passed"),
        "failed": sum(1 for item in RESULTS if item["status"] == "failed"),
    }
    html_report = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Playwright Report</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #0b1220;
      --panel: #111827;
      --text: #e5e7eb;
      --muted: #94a3b8;
      --ok: #16a34a;
      --bad: #dc2626;
      --line: rgba(148, 163, 184, 0.22);
    }}
    body {{
      margin: 0;
      padding: 32px;
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      background: linear-gradient(180deg, var(--bg), #020617);
      color: var(--text);
    }}
    .card {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(17, 24, 39, 0.92);
      box-shadow: 0 24px 80px rgba(15, 23, 42, 0.4);
    }}
    h1, h2 {{ margin: 0 0 12px; }}
    p {{ color: var(--muted); }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 20px;
      font-size: 14px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      text-align: left;
      vertical-align: top;
    }}
    tr.passed td {{ color: #d1fae5; }}
    tr.failed td {{ color: #fecaca; }}
    code, a {{ color: #fbbf24; word-break: break-word; }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin: 20px 0;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 16px;
      background: rgba(15, 23, 42, 0.65);
    }}
    .metric strong {{
      display: block;
      font-size: 28px;
      margin-top: 6px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Playwright Report</h1>
    <p>Resultados de la suite E2E de frontend.</p>
    <div class="summary">
      <div class="metric"><span>Total</span><strong>{summary["total"]}</strong></div>
      <div class="metric"><span>Pass</span><strong style="color: var(--ok);">{summary["passed"]}</strong></div>
      <div class="metric"><span>Fail</span><strong style="color: var(--bad);">{summary["failed"]}</strong></div>
    </div>
    <table>
      <thead>
        <tr>
          <th>Test</th>
          <th>Status</th>
          <th>Seconds</th>
          <th>URL</th>
          <th>Screenshot</th>
          <th>Trace</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows) if rows else '<tr><td colspan="6" class="muted">No hay resultados.</td></tr>'}
      </tbody>
    </table>
  </div>
</body>
</html>
"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "index.html").write_text(html_report, encoding="utf-8")
    _write_json(REPORT_DIR / "results.json", {"summary": summary, "results": RESULTS})
