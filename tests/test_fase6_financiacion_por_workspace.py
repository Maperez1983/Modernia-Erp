"""Fase 6 del ámbito por workspace (2026-09-19): financiación.

Asesoramientos e hipotecas en estudio acotaban por "las empresas del workspace". Ahora,
con workspace, por el de cada fila (ambito_filas_sql), con la empresa de financiación
como filtro dentro, y comprueban que el usuario pertenece a ese workspace o empresa. El
front les añade el workspace activo (conWorkspaceActivo). El panel de hipotecas ya iba
por build_service_scope_filter, que es solo por workspace desde la fase 2.
"""

import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")


def _bloque(ruta):
    i = SERVER.index(f'if path == "{ruta}":')
    return SERVER[i : SERVER.index('\n        if path == "/api/', i + 20)]


class ServidorTests(unittest.TestCase):
    def test_usan_el_ayudante_y_comprueban_pertenencia(self):
        for ruta, tabla in (("/api/fin_asesoramientos", "asesoramientos_financiacion"),
                            ("/api/fin_hipotecas_estudio", "hipotecas")):
            with self.subTest(ruta=ruta):
                bloque = _bloque(ruta)
                self.assertIn(f'ambito_filas_sql(\n                conn, "{tabla}"', bloque)
                self.assertIn("enforce_workspace_or_empresa_scope(", bloque)
                self.assertNotIn("resolve_empresa_ids_for_request(conn", bloque)


class FrontTests(unittest.TestCase):
    def test_envian_el_workspace_activo(self):
        self.assertIn("const conWorkspaceActivo = (params) => {", APP)
        self.assertIn("conWorkspaceActivo(new URLSearchParams({ empresa_id: empresaId, q }))", APP)
        self.assertIn("conWorkspaceActivo(new URLSearchParams({ empresa_id: empresaId }))", APP)


if __name__ == "__main__":
    unittest.main()
