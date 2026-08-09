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

import json
import re
import shutil
import subprocess
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

    def test_el_solape_se_mide_por_responsable_fecha_y_tramo(self):
        # Antes esto exigía `ev.time !== payload.hora`, la comparación por hora de
        # arranque. Se cambió por el solape de tramos; ver la clase de más abajo.
        c = APP[APP.index("const conflict = lastAgendaAllEvents"):][:900]
        self.assertIn("ev.dateKey !== payload.fecha", c)
        self.assertIn("ev.responsable !== payload.responsable", c)
        self.assertIn("agendaTramosSePisan(", c)

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


class ElResponsableNoSePierdeAlEditarTests(unittest.TestCase):
    """Editar una cita podía dejarla sin responsable sin que nadie lo tocara.

    El desplegable se llena con los usuarios activos **del servicio de la cita**, y su
    valor es el nombre de usuario. Pero hay citas guardadas a nombre de gente que ya no
    está, o escritas con el nombre completo en vez del usuario: en producción, 4 citas
    con «Miguel Angel Pérez» y 1 con «Sebastian Lallana», ninguno de los dos entre las
    opciones.

    Asignar a un `<select>` un valor que no existe lo deja en blanco —selectedIndex
    -1—, comprobado en el navegador. Al guardar se enviaba `responsable: ""` y el
    servidor lo pasa a NULL, así que abrir una de esas citas y darle a guardar le
    borraba el responsable.
    """

    def test_el_valor_guardado_se_anade_a_la_lista_si_no_estaba(self):
        self.assertIn("const asegurarOpcionDeResponsable", APP)
        c = cuerpo("const openActionEditor")
        self.assertIn("asegurarOpcionDeResponsable(actionModalResponsable, ev.responsable);", c)

    def test_se_anade_antes_de_asignar_el_valor(self):
        """Si se asignara primero, el select ya se habría quedado en blanco."""
        c = cuerpo("const openActionEditor")
        self.assertLess(
            c.index("asegurarOpcionDeResponsable(actionModalResponsable"),
            c.index('actionModalResponsable.value = ev.responsable || ""'),
        )

    def test_se_avisa_de_que_ese_responsable_ya_no_esta(self):
        c = cuerpo("const asegurarOpcionDeResponsable")
        self.assertIn("ya no está en el equipo", c)

    def test_sigue_sin_arrastrarse_cuando_la_cita_no_tiene_responsable(self):
        """El arreglo no puede reabrir el fallo antiguo: sin responsable, en blanco."""
        c = cuerpo("const asegurarOpcionDeResponsable")
        self.assertIn("if (!select || !valor) return;", c)

    def test_el_otro_editor_de_citas_tambien_lo_conserva(self):
        """Hay DOS editores de cita y arreglé sólo uno.

        `openCrmAgendaEditModal`, el de la pantalla Act./Citas, construye su propio
        modal y hacía esto:

            if (nextResp && responsableSelect.value !== nextResp)
                responsableSelect.value = "";

        Es decir, vaciaba el desplegable **a propósito** cuando el valor guardado no
        estaba entre las opciones, y al guardar enviaba `responsable: ""`. Encontrado
        probando en producción: abrí una de las nueve «Firmar encargo» de Estudio
        Velázquez y el responsable salía en blanco teniendo «Miguel Angel Pérez».
        """
        c = cuerpo("const openCrmAgendaEditModal")
        self.assertIn("asegurarOpcionDeResponsable(responsableSelect, nextResp);", c)
        self.assertNotIn(
            'if (nextResp && responsableSelect.value !== nextResp) responsableSelect.value = "";', c
        )

    def test_los_dos_editores_usan_el_mismo_ayudante(self):
        self.assertEqual(APP.count("asegurarOpcionDeResponsable(") , 2)


class ElSolapeMiraElTramoNoSoloLaHoraDeArranqueTests(unittest.TestCase):
    """El aviso comparaba `ev.time !== payload.hora`: solo la hora de arranque.

    Una visita de 10:00 a 11:00 y otra a las 10:30 con el mismo responsable se
    guardaban sin decir nada. En producción hay dos casos así, encontrados cruzando
    la tabla el 2026-08-08: SLallana con 09:30-10:30 contra una cita a las 10:00, y
    D.Garcia con 10:10-10:30 contra 10:20-10:25. 95 de las 166 citas de inmobiliaria
    llevan hora de fin, que era justo la que no se miraba.

    A la cita sin hora de fin no se le inventa duración: se trata como un instante.
    Suponerle, por ejemplo, una hora llenaría de avisos falsos una agenda donde 71
    citas no la tienen.
    """

    CASOS = [
        ("10:00", "11:00", "10:30", "11:30", True, "dos tramos que se pisan"),
        ("09:30", "10:30", "10:00", "", True, "un instante dentro de un tramo"),
        ("10:10", "10:30", "10:20", "10:25", True, "un tramo dentro de otro"),
        ("10:00", "11:00", "11:00", "12:00", False, "pegadas: una acaba donde empieza la otra"),
        ("10:00", "11:00", "09:00", "10:00", False, "la anterior acaba al empezar esta"),
        ("10:00", "", "10:00", "", True, "dos instantes a la misma hora"),
        ("10:00", "", "10:30", "", False, "dos instantes distintos"),
        ("10:00", "11:00", "12:00", "13:00", False, "sin relación"),
        ("10:00", "09:00", "10:30", "", False, "hora de fin anterior al inicio: se ignora"),
        ("", "", "10:00", "11:00", False, "sin hora no se compara"),
    ]

    def test_la_comparacion_usa_el_tramo(self):
        self.assertIn("agendaTramosSePisan(payload.hora, payload.hora_fin, ev.time, ev.timeEnd)", APP)
        self.assertNotIn("if (ev.time !== payload.hora) return false;", APP)

    def test_el_evento_lleva_el_asunto_para_poder_nombrar_el_choque(self):
        self.assertIn('asunto: row.asunto || "",', APP)

    def test_los_diez_casos(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node no está disponible")
        trozo = APP[APP.index("const normalizeAgendaTimeString"):
                    APP.index("const formatAgendaTimeFromMinutes")]
        casos = json.dumps([list(c[:4]) for c in self.CASOS])
        script = (
            trozo
            + "const casos = " + casos + ";"
            + "console.log(JSON.stringify(casos.map((c) => agendaTramosSePisan(c[0], c[1], c[2], c[3]))));"
        )
        salida = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
        obtenido = json.loads(salida.stdout.strip())
        for (a1, a2, b1, b2, esperado, desc), real in zip(self.CASOS, obtenido):
            with self.subTest(caso=desc):
                self.assertEqual(real, esperado, f"{a1}-{a2} contra {b1}-{b2}: {desc}")


if __name__ == "__main__":
    unittest.main()
