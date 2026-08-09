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


class LoQueOcupaUnTramoEsUnaCitaTests(unittest.TestCase):
    """Una firma en notaría de 10:30 a 13:30 no puede vivir en «Actividades».

    La clasificación miraba si la palabra «cita» aparecía en el tipo o el asunto, y
    la hora sólo si ambos venían vacíos. Encontrado probando en producción el
    2026-08-09: con el preset «Citas Equipo (caducadas)», buscar «encargo» daba «Sin
    acciones», y las nueve aparecían al pasar a «Actividades».

    Mirando los datos reales, el discriminador es el **tramo**: 12 acciones tienen
    hora de inicio y de fin y estaban de actividades —firmas de contrato, notaría y
    asesoramientos—, mientras que las 46 que se quedan como actividad —«Seguimiento»
    (27) y «Llamada» (19)— llevan hora de aviso pero no de fin y son tareas de
    verdad. Mi primera lectura, «45 citas mal clasificadas», era exagerada.

    La regla vive en un único sitio porque había DOS copias —la de la agenda y la de
    los contadores de la portada— y afinar sólo una habría hecho que el contador
    dijera un número y la lista que abre, otro.
    """

    CASOS = [
        ({"tipo": "Cita de adquisición", "hora": "10:00", "hora_fin": "11:00"}, True,
         "una cita de las de siempre"),
        ({"tipo": "Seguimiento", "hora": "10:00", "hora_fin": ""}, False,
         "seguimiento sin hora de fin: es una tarea"),
        ({"tipo": "Llamada", "hora": "10:00", "hora_fin": ""}, False,
         "llamada sin hora de fin: es una tarea"),
        ({"tipo": "Firma Notaria", "hora": "10:30", "hora_fin": "13:30"}, True,
         "tres horas en la notaría son una cita"),
        ({"tipo": "Firma contrato alquiler", "hora": "18:30", "hora_fin": "19:30"}, True,
         "firma de contrato con tramo"),
        ({"tipo": "contrato arrendamiento", "hora": "18:30", "hora_fin": "19:00"}, True,
         "contrato de arrendamiento con tramo"),
        ({"tipo": "Asesoramiento renta antigua", "hora": "17:00", "hora_fin": "17:30"}, True,
         "asesoramiento con tramo"),
        ({"tipo": "Post-aceptación", "hora": "18:30", "hora_fin": "19:30"}, True,
         "post-aceptación con tramo"),
        ({"tipo": "Post-aceptación", "hora": "10:00", "hora_fin": ""}, False,
         "la misma sin tramo se queda de tarea"),
        ({"tipo": "Actividad comercial", "hora": "10:00", "hora_fin": "11:00"}, False,
         "si el tipo dice actividad, manda lo escrito"),
        ({"tipo": "", "asunto": "", "hora": "10:00", "hora_fin": ""}, True,
         "sin tipo pero con hora: se respeta el comportamiento anterior"),
        ({"tipo": "", "asunto": "", "hora": "", "hora_fin": ""}, False, "sin nada"),
    ]

    def test_la_regla_vive_en_un_solo_sitio(self):
        self.assertEqual(APP.count("const esCitaPorSuTramo = (row) => {"), 1)
        # Tira de ella la agenda y los dos contadores de la portada.
        self.assertGreaterEqual(APP.count("esCitaPorSuTramo("), 3)

    def test_no_queda_ninguna_copia_de_la_regla_vieja(self):
        """Había dos `normalizeTipoKey` con el mismo cuerpo duplicado.

        Ojo con no pasarse: `resolveAgendaTipoKey` se le parece pero es otra cosa
        —reparte la etiqueta CITA / LLAM. / WA / MAIL / TAREA y sólo recibe el tipo,
        no la fila, así que no puede mirar la hora de fin—. Ésa se queda como está.
        """
        self.assertNotIn(
            'const hasHora = Boolean(String(row?.hora || row?.hora_fin || "").trim());', APP)
        # Ninguna pantalla vuelve a declarar la suya con cuerpo propio.
        self.assertEqual(APP.count("const normalizeTipoKey = (row) => {"), 0)

    def test_los_doce_casos(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node no está disponible")
        i = APP.index("const esCitaPorSuTramo = (row) => {")
        prof, fin = 0, -1
        for k in range(APP.index("{", i), len(APP)):
            if APP[k] == "{":
                prof += 1
            elif APP[k] == "}":
                prof -= 1
                if prof == 0:
                    fin = k + 1
                    break
        script = (
            'const normalizeSimple = (s) => String(s||"").normalize("NFD")'
            '.replace(/[\\u0300-\\u036f]/g,"").toLowerCase().trim();\n'
            + APP[i:fin] + ";\n"
            + "const casos = " + json.dumps([c[0] for c in self.CASOS]) + ";\n"
            + "console.log(JSON.stringify(casos.map(esCitaPorSuTramo)));"
        )
        salida = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
        for (fila, esperado, desc), real in zip(self.CASOS, json.loads(salida.stdout.strip())):
            with self.subTest(caso=desc):
                self.assertEqual(real, esperado, f"{fila.get('tipo')} {fila.get('hora')}-{fila.get('hora_fin')}: {desc}")


class ElEstadoDeUnaCitaSeGuardaCanonicoTests(unittest.TestCase):
    """El desplegable ofrece tres estados; la API aceptaba cualquier texto.

    En producción convivían «Completada» (140), «Completado» (1), «Hecho» (1) y una
    fila sin estado. Tres de 166, pero cualquier filtro o recuento que compare por
    texto se las pierde en silencio.
    """

    def setUp(self):
        import os
        os.environ.setdefault("DATABASE_URL", "")
        from web.server import normalizar_estado_de_accion
        self.normaliza = normalizar_estado_de_accion

    def test_las_formas_que_la_gente_escribe_acaban_en_la_canonica(self):
        for entrada, esperado in (
            ("Completado", "Completada"), ("completado", "Completada"),
            ("Hecho", "Completada"), ("hecha", "Completada"),
            ("Realizada", "Completada"), ("Cerrado", "Completada"),
            ("Cancelado", "Cancelada"), ("anulada", "Cancelada"),
            ("Pendiente", "Pendiente"), ("abierta", "Pendiente"),
        ):
            with self.subTest(entrada=entrada):
                self.assertEqual(self.normaliza(entrada), esperado)

    def test_vacio_es_pendiente(self):
        for entrada in ("", "   ", None):
            with self.subTest(entrada=entrada):
                self.assertEqual(self.normaliza(entrada), "Pendiente")

    def test_lo_que_no_se_reconoce_se_respeta(self):
        """Mejor un estado raro visible que uno cambiado a la brava por una
        heurística: si aparece algo nuevo, que se vea y se decida."""
        self.assertEqual(self.normaliza("En negociación"), "En negociación")

    def test_el_servidor_lo_aplica_al_crear_y_al_editar(self):
        servidor = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn('estado = normalizar_estado_de_accion(payload.get("estado"))', servidor)
        self.assertIn('updates["estado"] = normalizar_estado_de_accion(updates.get("estado"))', servidor)


def suma_de_alertas():
    """La suma que compone el total de la campanita del CRM.

    Hay varias `const total =` en app.js —minutos, vacaciones, importes—, así que se
    ancla en la de `collectCrmAlertsSnapshot`, que es la única que suma recuentos de
    alertas, y no en la primera que aparezca.
    """
    i = APP.index("const collectCrmAlertsSnapshot")
    j = APP.index("  const total =", i)
    return APP[j:APP.index(";", j)]


class ElCrmAvisaDeLosExpedientesParadosTests(unittest.TestCase):
    """«Sin próxima acción» sólo mira si el campo está vacío.

    Eso no detecta el caso que hace daño: un encargo con su próxima acción escrita
    hace dos meses y a la que nadie ha vuelto. Medido en producción el 2026-08-09: la
    última cita de toda la agenda era del 12 de junio, no había ninguna futura, y los
    19 expedientes vivos llevaban parados entre 65 y 115 días —uno sin una sola
    acción en toda su vida—.
    """

    def test_existe_la_alerta_y_va_la_primera(self):
        self.assertIn("expedientesParadosCount", APP)
        i_parados = APP.index('title: "Expedientes parados"')
        i_noticias = APP.index('title: "Noticias sin verificar"')
        self.assertLess(i_parados, i_noticias, "la alerta de parados debe encabezar la lista")

    def test_cuenta_solo_expedientes_vivos(self):
        i = APP.index("const expedientesParados = captacionesRows.filter")
        bloque = APP[i:i + 700]
        self.assertIn('etapa !== "Noticia" && etapa !== "Encargo"', bloque)

    def test_un_expediente_sin_ninguna_accion_tambien_cuenta(self):
        """Es el peor caso, no el más benigno: `|| 0` y 0 siempre es menor que el
        límite, así que entra."""
        i = APP.index("const expedientesParados = captacionesRows.filter")
        bloque = APP[i:i + 700]
        self.assertIn("ultimaAccionPorInmueble.get(inmuebleId) || 0", bloque)
        self.assertIn("return ultima < limiteFrio;", bloque)

    def test_suma_al_total_de_alertas(self):
        """Que el recuento entre en el total, sea o no el último sumando.

        Antes esto comprobaba «+ expedientesParadosCount;» con el punto y coma, o sea
        que exigía ser el último de la suma. Al añadir otra alerta —los inmuebles en
        encargo fuera del portal— el test se rompió sin que nada estuviera mal. Se
        mira la suma entera, que es lo que importa.
        """
        suma = suma_de_alertas()
        self.assertIn("expedientesParadosCount", suma)


class ElCrmAvisaDeLoQueNoEstaEnElPortalTests(unittest.TestCase):
    """Un inmueble en encargo fuera del portal es escaparate que no se usa.

    El CRM alimenta el portal Verifika2, pero publicar exige tres condiciones que se
    cumplen a mano —marcar el inmueble, verificar la noticia, y que no esté vendido—
    y nada avisaba de que quedaran a medias: 4 fichas publicadas de 86, todas de la
    misma agencia.

    El aviso sólo cuenta las que **podrían** publicarse ya: en encargo y con la
    noticia verificada. Avisar de las que el portal rechazaría igualmente sería
    invitar a intentar algo que no funciona, y a base de avisos inútiles se deja de
    mirar la campanita.
    """

    def bloque(self):
        i = APP.index("const sinPublicarEnPortal = inmueblesRows.filter")
        return APP[i:i + 800]

    def test_solo_cuenta_las_que_estan_en_encargo(self):
        self.assertIn('if (etapa !== "Encargo") return false;', self.bloque())

    def test_no_cuenta_las_que_ya_estan_publicadas(self):
        self.assertIn('portal_publicado', self.bloque())

    def test_exige_la_noticia_verificada(self):
        """Sin verificar, el portal no la aceptaría aunque se marcara."""
        self.assertIn("noticia_verificada", self.bloque())

    def test_suma_al_total(self):
        self.assertIn("sinPublicarEnPortalCount", suma_de_alertas())

    def test_el_recuento_sale_en_el_snapshot(self):
        i = APP.index("    expedientesParadosCount,\n    diasDelMasParado,")
        self.assertIn("sinPublicarEnPortalCount", APP[i:i + 200])

    def test_hay_una_tarjeta_que_lleva_al_listado(self):
        i = APP.index('title: "En encargo, fuera del portal"')
        tarjeta = APP[i - 200:i + 400]
        self.assertIn("sinPublicarEnPortalCount", tarjeta)
        self.assertIn('view: "inmuebles"', tarjeta)


class LosDosEjesDelPresetVanSeparadosTests(unittest.TestCase):
    """Catorce opciones en un desplegable, con dos ejes dentro.

    Había que leerse «Citas Equipo (7 días + caducadas)» entera para saber dónde
    estabas, y el eje de quién es justo el que hace que parezca que «desaparecen»
    citas —hay un comentario en el código avisando de eso—. El «de quién» pasa a su
    propio control y el resto va agrupado: siete opciones en vez de catorce.

    El valor guardado sigue siendo el de siempre, con su sufijo `_equipo`, así que
    nada de lo que lo lee ha tenido que cambiar.
    """

    HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")

    def test_el_desplegable_va_agrupado_y_sin_repetir_el_ambito(self):
        i = self.HTML.index('<select id="crmAgendaPreset"')
        bloque = self.HTML[i:self.HTML.index("</select>", i)]
        self.assertIn('<optgroup label="Citas">', bloque)
        self.assertIn('<optgroup label="Actividades">', bloque)
        self.assertNotIn("Equipo", bloque, "el ámbito ya no se repite en cada opción")
        self.assertEqual(bloque.count("<option"), 7)

    def test_existe_el_control_de_quien(self):
        self.assertIn('<select id="crmAgendaQuien"', self.HTML)
        i = self.HTML.index('<select id="crmAgendaQuien"')
        bloque = self.HTML[i:self.HTML.index("</select>", i)]
        self.assertIn('value="equipo"', bloque)
        self.assertIn('value="mias"', bloque)

    def test_el_valor_guardado_sigue_llevando_el_sufijo(self):
        self.assertIn("const presetAgendaCompuesto = () =>", APP)
        self.assertIn("localStorage.setItem(\"crm.agenda.preset\", presetAgendaCompuesto()", APP)
        # Y nadie lee ya el select a pelo esperando el sufijo.
        self.assertNotIn('String(crmAgendaPreset?.value || state.crmAgendaPreset', APP)

    def test_los_atajos_de_las_alertas_reparten_el_valor_en_los_dos_controles(self):
        self.assertNotIn("crmAgendaPreset.value = preset;", APP)
        self.assertGreaterEqual(APP.count("aplicaPresetAgenda(preset);"), 2)

    def test_la_composicion(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node no está disponible")
        i = APP.index("const AGENDA_SUFIJO_EQUIPO")
        trozo = APP[i:APP.index("const esCitaPorSuTramo")]
        casos = [("citas", "equipo", "citas_equipo"), ("citas", "mias", "citas"),
                 ("citas_caducadas", "equipo", "citas_caducadas_equipo"),
                 ("actividades_hoy", "mias", "actividades_hoy")]
        script = (
            "const preset={value:''},quien={value:''};"
            + trozo.replace("crmAgendaPreset", "preset").replace("crmAgendaQuien", "quien")
            + "const casos=" + json.dumps([[c[0], c[1]] for c in casos]) + ";"
            + "console.log(JSON.stringify(casos.map(([b,q])=>{preset.value=b;quien.value=q;return presetAgendaCompuesto();})));"
        )
        salida = subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)
        for (base, quien, esperado), real in zip(casos, json.loads(salida.stdout.strip())):
            with self.subTest(caso=f"{base}+{quien}"):
                self.assertEqual(real, esperado)


class LaAgendaNoSePisaConRespuestasAtrasadasTests(unittest.TestCase):
    """Cambiar de vista dispara otra carga, y la vieja podía llegar después.

    Me pasó varias veces probando en producción: entrabas en «Día», volvías a
    «Lista» y la lista salía vacía con el pie diciendo «2026-08-09 → 2026-08-09», el
    rango de la petición anterior.
    """

    def test_solo_se_pinta_la_ultima_peticion(self):
        self.assertIn("let crmAgendaPeticionEnCurso = 0;", APP)
        self.assertIn("const miPeticion = ++crmAgendaPeticionEnCurso;", APP)
        self.assertIn("if (miPeticion !== crmAgendaPeticionEnCurso) return;", APP)


class ElVacioDeLaAgendaExplicaLoQueHayFueraTests(unittest.TestCase):
    """«Sin acciones» a secas es engañoso con 121 cargadas y ninguna en la ventana."""

    def test_el_mensaje_dice_cuantas_hay_cargadas(self):
        i = APP.index("Sin acciones aquí.")
        bloque = APP[max(0, i - 900):i + 200]
        self.assertIn("state.crmAgendaRowsAll", bloque)
        self.assertIn("crmAgendaSearch?.value", bloque)
        self.assertIn("qué se muestra", bloque)

    def test_el_texto_de_busqueda_va_escapado(self):
        i = APP.index("Sin acciones aquí.")
        self.assertIn("escapeHtml(busqueda)", APP[max(0, i - 900):i + 200])


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
