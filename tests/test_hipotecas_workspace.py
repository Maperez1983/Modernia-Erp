"""`hipotecas` tenía frontera de sociedad, pero no de tenant.

Solo `empresa_id`: el mismo punto de partida que dejó 2014 clientes invisibles.
Se añade `workspace_id` y se estampa en las altas.

El estampado va en un UPDATE aparte, no dentro del INSERT, porque la tabla vive
en bases que aún no han migrado y en los propios tests: un INSERT con una columna
que no existe revienta el alta entera.

Y no lleva NOT NULL todavía. No es un descuido: la empresa Financiaciones Modernia
cuelga de dos workspaces (Modernia y Verifika²), así que el resolvedor se niega a
adivinar y devuelve ''. Con la restricción puesta, el alta fallaría.
"""

import unittest
from pathlib import Path

from web import server

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")


class LaColumnaTests(unittest.TestCase):
    def test_se_crea_al_arrancar(self):
        self.assertIn('ensure_column(conn, "hipotecas", "workspace_id", "workspace_id TEXT")', SERVER)

    def test_todavia_sin_not_null_y_se_dice_por_que(self):
        i = SERVER.index('ensure_column(conn, "hipotecas", "workspace_id"')
        tramo = SERVER[i: i + 700]
        self.assertNotIn('ensure_not_null(conn, "hipotecas"', tramo)
        self.assertIn("cuelga de dos workspaces", tramo)


class ElEstampadoTests(unittest.TestCase):
    def _funcion(self):
        i = SERVER.index("def stamp_hipoteca_workspace")
        return SERVER[i: SERVER.index("\ndef ", i + 10)]

    def test_no_revienta_si_la_columna_no_existe(self):
        f = self._funcion()
        self.assertIn('if "workspace_id" not in (table_columns(conn, "hipotecas") or set()):', f)
        self.assertIn('return ""', f)

    def test_no_adivina_cuando_la_empresa_es_de_varios_workspaces(self):
        # `resolve_workspace_id_for_empresa` devuelve '' en ese caso: se respeta.
        f = self._funcion()
        self.assertIn("resolve_workspace_id_for_empresa(conn, empresa_id)", f)
        self.assertIn("if not ws:", f)

    def test_se_llama_en_las_dos_altas(self):
        llamadas = SERVER.count("stamp_hipoteca_workspace(conn,") - SERVER.count("def stamp_hipoteca_workspace(conn,")
        self.assertEqual(llamadas, 2, "las dos vías de alta tienen que estampar")

    def test_el_insert_no_lleva_la_columna(self):
        # A propósito: ver el docstring del módulo.
        i = SERVER.index("INSERT INTO hipotecas (")
        self.assertNotIn("workspace_id", SERVER[i: SERVER.index(")", i)])


class ElResolvedorSigueSiendoPrudenteTests(unittest.TestCase):
    def test_no_inventa_workspace(self):
        i = SERVER.index("def resolve_workspace_id_for_empresa")
        f = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("NO adivinamos", f)


if __name__ == "__main__":
    unittest.main()
