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
        self.assertIn("fetch_geocode_coordinates(normalized_addr)", server_py)
        self.assertIn('lat_raw = str(calc.get("map_lat")', server_py)
        self.assertIn("staticmap.openstreetmap.de/staticmap.php", server_py)

    def test_budget_pdf_supports_team_photo_asset(self):
        server_py = (ROOT / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn('_load_asset_logo("photos/equipo-modernia.jpg"', server_py)


if __name__ == "__main__":
    unittest.main()
