import unittest
from datetime import date

from web.server import (
    IRPF_BASE_AHORRO_SCALE,
    _irpf_rental_reduction_pct,
    _irpf_savings_scale_for_year,
    _irpf_tax_progressive,
)


class IrpfSimulatorsTests(unittest.TestCase):
    def test_irpf_savings_tax_progressive_2024(self):
        _, brackets, _ = _irpf_savings_scale_for_year(2024)
        self.assertEqual(brackets, IRPF_BASE_AHORRO_SCALE[2024])
        # 6.000 * 19% + 4.000 * 21% = 1.980
        self.assertEqual(_irpf_tax_progressive(10000, brackets), 1980.0)

    def test_irpf_savings_scale_fallback(self):
        scale_year, _, assumed = _irpf_savings_scale_for_year(2026)
        self.assertTrue(assumed)
        self.assertEqual(scale_year, 2025)

    def test_irpf_rental_reduction_contract_before_cutoff(self):
        pct, reason = _irpf_rental_reduction_pct({"fecha_contrato": date(2022, 1, 1).isoformat()}, 2025)
        self.assertEqual(pct, 60.0)
        self.assertIn("26/05/2023", reason)

    def test_irpf_rental_reduction_zone_tensioned_reduction(self):
        payload = {
            "fecha_contrato": date(2024, 2, 1).isoformat(),
            "zona_tensionada": True,
            "rebaja_renta_pct": "5",
        }
        pct, reason = _irpf_rental_reduction_pct(payload, 2025)
        self.assertEqual(pct, 90.0)
        self.assertIn("rebaja", reason.lower())
