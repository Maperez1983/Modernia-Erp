"""Un cliente no puede volver a nacer sin workspace.

Es el fallo que abrió esta sesión: 2014 clientes en la tabla y 0 en las listas,
porque el ámbito se deducía de `clientes_empresas` y quien no tenía ese vínculo
desaparecía. Con la columna ya poblada (backfill del 2026-08-01) se cierra la
puerta por los dos lados:

  - en el código, rechazando el alta cuando no hay forma de saber el workspace;
  - en la base, con NOT NULL, que es lo único que aguanta si alguien inserta por
    otro camino.

El orden importa: primero que ninguna vía escriba NULL, después la restricción.
Al revés, la restricción convierte un cliente invisible en un error 500.
"""

import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
SCHEMA = (RAIZ / "web" / "schema_support.py").read_text(encoding="utf-8")


class ElAltaPorApiTests(unittest.TestCase):
    def _bloque(self):
        i = SERVER.index('elif parsed.path == "/api/clientes":')
        return SERVER[i: SERVER.index("json_response(self, {\"ok\": True, \"id\": cliente_id})", i)]

    def test_deduce_el_workspace_de_la_empresa(self):
        self.assertIn("cliente_workspace_id_for_write(", self._bloque())

    def test_rechaza_el_alta_si_no_hay_forma_de_saberlo(self):
        bloque = self._bloque()
        self.assertIn("if not ws_para_alta:", bloque)
        self.assertIn("status=400", bloque[bloque.index("if not ws_para_alta:"):])

    def test_ya_no_inserta_nulo(self):
        self.assertNotIn('values.insert(1, workspace_id or None)', self._bloque())


class ElAltaInternaTests(unittest.TestCase):
    """Seguros, inmobiliaria, financiaciones y presupuestos pasan por aquí."""

    def _funcion(self):
        i = SERVER.index("def insert_cliente_scoped")
        return SERVER[i: SERVER.index("\ndef ", i + 10)]

    def test_falla_claro_en_vez_de_insertar_nulo(self):
        f = self._funcion()
        self.assertIn("raise ValueError(", f)
        self.assertNotIn("vals.insert(1, ws or None)", f)

    def test_el_mensaje_dice_que_falta(self):
        f = self._funcion()
        self.assertIn("ni la petición trae workspace_id", f)


class LaRestriccionEnLaBaseTests(unittest.TestCase):
    def _ayudante(self):
        i = SCHEMA.index("def ensure_not_null")
        return SCHEMA[i: SCHEMA.index("\ndef ", i + 10)]

    def test_no_la_pone_si_quedan_filas_sucias(self):
        """Ponerla con datos sucios tumbaría el arranque de la aplicación entera."""
        f = self._ayudante()
        self.assertIn("IS NULL OR TRIM(", f)
        self.assertIn("if sucias:", f)
        self.assertIn("return False", f[f.index("if sucias:"):])

    def test_cuenta_tambien_las_vacias_no_solo_las_nulas(self):
        # NOT NULL no impide la cadena vacía; si ya la hubiera, mejor no poner nada.
        self.assertIn("TRIM(", self._ayudante())

    def test_solo_actua_en_postgres(self):
        # SQLite no sabe añadir NOT NULL sin reconstruir la tabla.
        f = self._ayudante()
        self.assertIn("is_postgres_enabled", f)
        self.assertIn("return False", f[: f.index("try:", f.index("is_postgres_enabled"))])

    def test_un_fallo_no_impide_arrancar(self):
        f = self._ayudante()
        tramo = f[f.index("ALTER TABLE"):]
        self.assertIn("except Exception:", tramo)
        self.assertIn("rollback", tramo)

    def test_se_aplica_al_arrancar(self):
        self.assertIn('ensure_not_null(conn, "clientes", "workspace_id")', SERVER)

    def test_va_despues_de_crear_la_columna(self):
        self.assertLess(
            SERVER.index('ensure_column(conn, "clientes", "workspace_id", "workspace_id TEXT")'),
            SERVER.index('ensure_not_null(conn, "clientes", "workspace_id")'),
        )


if __name__ == "__main__":
    unittest.main()
