"""La agenda no puede avisar de solapes solo de lo que se ve.

El usuario pidió revisar «que no haya datos de otras citas que persistan». El modal
de cita estaba bien: sus once campos se limpian tanto al crear como al editar, y los
comentarios del código recogen un fallo antiguo de ese tipo ya corregido —el
responsable de la cita anterior se quedaba pegado.

Lo que sí estaba mal era lo contrario: **el aviso de solape solo miraba las citas
visibles**. `lastAgendaEvents` guardaba la lista ya filtrada, y es la que usaba el
guardado para avisar de «existe otra cita con el mismo responsable y hora». Con un
filtro de servicio puesto, o desde la agenda de un inmueble concreto —que solo carga
las suyas—, dos citas del mismo responsable a la misma hora se guardaban sin decir
nada. El aviso fallaba justo cuando más falta hace: cuando no tienes delante la cita
con la que chocas.

Y un segundo detalle de la misma familia: el filtro de servicio vive en un `Map`
indexado por el contenedor, así que al reutilizar el mismo contenedor para otra ficha
se quedaba puesto, y la agenda salía vacía sin explicar por qué.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")


def cuerpo(nombre, fin="\nconst "):
    i = APP.index(nombre)
    return APP[i: APP.index(fin, i + 10)]


class ElAvisoDeSolapeMiraTodasLasCitasTests(unittest.TestCase):
    def test_se_guarda_la_lista_sin_filtrar(self):
        self.assertIn("let lastAgendaAllEvents = [];", APP)
        self.assertIn("lastAgendaAllEvents = Array.isArray(events) ? events : [];", APP)

    def test_el_solape_se_busca_contra_todas(self):
        self.assertIn("const conflict = lastAgendaAllEvents.find((ev) => {", APP)

    def test_ya_no_se_busca_contra_lo_filtrado(self):
        """Era el fallo: `lastAgendaEvents` es la lista que se está pintando."""
        self.assertNotIn("const conflict = lastAgendaEvents.find", APP)

    def test_la_lista_filtrada_sigue_existiendo_para_pintar(self):
        """No se quita: la vista sí debe respetar el filtro."""
        self.assertIn("lastAgendaEvents = filteredEvents;", APP)

    def test_el_solape_se_mide_por_responsable_fecha_y_hora(self):
        c = APP[APP.index("const conflict = lastAgendaAllEvents"):][:900]
        self.assertIn("ev.dateKey !== payload.fecha", c)
        self.assertIn("ev.time !== payload.hora", c)
        self.assertIn("ev.responsable === payload.responsable", c)

    def test_editar_una_cita_no_choca_consigo_misma(self):
        c = APP[APP.index("const conflict = lastAgendaAllEvents"):][:900]
        self.assertIn("if (editId && ev.id === editId) return false;", c)


class ElFiltroNoSeQuedaPegadoTests(unittest.TestCase):
    def test_se_suelta_si_ya_no_aplica(self):
        self.assertIn("!availableServices.includes(state.serviceFilter)", APP)
        i = APP.index("!availableServices.includes(state.serviceFilter)")
        self.assertIn('state.serviceFilter = "all";', APP[i: i + 200])

    def test_se_comprueba_antes_de_filtrar(self):
        i = APP.index("!availableServices.includes(state.serviceFilter)")
        j = APP.index("const filteredEvents = events.filter")
        self.assertLess(i, j)


class ElModalDeCitaSeLimpiaTests(unittest.TestCase):
    """Esto ya estaba bien; se fija para que siga estándolo."""

    CAMPOS = ["actionModalClienteInput", "actionModalClienteId", "actionModalServicioSelect",
              "actionModalFecha", "actionModalHora", "actionModalHoraFin", "actionModalTipo",
              "actionModalResponsable", "actionModalEstado", "actionModalRecordatorio",
              "actionModalNotas"]

    def test_los_once_campos_se_tocan_al_crear(self):
        c = cuerpo("const openActionCreator")
        for campo in self.CAMPOS:
            with self.subTest(campo=campo):
                self.assertIn(campo, c)

    def test_los_once_campos_se_tocan_al_editar(self):
        c = cuerpo("const openActionEditor")
        for campo in self.CAMPOS:
            with self.subTest(campo=campo):
                self.assertIn(campo, c)

    def test_el_responsable_no_se_hereda(self):
        """Fallo antiguo: al editar una cita sin responsable se quedaba el de la
        cita anterior."""
        self.assertIn('actionModalResponsable.value = ev.responsable || "";', APP)

    def test_el_tipo_se_resetea_aunque_el_select_no_tenga_la_opcion(self):
        c = cuerpo("const openActionCreator")
        self.assertIn("actionModalTipo.selectedIndex = 0;", c)

    def test_al_cerrar_no_queda_nada_del_registro_anterior(self):
        c = cuerpo("const closeActionEditor")
        self.assertIn('state.actionModalEditId = "";', c)
        self.assertIn("state.actionModalEditSnapshot = null;", c)
        self.assertIn("state.actionModalContext = null;", c)


if __name__ == "__main__":
    unittest.main()
