"""Regresiones de la pantalla de entrada, auditada en producción el 2026-07-31.

Lo que se encontró midiendo la home con sesión iniciada:

- "Continuar workspace · 78be2029839add99b5ec83570311faea · Sin empresa activa":
  un id interno de 32 caracteres a la vista del usuario.
- `/api/home_time_status` pedido dos veces en cada entrada (151 ms + 100 ms).
- El diálogo de fichaje se abre solo tapando la home y el foco se quedaba en
  `<body>`: quien navega por teclado tenía que tabular entre más de mil
  elementos de detrás para llegar a los botones que le tapaban la pantalla.
- "CRM 360" tres veces en la primera pantalla.
- La columna con todo el contenido ocupaba menos ancho que la que estaba vacía.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
CSS = (RAIZ / "web" / "styles.css").read_text(encoding="utf-8")


class IdInternoNoSeEnsenaTests(unittest.TestCase):
    def test_hay_deteccion_de_id_interno(self):
        self.assertIn("looksLikeInternalId", APP)
        # Hex de 32 y uuid con guiones: los dos formatos que usa el CRM.
        self.assertIn("[0-9a-f]{32}", APP)
        self.assertIn("[0-9a-f]{12}", APP)

    def test_el_nombre_visible_pasa_por_la_deteccion(self):
        bloque = APP[APP.index("const getWorkspaceDisplayName") : APP.index("const isGrupoModerniaWorkspace")]
        self.assertIn("looksLikeInternalId(rawName)", bloque)
        # Y antes de rendirse intenta resolver el nombre real desde state.workspaces.
        self.assertIn("workspaceNameById", bloque)

    def test_resolver_por_id_busca_en_la_lista_ya_cargada(self):
        bloque = APP[APP.index("const workspaceNameById") : APP.index("const getWorkspaceDisplayName")]
        self.assertIn("state?.workspaces", bloque)
        self.assertIn("nombre", bloque)


class CadaWorkspaceMuestraSuNombreTests(unittest.TestCase):
    """Entrar en Modernia y que la pantalla diga "Verifika²".

    `getWorkspaceDisplayName` renombraba modernia/grupomodernia/grupo-modernia al
    nombre de marca. Con un solo tenant era cosmético; con cuatro workspaces —dos
    llamados justamente Modernia y Verifika²— impedía saber en cuál estabas, y eso
    con Verifika² siendo superconjunto de Modernia y viendo sus mismos clientes.
    """

    def _bloque(self):
        return APP[APP.index("const getWorkspaceDisplayName") : APP.index("const isGrupoModerniaWorkspace")]

    def test_modernia_ya_no_se_renombra(self):
        bloque = self._bloque()
        for alias in ('"modernia"', '"grupomodernia"', '"grupo-modernia"'):
            self.assertNotIn(alias, bloque, f"{alias} sigue sustituyéndose por la marca")

    def test_el_nombre_de_la_ficha_manda(self):
        bloque = self._bloque()
        # Si viene el registro del workspace, se devuelve su nombre sin tocarlo.
        self.assertIn("nombreReal", bloque)
        self.assertLess(
            bloque.index("if (nombreReal) return nombreReal;"),
            bloque.index("normalizeWorkspaceIdentifier"),
            "el nombre real tiene que devolverse antes de cualquier normalización",
        )

    def test_el_slug_suelto_se_sigue_presentando_bien(self):
        # Varios callers pasan "verifika2" como respaldo: no puede leerse en minúsculas.
        bloque = self._bloque()
        self.assertIn('"verifika2", "verifika", "verifika-2"', bloque)
        self.assertIn("DEFAULT_TENANT_WORKSPACE_NAME", bloque)

    def test_no_se_toco_la_logica_del_copiloto_legal(self):
        # `isGrupoModerniaWorkspace` usa su propia lista y decide permisos, no texto.
        bloque = APP[APP.index("const isGrupoModerniaWorkspace") : APP.index("const workspaceHasEnabledModule")]
        self.assertIn('"modernia"', bloque)
        self.assertIn('"grupomodernia"', bloque)


class SinLlamadaDuplicadaTests(unittest.TestCase):
    def test_el_modal_reutiliza_el_estado_recien_cargado(self):
        bloque = APP[APP.index("const openHomeTimePunchModal") : APP.index("const renderWorkspaceTimeSummary")]
        self.assertIn("_homeTimeStatusLoadedAt", bloque)
        self.assertIn("HOME_TIME_STATUS_FRESCO_MS", bloque)
        # El return temprano tiene que ir ANTES del fetch, o no ahorra nada.
        corte = bloque.index("recienCargado")
        self.assertLess(corte, bloque.index('api("/api/home_time_status")'))

    def test_el_arranque_marca_cuando_lo_cargo(self):
        self.assertIn("_homeTimeStatusLoadedAt = state.homeTimeStatus ? Date.now() : 0;", APP)


class FocoDelDialogoTests(unittest.TestCase):
    def test_al_abrir_el_foco_entra_en_el_dialogo(self):
        bloque = APP[APP.index("const openHomeTimePunchModal") : APP.index("const renderWorkspaceTimeSummary")]
        self.assertIn("_homeTimePunchFocusOrigen = document.activeElement", bloque)
        self.assertIn(".focus()", bloque)

    def test_al_cerrar_el_foco_vuelve_a_su_sitio(self):
        bloque = APP[APP.index("const closeHomeTimePunchModal") : APP.index("const openHomeTimePunchModal")]
        self.assertIn("_homeTimePunchFocusOrigen", bloque)
        self.assertIn("focus()", bloque)

    def test_el_dialogo_esta_anunciado_como_tal(self):
        bloque = APP[APP.index("const ensureHomeTimePunchModal") : APP.index("const renderHomeTimePunchModal")]
        self.assertIn('setAttribute("role", "dialog")', bloque)
        self.assertIn('setAttribute("aria-modal", "true")', bloque)
        self.assertIn('aria-labelledby', bloque)
        self.assertIn('id="homeTimePunchTitulo"', bloque)

    def test_esc_cierra_guardando_el_descarte_del_dia(self):
        bloque = APP[APP.index("const ensureHomeTimePunchModal") : APP.index("const renderHomeTimePunchModal")]
        self.assertIn('event.key === "Escape"', bloque)
        # `close` es el mismo que el botón Cerrar, que persiste el descarte.
        self.assertIn("closeHomeTimePunchModal({ persist: true })", bloque)


class TituloNoSeRepiteTests(unittest.TestCase):
    def test_el_h2_de_la_home_no_repite_el_h1(self):
        self.assertIn("<h1>CRM 360</h1>", INDEX)
        self.assertNotIn("<h2>CRM 360</h2>", INDEX)
        self.assertIn("<h2>Inicio</h2>", INDEX)

    def test_la_barra_de_contexto_deriva_del_h2(self):
        # Por eso basta con arreglar el h2: la barra lo copia.
        ui = (RAIZ / "web" / "ui-foundation.js").read_text(encoding="utf-8")
        self.assertIn('visibleSection?.querySelector("h2', ui)


class RepartoDeLaHomeTests(unittest.TestCase):
    def _regla(self):
        i = CSS.index("body.theme-operativa .hero-shell {")
        return CSS[i : CSS.index("}", i)]

    def test_no_vuelve_la_columna_vacia(self):
        """La home pasó a una sola columna.

        Antes eran dos: 1.8fr para la que solo llevaba el título y el selector de
        año, y 0.95fr para la que llevaba todo. Cualquier reparto a dos columnas
        reintroduce el hueco, así que aquí se veta el patrón entero.
        """
        regla = self._regla()
        self.assertIn("grid-template-columns: minmax(0, 1fr);", regla)
        self.assertIsNone(
            re.search(r"grid-template-columns:[^;]*fr\)\s*minmax", regla),
            "la home volvió a repartirse en dos columnas",
        )

    def test_el_contenido_no_flota_centrado_en_el_hueco(self):
        self.assertIn("align-items: start;", self._regla())


class BusquedaAnunciadaTests(unittest.TestCase):
    def test_los_resultados_se_anuncian(self):
        self.assertIn('id="homeModuleSearchResults"', APP)
        self.assertIn('aria-live="polite"', APP)
        self.assertIn('aria-controls="homeModuleSearchResults"', APP)


if __name__ == "__main__":
    unittest.main()
