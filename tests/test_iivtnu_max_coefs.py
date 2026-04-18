import unittest
from datetime import date

from web.server import _iivtnu_max_coefs_for_devengo


class IivtnuMaxCoefsTests(unittest.TestCase):
    def test_2026_january_uses_rdl_16_2025_until_27(self):
        table, src = _iivtnu_max_coefs_for_devengo(date(2026, 1, 15))
        self.assertAlmostEqual(float(table.get("lt1") or 0.0), 0.16, places=6)
        self.assertIn("RDL 16/2025", str((src or {}).get("source_label") or ""))

    def test_2026_after_jan_28_reverts_to_rdl_8_2023(self):
        table, src = _iivtnu_max_coefs_for_devengo(date(2026, 2, 1))
        self.assertAlmostEqual(float(table.get("lt1") or 0.0), 0.15, places=6)
        self.assertIn("RDL 8/2023", str((src or {}).get("source_label") or ""))

