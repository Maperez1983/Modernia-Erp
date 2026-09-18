"""Fase 2 del ámbito por workspace (2026-09-18): las consultas acotan por `workspace_id`.

El escenario de siempre: una empresa compartida por dos workspaces, A y B. Antes, que
un dato "fuera de A" se decidía por su empresa, así que A veía lo de B (y el dato sin
empresa no lo veía nadie). Ahora lo decide el `workspace_id` del dato.
"""

import tempfile
import unittest
from pathlib import Path

from web import server as S

AHORA = "2026-09-18 09:00:00"


class _Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "f2.sqlite"
        S.ensure_tables(db)
        self.c = S.open_sqlite_conn(str(db), with_row_factory=True)
        self.addCleanup(self.c.close)
        self.c.commit()
        self.c.execute("PRAGMA foreign_keys = OFF")
        for ws in ("wsA", "wsB"):
            self.ins("workspaces", dict(id=ws, nombre=ws, slug=ws, estado="Activo"))
        self.ins("empresas", dict(id="empX", nombre="Compartida SL", nif="B11111111", activo=1))
        self.ins("empresas", dict(id="empSolaA", nombre="Solo A SL", nif="B22222222", activo=1))
        self.ins("workspace_empresas", dict(id="l1", workspace_id="wsA", empresa_id="empX"))
        self.ins("workspace_empresas", dict(id="l2", workspace_id="wsB", empresa_id="empX"))
        self.ins("workspace_empresas", dict(id="l3", workspace_id="wsA", empresa_id="empSolaA"))

    def ins(self, tabla, datos):
        datos = {"created_at": AHORA, "updated_at": AHORA, **datos}
        cols = {c[1] for c in self.c.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in cols}
        self.c.execute(
            f"INSERT OR REPLACE INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})",
            tuple(d.values()),
        )
        self.c.commit()

    def ws_de(self, tabla, fid):
        return self.c.execute(f"SELECT workspace_id FROM {tabla} WHERE id = ?", (fid,)).fetchone()[0]


class ElDisparadorTambienEnSQLiteTests(_Base):
    def test_la_fila_nueva_recibe_el_workspace_de_su_empresa(self):
        self.ins("seguros", dict(id="s1", empresa_id="empSolaA"))
        self.assertEqual(self.ws_de("seguros", "s1"), "wsA")

    def test_con_la_empresa_en_dos_workspaces_no_adivina(self):
        self.ins("seguros", dict(id="s2", empresa_id="empX"))
        self.assertIn(self.ws_de("seguros", "s2"), (None, ""))

    def test_si_ya_trae_workspace_no_se_toca(self):
        self.ins("seguros", dict(id="s3", empresa_id="empSolaA", workspace_id="wsB"))
        self.assertEqual(self.ws_de("seguros", "s3"), "wsB")

    def test_la_plataforma_no_cuenta(self):
        self.ins("workspaces", dict(id="wsPlat", nombre="Plataforma", slug="verifika", estado="Activo"))
        self.ins("empresas", dict(id="empTec", nombre="Verifika2", nif="B33333333", activo=1))
        self.ins("workspace_empresas", dict(id="l4", workspace_id="wsPlat", empresa_id="empTec"))
        self.ins("workspace_empresas", dict(id="l5", workspace_id="wsPlat", empresa_id="empSolaA"))
        self.ins("seguros", dict(id="s4", empresa_id="empSolaA"))
        self.assertEqual(self.ws_de("seguros", "s4"), "wsA")

    def test_las_tablas_sin_la_columna_la_tienen(self):
        cols = {c[1] for c in self.c.execute("pragma table_info(gestoria_trabajos)")}
        self.assertIn("workspace_id", cols)


class ClientesTests(_Base):
    def test_la_ficha_360_no_se_abre_desde_otro_workspace(self):
        self.ins("clientes", dict(id="cB", nombre="De B", empresa_id="empX", workspace_id="wsB"))
        self.ins("clientes_empresas", dict(id="ceB", cliente_id="cB", empresa_id="empX", servicio="seguros"))
        self.assertIn("error", S.fetch_workspace_cliente_360(self.c, "wsA", "cB"))

    def test_el_cliente_sin_vinculo_de_empresa_se_ve_en_su_workspace(self):
        self.ins("clientes", dict(id="cA", nombre="De A sin empresa", workspace_id="wsA"))
        filas = S.fetch_workspace_clientes(self.c, "wsA")["rows"]
        self.assertEqual([f["id"] for f in filas], ["cA"])

    def test_el_buscador_no_trae_los_de_otro_workspace(self):
        self.ins("clientes", dict(id="cB", nombre="De B", empresa_id="empX", workspace_id="wsB"))
        self.ins("clientes_empresas", dict(id="ceB", cliente_id="cB", empresa_id="empX", servicio="seguros"))
        self.assertEqual(S.fetch_workspace_clientes(self.c, "wsA")["rows"], [])

    def test_el_ambito_central_es_solo_el_workspace(self):
        sql, vals = S.clientes_workspace_scope_sql(self.c, "wsA", alias="c")
        self.assertEqual((sql, vals), ("COALESCE(c.workspace_id, '') = ?", ["wsA"]))


class FacturacionTests(_Base):
    def test_el_potencial_no_suma_dinero_de_otro_workspace(self):
        self.ins("seguros", dict(id="sA", empresa_id="empX", workspace_id="wsA", comision=100))
        self.ins("seguros", dict(id="sB", empresa_id="empX", workspace_id="wsB", comision=900))
        resumen = S.fetch_workspace_billing_summary(self.c, "wsA")
        self.assertEqual(resumen["potencial_operativo"], 100.0)

    def test_las_facturas_sin_empresa_salen(self):
        self.ins("workspace_facturacion", dict(id="fA", workspace_id="wsA", empresa_id=None,
                                              total=50, concepto="Sin sociedad", fecha_emision="2026-09-01"))
        filas = S.fetch_workspace_billing_rows(self.c, "wsA")["rows"]
        self.assertEqual([f["id"] for f in filas], ["fA"])


class PresupuestosTests(_Base):
    def test_con_workspace_solo_los_suyos(self):
        self.ins("workspace_presupuestos", dict(id="pA", workspace_id="wsA", empresa_id="empX", titulo="A"))
        self.ins("workspace_presupuestos", dict(id="pB", workspace_id="wsB", empresa_id="empX", titulo="B"))
        filas = S.fetch_empresa_presupuestos(self.c, "empX", workspace_id="wsA")["rows"]
        self.assertEqual([f["id"] for f in filas], ["pA"])


class GestoriaTests(unittest.TestCase):
    SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")

    def test_los_trabajos_con_workspace_acotan_por_el(self):
        i = self.SERVER.index('if path == "/api/gestoria_trabajos":')
        bloque = self.SERVER[i : self.SERVER.index("if path ==", i + 30)]
        self.assertIn("COALESCE(gt.workspace_id, '') = ?", bloque)

    def test_el_acceso_a_una_fila_mira_primero_su_workspace(self):
        i = self.SERVER.index("def enforce_gestoria_row_access(")
        bloque = self.SERVER[i : self.SERVER.index("\ndef ", i + 10)]
        self.assertLess(bloque.index("enforce_workspace_membership(conn, session, workspace_fila"),
                        bloque.index("enforce_empresa_membership(conn, session, empresa_id"))


class RRHHSinEmpresaTests(unittest.TestCase):
    SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")

    def test_los_endpoints_de_rrhh_no_exigen_empresa(self):
        for ruta in ("/api/workspace_rrhh_productividad_renta", "/api/workspace_rrhh_productividad",
                     "/api/workspace_rrhh_economicos_dashboard", "/api/workspace_rrhh_memoria_economica"):
            i = self.SERVER.index(f'if path == "{ruta}":')
            bloque = self.SERVER[i : self.SERVER.index("if path ==", i + 30)]
            self.assertNotIn('"empresa_id requerido"', bloque, ruta)

    def test_la_productividad_de_polizas_e_hipotecas_va_por_workspace(self):
        for funcion, alias in (("compute_workspace_rrhh_productividad_seguros", "s"),
                               ("compute_workspace_rrhh_productividad_hipotecas", "h")):
            i = self.SERVER.index(f"def {funcion}(")
            bloque = self.SERVER[i : self.SERVER.index("\ndef ", i + 10)]
            self.assertIn(f"COALESCE({alias}.workspace_id, '') = ?", bloque)
            self.assertNotIn(f'where = ["{alias}.empresa_id = ?"]', bloque)


if __name__ == "__main__":
    unittest.main()
