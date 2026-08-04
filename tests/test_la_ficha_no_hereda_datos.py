"""Una hipoteca enseñaba el banco y el estado de la ficha anterior.

Reproducido en producción el 2026-08-04 abriendo varias fichas seguidas:

    hipoteca "/De&— Pree 20..."   base: banco NULL, estado "Pendiente"
                                  pantalla: banco "Banco Santander", estado "Firmada"

Y abriendo la de Bankinter, la pantalla seguía diciendo "Banco Santander". Los dos
desplegables no se rellenaban nunca desde el registro.

La causa no estaba en la ficha sino en `ui-foundation.js`. Hay un mecanismo que
recuerda el valor de los controles entre visitas —útil para filtros, para el año
seleccionado, para la densidad de una tabla— y su regla decía:

    if (tagName === "textarea") return true;
    if (tagName === "select") return true;
    return CONTROL_PERSIST_RE.test(key);

Es decir: cualquier `select` se recordaba, viniera de donde viniera. Incluidos los
de una ficha, que no son preferencias sino datos de un expediente concreto. Al
abrir otro registro se reponía el valor guardado encima del real.

Lo grave no es lo que se ve, es lo que se guarda: el formulario mostraba "Firmada"
sobre una hipoteca pendiente, y darle a guardar lo habría escrito en la base.

Dos arreglos, porque uno solo no basta:

1. Los `select` y `textarea` pasan por el mismo criterio que el resto: solo se
   recuerda lo que parece un filtro o una preferencia de vista.
2. La ficha se marca con `data-ui-persist="0"`. Hace falta igualmente: el
   desplegable de banco se llama `hipotecaFichaBancoSelect`, y "Select" encaja con
   el patrón de filtros. El nombre de un control no puede ser lo que decida si un
   dato de negocio se guarda en el navegador.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
UI = (RAIZ / "web" / "ui-foundation.js").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")


def bloque_es_persistible():
    i = UI.index("const isPersistableControl = (el) => {")
    return UI[i: UI.index("\n  };", i)]


class SoloSeRecuerdanFiltrosYPreferenciasTests(unittest.TestCase):
    def test_un_select_ya_no_se_recuerda_por_el_hecho_de_serlo(self):
        bloque = bloque_es_persistible()
        self.assertNotIn('=== "select") return true', bloque)
        self.assertNotIn('=== "textarea") return true', bloque)

    def test_se_aplica_el_mismo_criterio_que_al_resto(self):
        self.assertIn("CONTROL_PERSIST_RE.test(getElementKey(el))", bloque_es_persistible())

    def test_el_patron_sigue_cubriendo_los_filtros_de_verdad(self):
        """Si se estrechara de más, se perderían los filtros que sí deben recordarse."""
        i = UI.index("const CONTROL_PERSIST_RE =")
        patron = re.search(r"/\((.*?)\)/i", UI[i: i + 200]).group(1)
        for palabra in ("search", "filter", "year", "view", "sort", "empresa", "tabla"):
            with self.subTest(palabra=palabra):
                self.assertIn(palabra, patron)


class LaFichaNoEsUnPanelDeFiltrosTests(unittest.TestCase):
    def test_la_ficha_de_hipoteca_no_persiste_sus_campos(self):
        i = APP.index('<form id="hipotecaFichaForm"')
        etiqueta = APP[i: i + 160]
        self.assertIn('data-ui-persist="0"', etiqueta)

    def test_tampoco_guarda_borrador(self):
        """El borrador de un expediente no se recupera en otro."""
        i = APP.index('<form id="hipotecaFichaForm"')
        self.assertIn('data-ui-draft="0"', APP[i: i + 160])

    def test_no_basta_con_el_criterio_del_nombre(self):
        """El desplegable se llama ...BancoSelect y "Select" encaja con el patrón.

        Por eso hace falta marcar el formulario además de estrechar la regla: que un
        dato de negocio se guarde o no en el navegador no puede depender de cómo se
        llame el control.
        """
        i = UI.index("const CONTROL_PERSIST_RE =")
        patron = re.search(r"/\((.*?)\)/i", UI[i: i + 200]).group(1)
        self.assertIn("select", patron)
        self.assertIn("hipotecaFichaBancoSelect", APP)


class LoQueSeGuardoAntesDejaDeAplicarseTests(unittest.TestCase):
    """Hay navegadores con los valores viejos ya guardados.

    No hace falta limpiarlos: la restauración comprueba la misma condición que el
    guardado, así que con la ficha marcada esas claves quedan inertes.
    """

    def test_la_restauracion_comprueba_lo_mismo_que_el_guardado(self):
        i = UI.index("const restoreControlState")
        self.assertIn("if (!isPersistableControl(el)) return;", UI[i: i + 400])

class NingunaFichaDeRegistroRecuerdaSusCamposTests(unittest.TestCase):
    """El arreglo por marcas se olvida en el siguiente formulario que alguien escriba.

    Tras arreglar la ficha de hipoteca quedaban 8 formularios de registro en
    index.html con el mismo agujero, casi todos por un `select` de empresa_id, que
    encaja con el patrón de filtros. Marcarlos a mano no escala.

    Un formulario con campo oculto `id` es la ficha de un registro: lo que hay
    dentro son datos de ese expediente, no preferencias. Se reconoce por la forma.
    """

    def test_se_reconoce_la_ficha_por_su_campo_oculto_id(self):
        bloque = bloque_es_persistible()
        self.assertIn("""form.querySelector('input[type="hidden"][name="id"]')""", bloque)

    def test_no_queda_ningun_formulario_de_registro_expuesto(self):
        """Comprobado sobre index.html, que es donde viven los formularios estáticos."""
        from html.parser import HTMLParser

        html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
        i = UI.index("const CONTROL_PERSIST_RE =")
        patron = re.compile(re.search(r"/\((.*?)\)/i", UI[i: i + 200]).group(1), re.I)

        class P(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.forms, self.pila = [], []

            def handle_starttag(self, tag, attrs):
                d = dict(attrs)
                if tag == "form":
                    self.pila.append({"id": d.get("id", ""), "persist": d.get("data-ui-persist"),
                                      "registro": False, "controles": []})
                elif tag in ("input", "select", "textarea") and self.pila:
                    if d.get("type") == "hidden" and d.get("name") == "id":
                        self.pila[-1]["registro"] = True
                    clave = d.get("id") or d.get("name") or ""
                    if clave:
                        self.pila[-1]["controles"].append(clave)

            def handle_endtag(self, tag):
                if tag == "form" and self.pila:
                    self.forms.append(self.pila.pop())

        p = P()
        p.feed(html)
        expuestos = [
            f["id"]
            for f in p.forms
            if f["id"] and f["registro"] and f["persist"] != "0"
            and any(patron.search(c) for c in f["controles"])
        ]
        # Estos son los que el criterio por nombre dejaría pasar. No se exige que la
        # lista esté vacía —cambiaría con cada formulario nuevo— sino que la regla
        # estructural los corte antes de llegar a ese criterio.
        bloque = bloque_es_persistible()
        corte = bloque.index("""input[type="hidden"][name="id"]""")
        por_nombre = bloque.index("CONTROL_PERSIST_RE.test(getElementKey(el))")
        self.assertLess(
            corte,
            por_nombre,
            "el criterio por nombre se evalúa antes que la regla de ficha de registro, "
            f"así que seguirían recordándose: {', '.join(expuestos)}",
        )


class UnBorradorSoloVuelveASuExpedienteTests(unittest.TestCase):
    """El borrador se guardaba con el id del formulario, no con el del registro.

    Dejar a medias una hipoteca y abrir otra restauraba encima los valores de la
    primera: el mismo fallo que el de los controles, por otra puerta.
    """

    def test_el_borrador_guarda_de_que_registro_es(self):
        i = UI.index("const serializeFormDraft")
        self.assertIn("__scope: getFormScope(form)", UI[i: i + 300])

    def test_no_se_restaura_un_borrador_de_otro_registro(self):
        i = UI.index("const restoreFormDraft")
        bloque = UI[i: i + 900]
        self.assertIn('String(draft.__scope || "") !== getFormScope(form)', bloque)
        self.assertIn("clearFormDraft(form)", bloque)

    def test_el_ambito_sale_del_id_del_registro(self):
        i = UI.index("const getFormScope")
        bloque = UI[i: i + 700]
        self.assertIn("""form.querySelector('input[name="id"]')""", bloque)
        self.assertIn('form.closest("[data-record-id]")', bloque)


if __name__ == "__main__":
    unittest.main()
