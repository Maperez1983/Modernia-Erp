import unittest


from web.server import _iivtnu_load_params_spain_hacienda_excel2022


class TestIivtnuHaciendaExcel2022Catalog(unittest.TestCase):
    def test_contains_expected_entries(self):
        data = _iivtnu_load_params_spain_hacienda_excel2022() or {}
        self.assertIsInstance(data, dict)
        years = data.get("years") or {}
        self.assertIsInstance(years, dict)
        y2025 = years.get("2025") or {}
        self.assertIsInstance(y2025, dict)

        # Málaga capital (INE 29067)
        malaga = y2025.get("29067")
        self.assertIsInstance(malaga, list)
        self.assertGreater(float(malaga[0] or 0), 0)
        self.assertAlmostEqual(float(malaga[0]), 29.0, places=2)

        # Palma (INE 07040)
        palma = y2025.get("07040")
        self.assertIsInstance(palma, list)
        self.assertGreater(float(palma[0] or 0), 0)
        self.assertAlmostEqual(float(palma[0]), 21.5, places=2)


if __name__ == "__main__":
    unittest.main()

