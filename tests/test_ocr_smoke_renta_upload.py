import base64
import io
import unittest


class TestOcrSmokeRentaUpload(unittest.TestCase):
    def _build_renta_pdf(self) -> bytes:
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(595, 842))  # A4
        c.setFont("Helvetica", 12)
        c.drawString(40, 800, "AGENCIA TRIBUTARIA")
        c.drawString(40, 780, "Ejercicio 2025")
        c.drawString(40, 760, "DNI/NIF: 12345678Z")
        c.drawString(40, 740, "Resultado de la declaración")
        c.showPage()
        c.save()
        return buf.getvalue()

    def test_process_renta_ocr_job_extracts_nif(self):
        from web.server import process_renta_ocr_job

        pdf_bytes = self._build_renta_pdf()
        payload = {
            "filename": "renta.pdf",
            "file_base64": base64.b64encode(pdf_bytes).decode("ascii"),
        }
        result = process_renta_ocr_job(payload, conn=None)
        self.assertIsInstance(result, dict)
        fields = result.get("fields") or {}
        self.assertEqual(str(fields.get("nif_detectado") or "").strip(), "12345678Z")


if __name__ == "__main__":
    unittest.main()

