"""Detalles de la ficha del inmueble y del orden del listado.

Tres cosas vistas abriendo la ficha en el navegador:

- **Los metros salían sin unidad.** La línea de características ponía «92 · 3 hab. ·
  2 baños»: los dos últimos dicen de qué son y el primero no. En el resto de la
  aplicación los metros sí llevan su «m²».
- **«✓ / ✗» como valor de un indicador.** Un aspa no distingue «no está
  planificado» de «ha fallado algo», y un lector de pantalla lee el símbolo, no lo
  que significa. Ahora dicen «Sí», «No» y «Pendiente».
- **El precio se salía de la pantalla en el listado.** Al llenar las tres columnas
  que estaban vacías, «Precio encargo» —que iba la última— quedaba fuera a 1280 px.
  Se reordena por lo que se mira primero: dónde está, por cuánto y en qué operación.
  La que se sale ahora es Subtipología, que la tienen 18 de los 86.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")


def tabla_listado():
    i = APP.index("const buildCrmInmueblesDenseTableNode")
    return APP[i: APP.index("\nconst ", i + 10)]


class LaFichaDiceLasUnidadesTests(unittest.TestCase):
    def test_los_metros_llevan_su_unidad(self):
        self.assertIn('`${formatDisplayCell("m2", inmueble.m2, "")} m²`', APP)

    def test_sin_metros_no_se_pinta_un_m2_suelto(self):
        """`0 m²` o ` m²` sin número es peor que no poner nada."""
        i = APP.index('inmueble.m2 ? `${formatDisplayCell("m2"')
        self.assertIn("inmueble.m2 ?", APP[i - 40: i + 20])

    def test_habitaciones_y_banos_siguen_diciendo_lo_suyo(self):
        self.assertIn('`${inmueble.habitaciones} hab.`', APP)
        self.assertIn('`${inmueble.banos} baños`', APP)


class LosIndicadoresSeLeenTests(unittest.TestCase):
    def test_ya_no_hay_aspas_en_los_indicadores(self):
        i = APP.index('{ label: "Planificado", value:')
        bloque = APP[i: i + 400]
        self.assertNotIn("✗", bloque)
        self.assertNotIn("✓", bloque)

    def test_planificado_dice_si_o_no(self):
        self.assertIn('{ label: "Planificado", value: isPlanned ? "Sí" : "No" }', APP)

    def test_la_valoracion_que_falta_es_pendiente_no_un_no(self):
        """«No» sonaría a que se decidió no valorar; lo que pasa es que falta."""
        self.assertIn('{ label: "Valoración", value: hasValoracion ? "Sí" : "Pendiente" }', APP)


class ElListadoOrdenaPorLoQueSeMiraTests(unittest.TestCase):
    ORDEN = ["", "Inmueble", "Precio encargo", "Necesidad de vta.",
             "Propietario", "Inmueble: Tel. pr.", "Subtipología inm."]

    def test_las_cabeceras_van_en_ese_orden(self):
        t = tabla_listado()
        i = t.index('"Inmueble",')
        bloque = t[i - 60: t.index("].forEach((label)", i)]
        encontrados = re.findall(r'"([^"]*)"', bloque)
        self.assertEqual([e for e in encontrados if e in self.ORDEN or e == ""], self.ORDEN)

    def test_las_celdas_van_en_el_mismo_orden_que_las_cabeceras(self):
        """Si se desordenan, cada dato aparece bajo el título de otro."""
        t = tabla_listado()
        celdas = re.findall(r"tr\.appendChild\((\w+)\);", t)
        self.assertEqual(celdas, ["selectTd", "inmuebleTd", "precioTd", "necTd", "propTd", "telTd", "subtipoTd"])

    def test_el_precio_va_justo_despues_de_la_direccion(self):
        t = tabla_listado()
        celdas = re.findall(r"tr\.appendChild\((\w+)\);", t)
        self.assertEqual(celdas[celdas.index("inmuebleTd") + 1], "precioTd")


if __name__ == "__main__":
    unittest.main()
