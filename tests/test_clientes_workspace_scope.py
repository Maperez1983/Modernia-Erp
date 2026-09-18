"""Regresión: el listado de clientes no puede depender solo de `clientes.workspace_id`.

Verificado en producción (2026-07-30): `clientes.workspace_id` llegó con una
migración y los 2014 clientes anteriores lo tienen vacío. Como la rama genérica de
`/api/clientes_list` filtraba solo por esa columna, cualquier vista de CRM que
pasara `workspace_id` devolvía CERO clientes mientras seguían en la tabla:

    /api/clientes_list                              -> 2014
    /api/clientes_list?empresa_id=...               -> 2014
    /api/clientes_list?workspace_id=...             -> 0
    /api/clientes_list?workspace_id=...&servicio=inmobiliaria -> 0

Solo la rama de gestoría se salvaba, porque ya combinaba el vínculo por empresas
del workspace. La misma forma del fallo estaba en la rama de seguros, donde el
`elif` de respaldo era inalcanzable: solo entraba si la columna NO existía, y
existe.

Estos tests fijan las dos propiedades del arreglo: que se acepte también al
cliente vinculado a una empresa del workspace, y que sin forma de acotar NO se
devuelva la tabla entera (eso enseñaría clientes de otros tenants).
"""

import unittest
from pathlib import Path


SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")


def _block(marker, end_marker):
    start = SERVER.index(marker)
    return SERVER[start : SERVER.index(end_marker, start)]


class ClientesWorkspaceScopeTests(unittest.TestCase):
    def test_generic_client_list_scopes_only_by_workspace(self):
        """Fase 2 (2026-09-18): el cliente es del workspace que lleva.

        Hasta la fase 1 muchos clientes no llevaban `workspace_id` y aquí se aceptaba
        también al que colgaba de una empresa del workspace. Como las empresas se
        comparten entre workspaces, eso enseñaba clientes de otro. Hoy todos lo
        llevan y un disparador se lo pone a los nuevos: el "o" sobra.
        """
        block = _block('if path == "/api/clientes_list":', 'if path == "/api/fin_inmobiliarias":')
        self.assertIn("COALESCE(c.workspace_id, '') = ?", block)
        self.assertNotIn("EXISTS (SELECT 1 FROM clientes_empresas ce", block)
        self.assertNotIn("fetch_workspace_operational_company_ids(conn, workspace_id)", block)

    def test_generic_client_list_is_fail_closed_without_scope(self):
        block = _block('if path == "/api/clientes_list":', 'if path == "/api/fin_inmobiliarias":')
        marker = "if scope_parts:"
        self.assertIn(marker, block)
        tail = block[block.index(marker) :]
        # Sin manera de acotar por workspace la respuesta es vacía, nunca la tabla entera.
        self.assertIn("rows = []", tail)

    def test_seguros_scope_combines_both_links(self):
        # La rama de seguros tenía el respaldo en un `elif` inalcanzable.
        self.assertNotIn('if workspace_id and "workspace_id" in seguros_cols:', SERVER)
        self.assertEqual(SERVER.count('if "workspace_id" in seguros_cols:'), 2)

    def test_multiservice_scope_is_only_the_workspace(self):
        """La rama de servicios acota por el workspace del cliente, sin "o por empresa"."""
        block = _block("\n            if normalized_services:", "# El scoping va por workspace, pero")
        self.assertIn('where_parts.append("COALESCE(c.workspace_id, \'\') = ?")', block)
        self.assertNotIn("ce.empresa_id IN", block)
        self.assertNotIn('" OR ".join(scope_parts)', block)

    def test_nif_duplicate_lookup_combines_links(self):
        """El mismo `elif` inalcanzable estaba en la búsqueda de duplicados por NIF.

        Aquí el síntoma no es una lista vacía sino un cliente repetido: si la
        búsqueda no encuentra al que ya existe, el alta lo crea otra vez.
        """
        block = _block("def resolve_clientes_by_nif_rows(", "\ndef ")
        self.assertNotIn('if workspace_id and "workspace_id" in ce_cols:', block)
        self.assertIn('if "workspace_id" in ce_cols:', block)
        self.assertIn('if "workspace_id" in cliente_cols:', block)
        self.assertIn('" OR ".join(scope_parts)', block)
        # Y sin forma de acotar, no se sugiere nada en vez de cruzar tenants.
        tail = block[block.index("if not scope_parts:") :]
        self.assertIn("return []", tail)

    def test_multiservice_scope_is_fail_closed(self):
        """Sin columna de workspace no hay forma de acotar: vacío, nunca la tabla entera."""
        block = _block("\n            if normalized_services:", "# El scoping va por workspace, pero")
        marker = 'if "workspace_id" not in c_cols:'
        self.assertIn(marker, block)
        tail = block[block.index(marker) :]
        self.assertIn("json_response(self, [])", tail)

if __name__ == "__main__":
    unittest.main()
