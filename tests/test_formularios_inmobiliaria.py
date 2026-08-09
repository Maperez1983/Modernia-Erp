"""Los formularios del CRM inmobiliario piden lo que no puede faltar.

Revisión de botonaje, campos y usabilidad del 2026-08-09. De 215 controles del
módulo, ninguno estaba muerto, no había botones sin nombre ni campos con el tipo
equivocado, y los dos borrados confirman antes de actuar. Salieron tres cosas:

  - `crmAgendaDay` era un selector de fecha suelto entre las flechas, sin etiqueta
    de ningún tipo. Un lector de pantalla decía «fecha» y nada más.
  - El alta de captación no exigía la «Necesidad» (venta o alquiler). Ésa es la raíz
    de que 78 inmuebles llegaran sin tipo de operación y hubiera que deducirlo del
    nombre del inmueble o dejarlo en blanco.
  - El formulario de pedidos no exigía **nada**: se podía crear un pedido entero en
    blanco, sin cliente.

Ojo con los falsos positivos: otros ocho campos parecían no tener nombre accesible y
lo tienen —la etiqueta los envuelve, que es válido—, y dos son campos ocultos.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")


def campos_del_formulario(form_id):
    i = HTML.index(f'id="{form_id}"')
    fin = HTML.index("</form>", i)
    return HTML[i:fin]


class LoQueNoPuedeFaltarSePideTests(unittest.TestCase):
    def test_una_captacion_nace_sabiendo_si_es_venta_o_alquiler(self):
        bloque = campos_del_formulario("crmCaptacionCreateForm")
        m = re.search(r'<select name="necesidad_venta_alquiler"([^>]*)>', bloque)
        self.assertIsNotNone(m, "falta el campo de necesidad en el alta")
        self.assertIn("required", m.group(1))

    def test_la_direccion_sigue_siendo_obligatoria(self):
        bloque = campos_del_formulario("crmCaptacionCreateForm")
        m = re.search(r'<input([^>]*name="direccion"[^>]*)>', bloque)
        self.assertIsNotNone(m)
        self.assertIn("required", m.group(1))

    def test_un_pedido_no_puede_nacer_sin_cliente(self):
        bloque = campos_del_formulario("inmuebleDemandaForm")
        m = re.search(r'<select id="inmuebleDemandaCliente"([^>]*)>', bloque)
        self.assertIsNotNone(m)
        self.assertIn("required", m.group(1))

    def test_una_cita_no_puede_nacer_sin_fecha(self):
        bloque = campos_del_formulario("crmAgendaForm")
        m = re.search(r'<input([^>]*name="fecha"[^>]*)>', bloque)
        self.assertIsNotNone(m)
        self.assertIn("required", m.group(1))


class TodoControlTieneNombreTests(unittest.TestCase):
    def test_el_selector_de_dia_de_la_agenda_se_llama_de_algo(self):
        m = re.search(r'<input id="crmAgendaDay"([^>]*)>', HTML)
        self.assertIsNotNone(m)
        self.assertIn("aria-label", m.group(1))


class LosBorradosAvisanTests(unittest.TestCase):
    """Borrar un inmueble arrastra su captación y sus documentos: hay que decirlo."""

    def test_borrar_un_inmueble_confirma_y_explica_el_arrastre(self):
        i = APP.index("inmueble_delete")
        previo = APP[max(0, i - 1600):i]
        self.assertIn("confirm(", previo)
        self.assertIn("eliminará también", previo)

    def test_borrar_una_cita_confirma(self):
        i = APP.index("acciones_delete")
        self.assertIn("confirm(", APP[max(0, i - 1600):i])


if __name__ == "__main__":
    unittest.main()
