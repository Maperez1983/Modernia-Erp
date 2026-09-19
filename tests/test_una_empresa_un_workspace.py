"""Una empresa pertenece a un solo workspace (regla del ámbito, 2026-09-19).

Quedan consultas antiguas que acotan por "las empresas del workspace". Dan lo mismo que
acotar por workspace solo mientras ninguna empresa esté en dos: así se midió en
producción (156 de 156). Si se vuelve a compartir una, esas consultas cruzan datos entre
workspaces, que es el fallo que se arrastró durante meses. Esta regla lo impide en las
tres puertas por las que una empresa entra en un workspace. El de plataforma no cuenta.
"""

import tempfile
import unittest
from pathlib import Path

from web import server as S

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
AHORA = "2026-09-19 09:00:00"


class ReglaTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "r.sqlite"
        S.ensure_tables(db)
        self.c = S.open_sqlite_conn(str(db), with_row_factory=True)
        self.addCleanup(self.c.close)
        self.c.commit()
        self.c.execute("PRAGMA foreign_keys = OFF")
        for ws, nombre, slug in (("wsA", "Modernia Prueba", "a-prueba"), ("wsB", "Otro", "b-prueba"),
                                 ("wsPlat", "Plataforma", "plat-prueba")):
            self.c.execute("INSERT INTO workspaces (id, nombre, slug, created_at, updated_at) VALUES (?,?,?,?,?)",
                           (ws, nombre, slug, AHORA, AHORA))
        for eid, nombre in (("empX", "Compartible SL"), ("empTec", "Verifika2")):
            self.c.execute("INSERT INTO empresas (id, nombre, activo, created_at, updated_at) VALUES (?,?,1,?,?)",
                           (eid, nombre, AHORA, AHORA))
        self.c.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, updated_at) VALUES ('t','wsPlat','empTec',?,?)",
                       (AHORA, AHORA))
        self.c.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, updated_at) VALUES ('a','wsA','empX',?,?)",
                       (AHORA, AHORA))
        self.c.commit()

    def test_detecta_la_empresa_en_otro_workspace(self):
        self.assertEqual(S.otros_workspaces_de_empresa(self.c, "empX", "wsB"), ["Modernia Prueba"])

    def test_el_mismo_workspace_no_cuenta(self):
        # Recalificar el vínculo que ya existe (p. ej. operativa -> participada) sigue permitido.
        self.assertEqual(S.otros_workspaces_de_empresa(self.c, "empX", "wsA"), [])

    def test_la_plataforma_no_cuenta_ni_como_destino_ni_como_origen(self):
        self.assertEqual(S.otros_workspaces_de_empresa(self.c, "empX", "wsPlat"), [])
        self.c.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, updated_at) VALUES ('p','wsPlat','empX',?,?)",
                       (AHORA, AHORA))
        self.c.commit()
        self.assertEqual(S.otros_workspaces_de_empresa(self.c, "empX", "wsB"), ["Modernia Prueba"])

    def test_una_empresa_libre_se_puede_vincular(self):
        self.c.execute("INSERT INTO empresas (id, nombre, activo, created_at, updated_at) VALUES ('empLibre','Libre SL',1,?,?)",
                       (AHORA, AHORA))
        self.c.commit()
        self.assertEqual(S.otros_workspaces_de_empresa(self.c, "empLibre", "wsB"), [])

    def test_el_mensaje_explica_que_hacer(self):
        r = S.respuesta_empresa_en_otro_workspace(["Modernia"])
        self.assertEqual(r["detail"], "empresa_en_otro_workspace")
        self.assertIn("desvincúlala antes", r["error"])


class LasTresPuertasTests(unittest.TestCase):
    def _bloque(self, ruta):
        i = SERVER.index(f'elif parsed.path == "{ruta}":')
        return SERVER[i : SERVER.index("\n        elif parsed.path ==", i + 20)]

    def test_la_regla_va_antes_de_vincular(self):
        for ruta in ("/api/workspace_empresa_link", "/api/workspace_company_create", "/api/workspace_customer_create"):
            with self.subTest(ruta=ruta):
                bloque = self._bloque(ruta)
                self.assertIn("otros_workspaces_de_empresa(conn,", bloque)
                self.assertIn("status=409", bloque)
                self.assertLess(bloque.index("otros_workspaces_de_empresa(conn,"),
                                bloque.index("INSERT OR IGNORE INTO workspace_empresas"))


if __name__ == "__main__":
    unittest.main()
