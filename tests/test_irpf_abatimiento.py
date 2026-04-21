import unittest

from web.server import _irpf_ganancia_simulate


class IrpfAbatimientoTests(unittest.TestCase):
    def test_abatimiento_dt9_with_mejoras_split(self):
        payload = {
            "ejercicio": "2025",
            "regimen_fiscal": "irpf",
            "ccaa": "AN",
            "participacion_pct": "100",
            "fecha_adquisicion": "1992-10-10",
            "fecha_transmision": "2025-02-03",
            "valor_adquisicion": "100000",
            "gastos_adquisicion": "8000",
            "inversiones_mejoras": "75000",
            "fecha_mejoras": "2012-07-01",
            "valor_transmision_mejoras": "150000",
            "amortizacion_deducida": "0",
            "valor_transmision": "500000",
            "gastos_transmision": "0",
            "plusvalia_municipal": "15000",
            "abatimiento_mode": "auto",
            "abatimiento_tipo": "inmueble",
            "abatimiento_vt1_acumulado_2015": "0",
        }
        out = _irpf_ganancia_simulate(payload)
        self.assertTrue(out.get("ok"))
        result = out.get("result") or {}
        ab = result.get("abatimiento") or {}

        self.assertEqual(ab.get("split_mejoras"), 1)
        self.assertAlmostEqual(float(result.get("ganancia_patrimonial")), 302000.00, places=2)
        self.assertAlmostEqual(float(ab.get("reduccion_importe")), 31082.86, places=2)
        self.assertAlmostEqual(float(result.get("ganancia_patrimonial_computable")), 270917.14, places=2)
        self.assertAlmostEqual(float(result.get("base_ahorro_sujeta")), 270917.14, places=2)


if __name__ == "__main__":
    unittest.main()

