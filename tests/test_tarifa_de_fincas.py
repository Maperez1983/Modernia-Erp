"""La tarifa de administración de fincas se puede tocar sin desplegar.

Dos cosas distintas, encontradas el 2026-08-07 al revisar presupuestos:

**Los trasteros no se cobraban.** La fórmula los contemplaba desde siempre
(`num_trasteros` sumaba 1 € por unidad), pero el formulario rápido de presupuestos
solo pedía viviendas, locales y aparcamientos. No estaba el campo, no viajaba en el
envío y `buildFincasBudgetLineas` ni lo miraba: una comunidad con 30 trasteros se
presupuestaba como si no tuviera ninguno, y el PDF salía con esa cifra.

**Los precios estaban escritos a mano** en dos sitios a la vez —`server.py` y
`app.js`—, así que subir la cuota por vivienda era un despliegue, y no había forma
de cobrar un trabajo puntual como la constitución de la comunidad.

Ahora la tarifa vive en `workspace_fincas_tarifas`, una por workspace. La de partida
son los mismos precios de siempre (5/1/1/1, mínimo 60), así que el día que esto entre
en producción los presupuestos salen exactamente igual que el día anterior; lo que
cambia es que a partir de ahí se pueden editar.
"""

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
from web import server  # noqa: E402


class LosTrasterosYaNoSePierdenTests(unittest.TestCase):
    """El fallo concreto que se buscaba: el formulario no los pedía."""

    def _formulario_rapido(self):
        i = HTML.index('id="workspaceFincasBudgetQuickForm"')
        return HTML[i: HTML.index("</form>", i)]

    def test_el_formulario_pregunta_por_los_trasteros(self):
        self.assertIn('name="num_trasteros"', self._formulario_rapido())

    def test_viajan_en_el_envio(self):
        i = APP.index('workspaceFincasBudgetQuickForm.addEventListener("submit"')
        cuerpo = APP[i: i + 6000]
        self.assertIn("num_trasteros: numTrasteros", cuerpo)

    def test_el_desglose_los_cobra(self):
        i = APP.index("const buildFincasBudgetLineas")
        cuerpo = APP[i: APP.index("\nconst ", i + 10)]
        self.assertIn("num_trasteros", cuerpo)

    def test_treinta_trasteros_cambian_el_precio(self):
        """La prueba de que no es cosmético: antes estas dos cifras eran iguales."""
        sin = server.compute_fincas_cuota_sugerida(num_vecinos=20, num_trasteros=0)
        con = server.compute_fincas_cuota_sugerida(num_vecinos=20, num_trasteros=30)
        self.assertEqual(sin, 100.0)
        self.assertEqual(con, 130.0)


class LaTarifaDePartidaNoCambiaNadaTests(unittest.TestCase):
    """Sembrar la tarifa no puede alterar lo que ya se venía cobrando."""

    def test_los_precios_de_partida_son_los_de_siempre(self):
        precios = {t["clave"]: t["precio"] for t in server.FINCAS_TARIFAS_DEFECTO}
        self.assertEqual(precios["vivienda"], 5.0)
        self.assertEqual(precios["local"], 1.0)
        self.assertEqual(precios["trastero"], 1.0)
        self.assertEqual(precios["aparcamiento"], 1.0)
        self.assertEqual(precios["minimo"], 60.0)

    def test_sin_tarifa_se_calcula_como_antes(self):
        self.assertEqual(server.compute_fincas_cuota_sugerida(0, 0, 0, 0), 60.0)
        self.assertEqual(server.compute_fincas_cuota_sugerida(10, 2, 3, 4), 60.0)
        self.assertEqual(server.compute_fincas_cuota_sugerida(24, 0, 0, 0), 120.0)

    def test_el_front_arranca_con_los_mismos_precios(self):
        """Si las dos listas se separan, el navegador y el PDF dirían cifras distintas."""
        i = APP.index("const FINCAS_TARIFA_DEFECTO")
        bloque = APP[i: APP.index("];", i)]
        for clave, precio in (("vivienda", 5), ("local", 1), ("trastero", 1), ("aparcamiento", 1), ("minimo", 60)):
            with self.subTest(clave=clave):
                self.assertIn(f'clave: "{clave}"', bloque)
                self.assertIn(f"precio: {precio},", bloque.split(f'clave: "{clave}"')[1].split("}")[0] + "}")


class LaTarifaMandaSobreElCalculoTests(unittest.TestCase):
    def test_un_precio_distinto_cambia_la_base(self):
        tarifa = [
            {"clave": "vivienda", "tipo": "unitaria", "precio": 8.0, "activo": 1},
            {"clave": "trastero", "tipo": "unitaria", "precio": 2.5, "activo": 1},
            {"clave": "minimo", "tipo": "minimo", "precio": 60.0, "activo": 1},
        ]
        # 20 × 8 + 10 × 2,5 = 185
        self.assertEqual(
            server.compute_fincas_cuota_sugerida(num_vecinos=20, num_trasteros=10, tarifas=tarifa),
            185.0,
        )

    def test_el_minimo_sigue_mandando_cuando_sale_poco(self):
        tarifa = [
            {"clave": "vivienda", "tipo": "unitaria", "precio": 5.0, "activo": 1},
            {"clave": "minimo", "tipo": "minimo", "precio": 90.0, "activo": 1},
        ]
        self.assertEqual(server.compute_fincas_cuota_sugerida(num_vecinos=4, tarifas=tarifa), 90.0)

    def test_un_concepto_desactivado_no_suma(self):
        tarifa = [
            {"clave": "vivienda", "tipo": "unitaria", "precio": 5.0, "activo": 1},
            {"clave": "trastero", "tipo": "unitaria", "precio": 3.0, "activo": 0},
            {"clave": "minimo", "tipo": "minimo", "precio": 0.0, "activo": 1},
        ]
        self.assertEqual(server.compute_fincas_cuota_sugerida(num_vecinos=10, num_trasteros=50, tarifas=tarifa), 50.0)

    def test_los_puntuales_no_entran_en_la_cuota_mensual(self):
        """La constitución de la comunidad se cobra una vez, no todos los meses."""
        tarifa = [
            {"clave": "vivienda", "tipo": "unitaria", "precio": 5.0, "activo": 1},
            {"clave": "alta_comunidad", "tipo": "fija", "precio": 400.0, "activo": 1},
            {"clave": "minimo", "tipo": "minimo", "precio": 60.0, "activo": 1},
        ]
        self.assertEqual(server.compute_fincas_cuota_sugerida(num_vecinos=20, tarifas=tarifa), 100.0)


class HayDondeTarifarUnTrabajoPuntualTests(unittest.TestCase):
    def test_la_constitucion_de_la_comunidad_viene_de_serie(self):
        claves = {t["clave"] for t in server.FINCAS_TARIFAS_DEFECTO}
        self.assertIn("alta_comunidad", claves)

    def test_viene_a_cero_para_que_se_le_ponga_precio(self):
        """Inventarle un importe sería peor que dejarlo en blanco."""
        alta = next(t for t in server.FINCAS_TARIFAS_DEFECTO if t["clave"] == "alta_comunidad")
        self.assertEqual(alta["precio"], 0.0)
        self.assertEqual(alta["tipo"], "fija")

    def test_el_formulario_tiene_donde_marcarlos(self):
        self.assertIn('id="workspaceFincasBudgetExtras"', HTML)
        self.assertIn("fincasExtrasSeleccionados", APP)

    def test_el_presupuesto_los_manda_al_servidor(self):
        i = APP.index('workspaceFincasBudgetQuickForm.addEventListener("submit"')
        self.assertIn("tarifas_fijas: extras", APP[i: i + 6000])

    def test_el_servidor_los_cobra_como_linea_aparte(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_presupuestos"')
        cuerpo = SERVER[i: i + 12000]
        self.assertIn('payload.get("tarifas_fijas")', cuerpo)
        self.assertIn('"categoria": "Servicios puntuales"', cuerpo)


class LaTarifaSeGuardaConPermisoTests(unittest.TestCase):
    def _manejador(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_tarifas"')
        return SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]

    def test_el_post_esta_dado_de_alta(self):
        """Sin esto el endpoint responde 'Endpoint no valido' y no se entera nadie."""
        i = SERVER.index('"/api/workspace_fincas_comunidades",')
        self.assertIn('"/api/workspace_fincas_tarifas",', SERVER[i - 4000: i + 4000])

    def test_exige_pertenecer_al_workspace_y_poder_escribir(self):
        self.assertIn(
            "enforce_workspace_membership(conn, session, workspace_id, write=True)",
            self._manejador(),
        )

    def test_el_get_tambien_comprueba(self):
        i = SERVER.index('if path == "/api/workspace_fincas_tarifas"')
        self.assertIn("enforce_workspace_membership", SERVER[i: i + 900])

    def test_la_comprobacion_va_antes_de_escribir(self):
        cuerpo = self._manejador()
        self.assertLess(cuerpo.index("enforce_workspace_membership"), cuerpo.index("INSERT INTO"))


class LasUnidadesMuevenElPrecioEnPantallaTests(unittest.TestCase):
    """El campo estaba, pero nadie escuchaba cuando se escribía en él.

    El 2026-08-11, revisando la pestaña: se teclean trasteros y aparcamientos y el
    presupuesto sale sin ellos. La fórmula era correcta y el PDF también —lo que
    fallaba estaba en medio—. La lista de campos que disparan el recálculo se
    escribió a mano como `["num_vecinos", "num_locales", "num_aparcamientos"]`, y al
    añadir el campo de trasteros nadie la tocó: el resumen, la base sugerida, el IVA
    y el total se quedaban con la cifra anterior.

    Ahora la lista se deriva de `FINCAS_TARIFA_UNIDADES`, que es el mismo mapa que usa
    el cálculo. Un concepto no puede entrar en el precio y quedarse fuera del recálculo.
    """

    def test_recalculan_las_cuatro_unidades(self):
        i = APP.index("const FINCAS_TARIFA_UNIDADES")
        mapa = APP[i: APP.index("};", i)]
        for campo in ("num_vecinos", "num_locales", "num_trasteros", "num_aparcamientos"):
            with self.subTest(campo=campo):
                self.assertIn(campo, mapa)

    def test_el_recalculo_se_engancha_desde_el_mapa(self):
        i = APP.index("Object.values(FINCAS_TARIFA_UNIDADES).forEach")
        self.assertIn("syncWorkspaceFincasBudgetQuickComputed", APP[i: i + 400])

    def test_ya_no_queda_la_lista_escrita_a_mano(self):
        """Que no vuelva: la lista a mano fue exactamente el fallo."""
        self.assertNotIn('["num_vecinos", "num_locales", "num_aparcamientos"]', APP)

    def test_la_tarifa_que_se_aplica_se_lee_en_pantalla(self):
        """El pie recitaba los precios de memoria —y sin los trasteros—, sin enterarse
        de que la tarifa ya se edita sin desplegar. Ahora sale de la que está en uso."""
        self.assertIn("data-resumen-tarifa", HTML)
        i = APP.index("const describeFincasTarifaVigente")
        cuerpo = APP[i: APP.index("\nconst ", i + 10)]
        self.assertIn("FINCAS_TARIFA_UNIDADES[item?.clave]", cuerpo)
        self.assertIn("fincasTarifaActual", cuerpo)


class ElPrecioPactadoEsUnSoloCampoTests(unittest.TestCase):
    """Tabular por el formulario congelaba el precio, y el PDF lo disimulaba.

    Había cuatro campos de importe seguidos —base sugerida, subtotal, IVA y total— de
    los que tres eran `readonly` y repetían la barra de resumen. El editable llevaba un
    «déjalo vacío para usar la base» imposible de cumplir, porque lo rellenaba el propio
    cálculo. Para saber si el importe lo había escrito una persona o el programa hacía
    falta una máquina de estados (`dataset.manual`, `manualSource`), y el `blur` marcaba
    el campo como escrito a mano solo con pasar por encima.

    Desde ahí el precio se quedaba congelado: las unidades que se teclearan después
    movían el desglose pero no el importe, y el PDF cuadraba la diferencia con un
    «ajuste comercial acordado» que nadie había acordado. El del total era todavía
    peor: `readonly`, así que nunca pudo haberlo escrito nadie.

    Ahora es un campo y significa una cosa: vacío manda la tarifa.
    """

    def test_ya_no_hay_maquina_de_estados(self):
        self.assertNotIn("dataset.manual =", APP)
        self.assertNotIn("dataset.manualSource", APP)

    def test_solo_queda_el_campo_del_precio_pactado(self):
        i = HTML.index('id="workspaceFincasBudgetQuickForm"')
        formulario = HTML[i: HTML.index("</form>", i)]
        self.assertIn('name="subtotal"', formulario)
        for muerto in ('name="subtotal_sugerido"', 'name="impuestos"', 'name="total"'):
            with self.subTest(campo=muerto):
                self.assertNotIn(muerto, formulario)

    def test_vacio_quiere_decir_tarifa(self):
        i = APP.index('workspaceFincasBudgetQuickForm.addEventListener("submit"')
        cuerpo = APP[i: i + 6000]
        self.assertIn("const pactado = String(values.subtotal", cuerpo)
        self.assertIn("pactado ? Math.max(0, parseMoneyValue(pactado)) : suggestedSubtotal", cuerpo)

    def test_al_reabrir_un_presupuesto_se_recupera_el_precio_pactado(self):
        """Antes se descartaba: abrir uno cerrado en 140 € y volver a guardarlo lo
        devolvía al precio de tarifa."""
        i = APP.index("const applyWorkspaceFincasBudgetQuickBudget")
        cuerpo = APP[i: APP.index("const applyWorkspaceFincasBudgetQuickPrefill", i)]
        self.assertIn("tarifaEntonces", cuerpo)
        self.assertIn("calc.cuota_sugerida", cuerpo)
        self.assertIn("hayPuntuales", cuerpo)


class LosPanelesDelPresupuestoCarganTests(unittest.TestCase):
    """«Plantillas de contrato» y «Equipo» llamaban a un helper que no existe.

    `apiGet` no está definido en el bundle —el helper se llama `api`—, así que abrir
    cualquiera de los dos desplegables lanzaba un ReferenceError que el `catch`
    convertía en el mensaje «apiGet is not defined» debajo del título. Los dos paneles
    llevaban vacíos desde que se escribieron.
    """

    def test_no_se_llama_a_un_helper_inexistente(self):
        self.assertNotIn("apiGet(", APP)

    def test_los_dos_paneles_usan_el_helper_de_verdad(self):
        for funcion in ("cargarPlantillasDeContrato", "cargarEquipoDeFincas"):
            with self.subTest(funcion=funcion):
                i = APP.index(f"const {funcion} = async")
                self.assertIn("await api(", APP[i: i + 900])


class LosAjustesTienenSuPropiaPestanaTests(unittest.TestCase):
    """La pestaña de presupuestos hacía tres trabajos a la vez.

    Dentro del mismo formulario con el que se hace un presupuesto vivían la tabla de
    precios, la lista del equipo y el texto del contrato de administración —un
    `textarea` de 18 renglones—. Nada de eso es de un presupuesto: se guarda para todo
    el workspace, como decía la propia letra pequeña. Hacer un presupuesto obligaba a
    pasar por delante de todo ello.
    """

    def _formulario(self):
        i = HTML.index('id="workspaceFincasBudgetQuickForm"')
        return HTML[i: HTML.index("</form>", i)]

    def _pestana_de_ajustes(self):
        i = HTML.index('data-fincas-tab="ajustes"')
        return HTML[i: HTML.index("\n        <div class=", i)]

    def test_la_pestana_existe_y_es_navegable(self):
        self.assertIn('data-fincas-tab-btn="ajustes"', HTML)
        i = APP.index("const normalizeWorkspaceFincasTab")
        self.assertIn('"ajustes"', APP[i: i + 500])

    def test_los_tres_paneles_se_han_mudado(self):
        formulario = self._formulario()
        ajustes = self._pestana_de_ajustes()
        for panel in ("workspaceFincasTarifaPanel",
                      "workspaceFincasBudgetEquipoPanel",
                      "workspaceContratoPlantillasPanel"):
            with self.subTest(panel=panel):
                self.assertNotIn(panel, formulario)
                self.assertIn(panel, ajustes)

    def test_lo_que_si_es_del_presupuesto_se_queda(self):
        """La carta y la foto sí son de este presupuesto: escriben en el formulario."""
        formulario = self._formulario()
        self.assertIn("workspaceFincasBudgetCartaPanel", formulario)
        self.assertIn('name="carta_presentacion"', formulario)
        self.assertIn("workspaceFincasBudgetBuildingPhoto", formulario)

    def test_al_abrir_la_pestana_se_cargan_los_tres(self):
        i = APP.index('if (normalized === "ajustes")')
        cuerpo = APP[i: i + 700]
        for carga in ("cargarFincasTarifas", "cargarEquipoDeFincas", "cargarPlantillasDeContrato"):
            with self.subTest(carga=carga):
                self.assertIn(carga, cuerpo)


class ElResumenEconomicoSaleUnaSolaVezTests(unittest.TestCase):
    """Salía dos veces y con nombres distintos para la misma cifra.

    Arriba, una barra pegada con «Cuota mensual» y «Base mensual»; al final del
    formulario, otra tarjeta llamada también «Resumen económico» con «Total» y
    «Subtotal», que son esos mismos dos números con otro nombre. Queda la de arriba,
    que es la que distingue lo mensual de lo puntual, y se le añade el coste anual.
    """

    def test_la_tarjeta_duplicada_ya_no_esta(self):
        self.assertNotIn("workspaceFincasBudgetHero", APP)
        self.assertNotIn("workspaceFincasBudgetHero", HTML)

    def test_la_barra_de_arriba_dice_tambien_el_coste_anual(self):
        i = HTML.index('id="workspaceFincasBudgetResumen"')
        barra = HTML[i: HTML.index("</div>\n", i) + 400]
        self.assertIn('data-resumen="anual"', barra)


class ElPdfCobraTodasLasUnidadesTests(unittest.TestCase):
    """La otra punta del circuito: con los datos delante, el documento los cobra."""

    def _texto_del_pdf(self, lineas, subtotal):
        import json
        from io import BytesIO

        from pypdf import PdfReader

        calc = {
            "num_vecinos": 20, "num_locales": 2, "num_trasteros": 10, "num_aparcamientos": 15,
            "comunidad_denominacion": "C.P. de prueba", "cuota_sugerida": 127.0,
        }
        budget = {
            "id": "b1", "servicio": "fincas", "titulo": "Prueba", "fecha": "2026-08-11",
            "subtotal": subtotal, "impuestos": round(subtotal * 0.21, 2),
            "total": round(subtotal * 1.21, 2), "calculo_json": json.dumps(calc),
        }
        pdf = server.build_workspace_budget_pdf(
            budget, {"nombre": "Modernia"}, {"nombre": "Fincas Velazquez"},
            {"nombre": "C.P. de prueba"}, lineas,
        )
        return "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)

    def _lineas(self):
        return [
            {"categoria": "Edificio", "concepto": "Por vivienda", "cantidad": 20,
             "unidad": "vivienda", "precio_unitario": 5, "total_linea": 100.0},
            {"categoria": "Edificio", "concepto": "Por local", "cantidad": 2,
             "unidad": "local", "precio_unitario": 1, "total_linea": 2.0},
            {"categoria": "Edificio", "concepto": "Por trastero", "cantidad": 10,
             "unidad": "trastero", "precio_unitario": 1, "total_linea": 10.0},
            {"categoria": "Edificio", "concepto": "Por aparcamiento", "cantidad": 15,
             "unidad": "plaza", "precio_unitario": 1, "total_linea": 15.0},
        ]

    def test_salen_en_las_unidades_del_edificio(self):
        texto = self._texto_del_pdf(self._lineas(), 127.0)
        self.assertIn("Trasteros: 10", texto)
        self.assertIn("Aparcamientos: 15", texto)

    def test_se_cobran_y_el_total_los_incluye(self):
        texto = self._texto_del_pdf(self._lineas(), 127.0)
        self.assertIn("Por trastero", texto)
        self.assertIn("Por aparcamiento", texto)
        self.assertIn("127,00 €", texto)

    def test_sin_precio_congelado_no_aparece_ningun_ajuste(self):
        """El «ajuste comercial» es para un precio pactado de verdad, no para tapar
        un subtotal que se quedó atrás."""
        self.assertNotIn("Ajuste comercial", self._texto_del_pdf(self._lineas(), 127.0))


if __name__ == "__main__":
    unittest.main()
