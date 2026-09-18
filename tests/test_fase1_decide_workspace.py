"""La regla con la que la fase 1 rellena `workspace_id` (scripts/fase1_workspace_id.py).

Se prueba sin base: es la parte que decide, y equivocarse aquí mezcla tenants.
"""

import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "fase1", Path(__file__).resolve().parents[1] / "scripts" / "fase1_workspace_id.py"
)
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)

PLAT = "ws-plataforma"
MAPA = {
    "emp-modernia": ["ws-modernia", PLAT],
    "emp-ansa": ["ws-centro", PLAT],
    "emp-tecnica": [PLAT],
    "emp-dudosa": ["ws-a", "ws-b", PLAT],
}
CLIENTES = {"cli-mod": "ws-modernia", "cli-plat": PLAT}


def decide(empresa, cliente=None):
    return F.decide_workspace(empresa, cliente, mapa_empresa=MAPA, ws_de_cliente=CLIENTES, plataforma=PLAT)


class DecideWorkspaceTests(unittest.TestCase):
    def test_por_empresa_descartando_la_plataforma(self):
        self.assertEqual(decide("emp-modernia"), ("ws-modernia", "empresa"))
        self.assertEqual(decide("emp-ansa"), ("ws-centro", "empresa"))

    def test_nunca_asigna_la_plataforma(self):
        self.assertEqual(decide("emp-tecnica")[0], "")
        self.assertEqual(decide(None, "cli-plat")[0], "")

    def test_sin_empresa_tira_del_cliente(self):
        self.assertEqual(decide(None, "cli-mod"), ("ws-modernia", "cliente"))
        self.assertEqual(decide("emp-tecnica", "cli-mod"), ("ws-modernia", "cliente"))

    def test_la_duda_no_se_resuelve_adivinando(self):
        self.assertEqual(decide("emp-dudosa"), ("", "empresa_ambigua"))
        self.assertEqual(decide(None), ("", "sin_empresa_ni_cliente"))
        self.assertEqual(decide("emp-desconocida"), ("", "empresa_de_plataforma_o_sin_vinculo"))

    def test_no_toca_vinculos_ni_registro_horario(self):
        for tabla in ("workspace_empresas", "workspace_companies", "clientes_empresas",
                      "workspace_registro_horario", "workspace_registro_personal", "hipotecas_dedup_backup"):
            self.assertFalse(F.es_tabla_de_negocio(tabla), tabla)
        for tabla in ("seguros", "gestoria_docs", "hipotecas", "movimientos"):
            self.assertTrue(F.es_tabla_de_negocio(tabla), tabla)


if __name__ == "__main__":
    unittest.main()
