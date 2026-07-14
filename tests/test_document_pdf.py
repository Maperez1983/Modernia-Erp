import importlib
import unittest
from io import BytesIO

from web import document_pdf
from web import server


class DocumentPdfTests(unittest.TestCase):
    def _pdf_text(self, pdf_bytes):
        if server.PdfReader is None:
            return None
        reader = server.PdfReader(BytesIO(pdf_bytes))
        return "\n".join((page.extract_text() or "").strip() for page in reader.pages)

    def _assert_same_pdf_shape(self, left, right):
        self.assertTrue(left.startswith(b"%PDF"))
        self.assertTrue(right.startswith(b"%PDF"))
        self.assertGreater(len(left), 0)
        self.assertGreater(len(right), 0)
        if server.PdfReader is not None:
            left_reader = server.PdfReader(BytesIO(left))
            right_reader = server.PdfReader(BytesIO(right))
            self.assertEqual(len(left_reader.pages), len(right_reader.pages))
            self.assertEqual(self._pdf_text(left), self._pdf_text(right))

    def test_branded_document_pdf_matches_server_wrapper(self):
        sections = [
            ("Resumen", [("Clave", "Valor"), "Línea de apoyo"]),
            ("Observaciones", ["Detalle 1", "Detalle 2"]),
        ]

        self._assert_same_pdf_shape(
            server.build_branded_document_pdf("Documento base", "Subtítulo base", sections, ["Pie 1", "Pie 2"]),
            document_pdf.build_branded_document_pdf("Documento base", "Subtítulo base", sections, ["Pie 1", "Pie 2"]),
        )

    def test_branded_text_document_pdf_matches_server_wrapper(self):
        body_lines = ["Línea 1", "", "Línea 2", "__PAGE_BREAK__", "Línea 3"]

        self._assert_same_pdf_shape(
            server.build_branded_text_document_pdf("Texto base", "Subtítulo texto", body_lines, ["Pie textual"]),
            document_pdf.build_branded_text_document_pdf("Texto base", "Subtítulo texto", body_lines, ["Pie textual"]),
        )

    def test_company_branded_document_pdf_matches_server_wrapper_for_plain_company(self):
        company = {"nombre": "Empresa Demo", "logo_url": ""}
        sections = [("Datos", [("Campo", "Valor"), "Observación"])]

        self._assert_same_pdf_shape(
            server.build_company_branded_document_pdf(company, "Documento empresa", "Subtítulo empresa", sections, ["Pie"]),
            document_pdf.build_company_branded_document_pdf(company, "Documento empresa", "Subtítulo empresa", sections, ["Pie"]),
        )

    def test_company_branded_text_document_pdf_matches_server_wrapper_for_modernia_company(self):
        company = {"nombre": "Modernia Demo SL", "logo_url": "/assets/grupo_modernia_logo.png"}
        body_lines = ["A", "B", "C"]
        original_dependencies = dict(document_pdf._DEPENDENCIES)
        fresh_document_pdf = importlib.reload(document_pdf)
        try:
            self._assert_same_pdf_shape(
                server.build_company_branded_text_document_pdf(company, "Documento Modernia", "Subtítulo Modernia", body_lines, ["Pie"]),
                fresh_document_pdf.build_company_branded_text_document_pdf(company, "Documento Modernia", "Subtítulo Modernia", body_lines, ["Pie"]),
            )
        finally:
            fresh_document_pdf.configure_dependencies(**original_dependencies)

    def test_signature_evidence_pdf_matches_server_wrapper(self):
        request_row = {
            "id": "req-1",
            "doc_nombre": "Contrato de prueba",
            "doc_url": "/docs/contrato.pdf",
            "document_sha256": "abc123",
            "purpose": "Prueba de firma",
            "signer_nombre": "Ana López",
            "signer_nif": "12345678A",
            "signed_name": "Ana López",
            "signed_nif": "12345678A",
            "sent_at": "2026-07-13T10:00:00+00:00",
            "opened_at": "2026-07-13T10:01:00+00:00",
            "signed_at": "2026-07-13T10:02:00+00:00",
            "otp_required": 1,
            "acceptance_text": "Acepto el documento",
        }
        evidence = {
            "document_sha256": "abc123",
            "signed_name": "Ana López",
            "signed_nif": "12345678A",
            "signed_at": "2026-07-13T10:02:00+00:00",
            "ip": "127.0.0.1",
            "user_agent": "TestAgent/1.0",
            "acceptance_text": "Acepto el documento",
        }

        self._assert_same_pdf_shape(
            server.build_signature_evidence_pdf(request_row, evidence),
            document_pdf.build_signature_evidence_pdf(request_row, evidence),
        )

        if server.PdfReader is not None:
            text = self._pdf_text(document_pdf.build_signature_evidence_pdf(request_row, evidence))
            self.assertIn("JUSTIFICANTE", text)
            self.assertIn("Contrato de prueba", text)
