"""Tres fallos que solo se veían en Postgres (2026-09-18).

Tras publicar la fase 3, la primera carga de Modernia Centro dejó un error
`InFailedSqlTransaction` en tarifas de fincas y en registro horario. No se reproducía
llamando a mano. Se reprodujo levantando el CRM contra un Postgres local con
`log_min_error_statement = error` y lanzando a la vez las peticiones de la primera
visita a un workspace, como hace la página. El registro de Postgres sacó tres cosas:

1. Tarifas de fincas: la primera visita siembra la tarifa por defecto; dos peticiones a
   la vez sembraban las dos y la segunda chocaba con el índice único (workspace, clave).
2. `home_time_status` buscaba la ficha por email y por nombre con
   `SELECT DISTINCT ... ORDER BY updated_at`, que Postgres rechaza siempre: ese respaldo
   no había funcionado nunca en producción. SQLite lo acepta, por eso la suite no lo veía.
   Lo mismo en las sugerencias de cliente del hub de documentos (ORDER BY LENGTH(nombre)).
3. Una base Postgres nueva no recibía la columna `workspace_id` (en producción la puso
   el script de la fase 1): el resumen de facturación fallaba por falta de columna.
"""

import re
import unittest
from pathlib import Path

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")


def _funcion(firma):
    i = SERVER.index(firma)
    return SERVER[i : SERVER.index("\ndef ", i + 10)]


class TarifasTests(unittest.TestCase):
    def test_sembrar_dos_veces_a_la_vez_no_choca(self):
        cuerpo = _funcion("def fetch_workspace_fincas_tarifas(")
        self.assertIn('"INSERT OR IGNORE INTO workspace_fincas_tarifas "', cuerpo)
        self.assertNotIn('"INSERT INTO workspace_fincas_tarifas "', cuerpo)


class DistinctConOrdenTests(unittest.TestCase):
    """Postgres: con SELECT DISTINCT, lo del ORDER BY tiene que estar en la selección."""

    def test_home_time_status_ya_no_lo_usa(self):
        i = SERVER.index('if path == "/api/home_time_status":')
        bloque = SERVER[i : SERVER.index("ok, err = enforce_workspace_membership(conn, session, workspace_id)", i)]
        self.assertNotRegex(bloque, r"SELECT DISTINCT workspace_id\s+FROM workspace_registro_personal[^\"]*ORDER BY")
        self.assertEqual(bloque.count("GROUP BY workspace_id"), 2)

    def test_las_sugerencias_del_hub_tampoco(self):
        cuerpo = _funcion("def fetch_workspace_document_hub(")
        self.assertNotRegex(cuerpo, r"SELECT DISTINCT c\.id[^\"]*ORDER BY LENGTH")
        self.assertIn("WHERE COALESCE(c.workspace_id, '') = ?", cuerpo)

    def test_ningun_distinct_ordena_por_length(self):
        # El patrón que más fácil se cuela: ordenar por una expresión sobre DISTINCT.
        for m in re.finditer(r"SELECT\s+DISTINCT\s", SERVER):
            consulta = SERVER[m.start() : SERVER.find('"""', m.start())]
            self.assertNotRegex(consulta, r"ORDER BY\s+LENGTH\(", consulta[:200])


class PostgresNuevoTests(unittest.TestCase):
    def test_una_base_postgres_nueva_recibe_columna_y_disparador(self):
        cuerpo = _funcion("def ensure_ambito_workspace(")
        self.assertIn("_ensure_ambito_workspace_postgres(conn)", cuerpo)
        pg = _funcion("def _ensure_ambito_workspace_postgres(")
        # Solo toca lo que falta: en producción no hace DDL.
        self.assertIn("pendientes = [p for p in pendientes if not (p[1] and p[2])]", pg)
        self.assertIn("if pendientes:", pg)
        self.assertIn("ADD COLUMN IF NOT EXISTS workspace_id", pg)


if __name__ == "__main__":
    unittest.main()
