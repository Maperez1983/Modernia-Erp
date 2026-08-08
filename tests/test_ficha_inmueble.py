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


class LosCamposDeLaFichaTienenNombreTests(unittest.TestCase):
    """38 de los 39 campos de la ficha no tenían nombre accesible.

    Las filas se pintan así:

        <div class="tc-fieldrow">
          <div class="tc-fieldlabel">Número</div>
          <div class="tc-fieldvalue"><input data-field="direccion_numero"></div>
        </div>

    La etiqueta es un `<div>`, no un `<label>`, y no hay `for` ni
    `aria-labelledby`. En pantalla se ve etiquetado; para un lector de pantalla los
    38 campos del formulario principal del módulo eran «cuadro de texto» a secas. Y
    pulsar el texto no llevaba el foco al campo, que es lo que hace un `<label>` de
    verdad y lo que la gente espera.

    Primero lo resolví con `aria-labelledby` apuntando al div, y el campo pasó a
    llamarse «OperaciónCLAVE»: la etiqueta lleva dentro una píldora («Clave»,
    «Obligatorio para cierre») que es una anotación, no parte del nombre. Se toma el
    texto sin ella.
    """

    def test_cada_campo_recibe_su_nombre(self):
        self.assertIn('input.setAttribute("aria-label", nombreAccesible)', APP)

    def test_el_nombre_no_arrastra_la_pildora(self):
        i = APP.index("const nombreAccesible = (() => {")
        cuerpo = APP[i: i + 400]
        self.assertIn('querySelectorAll(".editable-field-hint").forEach((n) => n.remove())', cuerpo)

    def test_pulsar_la_etiqueta_enfoca_el_campo(self):
        """Es lo que haría un <label> y lo que la gente espera al pulsar el texto."""
        i = APP.index("label.addEventListener(\"click\"")
        self.assertIn("input.focus();", APP[i: i + 260])

    def test_pulsar_la_pildora_no_enfoca(self):
        """La píldora es informativa; llevar el foco al pulsarla despistaría."""
        i = APP.index("label.addEventListener(\"click\"")
        self.assertIn('ev.target.closest(".editable-field-hint")', APP[i: i + 260])

    def test_solo_en_la_maqueta_que_usa_divs(self):
        """La otra maqueta usa <h3> y no necesita el apaño del clic."""
        i = APP.index("const nombreAccesible")
        self.assertIn("if (useTecnoLayout) {", APP[i: i + 900])


class AbrirInmobiliariaNoCargaElHubDeRrhhTests(unittest.TestCase):
    """Abrir el CRM inmobiliario pedía más datos de RRHH que de inmuebles.

    Medido en el navegador al entrar en el módulo: 34 peticiones, de las cuales 8
    eran de RRHH, fichaje y contratos, y solo 7 de inmobiliaria. La causa:
    `loadWorkspaceDetail` —que corre en cualquier vista— pintaba siempre
    `renderWorkspaceCopilotHub()` y `renderWorkspaceRrhhHub()`, y esos dos hubs
    disparan sus propias cargas aunque su panel esté oculto.

    Ahora solo se pintan si su panel está a la vista. El de RRHH ya se recargaba al
    entrar en su vista (`refreshWorkspaceRrhh` en `setWorkspaceView`); el del
    copiloto no se repintaba en ningún sitio, así que hubo que añadirlo al entrar en
    «motores» o habría quedado vacío.

    Comprobado después en el navegador: RRHH entra con sus pestañas y el copiloto se
    pinta. Quedan 6 peticiones de fichaje que vienen por otro camino —el widget de
    registro horario— y esas no se tocan aquí.
    """

    def test_los_hubs_solo_se_pintan_si_se_ven(self):
        i = APP.index("if (workspaceCopilotHub?.offsetParent) {")
        cuerpo = APP[i: i + 260]
        self.assertIn("renderWorkspaceCopilotHub();", cuerpo)
        self.assertIn("if (workspaceRrhhHub?.offsetParent) {", cuerpo)

    def test_ya_no_se_pintan_siempre(self):
        self.assertNotIn("  renderWorkspaceCopilotHub();\n  renderWorkspaceRrhhHub();", APP)

    def test_el_copiloto_se_repinta_al_entrar_en_motores(self):
        """No se repintaba en ningún sitio: sin esto quedaría vacío."""
        i = APP.index('if (normalized === "motores") {')
        self.assertIn("renderWorkspaceCopilotHub();", APP[i: i + 500])

    def test_rrhh_ya_se_recargaba_al_entrar(self):
        i = APP.index('if (normalized === "rrhh") {')
        self.assertIn("refreshWorkspaceRrhh()", APP[i: i + 260])
