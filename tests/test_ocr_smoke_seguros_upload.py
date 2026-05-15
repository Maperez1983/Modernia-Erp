import base64
import io
import tempfile
from pathlib import Path
import unittest


class TestOcrSmokeSegurosUpload(unittest.TestCase):
    def _build_poliza_pdf(self) -> bytes:
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(595, 842))  # A4
        c.setFont("Helvetica", 12)
        c.drawString(40, 800, "PÓLIZA DE SEGURO")
        c.drawString(40, 780, "TOMADOR: Juan Pérez")
        c.drawString(40, 760, "COMPAÑÍA: MAPFRE")
        c.drawString(40, 740, "Nº PÓLIZA: 1234567890")
        c.drawString(40, 720, "FECHA EFECTO: 2026-05-01")
        c.showPage()
        c.save()
        return buf.getvalue()

    def test_process_seguros_ocr_base64_does_not_error(self):
        from web.server import process_seguros_ocr
        from web.server import ensure_tables, open_sqlite_conn

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=True) as tmp:
            db_path = Path(tmp.name)
            ensure_tables(db_path)
            conn = open_sqlite_conn(str(db_path), with_row_factory=True)
            try:
                pdf_bytes = self._build_poliza_pdf()
                payload = {
                    "filename": "poliza.pdf",
                    "file_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                    "fast_mode": True,
                }
                result = process_seguros_ocr(payload, conn, session=None)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        self.assertIsInstance(result, dict)
        fields = result.get("fields") or {}
        self.assertTrue(str(fields.get("poliza_numero") or "").strip())
        self.assertTrue(str(fields.get("compania") or "").strip())


if __name__ == "__main__":
    unittest.main()
