"""`hipotecas` tenía frontera de sociedad, pero no de tenant.

Solo `empresa_id`: el mismo punto de partida que dejó 2014 clientes invisibles.
Se añade `workspace_id` y se estampa en las altas.

El estampado va en un UPDATE aparte, no dentro del INSERT, porque la tabla vive
en bases que aún no han migrado y en los propios tests: un INSERT con una columna
que no existe revienta el alta entera.

Sigue sin NOT NULL, y esta vez con la lección aprendida a base de romper
producción: el 2026-08-03 se desenganchó el holding, se dio por bueno que cada
empresa colgaba de un solo workspace y se puso la restricción. El siguiente
arranque volvió a enganchar todas las empresas al workspace por defecto
—`bootstrap_default_workspace` lo hacía en cada arranque— y dar de alta una
hipoteca empezó a fallar con violación de NOT NULL.

Se repondrá cuando el desenganche aguante un arranque. Ver
`test_bootstrap_no_reengancha`.
"""

import unittest
from pathlib import Path

from web import server

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")


class LaColumnaTests(unittest.TestCase):
    def test_se_crea_al_arrancar(self):
        self.assertIn('ensure_column(conn, "hipotecas", "workspace_id", "workspace_id TEXT")', SERVER)

    def test_no_lleva_not_null_todavia(self):
        i = SERVER.index('ensure_column(conn, "hipotecas", "workspace_id"')
        tramo = SERVER[i: i + 900]
        self.assertNotIn('ensure_not_null(conn, "hipotecas"', tramo)

    def test_queda_escrito_por_que(self):
        # Para que nadie la reponga a ciegas: ya tumbó el alta de hipotecas una vez.
        i = SERVER.index('ensure_column(conn, "hipotecas", "workspace_id"')
        self.assertIn("alta de hipotecas dejó de funcionar", SERVER[i: i + 1200])


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

    def test_hoy_no_se_llama_y_se_dice_por_que(self):
        """Estampar esconde el registro de los demás workspaces que tienen esa empresa.

        Al estampar las 110 hipotecas con Modernia desaparecieron de Verifika², que
        es el workspace por defecto: el módulo se quedó vacío en pantalla.
        """
        llamadas = SERVER.count("stamp_hipoteca_workspace(conn,") - SERVER.count("def stamp_hipoteca_workspace(conn,")
        self.assertEqual(llamadas, 0)
        i = SERVER.index("def stamp_hipoteca_workspace")
        self.assertIn("HOY NO SE LLAMA", SERVER[i: i + 400])

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
