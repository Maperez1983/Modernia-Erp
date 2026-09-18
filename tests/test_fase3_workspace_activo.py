"""Fase 3 del ámbito por workspace (2026-09-18): el workspace activo no se adivina.

Antes, si nadie había elegido workspace, la aplicación cogía el primero de la lista por
orden alfabético, o caía al slug escrito a mano "verifika2" —que ni existe (el real es
"verifika") y es el de plataforma, donde no se trabaja—. Y el guardado en el navegador
ganaba a la URL: con A guardado, un enlace a B mandaba las primeras peticiones a A.
El servidor, sin ficha de fichaje, también probaba slugs a mano.
"""

import tempfile
import unittest
from pathlib import Path

from web import server as S

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")


class FrontTests(unittest.TestCase):
    def test_la_url_manda_en_los_tres_resolutores(self):
        self.assertNotIn(
            'String(state.currentWorkspaceId || "").trim()\n      || String(getTenantWorkspaceIdFromUrl() || "").trim()',
            APP,
        )
        self.assertEqual(
            APP.count('String(getTenantWorkspaceIdFromUrl() || "").trim()\n      || String(state.currentWorkspaceId || "").trim()'),
            3,
        )

    def test_nunca_se_elige_el_primero_de_la_lista_a_ciegas(self):
        self.assertNotIn(': items[0]?.id || "";', APP)
        self.assertNotIn("(state.workspaces[0] && state.workspaces[0].id)", APP)
        self.assertEqual(APP.count("pickPreferredWorkspaceRow("), 3)  # los tres sitios que elegían a ciegas

    def test_el_preferido_es_el_de_la_ficha_y_nunca_la_plataforma_si_hay_otro(self):
        i = APP.index("const pickPreferredWorkspaceRow = (rows) => {")
        bloque = APP[i : APP.index("\n};", i)]
        self.assertLess(bloque.index("homeTimeStatus?.workspace_id"), bloque.index("isPlatformWorkspaceRow(row)"))
        self.assertIn("|| items[0]", bloque)


class ServidorTests(unittest.TestCase):
    def test_sin_ficha_no_prueba_slugs_escritos_a_mano(self):
        i = SERVER.index('if path == "/api/home_time_status":')
        bloque = SERVER[i : SERVER.index("ok, err = enforce_workspace_membership(conn, session, workspace_id)", i)]
        self.assertNotIn('"verifika2"', bloque)
        self.assertNotIn('"modernia"', bloque)
        self.assertIn("workspace_de_plataforma_id(conn)", bloque)

    def test_identifica_el_workspace_de_plataforma(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "f3.sqlite"
        S.ensure_tables(db)
        c = S.open_sqlite_conn(str(db), with_row_factory=True)
        self.addCleanup(c.close)
        c.execute("INSERT INTO empresas (id, nombre, activo, created_at, updated_at) VALUES ('empTec', 'Verifika2', 1, 'x', 'x')")
        c.execute("INSERT INTO workspaces (id, nombre, slug, created_at, updated_at) VALUES ('wsPlat', 'Plataforma', 'plataforma-prueba', 'x', 'x')")
        c.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, updated_at) VALUES ('l', 'wsPlat', 'empTec', 'x', 'x')")
        c.commit()
        self.assertEqual(S.workspace_de_plataforma_id(c), "wsPlat")


if __name__ == "__main__":
    unittest.main()
