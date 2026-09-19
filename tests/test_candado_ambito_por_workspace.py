"""Candado del ámbito por workspace (fase 5, 2026-09-18).

Regla de arquitectura, validada con el usuario tras varias auditorías que arreglaban una
pantalla y el fallo volvía por otra: **un dato es del workspace que lleva en
`workspace_id`; la empresa es un atributo, nunca decide de quién es un dato.**

Quedan en `server.py` sitios antiguos que acotan por "las empresas del workspace". Hoy
dan el mismo resultado que acotar por workspace, porque desde la fase 4 ninguna empresa
se comparte entre workspaces; pero si alguien vuelve a vincular una empresa a dos, se
reabriría el cruce. Esta prueba es un trinquete: congela cuántos quedan y **falla si
aparece uno nuevo**. Cuando se convierte uno a `workspace_id`, se baja aquí el número.

Si esta prueba te falla por añadir código: acota por `workspace_id` (hay columna en
todas las tablas de negocio y un disparador que la rellena). No subas el número.
"""

import unittest
from pathlib import Path

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")

# Recuento a 2026-09-18, tras la fase 2. Solo puede bajar.
TECHO = {
    "fetch_workspace_company_ids(conn": 45,
    "fetch_workspace_operational_company_ids(conn": 1,
    "resolve_workspace_company_ids(conn": 18,
    "resolve_workspace_scope_empresa_ids(conn": 12,
    "resolve_empresa_ids_for_request(conn": 9,
    "ce.empresa_id IN (": 28,
}


class CandadoTests(unittest.TestCase):
    def test_no_aparecen_nuevos_ambitos_por_empresa(self):
        for patron, techo in TECHO.items():
            with self.subTest(patron=patron):
                actual = SERVER.count(patron)
                self.assertLessEqual(
                    actual,
                    techo,
                    f"Hay {actual} usos de `{patron}` y el techo es {techo}: acota por workspace_id.",
                )

    def test_los_ayudantes_centrales_acotan_por_workspace(self):
        # Los dos por los que pasa más código no pueden volver al "o por empresa".
        for firma in ("def clientes_workspace_scope_sql(", "def build_service_scope_filter("):
            i = SERVER.index(firma)
            cuerpo = SERVER[i : SERVER.index("\ndef ", i + 10)]
            self.assertIn("workspace_id, '') = ?", cuerpo, firma)
            self.assertNotIn("workspace_id, '') = '' AND", cuerpo, firma)

    def test_la_base_de_pruebas_se_comporta_como_produccion(self):
        # La columna y el disparador de relleno también en SQLite (ver ensure_ambito_workspace).
        i = SERVER.index("def _ensure_tables_sin_red(")  # el cuerpo real de ensure_tables
        cuerpo = SERVER[i : SERVER.index("\ndef ", i + 10)]
        self.assertIn("ensure_ambito_workspace(conn)", cuerpo)


class VigilanciaTests(unittest.TestCase):
    def test_cuenta_las_filas_sin_workspace(self):
        import tempfile

        from web import server as S

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "v.sqlite"
        S.ensure_tables(db)
        c = S.open_sqlite_conn(str(db), with_row_factory=True)
        self.addCleanup(c.close)
        c.commit()
        c.execute("PRAGMA foreign_keys = OFF")
        c.execute("INSERT INTO seguros (id, empresa_id, workspace_id, created_at, updated_at) VALUES ('huerfana', NULL, NULL, 'x', 'x')")
        c.execute("INSERT INTO seguros (id, empresa_id, workspace_id, created_at, updated_at) VALUES ('buena', NULL, 'wsA', 'x', 'x')")
        c.commit()
        salud = S.ambito_workspace_salud(c)
        seguros = [f for f in salud["tablas_con_huecos"] if f["tabla"] == "seguros"]
        self.assertEqual(seguros, [{"tabla": "seguros", "sin_workspace": 1, "total": 2}])

    def test_solo_la_ve_la_plataforma(self):
        i = SERVER.index('if path == "/api/ambito_workspace_salud":')
        bloque = SERVER[i : SERVER.index("if path ==", i + 20)]
        self.assertIn("is_superadmin_actor(conn, session)", bloque)


if __name__ == "__main__":
    unittest.main()
