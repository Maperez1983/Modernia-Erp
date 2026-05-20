import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FincasBudgetPdfTableAlignmentRegressionTests(unittest.TestCase):
    def test_budget_pdf_partidas_right_align_numeric_cells(self):
        """
        Regression: los importes/cantidades deben quedar dentro de su recuadro.
        Forzamos alineación a la derecha en columnas numéricas.
        """
        server_py = (ROOT / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn("_draw_cell_text(draw, \"cantidad\"", server_py)
        self.assertIn("align=\"right\")", server_py)


if __name__ == "__main__":
    unittest.main()

