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
    def test_generic_client_list_falls_back_to_workspace_companies(self):
        block = _block('if path == "/api/clientes_list":', 'if path == "/api/fin_inmobiliarias":')

        # El vínculo por empresas del workspace tiene que estar en la rama genérica.
        self.assertIn("EXISTS (SELECT 1 FROM clientes_empresas ce", block)
        self.assertIn("fetch_workspace_company_ids(conn, workspace_id)", block)

        # Y no puede quedar ningún filtro que use la columna como única condición.
        self.assertNotIn(
            "FROM clientes c WHERE COALESCE(c.workspace_id, '') = ? ORDER BY c.nombre",
            block,
            "El filtro por workspace no puede depender solo de `clientes.workspace_id`: "
            "está vacía en todo lo anterior a la migración.",
        )

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


if __name__ == "__main__":
    unittest.main()
