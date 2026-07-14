import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

from web import ocr_service


class OcrServiceCoverageTests(unittest.TestCase):
    def test_external_ocr_config_flags_and_sanitized_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            creds_path = Path(tmpdir) / "creds.json"
            creds_path.write_text("{}", encoding="utf-8")

            with mock.patch.dict(
                ocr_service.os.environ,
                {
                    "OCR_GOOGLE_APPLICATION_CREDENTIALS": str(creds_path),
                    "GOOGLE_VISION_API_KEY": "api-key extra-token",
                    "OCR_EXTERNAL_ENABLED": "1",
                    "DOCUMENTAI_PROCESSOR_ID": "proc-1",
                },
                clear=True,
            ):
                self.assertEqual(ocr_service._resolve_external_ocr_config(), (str(creds_path), "api-key"))
                self.assertTrue(ocr_service.external_ocr_available())
                self.assertTrue(ocr_service.docai_available())

            with mock.patch.dict(
                ocr_service.os.environ,
                {
                    "OCR_EXTERNAL_ENABLED": "0",
                },
                clear=True,
            ):
                self.assertFalse(ocr_service.external_ocr_available(resolver=lambda: ("", "vision-key")))
                self.assertFalse(ocr_service.docai_available())
                self.assertEqual(
                    ocr_service.ocr_image_external(b"image-bytes", resolver=lambda: ("", "")),
                    ("", "OCR externo no configurado"),
                )

            with mock.patch.dict(ocr_service.os.environ, {}, clear=True):
                with mock.patch.object(
                    ocr_service.urllib.request,
                    "urlopen",
                    side_effect=RuntimeError("fallo con api-key secreta"),
                ):
                    text, error = ocr_service.ocr_image_external(
                        b"image-bytes",
                        resolver=lambda: ("", "api-key secreta"),
                    )
                    self.assertEqual(text, "")
                    self.assertIn("***", error)
                    self.assertNotIn("api-key secreta", error)

    def test_docai_success_and_missing_config_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            creds_path = Path(tmpdir) / "creds.json"
            creds_path.write_text("{}", encoding="utf-8")

            self.assertEqual(
                ocr_service.ocr_image_docai(b"image-bytes", "image/png", resolver=lambda: ("", "")),
                ("", {}, "Document AI: credenciales no configuradas"),
            )

            with mock.patch.dict(
                ocr_service.os.environ,
                {"DOCUMENTAI_PROCESSOR_ID": ""},
                clear=True,
            ):
                self.assertEqual(
                    ocr_service.ocr_image_docai(b"image-bytes", "image/png", resolver=lambda: (str(creds_path), "")),
                    ("", {}, "Document AI: falta DOCUMENTAI_PROCESSOR_ID"),
                )

            class FakeCreds:
                def __init__(self):
                    self.token = "tok-123"
                    self.project_id = "proj-1"

                def refresh(self, request):
                    self.token = "tok-123"

            def fake_from_service_account_file(path, scopes=None):
                self.assertEqual(Path(path), creds_path)
                self.assertIn("cloud-platform", " ".join(scopes or []))
                return FakeCreds()

            fake_google = ModuleType("google")
            fake_google.__path__ = []
            fake_oauth2 = ModuleType("google.oauth2")
            fake_oauth2.__path__ = []
            fake_service_account = ModuleType("google.oauth2.service_account")
            fake_service_account.Credentials = SimpleNamespace(from_service_account_file=fake_from_service_account_file)
            fake_oauth2.service_account = fake_service_account
            fake_auth = ModuleType("google.auth")
            fake_auth.__path__ = []
            fake_transport = ModuleType("google.auth.transport")
            fake_transport.__path__ = []
            fake_requests = ModuleType("google.auth.transport.requests")

            class FakeRequest:
                pass

            fake_requests.Request = FakeRequest
            fake_transport.requests = fake_requests
            fake_auth.transport = fake_transport
            fake_google.oauth2 = fake_oauth2
            fake_google.auth = fake_auth

            fake_text = "Nombre Ana Nombre Luis"
            fake_response = mock.MagicMock()
            fake_response.read.return_value = json.dumps(
                {
                    "document": {
                        "text": fake_text,
                        "pages": [
                            {
                                "formFields": [
                                    {
                                        "fieldName": {
                                            "textAnchor": {
                                                "textSegments": [
                                                    {"startIndex": 0, "endIndex": 6},
                                                ]
                                            }
                                        },
                                        "fieldValue": {
                                            "textAnchor": {
                                                "textSegments": [
                                                    {"startIndex": 7, "endIndex": 10},
                                                ]
                                            }
                                        },
                                    },
                                    {
                                        "fieldName": {
                                            "textAnchor": {
                                                "textSegments": [
                                                    {"startIndex": 11, "endIndex": 17},
                                                ]
                                            }
                                        },
                                        "fieldValue": {
                                            "textAnchor": {
                                                "textSegments": [
                                                    {"startIndex": 18, "endIndex": 22},
                                                ]
                                            }
                                        },
                                    },
                                ]
                            }
                        ],
                    }
                }
            ).encode("utf-8")
            fake_response.__enter__.return_value = fake_response
            fake_response.__exit__.return_value = None

            with mock.patch.dict(
                sys.modules,
                {
                    "google": fake_google,
                    "google.oauth2": fake_oauth2,
                    "google.oauth2.service_account": fake_service_account,
                    "google.auth": fake_auth,
                    "google.auth.transport": fake_transport,
                    "google.auth.transport.requests": fake_requests,
                },
            ):
                with mock.patch.dict(
                    ocr_service.os.environ,
                    {
                        "DOCUMENTAI_PROCESSOR_ID": "proc-1",
                        "DOCUMENTAI_LOCATION": "us",
                    },
                    clear=True,
                ):
                    with mock.patch.object(ocr_service.urllib.request, "urlopen", return_value=fake_response):
                        text, fields, error = ocr_service.ocr_image_docai(
                            b"image-bytes",
                            None,
                            resolver=lambda: (str(creds_path), ""),
                        )
                        self.assertEqual(error, "")
                        self.assertEqual(text, fake_text)
                        self.assertEqual(fields["nombre 1"], "Ana")
                        self.assertEqual(fields["nombre 2"], "Luis")
                        self.assertEqual(ocr_service.normalize_field_label("Correo electrónico"), "correo electronico")

    def test_ocr_external_missing_google_dependencies_and_invalid_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            creds_path = Path(tmpdir) / "creds.json"
            creds_path.write_text("{}", encoding="utf-8")

            real_import = __import__

            def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
                if name.startswith("google"):
                    raise ImportError("missing google deps")
                return real_import(name, globals, locals, fromlist, level)

            with mock.patch.dict(ocr_service.os.environ, {"OCR_EXTERNAL_ENABLED": "1"}, clear=True):
                with mock.patch("builtins.__import__", side_effect=fake_import):
                    self.assertEqual(
                        ocr_service.ocr_image_external(b"image-bytes", resolver=lambda: (str(creds_path), "")),
                        ("", "OCR externo: instala google-auth y requests (pip install google-auth requests)"),
                    )

            class BrokenCreds:
                token = "tok"

                def refresh(self, request):
                    raise RuntimeError("credenciales rotas")

            fake_google = ModuleType("google")
            fake_google.__path__ = []
            fake_oauth2 = ModuleType("google.oauth2")
            fake_oauth2.__path__ = []
            fake_service_account = ModuleType("google.oauth2.service_account")
            fake_service_account.Credentials = SimpleNamespace(
                from_service_account_file=lambda path, scopes=None: BrokenCreds()
            )
            fake_oauth2.service_account = fake_service_account
            fake_auth = ModuleType("google.auth")
            fake_auth.__path__ = []
            fake_transport = ModuleType("google.auth.transport")
            fake_transport.__path__ = []
            fake_requests = ModuleType("google.auth.transport.requests")
            fake_requests.Request = object
            fake_transport.requests = fake_requests
            fake_auth.transport = fake_transport
            fake_google.oauth2 = fake_oauth2
            fake_google.auth = fake_auth

            with mock.patch.dict(
                sys.modules,
                {
                    "google": fake_google,
                    "google.oauth2": fake_oauth2,
                    "google.oauth2.service_account": fake_service_account,
                    "google.auth": fake_auth,
                    "google.auth.transport": fake_transport,
                    "google.auth.transport.requests": fake_requests,
                },
            ):
                with mock.patch.dict(
                    ocr_service.os.environ,
                    {"DOCUMENTAI_PROCESSOR_ID": "proc-1", "DOCUMENTAI_LOCATION": "us"},
                    clear=True,
                ):
                    result = ocr_service.ocr_image_docai(
                        b"image-bytes",
                        "image/png",
                        resolver=lambda: (str(creds_path), ""),
                    )
                    self.assertEqual(result[0], "")
                    self.assertEqual(result[1], {})
                    self.assertIn("credenciales inválidas", result[2])
