"""Fase 6 del ámbito por workspace (2026-09-19): seguros.

- Ofertas y referidos iban por `clientes.empresa_id` (vacía en 1.163 clientes) y, peor,
  el front no enviaba ni workspace ni empresa (`api()` solo los añade en los POST): quien
  no era de plataforma recibía un 400 y las dos tablas salían vacías. Y la plataforma
  veía los de todos los workspaces aunque pidiera uno.
- La exportación de recibos acota por el workspace de cada recibo.
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
    def test_ofertas_y_referidos_con_workspace_van_por_el_del_cliente(self):
        for ruta in ("/api/seguros_ofertas", "/api/seguros_referidos"):
            with self.subTest(ruta=ruta):
                bloque = _bloque(ruta)
                self.assertIn("COALESCE(c.workspace_id, '') = ?", bloque)
                self.assertIn("enforce_workspace_membership(", bloque)
                # El workspace manda también para la plataforma: va antes que el privilegio.
                self.assertLess(bloque.index("if _of_ws:" if "ofertas" in ruta else "if _ref_ws:"),
                                bloque.index("elif not _of_privileged" if "ofertas" in ruta else "elif not _ref_privileged"))

    def test_recibos_usan_el_ayudante(self):
        bloque = _bloque("/api/seguros_recibos_export")
        self.assertIn('ambito_filas_sql(\n                conn, "seguros_recibos", "r"', bloque)
        self.assertNotIn("resolve_empresa_ids_for_request(conn", bloque)


class FrontTests(unittest.TestCase):
    def test_ofertas_y_referidos_envian_el_ambito(self):
        self.assertIn("const segurosScopeParams = (params) => {", APP)
        self.assertIn("const params = segurosScopeParams(new URLSearchParams());", APP)
        self.assertIn("api(`/api/seguros_referidos?${segurosScopeParams(new URLSearchParams()).toString()}`)", APP)
        self.assertNotIn('api("/api/seguros_referidos")', APP)


if __name__ == "__main__":
    unittest.main()
