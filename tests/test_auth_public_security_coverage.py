import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from web import auth_security
from web import public_links
from web import security_utils


class AuthPublicSecurityCoverageTests(unittest.TestCase):
    def test_password_hash_roundtrip_and_rehash_threshold(self):
        with mock.patch.object(auth_security.os, "urandom", return_value=b"\x01" * 16):
            weak_hash = auth_security.hash_password("secreto", iterations=120000)
        self.assertTrue(weak_hash.startswith("pbkdf2_sha256$120000$"))
        self.assertTrue(auth_security.verify_password("secreto", weak_hash))
        self.assertFalse(auth_security.verify_password("incorrecto", weak_hash))
        self.assertTrue(auth_security.needs_password_rehash(weak_hash))

        with mock.patch.object(auth_security.os, "urandom", return_value=b"\x02" * 16):
            strong_hash = auth_security.hash_password("secreto", iterations=auth_security.DEFAULT_PBKDF2_ITERATIONS)
        self.assertTrue(auth_security.verify_password("secreto", strong_hash))
        self.assertFalse(auth_security.needs_password_rehash(strong_hash))
        self.assertIsNone(auth_security.hash_password("", iterations=auth_security.DEFAULT_PBKDF2_ITERATIONS))

    def test_password_hash_legacy_format_and_invalid_inputs(self):
        salt = "pepper"
        stored = hashlib.sha256((salt + "clave").encode("utf-8")).hexdigest()
        legacy_hash = f"{salt}${stored}"

        self.assertTrue(auth_security.verify_password("clave", legacy_hash))
        self.assertFalse(auth_security.verify_password("otra", legacy_hash))
        self.assertFalse(auth_security.verify_password("", legacy_hash))
        self.assertFalse(auth_security.verify_password("clave", "sin-delimitador"))
        self.assertFalse(auth_security.verify_password("clave", "pbkdf2_sha256$123$salt"))
        self.assertFalse(auth_security.verify_password("clave", "pbkdf2_sha256$bad$salt$digest"))
        self.assertFalse(auth_security.verify_password("clave", "pbkdf2_sha256$123$salt$"))
        self.assertTrue(auth_security.needs_password_rehash(legacy_hash))
        self.assertTrue(auth_security.needs_password_rehash(""))
        self.assertTrue(auth_security.needs_password_rehash("pbkdf2_sha256$abc$salt$digest"))
        self.assertTrue(auth_security.needs_password_rehash("pbkdf2_sha256$123$salt"))
        self.assertTrue(auth_security.needs_password_rehash("pbkdf2_sha256$bad$salt$digest"))

    def test_public_link_helpers_use_env_precedence_and_quote_fragments(self):
        with mock.patch.dict(
            public_links.os.environ,
            {
                "APP_BASE_URL": "https://crm.example.com/",
                "PUBLIC_URL": "https://public.example.com/",
                "RENDER_EXTERNAL_URL": "https://render.example.com/",
                "APP_PUBLIC_URL": "https://app-public.example.com/",
            },
            clear=True,
        ):
            self.assertEqual(public_links.configured_app_base_url(), "https://crm.example.com")
            self.assertEqual(public_links.resolve_public_link_base_url(""), "https://crm.example.com")
            self.assertEqual(
                public_links.resolve_public_link_base_url(" https://override.example.com/kiosk/ "),
                "https://override.example.com/kiosk",
            )
            self.assertEqual(public_links.external_base_url(), "https://crm.example.com")

        with mock.patch.dict(
            public_links.os.environ,
            {
                "PUBLIC_URL": "https://public.example.com/",
            },
            clear=True,
        ):
            self.assertEqual(public_links.resolve_public_link_base_url(""), "https://public.example.com")
            self.assertEqual(public_links.external_base_url(), "https://public.example.com")

        with mock.patch.dict(public_links.os.environ, {}, clear=True):
            self.assertEqual(public_links.external_base_url(), "http://localhost:8000")

        self.assertEqual(
            public_links.build_public_fragment_url("activar_token", "a b/c", base_url="https://crm.example.com/", path="kiosk"),
            "https://crm.example.com/kiosk#activar_token=a%20b/c",
        )
        self.assertEqual(public_links.build_public_fragment_url("", "abc"), "/#token=abc")

        with mock.patch.object(public_links.secrets, "token_urlsafe", return_value="tok-123") as token_mock:
            self.assertEqual(public_links.make_signature_token(), "tok-123")
            token_mock.assert_called_once_with(32)

        self.assertEqual(public_links.hash_signature_token("abc"), hashlib.sha256(b"abc").hexdigest())

        payload = public_links.signature_request_public_payload(
            {
                "id": "req-1",
                "inmueble_id": "inm-1",
                "doc_nombre": "Contrato",
                "doc_url": "/docs/contrato.pdf",
                "signer_nombre": "Ana López",
                "signer_nif": "12345678A",
                "signer_email": "ana@example.com",
                "purpose": "Prueba",
                "status": None,
                "otp_required": "1",
                "expires_at": None,
                "opened_at": "2026-07-13T10:00:00+00:00",
                "signed_at": None,
                "signed_doc_url": None,
            },
            token="ignored",
        )
        self.assertEqual(payload["doc_public_url"], "/api/inmueble_signature_document")
        self.assertTrue(payload["otp_required"])
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["doc_nombre"], "Contrato")
        self.assertIsNone(public_links.signature_request_public_payload(None))

    def test_security_url_and_path_helpers(self):
        with mock.patch.object(security_utils.hmac, "compare_digest", side_effect=RuntimeError("boom")):
            self.assertFalse(security_utils._ct_eq("a", "a"))

        self.assertEqual(security_utils._normalize_s3_key(r"\docs\factura.pdf"), "docs/factura.pdf")
        candidates = security_utils._iter_s3_legacy_key_candidates("0123456789abcdef0123456789abcdef")
        self.assertEqual(candidates[0], "0123456789abcdef0123456789abcdef")
        self.assertIn("docs/0123456789abcdef0123456789abcdef.pdf", candidates)
        self.assertEqual(len(candidates), len(set(candidates)))
        self.assertTrue(security_utils._is_public_doc_url("/uploads/contrato.pdf"))
        self.assertTrue(security_utils._is_public_doc_url("s3://bucket/contrato.pdf"))
        self.assertTrue(security_utils._is_public_doc_url("https://example.com/contrato.pdf"))
        self.assertFalse(security_utils._is_public_doc_url(""))
        self.assertTrue(security_utils._looks_like_placeholder_doc_key("0123456789abcdef0123456789abcdef"))
        self.assertEqual(security_utils._normalize_doc_key_for_ui("0123456789abcdef0123456789abcdef"), "")
        self.assertEqual(security_utils._normalize_doc_key_for_ui("facturas/2026-01.pdf"), "facturas/2026-01.pdf")

    def test_security_text_hostname_and_resolve_helpers(self):
        self.assertEqual(
            security_utils.html_to_text("<p>Hola</p><script>alert(1)</script><style>.x{}</style> Mundo"),
            "Hola Mundo",
        )
        self.assertEqual(
            security_utils._html_to_text("<html><head><title>Mi <b>Doc</b></title></head><body>x</body></html>").split(),
            ["Mi", "Doc", "x"],
        )
        self.assertEqual(
            security_utils._extract_title("<html><head><title>Mi <b>Doc</b></title></head></html>").split(),
            ["Mi", "Doc"],
        )
        self.assertTrue(security_utils._is_ip_literal("127.0.0.1"))
        self.assertTrue(security_utils._is_ip_literal("::1"))
        self.assertTrue(security_utils._is_disallowed_hostname("localhost"))
        self.assertTrue(security_utils._domain_is_allowed("sub.example.com", ["example.com"]))
        self.assertFalse(security_utils._domain_is_allowed("localhost", ["example.com"]))

        with mock.patch.object(
            security_utils.socket,
            "getaddrinfo",
            return_value=[(None, None, None, None, ("127.0.0.1", 0))],
        ):
            self.assertEqual(
                security_utils._hostname_resolves_to_disallowed_ip("example.com"),
                (True, "resuelve a IP no global (127.0.0.1)"),
            )

        with mock.patch.object(
            security_utils.socket,
            "getaddrinfo",
            return_value=[(None, None, None, None, ("93.184.216.34", 0))],
        ):
            self.assertEqual(security_utils._hostname_resolves_to_disallowed_ip("example.com"), (False, ""))

        with mock.patch.object(security_utils.socket, "getaddrinfo", side_effect=OSError("dns fail")):
            self.assertEqual(security_utils._hostname_resolves_to_disallowed_ip("example.com"), (True, "no se pudo resolver DNS"))

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            resolved_base = base.resolve()
            safe = security_utils.safe_resolve_under(base, "docs/factura.pdf")
            self.assertEqual(safe, resolved_base / "docs" / "factura.pdf")
            self.assertIsNone(security_utils.safe_resolve_under(base, "../secreto.txt"))
            self.assertIsNone(security_utils.safe_resolve_under(base, ""))
