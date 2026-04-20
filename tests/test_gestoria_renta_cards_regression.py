import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GestoriaRentaCardsRegressionTests(unittest.TestCase):
    def test_gestoria_renta_cards_docs_order_by_casts_fecha_to_text(self):
        """
        Regression: en Postgres, `COALESCE(fecha, '')` puede fallar si `fecha` no es TEXT.
        Aseguramos que el ORDER BY en `/api/gestoria_renta_cards` castea `fecha` a TEXT.
        """
        server_py = (ROOT / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn("CAST(fecha AS TEXT)", server_py)


if __name__ == "__main__":
    unittest.main()

