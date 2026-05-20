import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FincasBudgetPdfCoverLayoutRegressionTests(unittest.TestCase):
    def test_fincas_budget_cover_reserves_right_space_for_colegio_badge(self):
        """
        Regression: en la portada de Fincas (Carta de presentación) el título no debe
        quedar debajo del sello del colegio. Aseguramos que el código reserva un
        `right_limit` en función de `colegio_box` antes de dibujar el título.
        """
        server_py = (ROOT / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn("colegio_box = (page_width - margin_x - 340, 24, page_width - margin_x, 24 + 90)", server_py)
        self.assertIn("right_limit = colegio_box[0] - 18 if colegio_logo else (page_width - margin_x)", server_py)

    def test_fincas_budget_cover_title_splits_as_carta_de_presentacion(self):
        """
        Regression: forzamos split determinista del título cuando no cabe para evitar
        solapes con el sello.
        """
        server_py = (ROOT / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn("prefer_split=(\"CARTA DE\", \"PRESENTACIÓN\")", server_py)


if __name__ == "__main__":
    unittest.main()
