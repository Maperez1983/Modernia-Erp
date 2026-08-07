"""Corregir un presupuesto lo corrige, no deja dos.

El usuario avisó de que al cambiar un presupuesto salía duplicado. Los datos de
producción lo confirmaban sin lugar a dudas: de los diez presupuestos guardados,
**ninguno tenía `updated_at` distinto de `created_at`**. Es decir, en toda la vida
de la aplicación no se había actualizado uno solo. Y se veían los racimos: tres
C.P ASTREA idénticos (dos de ellos creados con catorce segundos de diferencia), dos
de 177 viviendas, dos de 8, dos de 12.

La causa estaba en una línea. El servidor decide entre UPDATE e INSERT mirando el
`id` que le llega:

    record_id = str(payload.get("id") or "").strip()
    ...
    if record_id:  ->  UPDATE + rehacer las partidas
    else:          ->  INSERT

y el formulario rápido mandaba `id: ""` escrito a fuego. Siempre. La única forma de
volver sobre un presupuesto era el desplegable «Precargar datos», que copia los
valores del anterior: al guardar, otro presupuesto.

Ahora el formulario lleva un campo `presupuesto_id`. Precargar desde un presupuesto
lo rellena y enciende el aviso de modo edición; precargar desde una comunidad, o
darle a «Nuevo», lo vacía. Duplicar a propósito sigue estando —hay fincas con dos
escaleras, y a veces se quiere guardar una variante aparte— pero hay que pedirlo con
el botón, ya no es lo único que ocurre.
"""

import re
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))


def cuerpo_del_submit():
    i = APP.index('workspaceFincasBudgetQuickForm.addEventListener("submit"')
    return APP[i: i + 12000]


def cuerpo_de(nombre):
    i = APP.index(nombre)
    return APP[i: APP.index("\nconst ", i + 10)]


class ElFormularioMandaElIdTests(unittest.TestCase):
    def test_ya_no_va_escrito_a_fuego_a_vacio(self):
        """Era `id: "",` justo al abrir el payload. Ahí estaba todo el fallo."""
        self.assertNotIn('id: "",', cuerpo_del_submit())

    def test_el_id_sale_del_campo_del_formulario(self):
        self.assertIn('id: String(values.presupuesto_id || "").trim()', cuerpo_del_submit())

    def test_el_campo_existe_en_el_formulario(self):
        i = HTML.index('id="workspaceFincasBudgetQuickForm"')
        formulario = HTML[i: HTML.index("</form>", i)]
        self.assertIn('name="presupuesto_id"', formulario)


class ElModoEdicionSeEnciendeYSeApagaTests(unittest.TestCase):
    def test_precargar_desde_un_presupuesto_lo_enciende(self):
        self.assertIn("setWorkspaceFincasBudgetEditando(budget)", cuerpo_de("const applyWorkspaceFincasBudgetQuickBudget"))

    def test_precargar_desde_una_comunidad_lo_apaga(self):
        """Copiar los datos de una comunidad es empezar uno nuevo, no editar."""
        self.assertIn("setWorkspaceFincasBudgetEditando(null)", cuerpo_de("const applyWorkspaceFincasBudgetQuickCommunity"))

    def test_el_boton_nuevo_lo_apaga(self):
        self.assertIn("setWorkspaceFincasBudgetEditando(null)", cuerpo_de("const resetWorkspaceFincasBudgetQuickForm"))

    def test_dejar_el_desplegable_en_blanco_lo_apaga(self):
        self.assertIn("setWorkspaceFincasBudgetEditando(null)", cuerpo_de("const applyWorkspaceFincasBudgetQuickPrefill"))

    def test_guardar_dos_veces_no_puede_dejar_dos(self):
        """Tras guardar se sigue editando el mismo, así que el segundo clic actualiza."""
        cuerpo = cuerpo_del_submit()
        self.assertIn("setWorkspaceFincasBudgetEditando({ id: budgetId", cuerpo)

    def test_se_marca_despues_de_recargar_la_pantalla(self):
        """`loadWorkspaceDetail` repuebla el desplegable; marcarlo antes se perdería."""
        cuerpo = cuerpo_del_submit()
        self.assertLess(
            cuerpo.index("await loadWorkspaceDetail"),
            cuerpo.index("setWorkspaceFincasBudgetEditando({ id: budgetId"),
        )


class SeVeQueSeEstaEditandoTests(unittest.TestCase):
    def test_hay_un_aviso_en_pantalla(self):
        self.assertIn('id="workspaceFincasBudgetEditando"', HTML)
        self.assertIn("Estás modificando un presupuesto ya creado", HTML)

    def test_dice_lo_que_va_a_pasar_al_guardar(self):
        self.assertIn("se actualiza ese mismo presupuesto", HTML)
        self.assertIn("No se crea otro", HTML)

    def test_el_boton_de_guardar_cambia_de_texto(self):
        cuerpo = cuerpo_de("const setWorkspaceFincasBudgetEditando")
        self.assertIn('"Guardar cambios + PDF"', cuerpo)
        self.assertIn('"Crear presupuesto + PDF"', cuerpo)

    def test_el_aviso_tiene_estilo_propio(self):
        css = (RAIZ / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".presu-editando {", css)
        self.assertIn(".presu-editando[hidden] { display: none; }", css)

    def test_el_estado_distingue_crear_de_actualizar(self):
        cuerpo = cuerpo_del_submit()
        self.assertIn('"Presupuesto actualizado"', cuerpo)
        self.assertIn('"Presupuesto creado"', cuerpo)


class DuplicarSigueSiendoPosibleAPeticionTests(unittest.TestCase):
    def test_hay_boton_para_crear_uno_nuevo_en_su_lugar(self):
        self.assertIn('id="workspaceFincasBudgetCrearCopia"', HTML)

    def test_el_boton_apaga_el_modo_edicion(self):
        i = APP.index("if (workspaceFincasBudgetCrearCopia)")
        self.assertIn("setWorkspaceFincasBudgetEditando(null)", APP[i: i + 600])

    def test_avisa_de_que_no_tocara_el_anterior(self):
        self.assertIn("sin tocar el anterior", APP)


class ElServidorHaceLoQueSeEsperaTests(unittest.TestCase):
    """Esta parte ya estaba bien; se fija para que el arreglo no se quede huérfano."""

    def handler(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_presupuestos"')
        return SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]

    def test_decide_por_el_id_que_le_llega(self):
        cuerpo = self.handler()
        self.assertIn('record_id = str(payload.get("id") or "").strip()', cuerpo)
        self.assertIn("if record_id:", cuerpo)

    def test_con_id_actualiza_y_rehace_las_partidas(self):
        cuerpo = self.handler()
        i = cuerpo.index("if record_id:")
        rama = cuerpo[i: cuerpo.index("            else:", i)]
        self.assertIn("UPDATE workspace_presupuestos", rama)
        self.assertIn("DELETE FROM workspace_presupuesto_lineas", rama)
        self.assertIn("calculo_json = ?", rama)

    def test_no_deja_actualizar_uno_de_otro_workspace(self):
        cuerpo = self.handler()
        i = cuerpo.index("UPDATE workspace_presupuestos")
        self.assertIn("WHERE id = ? AND workspace_id = ?", cuerpo[i: i + 1200])

    def test_sin_id_inserta_uno_nuevo(self):
        cuerpo = self.handler()
        i = cuerpo.index("if record_id:")
        resto = cuerpo[cuerpo.index("            else:", i):]
        self.assertIn("INSERT INTO workspace_presupuestos", resto[:2000])


class LaCacheSeInvalidaTests(unittest.TestCase):
    """Sin esto el navegador seguiría sirviendo el `app.js` con el fallo."""

    def version(self, texto, fichero):
        return re.search(rf"{re.escape(fichero)}\?v=(\d+)", texto).group(1)

    def test_html_y_service_worker_piden_la_misma(self):
        sw = (RAIZ / "web" / "sw.js").read_text(encoding="utf-8")
        for fichero in ("app.js", "styles.css"):
            with self.subTest(fichero=fichero):
                self.assertEqual(self.version(HTML, fichero), self.version(sw, fichero))


if __name__ == "__main__":
    unittest.main()
