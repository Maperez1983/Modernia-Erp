import unittest

from web.server import _irpf_ganancia_simulate


class IrpfGananciaSimulateTests(unittest.TestCase):
    def test_basic_gain_2025(self):
        payload = {
            "ejercicio": "2025",
            "participacion_pct": "100",
            "fecha_adquisicion": "2010-02-17",
            "fecha_transmision": "2020-03-10",
            "valor_adquisicion": "150.000,00",
            "valor_transmision": "200.000,00",
            "gastos_adquisicion": "0,00",
            "gastos_transmision": "0,00",
            "plusvalia_municipal": "0,00",
        }
        out = _irpf_ganancia_simulate(payload)
        self.assertTrue(out.get("ok"))
        self.assertEqual(out["params"]["ejercicio"], 2025)
        self.assertEqual(out["params"]["escala_ejercicio"], 2025)
        self.assertEqual(out["params"]["escala_asumida"], 0)
        self.assertAlmostEqual(float(out["result"]["ganancia_patrimonial"]), 50000.00, places=2)
        self.assertAlmostEqual(float(out["result"]["base_ahorro_sujeta"]), 50000.00, places=2)
        self.assertAlmostEqual(float(out["result"]["cuota_ahorro_estimada"]), 10380.00, places=2)

    def test_scale_diff_2024_vs_assumed_2025(self):
        payload_2024 = {
            "ejercicio": "2024",
            "participacion_pct": "100",
            "fecha_adquisicion": "2010-01-01",
            "fecha_transmision": "2024-06-01",
            "valor_adquisicion": "150.000,00",
            "valor_transmision": "550.000,00",
        }
        out_2024 = _irpf_ganancia_simulate(payload_2024)
        self.assertEqual(out_2024["params"]["escala_ejercicio"], 2024)
        self.assertEqual(out_2024["params"]["escala_asumida"], 0)
        self.assertAlmostEqual(float(out_2024["result"]["ganancia_patrimonial"]), 400000.00, places=2)
        self.assertAlmostEqual(float(out_2024["result"]["cuota_ahorro_estimada"]), 99880.00, places=2)

        payload_2026 = dict(payload_2024)
        payload_2026["ejercicio"] = "2026"
        out_2026 = _irpf_ganancia_simulate(payload_2026)
        self.assertEqual(out_2026["params"]["escala_ejercicio"], 2025)
        self.assertEqual(out_2026["params"]["escala_asumida"], 1)
        self.assertAlmostEqual(float(out_2026["result"]["cuota_ahorro_estimada"]), 101880.00, places=2)

    def test_reinvestment_exemption_is_proportional(self):
        payload = {
            "ejercicio": "2025",
            "participacion_pct": "100",
            "fecha_adquisicion": "2015-01-01",
            "fecha_transmision": "2025-01-02",
            "valor_adquisicion": "100.000,00",
            "valor_transmision": "200.000,00",
            "vivienda_habitual": "on",
            "importe_reinvertido": "50.000,00",
            "prestamo_pendiente": "0,00",
        }
        out = _irpf_ganancia_simulate(payload)
        self.assertTrue(out.get("ok"))
        self.assertAlmostEqual(float(out["result"]["ganancia_patrimonial"]), 100000.00, places=2)
        self.assertAlmostEqual(float(out["result"]["exento"]), 25000.00, places=2)
        self.assertAlmostEqual(float(out["result"]["base_ahorro_sujeta"]), 75000.00, places=2)
        self.assertAlmostEqual(float(out["result"]["cuota_ahorro_estimada"]), 16130.00, places=2)

    def test_irnr_gain_with_retention(self):
        payload = {
            "regimen_fiscal": "irnr",
            "ejercicio": "2025",
            "participacion_pct": "100",
            "fecha_adquisicion": "2010-01-01",
            "fecha_transmision": "2025-02-01",
            "valor_adquisicion": "100.000,00",
            "valor_transmision": "200.000,00",
            "retencion_pct": "3",
        }
        out = _irpf_ganancia_simulate(payload)
        self.assertTrue(out.get("ok"))
        self.assertEqual(out["params"]["regimen_fiscal"], "irnr")
        self.assertAlmostEqual(float(out["result"]["ganancia_patrimonial"]), 100000.00, places=2)
        self.assertAlmostEqual(float(out["result"]["cuota_ahorro_estimada"]), 19000.00, places=2)
        self.assertAlmostEqual(float(out["result"]["retencion_importe"]), 6000.00, places=2)
        self.assertAlmostEqual(float(out["result"]["cuota_neta"]), 13000.00, places=2)

    def test_irnr_rate_2015_cutoff(self):
        payload = {
            "regimen_fiscal": "irnr",
            "ejercicio": "2015",
            "participacion_pct": "100",
            "fecha_adquisicion": "2010-01-01",
            "valor_adquisicion": "0,00",
            "valor_transmision": "100.000,00",
            "retencion_pct": "0",
        }
        payload_before = dict(payload)
        payload_before["fecha_transmision"] = "2015-07-11"
        out_before = _irpf_ganancia_simulate(payload_before)
        self.assertAlmostEqual(float(out_before["result"]["cuota_ahorro_estimada"]), 20000.00, places=2)

        payload_after = dict(payload)
        payload_after["fecha_transmision"] = "2015-07-12"
        out_after = _irpf_ganancia_simulate(payload_after)
        self.assertAlmostEqual(float(out_after["result"]["cuota_ahorro_estimada"]), 19500.00, places=2)


if __name__ == "__main__":
    unittest.main()
