import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from web import ocr_service
from web import public_links
from web import security_utils
from web import server


class TechnicalAuditRegressionTests(unittest.TestCase):
    def test_resolve_external_ocr_config_prefers_explicit_env_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            explicit_path = tmp_path / "explicit-creds.json"
            standard_path = tmp_path / "standard-creds.json"
            explicit_path.write_text("{}", encoding="utf-8")
            standard_path.write_text("{}", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {
                    "OCR_GOOGLE_APPLICATION_CREDENTIALS": str(explicit_path),
                    "GOOGLE_APPLICATION_CREDENTIALS": str(standard_path),
                },
                clear=True,
            ):
                expected = (str(explicit_path), "")
                self.assertEqual(server._resolve_external_ocr_config(), expected)
                self.assertEqual(ocr_service._resolve_external_ocr_config(), expected)

            with mock.patch.dict(
                os.environ,
                {
                    "GOOGLE_APPLICATION_CREDENTIALS": str(standard_path),
                },
                clear=True,
            ):
                expected = (str(standard_path), "")
                self.assertEqual(server._resolve_external_ocr_config(), expected)
                self.assertEqual(ocr_service._resolve_external_ocr_config(), expected)

    def test_resolve_external_ocr_config_rejects_missing_directory_and_non_json_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            missing_path = tmp_path / "missing-creds.json"
            directory_path = tmp_path / "creds-dir"
            non_json_path = tmp_path / "creds.txt"
            directory_path.mkdir()
            non_json_path.write_text("{}", encoding="utf-8")

            with mock.patch.dict(
                os.environ,
                {"OCR_GOOGLE_APPLICATION_CREDENTIALS": str(missing_path)},
                clear=True,
            ):
                self.assertEqual(server._resolve_external_ocr_config(), ("", ""))
                self.assertEqual(ocr_service._resolve_external_ocr_config(), ("", ""))

            with mock.patch.dict(
                os.environ,
                {"OCR_GOOGLE_APPLICATION_CREDENTIALS": str(directory_path)},
                clear=True,
            ):
                self.assertEqual(server._resolve_external_ocr_config(), ("", ""))
                self.assertEqual(ocr_service._resolve_external_ocr_config(), ("", ""))

            with mock.patch.dict(
                os.environ,
                {"OCR_GOOGLE_APPLICATION_CREDENTIALS": str(non_json_path)},
                clear=True,
            ):
                self.assertEqual(server._resolve_external_ocr_config(), ("", ""))
                self.assertEqual(ocr_service._resolve_external_ocr_config(), ("", ""))

    def test_resolve_external_ocr_config_returns_empty_without_variables(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(server._resolve_external_ocr_config(), ("", ""))
            self.assertEqual(ocr_service._resolve_external_ocr_config(), ("", ""))

    def test_resolve_external_ocr_config_does_not_autodiscover_vision_sa_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            web_root = tmp_path / "web"
            web_root.mkdir()
            (tmp_path / "vision-sa.json").write_text("{}", encoding="utf-8")

            with mock.patch.object(server, "ROOT", web_root):
                cwd_error = AssertionError("cwd lookup is not allowed")
                with mock.patch.object(server.Path, "cwd", side_effect=cwd_error):
                    with mock.patch.object(ocr_service.Path, "cwd", side_effect=cwd_error):
                        with mock.patch.dict(os.environ, {}, clear=True):
                            self.assertEqual(server._resolve_external_ocr_config(), ("", ""))
                            self.assertEqual(ocr_service._resolve_external_ocr_config(), ("", ""))

    def test_external_ocr_functions_match_new_module(self):
        fake_response = mock.MagicMock()
        fake_response.read.return_value = (
            b'{"responses":[{"fullTextAnnotation":{"text":"OCR OK"}}]}'
        )
        fake_response.__enter__.return_value = fake_response
        fake_response.__exit__.return_value = None

        helper = mock.Mock(return_value=("", "vision-key"))

        with mock.patch.object(server, "_resolve_external_ocr_config", helper):
            with mock.patch.object(ocr_service.urllib.request, "urlopen", return_value=fake_response) as urlopen_mock:
                self.assertEqual(
                    server.external_ocr_available(),
                    ocr_service.external_ocr_available(resolver=server._resolve_external_ocr_config),
                )
                self.assertEqual(
                    server.ocr_image_external(b"image-bytes"),
                    ocr_service.ocr_image_external(b"image-bytes", resolver=server._resolve_external_ocr_config),
                )

        self.assertEqual(helper.call_count, 4)
        self.assertEqual(urlopen_mock.call_count, 2)

    def test_docai_ocr_matches_new_module_without_credentials(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                server.ocr_image_docai(b"image-bytes", "image/png"),
                ocr_service.ocr_image_docai(b"image-bytes", "image/png"),
            )

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
            expected = "http://localhost:8000"
            self.assertEqual(server.Handler._external_base_url(handler), expected)
            self.assertEqual(public_links.external_base_url(), expected)

    def test_public_link_helpers_match_new_module(self):
        payload = {"id": "req-1", "doc_nombre": "Contrato", "otp_required": 1}
        with mock.patch.dict(
            os.environ,
            {
                "APP_BASE_URL": "https://crm.example.com",
                "PUBLIC_URL": "https://public.example.com",
            },
            clear=True,
        ):
            self.assertEqual(server.configured_app_base_url(), public_links.configured_app_base_url())
            self.assertEqual(
                server.resolve_public_link_base_url(""),
                public_links.resolve_public_link_base_url(""),
            )
            self.assertEqual(
                server.build_public_fragment_url("activar_token", "abc"),
                public_links.build_public_fragment_url("activar_token", "abc"),
            )
            self.assertEqual(
                server.build_public_fragment_url("token", "abc", base_url="https://crm.example.com", path="/kiosk"),
                public_links.build_public_fragment_url("token", "abc", base_url="https://crm.example.com", path="/kiosk"),
            )
        with mock.patch.object(public_links.secrets, "token_urlsafe", return_value="fixed-token"):
            self.assertEqual(server.make_signature_token(), public_links.make_signature_token())
        self.assertEqual(
            server.hash_signature_token("abc123"),
            public_links.hash_signature_token("abc123"),
        )
        self.assertEqual(
            server.signature_request_public_payload(payload, token="ignored"),
            public_links.signature_request_public_payload(payload, token="ignored"),
        )

    def test_security_helpers_match_new_module(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir)
            target_path = base_path / "safe" / "file.txt"
            target_path.parent.mkdir(parents=True)

            sample_html = "<p>Hello</p><script>ignored()</script>"
            sample_strict_html = "<p>Hello</p>\n\n<p>World</p>"
            sample_json = '{"ok": true}'
            placeholder_key = "0123456789abcdef0123456789abcdef"
            s3_key = r"folder\\nested\\file.pdf"

            with mock.patch.object(server, "COPILOT_WEB_ALLOWED_DOMAINS", {"example.com"}):
                self.assertEqual(server._ct_eq("abc", "abc"), security_utils._ct_eq("abc", "abc"))
                self.assertEqual(server._ct_eq("abc", "xyz"), security_utils._ct_eq("abc", "xyz"))
                self.assertEqual(server._normalize_s3_key(s3_key), security_utils._normalize_s3_key(s3_key))
                self.assertEqual(
                    server._iter_s3_legacy_key_candidates(placeholder_key),
                    security_utils._iter_s3_legacy_key_candidates(placeholder_key),
                )
                self.assertEqual(server._is_public_doc_url("https://example.com/doc.pdf"), security_utils._is_public_doc_url("https://example.com/doc.pdf"))
                self.assertEqual(server._looks_like_placeholder_doc_key(placeholder_key), security_utils._looks_like_placeholder_doc_key(placeholder_key))
                self.assertEqual(server._normalize_doc_key_for_ui("s3://bucket/doc.pdf"), security_utils._normalize_doc_key_for_ui("s3://bucket/doc.pdf"))
                self.assertEqual(server._safe_json_object(sample_json), security_utils._safe_json_object(sample_json))
                self.assertEqual(server.html_to_text(sample_html), security_utils.html_to_text(sample_html))
                self.assertEqual(server._html_to_text(sample_strict_html), security_utils._html_to_text(sample_strict_html))
                self.assertEqual(server._extract_title("<html><head><title>  Demo  </title></head></html>"), security_utils._extract_title("<html><head><title>  Demo  </title></head></html>"))
                self.assertEqual(server._pdf_escape("a(b)\\c"), security_utils._pdf_escape("a(b)\\c"))
                self.assertEqual(server.safe_resolve_under(base_path, "safe/file.txt"), security_utils.safe_resolve_under(base_path, "safe/file.txt"))
                self.assertIsNone(server.safe_resolve_under(base_path, "../escape.txt"))
                self.assertEqual(server._domain_is_allowed("example.com"), security_utils._domain_is_allowed("example.com", {"example.com"}))
                self.assertFalse(server._domain_is_allowed("localhost"))

            with mock.patch.object(security_utils.socket, "getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 0))]):
                self.assertEqual(
                    server._hostname_resolves_to_disallowed_ip("example.com"),
                    security_utils._hostname_resolves_to_disallowed_ip("example.com"),
                )

            with mock.patch.object(security_utils.socket, "getaddrinfo", return_value=[(None, None, None, None, ("8.8.8.8", 0))]):
                self.assertEqual(
                    server._hostname_resolves_to_disallowed_ip("example.com"),
                    security_utils._hostname_resolves_to_disallowed_ip("example.com"),
                )

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
        self.assertEqual(public, public_links.signature_request_public_payload(row, token=result["token"]))
        self.assertEqual(public["doc_public_url"], "/api/inmueble_signature_document")
        self.assertNotIn("?token=", public["doc_public_url"])
        conn.close()
