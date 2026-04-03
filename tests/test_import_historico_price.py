import unittest

from scripts.import_inmuebles_vendidos_historial import find_best_sale_price


class TestFindBestSalePrice(unittest.TestCase):
    def test_prefers_total_over_arras(self) -> None:
        text = (
            "PRECIO: El precio total de compraventa queda fijado en 46.000 euros.\n"
            "En concepto de arras/señal se entrega la cantidad de 3.000 euros.\n"
        )
        self.assertEqual(find_best_sale_price(text), 46000.0)

    def test_ignores_small_amounts(self) -> None:
        text = "En concepto de arras/señal se entrega la cantidad de 3.000 euros."
        self.assertIsNone(find_best_sale_price(text))


if __name__ == "__main__":
    unittest.main()
