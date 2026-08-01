"""El panel de workspaces mezclaba tres ámbitos y contaba mal.

Lo que se veía en producción el 2026-08-01, bajo un título que decía
"Configurando: Modernia":

  - "Empresas operativas 19" y "Módulos activos 51", que son la suma de los cuatro
    workspaces. Modernia tiene 8 empresas y 15 módulos.
  - "Salud operativa de Estudio Velazquez 2012 SL · 2004 clientes", cuando esas
    cifras son del workspace entero —`fetch_workspace_health` no recibe empresa— y
    el total real es 2014: el recuento iba por `clientes_empresas`, así que los
    clientes sin empresa no contaban. Justo los que la misma pantalla señalaba
    arriba como "5 clientes sin asignar".
  - "Inmovere Holding" como raíz del organigrama, escrito a mano: en cualquier otro
    tenant habría salido igual.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")


class LaTarjetaDeSaludTests(unittest.TestCase):
    def test_se_titula_con_el_workspace_no_con_la_empresa_activa(self):
        i = APP.index("const renderWorkspaceHealth")
        bloque = APP[i: i + 2500]
        self.assertIn("Salud operativa de ${escapeHtml(workspaceLabel)}", bloque)
        self.assertNotIn("getWorkspaceCompanyContextLabel()", bloque)

    def test_dice_que_suma_las_empresas(self):
        i = APP.index("const renderWorkspaceHealth")
        self.assertIn("Suma de las empresas del workspace", APP[i: i + 2500])


class ElRecuentoDeClientesTests(unittest.TestCase):
    def _bloque(self):
        i = SERVER.index("def fetch_workspace_health")
        return SERVER[i: SERVER.index("\ndef ", i + 10)]

    def test_cuenta_tambien_a_los_que_no_tienen_empresa(self):
        bloque = self._bloque()
        self.assertIn("UNION", bloque)
        self.assertIn("FROM clientes c", bloque)

    def test_usa_la_regla_de_ambito_del_resto_del_crm(self):
        bloque = self._bloque()
        self.assertIn("COALESCE(c.workspace_id, '') = ?", bloque)
        self.assertIn("COALESCE(c.workspace_id, '') = '' AND COALESCE(c.empresa_id, '') IN", bloque)

    def test_sigue_contando_a_los_vinculados_por_la_tabla_de_relacion(self):
        # Un cliente puede estar en una empresa del workspace solo por `clientes_empresas`.
        self.assertIn("FROM clientes_empresas ce", self._bloque())

    def test_aguanta_una_base_sin_la_columna(self):
        bloque = self._bloque()
        self.assertIn('if "workspace_id" in c_cols:', bloque)


class ElAyudanteDeAmbitoTests(unittest.TestCase):
    """La regla estaba copiada a mano en varios sitios."""

    def _funcion(self):
        i = SERVER.index("def clientes_workspace_scope_sql")
        return SERVER[i: SERVER.index("\ndef ", i + 10)]

    def test_sin_workspace_no_inventa_filtro(self):
        self.assertIn('return "", []', self._funcion())

    def test_rescata_a_los_clientes_sin_workspace_estampado(self):
        f = self._funcion()
        self.assertIn("COALESCE({alias}.workspace_id, '') = '' ", f.replace("f\"", '"'))


class LosContadoresDicenSuAmbitoTests(unittest.TestCase):
    def test_dejan_claro_que_son_de_plataforma(self):
        i = APP.index("const renderWorkspaceKpis")
        bloque = APP[i: i + 1200]
        self.assertIn("de la plataforma", bloque)
        self.assertIn("En todos los workspaces, no solo en este", bloque)


class LosPendientesTests(unittest.TestCase):
    def test_son_los_del_checklist_y_se_dice(self):
        i = APP.index("const getWorkspacePendingCount")
        bloque = APP[i: APP.index("\n};", i)]
        self.assertNotIn("Math.max", bloque)
        self.assertIn('item?.done', bloque)
        self.assertIn("Del checklist de puesta en marcha", APP)


class ElOrganigramaTests(unittest.TestCase):
    def test_la_raiz_sale_del_workspace(self):
        i = APP.index("const renderHoldingOrgChart")
        bloque = APP[i: i + 3000]
        self.assertNotIn("<h4>Inmovere Holding</h4>", bloque)
        self.assertIn("getWorkspaceDisplayName(state.currentWorkspaceId)", bloque)

    def test_el_nodo_aie_solo_si_esa_empresa_existe(self):
        i = APP.index("const renderHoldingOrgChart")
        bloque = APP[i: i + 3000]
        self.assertIn("companies.includes(AIE_COMPANY)", bloque)


class ClientesStatsAcotaPorTenantTests(unittest.TestCase):
    def _bloque(self):
        i = SERVER.index('if path == "/api/clientes_stats":')
        return SERVER[i: SERVER.index('if path == "/api/', i + 60)]

    def test_lee_el_workspace(self):
        self.assertIn('workspace_id = (params.get("workspace_id", [""])[0] or "").strip()', self._bloque())

    def test_no_queda_ningun_recuento_global_sin_condicion(self):
        bloque = self._bloque()
        # El total pelado solo puede quedar como respaldo cuando no llega workspace.
        i = bloque.index('SELECT COUNT(*) AS total FROM clientes"')
        antes = bloque[:i]
        self.assertIn("elif ws_where:", antes)
        self.assertIn("else:", antes)


class NoSePideDosVecesLoMismoALaVezTests(unittest.TestCase):
    """37 peticiones para una pantalla, con /api/health seis veces."""

    def test_las_peticiones_en_vuelo_se_comparten(self):
        i = APP.index("const safeWorkspaceApi = async")
        bloque = APP[i: i + 1400]
        self.assertIn("peticionesEnVuelo.has(clave)", bloque)
        self.assertIn("peticionesEnVuelo.set(clave, promesa)", bloque)

    def test_se_olvida_al_terminar_para_no_servir_datos_viejos(self):
        i = APP.index("const safeWorkspaceApi = async")
        bloque = APP[i: i + 1400]
        self.assertIn("peticionesEnVuelo.delete(clave)", bloque)
        self.assertIn("finally", bloque)

    def test_la_plantilla_no_se_pide_fuera_de_rrhh(self):
        i = APP.index("const loadWorkspaceRrhhRoster")
        bloque = APP[i: APP.index("\n};", i)]
        self.assertIn('!== "rrhh"', bloque)


if __name__ == "__main__":
    unittest.main()
