"""El CRM hipotecario deja de estar atado a una empresa.

Todo lo roto de estos días era el mismo fallo con distinta ropa: el ámbito real es
el workspace y el código filtraba por sociedad.

  - 2014 clientes invisibles, porque el ámbito se deducía de `clientes_empresas`.
  - Daniel García y Teresa Ramos fuera de la plantilla de RRHH.
  - La salud del workspace atribuida a una de sus ocho sociedades.
  - Y el dashboard de hipotecas vacío: con Estudio Velázquez como empresa activa
    pedía SUS hipotecas —cero—, cuando las 110 están en Financiaciones Modernia.

El dashboard además, llamado por workspace, se quedaba con la PRIMERA empresa de
la lista "para no bloquear" y devolvía su resumen como si fuera el del tenant.

`build_service_scope_filter` ya existía y solo lo usaba un endpoint de ocho.
"""

import unittest
from pathlib import Path

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
APP = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")


def _endpoint(nombre):
    i = SERVER.index('if path == "/api/{}":'.format(nombre))
    return SERVER[i: SERVER.index('        if path == "/api/', i + 60)]


class ElDashboardVaPorWorkspaceTests(unittest.TestCase):
    def test_usa_el_filtro_de_ambito(self):
        b = _endpoint("hipoteca_dashboard")
        self.assertIn('build_service_scope_filter(', b)

    def test_ninguna_consulta_se_ata_a_una_empresa(self):
        self.assertNotIn("WHERE empresa_id = ?", _endpoint("hipoteca_dashboard"))

    def test_ya_no_se_queda_con_la_primera_empresa(self):
        b = _endpoint("hipoteca_dashboard")
        self.assertNotIn("empresa_id = empresa_ids[0]", b)
        self.assertIn("la PRIMERA empresa", b)

    def test_admite_que_solo_llegue_el_workspace(self):
        self.assertIn("if not empresa_id and not workspace_id:", _endpoint("hipoteca_dashboard"))

    def test_la_cache_distingue_el_workspace(self):
        # Sin esto, dos workspaces distintos compartirían resultado cacheado.
        b = _endpoint("hipoteca_dashboard")
        i = b.index("cache_key = (")
        self.assertIn("workspace_id", b[i: i + 220])


class LosRecolectoresAdmitenWorkspaceTests(unittest.TestCase):
    RECOLECTORES = (
        "collect_hipotecas_export_rows",
        "collect_hipotecas_firmadas_rows",
        "collect_hipotecas_firmadas_export_rows",
        "collect_hipoteca_dashboard_entity_total_rows",
    )

    def test_todos_aceptan_workspace_id(self):
        for nombre in self.RECOLECTORES:
            i = SERVER.index("def {}(".format(nombre))
            firma = SERVER[i: SERVER.index("):", i)]
            with self.subTest(recolector=nombre):
                self.assertIn("workspace_id", firma)

    def test_ninguno_filtra_por_una_sola_empresa(self):
        for nombre in self.RECOLECTORES:
            i = SERVER.index("def {}(".format(nombre))
            cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
            with self.subTest(recolector=nombre):
                self.assertNotIn("WHERE empresa_id = ?", cuerpo)
                self.assertIn("build_service_scope_filter(", cuerpo)


class LaPantallaMandaElWorkspaceTests(unittest.TestCase):
    def test_el_dashboard_lo_incluye_en_la_peticion(self):
        i = APP.index("const loadHipotecaDashboard = () => {")
        bloque = APP[i: APP.index("hipotecaDashboardApi(", i)]
        self.assertIn('params.set("workspace_id", wsId)', bloque)


if __name__ == "__main__":
    unittest.main()
