import io
import unittest


class TestRrhhNominasSplitPdf(unittest.TestCase):
    def _build_pdf(self) -> bytes:
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(595, 842))  # A4 aprox
        c.setFont("Helvetica", 12)
        c.drawString(40, 800, "NIF: 12345678Z")
        c.drawString(40, 780, "Periodo: 02/2026")
        c.drawString(40, 760, "Liquido a percibir: 665,14")
        c.showPage()

        c.setFont("Helvetica", 12)
        c.drawString(40, 800, "Detalle devengos y deducciones (continuación)")
        c.drawString(40, 780, "Neto: 665,14")
        c.showPage()

        c.setFont("Helvetica", 12)
        c.drawString(40, 800, "NIF: 87654321X")
        c.drawString(40, 780, "Periodo: 02/2026")
        c.drawString(40, 760, "Liquido a percibir: 700,00")
        c.showPage()

        c.save()
        return buf.getvalue()

    def test_split_groups_contiguous_pages_by_nif(self):
        from web.server import split_nominas_pdf_by_nif

        pdf_bytes = self._build_pdf()
        parts = split_nominas_pdf_by_nif(pdf_bytes)
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0]["nif"], "12345678Z")
        self.assertEqual(parts[1]["nif"], "87654321X")
        self.assertEqual(parts[0]["pages"], [0, 1])
        self.assertEqual(parts[1]["pages"], [2])
        self.assertTrue(parts[0]["pdf_bytes"].startswith(b"%PDF"))
        self.assertTrue(parts[1]["pdf_bytes"].startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()

