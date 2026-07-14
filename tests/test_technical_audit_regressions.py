import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from web import server


class TechnicalAuditRegressionTests(unittest.TestCase):
    def test_fetch_workspace_company_ids_does_not_backfill_every_company(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE workspaces (
              id TEXT PRIMARY KEY,
              slug TEXT,
              nombre TEXT
            );
            CREATE TABLE empresas (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              activo INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE workspace_empresas (
              id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              empresa_id TEXT NOT NULL,
              rol TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE workspace_companies (
              workspace_id TEXT NOT NULL,
              legacy_empresa_id TEXT,
              activo INTEGER NOT NULL DEFAULT 1,
              nombre TEXT
            );
            CREATE TABLE workspace_registro_personal (
              id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              empresa_id TEXT,
              activo INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        conn.executemany(
            "INSERT INTO empresas (id, nombre, activo) VALUES (?, ?, 1)",
            [("emp-1", "Empresa Uno"), ("emp-2", "Empresa Dos")],
        )
        conn.execute("INSERT INTO workspaces (id, slug, nombre) VALUES (?, ?, ?)", ("ws-1", "ws-1", "Workspace 1"))
        conn.commit()

        ids = server.fetch_workspace_company_ids(conn, "ws-1")
        self.assertEqual(ids, [])
        count = conn.execute("SELECT COUNT(*) AS total FROM workspace_empresas").fetchone()["total"]
        self.assertEqual(count, 0)
        conn.close()

    def test_external_base_url_ignores_host_headers(self):
        handler = SimpleNamespace(
            headers={
                "Host": "attacker.example",
                "X-Forwarded-Host": "attacker.example",
                "X-Forwarded-Proto": "https",
            }
        )
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(server.Handler._external_base_url(handler), "http://localhost:8000")

    def test_workspace_service_alone_does_not_grant_privileged_session(self):
        self.assertFalse(server.workspace_session_is_privileged({"rol": "", "servicio": "Administración"}))
        self.assertFalse(server.workspace_session_is_privileged({"rol": "", "servicio": "Control"}))

    def test_login_rate_limit_persists_across_memory_reset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "auth.sqlite")

            def open_auth_store_conn(with_row_factory=True):
                conn = sqlite3.connect(db_path)
                if with_row_factory:
                    conn.row_factory = sqlite3.Row
                return conn

            with mock.patch.object(server, "open_auth_store_conn", side_effect=open_auth_store_conn):
                for _ in range(server.LOGIN_RATE_MAX_ATTEMPTS):
                    server.register_login_attempt("1.2.3.4", "alice", ok=False)

                allowed, retry_after = server.check_login_rate_limit("1.2.3.4", "alice")
                self.assertFalse(allowed)
                self.assertGreaterEqual(retry_after, 1)

                allowed_after_reset, retry_after_after_reset = server.check_login_rate_limit("1.2.3.4", "alice")
                self.assertFalse(allowed_after_reset)
                self.assertGreaterEqual(retry_after_after_reset, 1)

                server.register_login_attempt("1.2.3.4", "alice", ok=True)
                allowed_after_success, retry_after_after_success = server.check_login_rate_limit("1.2.3.4", "alice")
                self.assertTrue(allowed_after_success)
                self.assertEqual(retry_after_after_success, 0)

    def test_signature_public_payload_uses_fragment_links(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE inmuebles (
              id TEXT PRIMARY KEY,
              empresa_id TEXT NOT NULL
            );
            CREATE TABLE inmueble_docs (
              id TEXT PRIMARY KEY,
              inmueble_id TEXT NOT NULL,
              nombre TEXT,
              url TEXT
            );
            """
        )
        conn.execute("INSERT INTO inmuebles (id, empresa_id) VALUES (?, ?)", ("inm-1", "emp-1"))
        conn.execute(
            "INSERT INTO inmueble_docs (id, inmueble_id, nombre, url) VALUES (?, ?, ?, ?)",
            ("doc-1", "inm-1", "Contrato", "/uploads/contrato.pdf"),
        )
        conn.commit()

        result = server.create_inmueble_signature_request(
            conn,
            empresa_id="emp-1",
            inmueble_id="inm-1",
            doc_id="doc-1",
            doc_url="/uploads/contrato.pdf",
            doc_nombre="Contrato",
            signer_nombre="Persona",
            signer_nif="12345678A",
            signer_email="firma@example.com",
            signer_telefono="600000000",
            purpose="Firma",
            otp_required=False,
            expires_days=15,
            created_by="tester",
            now="2026-07-13T12:00:00+00:00",
        )
        self.assertTrue(result["public_url"].startswith("/#firma_inmo="))
        row = server._signature_request_row_by_token(conn, result["token"])
        public = server.signature_request_public_payload(row, token=result["token"])
        self.assertEqual(public["doc_public_url"], "/api/inmueble_signature_document")
        self.assertNotIn("?token=", public["doc_public_url"])
        conn.close()
