"""El dashboard de hipotecas abría vacío pidiendo un año.

Entrabas a Financiaciones y no veías ni una cifra: un desplegable en "Año ·
Elegir…" y el texto "Selecciona un ejercicio para cargar métricas, gráficos y
tarjetas". El primer clic de cada visita era decirle a la aplicación algo que
ella ya sabía: la petición inicial devuelve `available_years`, así que en el
momento de pedir el año ya tenía la lista delante.

Nadie entra a un dashboard para elegir un año; entra para ver cómo va.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")


class AbreEnElAnoEnCursoTests(unittest.TestCase):
    def _bloque(self):
        i = APP.index("const loadHipotecaDashboard = () => {")
        return APP[i: i + 4000]

    def test_elige_el_ano_en_curso_si_hay_datos(self):
        bloque = self._bloque()
        self.assertIn("new Date().getFullYear()", bloque)
        self.assertIn("availableYears.includes(enCurso)", bloque)

    def test_si_no_hay_ano_en_curso_coge_el_mas_reciente(self):
        self.assertIn("availableYears.slice().sort((a, b) => Number(b) - Number(a))[0]", self._bloque())

    def test_recarga_con_el_ano_ya_puesto(self):
        bloque = self._bloque()
        self.assertIn("syncHipotecaDashboardYearSelect(hipotecaDashboardYearSelect, availableYears, porDefecto)", bloque)
        self.assertIn("loadHipotecaDashboard();", bloque)

    def test_no_se_llama_a_si_mismo_sin_fin(self):
        """La recarga solo ocurre cuando no había año pedido, y deja uno puesto.

        Si el selector no se rellenara antes de recargar, `requestedYear` seguiría
        vacío en la vuelta siguiente y la pantalla entraría en bucle.
        """
        bloque = self._bloque()
        i = bloque.index("if (!requestedYear) {")
        rama = bloque[i: bloque.index("loadHipotecaDashboard();", i)]
        self.assertIn("syncHipotecaDashboardYearSelect", rama)

    def test_ya_no_pide_elegir_un_ejercicio(self):
        self.assertNotIn("Selecciona un ejercicio para cargar", HTML)
        self.assertNotIn("Elige un año para cargar el dashboard.", APP)
        self.assertNotIn("Año · Elegir…", APP)
        self.assertNotIn("Año · Elegir…", HTML)

    def test_sin_datos_lo_dice_en_vez_de_pedir_un_ano(self):
        bloque = self._bloque()
        self.assertIn("Todavía no hay hipotecas firmadas", bloque)

    def test_se_puede_volver_a_ver_todos_los_anos(self):
        """La opción vacía sigue existiendo: elegir año es una opción, no un peaje."""
        self.assertIn('createOption("", "Año · Todos")', APP)


if __name__ == "__main__":
    unittest.main()
