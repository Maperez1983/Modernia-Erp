"""El dinero se guardaba en `real`, y convertirlo mal se come los céntimos.

Todas las columnas de importe eran `real`: coma flotante de precisión simple, unos
7 dígitos significativos. Para seis dígitos con céntimos ya no llega, y el error se
acumula al sumar. Medido en producción sobre las hipotecas firmadas, la misma suma
daba 9.351.707,00 o 9.351.707,40 según cómo se sumara.

La trampa está en la conversión. `ALTER TABLE ... USING columna::numeric` arrastra
la precisión del float4 y redondea:

    real 108374.63  ->  numeric 108375
    real  82630.39  ->  numeric  82630.4

Hay que pasar por texto, `columna::text::numeric`, que usa la representación decimal
más corta que round-trip el float —el número que se tecleó— y conserva 108374.63.
En producción había 4 hipotecas, 166 movimientos y 67 comisiones de seguros que
habrían perdido los céntimos con el cast directo, sin un solo error por ningún lado.

La suma correcta, ya migrado, es 9.351.706,19 €: las otras dos cifras eran
artefactos del `real`.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GUION = (RAIZ / "scripts" / "migrar_dinero_a_numeric.py").read_text(encoding="utf-8")


class LaConversionPasaPorTextoTests(unittest.TestCase):
    def test_el_alter_usa_text_numeric(self):
        self.assertIn('::text::numeric', GUION)

    def test_no_queda_ningun_cast_directo_en_el_alter(self):
        """`USING columna::numeric` a secas es justo lo que se lleva los céntimos."""
        alters = re.findall(r"ALTER COLUMN.*?USING[^\"']*", GUION, re.S)
        self.assertTrue(alters, "no se encontró ningún ALTER en el guion")
        for alter in alters:
            with self.subTest(alter=alter[:80]):
                self.assertIn("::text::numeric", alter)


class SoloSeConvierteLoQueEsDineroTests(unittest.TestCase):
    def setUp(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "migrar_dinero", RAIZ / "scripts" / "migrar_dinero_a_numeric.py"
        )
        self.modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.modulo)

    def test_reconoce_el_dinero(self):
        for columna in (
            "importe",
            "importe_hipoteca",
            "precio",
            "precio_encargo",
            "comision",
            "prima_total",
            "total",
            "subtotal",
            "base_imponible",
            "cuota_iva",
            "honorarios",
            "entrada",
            "bruto",
            "neto",
        ):
            with self.subTest(columna=columna):
                self.assertTrue(self.modulo.es_columna_de_dinero(columna), columna)

    def test_no_toca_lo_que_no_es_dinero(self):
        """Convertir una latitud o una marca de tiempo sería otro error distinto."""
        for columna in (
            "lat",
            "lon",
            "geo_in_lat",
            "porcentaje",
            "comision_pct",
            "iva_pct",
            "confianza",
            "conciliacion_confianza",
            "ocr_confidence",
            "m2",
            "m2_min",
            "probabilidad",
            "coeficiente",
            "created_at",
            "expires_at",
            "vacaciones_dias_anuales",
            "horas_pactadas_dia",
            "vida_util_anios",
            "numero_alquileres",
        ):
            with self.subTest(columna=columna):
                self.assertFalse(self.modulo.es_columna_de_dinero(columna), columna)


class ElServidorEntiendeDecimalTests(unittest.TestCase):
    """Con las columnas en NUMERIC, Postgres devuelve Decimal en vez de float."""

    def setUp(self):
        self.servidor = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

    def test_el_serializador_json_lo_contempla(self):
        i = self.servidor.index("def _json_default")
        self.assertIn("isinstance(value, Decimal)", self.servidor[i: i + 600])

    def test_parse_money_value_lo_trata_a_la_cara(self):
        """Antes salía bien de rebote, pasando por la rama de texto."""
        i = self.servidor.index("def parse_money_value")
        bloque = self.servidor[i: i + 700]
        self.assertIn("isinstance(value, Decimal)", bloque)
        # Y antes que la rama de int/float, para no depender del orden por accidente.
        self.assertLess(
            bloque.index("isinstance(value, Decimal)"),
            bloque.index("isinstance(value, (int, float))"),
        )


if __name__ == "__main__":
    unittest.main()
