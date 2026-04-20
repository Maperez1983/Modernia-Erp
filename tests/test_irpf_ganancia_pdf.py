import unittest
from io import BytesIO

from pypdf import PdfReader

from web.server import _irpf_ganancia_simulate, build_irpf_ganancia_report_pdf


class IrpfGananciaPdfTests(unittest.TestCase):
    def test_generates_pdf_bytes(self):
        payload = {
            "brand_logo_url": "/assets/grupo_modernia_logo.png",
            "empresa_nombre": "Grupo Modernia",
            "ejercicio": "2025",
            "participacion_pct": "100",
            "fecha_adquisicion": "2010-02-17",
            "fecha_transmision": "2020-03-10",
            "valor_adquisicion": "150.000,00",
            "valor_transmision": "200.000,00",
        }
        out = _irpf_ganancia_simulate(payload)
        pdf_bytes = build_irpf_ganancia_report_pdf(payload, out)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        reader = PdfReader(BytesIO(pdf_bytes))
        self.assertGreaterEqual(len(reader.pages), 1)


if __name__ == "__main__":
    unittest.main()

