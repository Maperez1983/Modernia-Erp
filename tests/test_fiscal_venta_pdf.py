import unittest
from io import BytesIO

from pypdf import PdfReader

from web.server import build_fiscal_venta_report_pdf


class FiscalVentaPdfTests(unittest.TestCase):
    def test_generates_pdf_bytes(self):
        payload = {
            "brand_logo_url": "/assets/grupo_modernia_logo.png",
            "empresa_nombre": "Grupo Modernia",
            "referencia": "Test inmueble",
            "ccaa": "AN",
            "irpf_payload": {
                "ejercicio": "2025",
                "fecha_adquisicion": "2010-01-01",
                "fecha_transmision": "2025-02-01",
                "participacion_pct": "100",
                "valor_adquisicion": "100.000,00",
                "valor_transmision": "200.000,00",
                "regimen_fiscal": "irpf",
            },
            "iivtnu_payload": {
                "municipio_ine": "29067",
                "codigo_postal": "29001",
                "fecha_adquisicion": "2010-01-01",
                "fecha_transmision": "2025-02-01",
                "valor_suelo": "50000,00",
                "participacion_pct": "100",
            },
        }
        irpf_out = {
            "ok": True,
            "params": {"ejercicio": 2025, "regimen_fiscal": "irpf", "ccaa": "AN", "ccaa_label": "Andalucía"},
            "result": {
                "valor_adquisicion_calc": 100000.0,
                "valor_transmision_calc": 200000.0,
                "ganancia_patrimonial": 100000.0,
                "exento": 0.0,
                "exencion_motivo": "",
                "base_ahorro_sujeta": 100000.0,
                "cuota_ahorro_estimada": 21000.0,
            },
        }
        iivtnu_out = {
            "ok": True,
            "params": {"source_label": "Test", "coef_source_label": "Test coef"},
            "result": {
                "metodo_recomendado": "objetivo",
                "cuota_recomendada": 123.45,
                "years": 10,
                "months": 0,
                "coef_objetivo": 0.12,
                "tipo_gravamen_pct": 29.0,
                "bonificacion_pct": 0.0,
                "objetivo": {"base_imponible": 5000.0, "cuota_tributaria": 123.45},
            },
        }
        pdf_bytes = build_fiscal_venta_report_pdf(payload, irpf_out, iivtnu_out)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        reader = PdfReader(BytesIO(pdf_bytes))
        self.assertGreaterEqual(len(reader.pages), 1)


if __name__ == "__main__":
    unittest.main()

