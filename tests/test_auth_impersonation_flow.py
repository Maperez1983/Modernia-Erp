import sqlite3
import inspect
import sys
import tempfile
import types
import unittest
from pathlib import Path

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

from web.server import (
    AUTH_SESSIONS,
    AUTH_SESSIONS_LOCK,
    build_impersonated_auth_session,
    create_auth_session,
    delete_auth_session,
    ensure_auth_impersonation_audit_table,
    finish_impersonation_session,
    get_auth_session,
)


class AuthImpersonationFlowTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.tokens = []
        with AUTH_SESSIONS_LOCK:
            AUTH_SESSIONS.clear()

    def tearDown(self):
        for token in self.tokens:
            try:
                delete_auth_session(token)
            except Exception:
                pass
        with AUTH_SESSIONS_LOCK:
            AUTH_SESSIONS.clear()
        self.conn.close()

    def test_build_impersonated_auth_session_creates_audit_and_keeps_original_token(self):
        actor = create_auth_session(
            {
                "id": "admin-1",
                "usuario": "admin.user",
                "nombre": "Admin",
                "apellido": "User",
                "rol": "Administrador",
                "email": "admin@example.com",
                "servicio": "Gestoría",
            }
        )
        self.tokens.append(str(actor.get("token") or "").strip())
        target = {
            "id": "user-1",
            "usuario": "normal.user",
            "nombre": "Normal",
            "apellido": "User",
            "rol": "Lectura",
            "email": "normal@example.com",
            "servicio": "Gestoría",
        }
        session = build_impersonated_auth_session(
            self.conn,
            actor,
            str(actor.get("token") or "").strip(),
            target,
            workspace_id="ws-1",
            reason="Diagnóstico operativo",
        )
        self.tokens.append(str(session.get("token") or "").strip())
        self.assertTrue(bool(session.get("impersonating")))
        self.assertEqual(str(session.get("impersonated_by_usuario") or "").strip(), "admin.user")
        self.assertEqual(str(session.get("original_token") or "").strip(), str(actor.get("token") or "").strip())
        audit_row = self.conn.execute(
            "SELECT actor_usuario, target_usuario, workspace_id, status FROM auth_impersonation_audit WHERE id = ?",
            (str(session.get("impersonation_audit_id") or "").strip(),),
        ).fetchone()
        self.assertEqual(str(audit_row["actor_usuario"] or "").strip(), "admin.user")
        self.assertEqual(str(audit_row["target_usuario"] or "").strip(), "normal.user")
        self.assertEqual(str(audit_row["workspace_id"] or "").strip(), "ws-1")
        self.assertEqual(str(audit_row["status"] or "").strip(), "active")

    def test_finish_impersonation_session_restores_original_session(self):
        actor = create_auth_session(
            {
                "id": "admin-1",
                "usuario": "admin.user",
                "nombre": "Admin",
                "apellido": "User",
                "rol": "Administrador",
                "email": "admin@example.com",
                "servicio": "Gestoría",
            }
        )
        self.tokens.append(str(actor.get("token") or "").strip())
        ensure_auth_impersonation_audit_table(self.conn)
        session = build_impersonated_auth_session(
            self.conn,
            actor,
            str(actor.get("token") or "").strip(),
            {
                "id": "user-1",
                "usuario": "normal.user",
                "nombre": "Normal",
                "apellido": "User",
                "rol": "Lectura",
                "email": "normal@example.com",
                "servicio": "Gestoría",
            },
            workspace_id="ws-1",
            reason="Diagnóstico operativo",
        )
        self.tokens.append(str(session.get("token") or "").strip())
        restored = finish_impersonation_session(self.conn, session)
        self.assertIsNotNone(restored)
        self.assertEqual(str(restored.get("token") or "").strip(), str(actor.get("token") or "").strip())
        self.assertIsNone(get_auth_session(str(session.get("token") or "").strip()))
        audit_row = self.conn.execute(
            "SELECT status, ended_at FROM auth_impersonation_audit WHERE id = ?",
            (str(session.get("impersonation_audit_id") or "").strip(),),
        ).fetchone()
        self.assertEqual(str(audit_row["status"] or "").strip(), "ended")
        self.assertTrue(str(audit_row["ended_at"] or "").strip())

    def test_impersonation_endpoints_are_in_post_allowlist(self):
        from web import server as server_mod

        source = inspect.getsource(server_mod.Handler._do_POST)
        self.assertIn('"/api/auth_impersonate_user"', source)
        self.assertIn('"/api/auth_stop_impersonation"', source)
        self.assertIn('"/api/auth_request_access_recovery"', source)
        self.assertIn('"/api/auth_request_access_help"', source)


if __name__ == "__main__":
    unittest.main()
