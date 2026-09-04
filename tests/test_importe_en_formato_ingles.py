"""Un importe pegado de una factura en inglés se guardaba mil veces más pequeño.

`parse_money_value` daba por hecho que con los dos separadores el formato era español
—puntos de millar, coma decimal—, así que "1,234.56" acababa en 1,23 €. Se guardaba con
un «ok» y sin aviso: el gasto entra en la contabilidad de la comunidad con dos euros
menos de tres cifras y nadie se entera hasta que no cuadra el ejercicio.

Y pasa: los extractos bancarios, los Excel exportados con configuración inglesa y las
facturas de proveedores extranjeros vienen así, y el importe se pega tal cual.

El criterio ahora es el separador que va **el último**, que es el decimal. Resuelve los
dos formatos sin preguntar y no cambia nada de lo que ya funcionaba, porque en un
importe español la coma siempre va detrás del punto.
"""

import os
import unittest

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("POSTGRES_URL", "")

from web.server import parse_money_value  # noqa: E402


class ElImporteSeLeeComoLoTecleaLaGenteTests(unittest.TestCase):
    def test_formato_espanol(self):
        for texto, esperado in (
            ("1.234,56", 1234.56),
            ("20.000,50", 20000.50),
            ("1.234.567,89", 1234567.89),
            ("1234,56", 1234.56),
            ("1.234", 1234.0),
            ("0,5", 0.5),
        ):
            with self.subTest(texto=texto):
                self.assertAlmostEqual(parse_money_value(texto), esperado, places=2)

    def test_formato_ingles(self):
        """Lo que se pega de un extracto o de un Excel en inglés."""
        for texto, esperado in (
            ("1,234.56", 1234.56),
            ("20,000.50", 20000.50),
            ("1,234,567.89", 1234567.89),
        ):
            with self.subTest(texto=texto):
                self.assertAlmostEqual(parse_money_value(texto), esperado, places=2)

    def test_el_caso_que_fallaba(self):
        """Mil veces menos, y con un «ok» por respuesta."""
        self.assertNotAlmostEqual(parse_money_value("1,234.56"), 1.23, places=2)
        self.assertAlmostEqual(parse_money_value("1,234.56"), 1234.56, places=2)

    def test_lo_demas_sigue_igual(self):
        for texto, esperado in (
            ("1234.56", 1234.56),
            ("€1234", 1234.0),
            ("1 234,56", 1234.56),
            (" 1234 ", 1234.0),
            ("-1234,56", -1234.56),
            ("", 0.0),
            (None, 0.0),
            (1234.56, 1234.56),
        ):
            with self.subTest(texto=texto):
                self.assertAlmostEqual(parse_money_value(texto), esperado, places=2)


if __name__ == "__main__":
    unittest.main()
