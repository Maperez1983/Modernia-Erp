"""Fase 6 del ámbito por workspace (2026-09-18): gestoría.

Los endpoints de gestoría acotaban por "las empresas del workspace" (`empresa_id IN`).
Ahora, con workspace, acotan por el `workspace_id` de la fila y la empresa solo filtra
dentro. Los libros contables y la plantilla Excel siguen por empresa a propósito: la
contabilidad es de cada sociedad.
"""

import tempfile
import unittest
from pathlib import Path

from web import server as S

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
AHORA = "2026-09-18 09:00:00"


class AyudanteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "f6.sqlite"
        S.ensure_tables(db)
        self.c = S.open_sqlite_conn(str(db), with_row_factory=True)
        self.addCleanup(self.c.close)
        self.c.commit()
        self.c.execute("PRAGMA foreign_keys = OFF")
        self.c.execute("INSERT INTO workspaces (id, nombre, slug, created_at, updated_at) VALUES ('wsA','A','ws-a',?,?)", (AHORA, AHORA))
        self.c.execute("INSERT INTO empresas (id, nombre, activo, created_at, updated_at) VALUES ('empA','A SL',1,?,?)", (AHORA, AHORA))
        self.c.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, updated_at) VALUES ('l','wsA','empA',?,?)", (AHORA, AHORA))
        self.c.commit()

    def test_con_workspace_acota_por_el_de_la_fila(self):
        sql, vals = S.ambito_filas_sql(self.c, "gestoria_sociedades", "s", workspace_id="wsA")
        self.assertEqual((sql, vals), ("COALESCE(s.workspace_id, '') = ?", ["wsA"]))

    def test_la_empresa_filtra_dentro_del_workspace(self):
        sql, vals = S.ambito_filas_sql(self.c, "gestoria_socios", "", workspace_id="wsA", empresa_id="empA")
        self.assertEqual(sql, "COALESCE(workspace_id, '') = ? AND empresa_id = ?")
        self.assertEqual(vals, ["wsA", "empA"])

    def test_sin_workspace_se_queda_lo_antiguo_por_empresa(self):
        sql, vals = S.ambito_filas_sql(self.c, "gestoria_actas", "a", empresa_id="empA")
        self.assertEqual((sql, vals), ("a.empresa_id IN (?)", ["empA"]))

    def test_sin_nada_no_hay_ambito(self):
        self.assertEqual(S.ambito_filas_sql(self.c, "gestoria_actas", "a"), (None, []))


class EndpointsTests(unittest.TestCase):
    def _bloque(self, ruta):
        i = SERVER.index(f'if path == "{ruta}":')
        return SERVER[i : SERVER.index('\n        if path == "/api/', i + 20)]

    def test_los_convertidos_usan_el_ayudante(self):
        for ruta in ("/api/gestoria_sociedades", "/api/gestoria_socios", "/api/gestoria_socios_cambios",
                     "/api/gestoria_actas", "/api/gestoria_acta_firmas", "/api/gestoria_import_lotes",
                     "/api/gestoria_cuentas_bancarias", "/api/gestoria_movimientos_bancarios",
                     "/api/renta_quick_pending"):
            with self.subTest(ruta=ruta):
                bloque = self._bloque(ruta)
                self.assertIn("ambito_filas_sql(", bloque)
                self.assertNotIn("resolve_empresa_ids_for_request(conn", bloque)

    def test_modelos_y_tareas_van_por_el_workspace_del_cliente(self):
        for ruta in ("/api/gestoria_modelos", "/api/gestoria_conta_tasks"):
            with self.subTest(ruta=ruta):
                self.assertIn("COALESCE(c.workspace_id, '') = ?", self._bloque(ruta))


if __name__ == "__main__":
    unittest.main()
