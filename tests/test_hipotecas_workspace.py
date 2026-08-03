"""`hipotecas` tenía frontera de sociedad, pero no de tenant.

Solo `empresa_id`: el mismo punto de partida que dejó 2014 clientes invisibles.
Se añade `workspace_id` y se estampa en las altas.

El estampado va en un UPDATE aparte, no dentro del INSERT, porque la tabla vive
en bases que aún no han migrado y en los propios tests: un INSERT con una columna
que no existe revienta el alta entera.

Al principio se dejó sin NOT NULL a propósito: la empresa Financiaciones Modernia
colgaba a la vez de Modernia y de Verifika², el resolvedor se negaba a adivinar y
devolvía '', y con la restricción puesta el alta habría fallado. Al dejar de
heredar el holding las sociedades de sus participadas, cada empresa pertenece a un
solo workspace y la restricción ya se puede sostener.
"""

import unittest
from pathlib import Path

from web import server

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")


class LaColumnaTests(unittest.TestCase):
    def test_se_crea_al_arrancar(self):
        self.assertIn('ensure_column(conn, "hipotecas", "workspace_id", "workspace_id TEXT")', SERVER)

    def test_lleva_not_null(self):
        i = SERVER.index('ensure_column(conn, "hipotecas", "workspace_id"')
        tramo = SERVER[i: i + 900]
        self.assertIn('ensure_not_null(conn, "hipotecas", "workspace_id")', tramo)

    def test_queda_escrito_por_que_no_se_pudo_antes(self):
        # Para que nadie la quite creyendo que sobra, ni la vuelva a poner a ciegas.
        i = SERVER.index('ensure_column(conn, "hipotecas", "workspace_id"')
        self.assertIn("colgaba a la vez de Modernia y de Verifika", SERVER[i: i + 900])


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


class ElHoldingNoHeredaSociedadesTests(unittest.TestCase):
    """Verifika² enlazaba las 8 sociedades de Modernia y la de Modernia Centro.

    Mientras una empresa colgaba de dos workspaces, `resolve_workspace_id_for_empresa`
    no podía deducir nada —y hacía bien: estampar el workspace equivocado sería una
    fuga entre tenants—. Eso bloqueaba el NOT NULL de `hipotecas.workspace_id` y
    hacía que Verifika² "viera" 2009 clientes y 110 hipotecas que no son suyos.

    Este test no puede comprobar los datos de producción; fija la regla que los
    hizo posibles.
    """

    def test_el_resolvedor_no_adivina_con_varios_workspaces(self):
        i = SERVER.index("def resolve_workspace_id_for_empresa")
        f = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("NO adivinamos", f)
        self.assertIn("fuga entre tenants", f)
