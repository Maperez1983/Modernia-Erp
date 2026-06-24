import inspect
import json
import sqlite3
import subprocess
import sys
import types
import unittest
import uuid

try:
    import PIL  # noqa: F401
except Exception:
    if "PIL" not in sys.modules:
        pil_stub = types.ModuleType("PIL")
        pil_stub.Image = object()
        pil_stub.ImageDraw = object()
        pil_stub.ImageEnhance = object()
        pil_stub.ImageFilter = object()
        pil_stub.ImageFont = object()
        pil_stub.ImageOps = object()
        sys.modules["PIL"] = pil_stub

from web import server as server_mod
from web.server import (
    AUTH_SESSIONS,
    AUTH_SESSIONS_LOCK,
    OLLANA_SYSTEM_STATE,
    describe_ollana_system_session,
    ensure_ollana_browser_runtime,
    ensure_ollana_system_session,
    ensure_usuarios_schema,
    hash_password,
    run_ollana_browser_review,
)


class OllanaSystemSessionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_usuarios_schema(self.conn)
        self.user_id = f"ollana-{uuid.uuid4().hex}"
        self.login = f"ollana.{uuid.uuid4().hex[:8]}"
        self.conn.execute(
            """
            INSERT INTO usuarios (
                id, nombre, apellido, usuario, email, servicio, rol, password_hash, activo, created_at, updated_at
            ) VALUES (
                ?, 'Ollana', 'System', ?, 'ollana@example.com',
                'Gestoría, Financiaciones', 'Administrador', ?, 1, datetime('now'), datetime('now')
            )
            """,
            (self.user_id, self.login, hash_password("SecretPass!123")),
        )
        self.conn.commit()
        self._orig_enabled = server_mod.OLLANA_SYSTEM_ENABLED
        self._orig_login = server_mod.OLLANA_SYSTEM_LOGIN
        self._orig_password = server_mod.OLLANA_SYSTEM_PASSWORD
        server_mod.OLLANA_SYSTEM_ENABLED = True
        server_mod.OLLANA_SYSTEM_LOGIN = self.login
        server_mod.OLLANA_SYSTEM_PASSWORD = "SecretPass!123"
        with AUTH_SESSIONS_LOCK:
            AUTH_SESSIONS.clear()
        OLLANA_SYSTEM_STATE.update(
            {
                "last_attempt_at": 0.0,
                "last_error": "",
                "last_token": "",
                "last_user_id": "",
                "last_usuario": "",
                "last_expires_at": 0.0,
            }
        )

    def tearDown(self):
        server_mod.OLLANA_SYSTEM_ENABLED = self._orig_enabled
        server_mod.OLLANA_SYSTEM_LOGIN = self._orig_login
        server_mod.OLLANA_SYSTEM_PASSWORD = self._orig_password
        with AUTH_SESSIONS_LOCK:
            AUTH_SESSIONS.clear()
        self.conn.close()

    def test_ensure_ollana_system_session_creates_and_reuses_technical_session(self):
        first = ensure_ollana_system_session(conn=self.conn)
        self.assertTrue(first["ok"])
        self.assertFalse(first["reused"])
        self.assertEqual(str((first.get("session") or {}).get("usuario") or ""), self.login)
        self.assertEqual(str((first.get("session") or {}).get("session_kind") or ""), "technical_base")
        self.assertEqual(str((first.get("session") or {}).get("session_label") or ""), "ollana_system")

        second = ensure_ollana_system_session(conn=self.conn)
        self.assertTrue(second["ok"])
        self.assertTrue(second["reused"])
        self.assertEqual(
            str((second.get("session") or {}).get("token") or ""),
            str((first.get("session") or {}).get("token") or ""),
        )

    def test_describe_ollana_system_session_reports_active_state(self):
        ensure_ollana_system_session(conn=self.conn)
        status = describe_ollana_system_session(ensure=False, conn=self.conn)
        self.assertTrue(status["configured"])
        self.assertTrue(status["active"])
        self.assertEqual(str((status.get("session") or {}).get("usuario") or ""), self.login)

    def test_ollana_status_and_bootstrap_endpoints_are_exposed(self):
        get_source = inspect.getsource(server_mod.Handler._do_GET)
        post_source = inspect.getsource(server_mod.Handler._do_POST)
        self.assertIn('"/api/auth_ollana_status"', get_source)
        self.assertIn('"/api/auth_ollana_bootstrap"', post_source)
        self.assertIn('"/api/auth_ollana_browser_review"', post_source)

    def test_run_ollana_browser_review_skips_when_account_not_configured(self):
        server_mod.OLLANA_SYSTEM_ENABLED = False
        result = run_ollana_browser_review({"route": "/?nosw=1&swcleared=1"})
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("status"), "skipped")

    def test_run_ollana_browser_review_passes_web_search_env(self):
        old_runner = server_mod.run_subprocess
        captured = {}

        def fake_run_subprocess(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            captured["env"] = dict(kwargs.get("env") or {})
            payload = {
                "ok": True,
                "status": "passed",
                "task": "web_search",
                "search": {"ok": True, "query": "alquiler turístico", "results": [{"title": "BOE", "url": "https://boe.es"}]},
            }
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        try:
            server_mod.run_subprocess = fake_run_subprocess
            result = run_ollana_browser_review({"task": "web_search", "query": "alquiler turístico", "provider": "bing"})
            self.assertTrue(result["ok"])
            self.assertEqual(result.get("task"), "web_search")
            self.assertEqual(captured["env"]["OLLANA_BROWSER_TASK"], "web_search")
            self.assertEqual(captured["env"]["OLLANA_BROWSER_SEARCH_QUERY"], "alquiler turístico")
            self.assertEqual(captured["env"]["OLLANA_BROWSER_SEARCH_PROVIDER"], "bing")
        finally:
            server_mod.run_subprocess = old_runner

    def test_ensure_ollana_browser_runtime_marks_ready_after_install(self):
        old_runner = server_mod.run_subprocess
        old_find_spec = server_mod.importlib.util.find_spec
        calls = []

        def fake_run_subprocess(cmd, **kwargs):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        try:
            server_mod.run_subprocess = fake_run_subprocess
            server_mod.importlib.util.find_spec = lambda name: object() if name == "playwright" else None
            result = ensure_ollana_browser_runtime()
            self.assertTrue(result["ok"])
            self.assertTrue(any(cmd[:3] == [sys.executable or "python3", "-m", "playwright"] for cmd in calls))
            status = describe_ollana_system_session(ensure=False, conn=self.conn)
            self.assertTrue(status["browser_runtime"]["ready"])
        finally:
            server_mod.run_subprocess = old_runner
            server_mod.importlib.util.find_spec = old_find_spec


if __name__ == "__main__":
    unittest.main()
