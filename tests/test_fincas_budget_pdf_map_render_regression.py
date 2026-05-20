import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FincasBudgetPdfMapRenderRegressionTests(unittest.TestCase):
    def test_budget_pdf_tries_to_render_static_map_when_address_present(self):
        """
        Regression: en la sección "MAPA / EDIFICIO" no basta con un QR; intentamos
        renderizar un mapa estático (server-side) a partir de la dirección.
        """
        server_py = (ROOT / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn("fetch_geocode_coordinates(addr_for_map)", server_py)
        self.assertIn("staticmap.openstreetmap.de/staticmap.php", server_py)


if __name__ == "__main__":
    unittest.main()
