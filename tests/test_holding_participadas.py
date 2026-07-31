"""El holding no hereda la cartera de sus participadas.

Medido en producción el 2026-07-31: Verifika², que es el workspace paraguas del
grupo, estaba vinculado a las 8 empresas de Modernia y por eso veía sus 2004
clientes. Los suyos propios son 5. El vínculo de un holding con una participada
dice de quién es la EMPRESA, no de quién son sus CLIENTES.

`workspace_empresas.rol` ya existía en el esquema pero el código solo escribía
'operativa' y nunca lo consultaba. Aquí se le da uso: solo los vínculos
operativos dan visibilidad sobre los datos. El panel de empresas sigue viendo
también las participadas — el holding tiene que saber qué cuelga de él.
"""

import sqlite3
import unittest
from pathlib import Path

from web import server

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")

HOLDING = "ws-verifika"
FILIAL = "ws-modernia"

SCHEMA = """
CREATE TABLE empresas (id TEXT PRIMARY KEY, nombre TEXT, activo INTEGER NOT NULL DEFAULT 1);
CREATE TABLE workspaces (id TEXT PRIMARY KEY, nombre TEXT, slug TEXT, estado TEXT);
CREATE TABLE workspace_empresas (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, empresa_id TEXT NOT NULL,
  rol TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE workspace_companies (
  workspace_id TEXT NOT NULL, legacy_empresa_id TEXT, activo INTEGER NOT NULL DEFAULT 1, nombre TEXT
);
CREATE TABLE workspace_registro_personal (id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT, activo INTEGER);
CREATE TABLE clientes (id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT, nombre TEXT);
CREATE TABLE clientes_empresas (id TEXT PRIMARY KEY, cliente_id TEXT, empresa_id TEXT, workspace_id TEXT, servicio TEXT);
"""


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO empresas (id, nombre) VALUES (?, ?)",
        [("emp-operativa", "Fincas Velazquez"), ("emp-propia", "Verifika2")],
    )
    for ws, nombre in ((HOLDING, "Verifika2"), (FILIAL, "Modernia")):
        conn.execute("INSERT INTO workspaces (id, nombre, slug, estado) VALUES (?, ?, ?, 'Activo')", (ws, nombre, ws))
    conn.executemany(
        "INSERT INTO workspace_empresas (id, workspace_id, empresa_id, rol) VALUES (?, ?, ?, ?)",
        [
            # La filial explota su empresa.
            ("we-1", FILIAL, "emp-operativa", "operativa"),
            # El holding participa en esa misma empresa, y explota la suya.
            ("we-2", HOLDING, "emp-operativa", "participada"),
            ("we-3", HOLDING, "emp-propia", "operativa"),
        ],
    )
    conn.commit()
    return conn


class AmbitoDeDatosPorRolTests(unittest.TestCase):
    def setUp(self):
        self.conn = _conn()

    def tearDown(self):
        self.conn.close()

    def test_el_holding_no_ve_los_datos_de_su_participada(self):
        ids = server.fetch_workspace_operational_company_ids(self.conn, HOLDING)
        self.assertEqual(ids, ["emp-propia"])
        self.assertNotIn("emp-operativa", ids)

    def test_pero_si_la_ve_en_el_panel_de_empresas(self):
        # El holding tiene que saber qué empresas cuelgan de él.
        ids = server.fetch_workspace_company_ids(self.conn, HOLDING)
        self.assertEqual(sorted(ids), ["emp-operativa", "emp-propia"])

    def test_la_filial_no_se_entera_de_nada(self):
        self.assertEqual(server.fetch_workspace_operational_company_ids(self.conn, FILIAL), ["emp-operativa"])
        self.assertEqual(server.fetch_workspace_company_ids(self.conn, FILIAL), ["emp-operativa"])

    def test_el_rol_vacio_cuenta_como_operativo(self):
        # Los vínculos legacy no traen rol; no pueden perder visibilidad de golpe.
        self.conn.execute("UPDATE workspace_empresas SET rol = NULL WHERE id = 'we-2'")
        self.conn.commit()
        self.assertIn("emp-operativa", server.fetch_workspace_operational_company_ids(self.conn, HOLDING))

    def test_el_rol_no_distingue_mayusculas_ni_espacios(self):
        self.conn.execute("UPDATE workspace_empresas SET rol = '  OPERATIVA ' WHERE id = 'we-2'")
        self.conn.commit()
        self.assertIn("emp-operativa", server.fetch_workspace_operational_company_ids(self.conn, HOLDING))

    def test_scope_empresa_ids_propaga_el_filtro(self):
        ids = server.resolve_workspace_scope_empresa_ids(self.conn, HOLDING, solo_operativas=True)
        self.assertEqual(ids, ["emp-propia"])


class LasListasDeClientesUsanElAmbitoOperativoTests(unittest.TestCase):
    def _bloque_clientes_list(self):
        inicio = SERVER.index('if path == "/api/clientes_list":')
        return SERVER[inicio : SERVER.index('if path == "/api/fin_inmobiliarias":', inicio)]

    def test_las_cuatro_ramas_usan_el_resolutor_operativo(self):
        bloque = self._bloque_clientes_list()
        self.assertEqual(bloque.count("fetch_workspace_operational_company_ids(conn, workspace_id)"), 4)
        # Y ninguna se quedó con el que incluye participadas.
        self.assertNotIn("fetch_workspace_company_ids(conn, workspace_id)", bloque)

    def test_la_busqueda_de_duplicados_tambien(self):
        inicio = SERVER.index("def resolve_clientes_by_nif_rows(")
        bloque = SERVER[inicio : SERVER.index("\ndef ", inicio + 10)]
        self.assertIn("solo_operativas=True", bloque)

    def test_el_panel_de_empresas_no_filtra_por_rol(self):
        # `/api/empresas` sigue mostrando las participadas.
        inicio = SERVER.index('if path == "/api/empresas":')
        bloque = SERVER[inicio : SERVER.index('if path == "/api/convenios_catalog":', inicio)]
        self.assertNotIn("operational", bloque)


class RecalificarUnVinculoTests(unittest.TestCase):
    def test_el_endpoint_actualiza_el_rol_de_un_vinculo_existente(self):
        # Con solo INSERT OR IGNORE no había forma de marcar una empresa ya
        # vinculada como participada, que es justo lo que hace falta.
        inicio = SERVER.index('elif parsed.path == "/api/workspace_empresa_link":')
        bloque = SERVER[inicio : SERVER.index("elif parsed.path ==", inicio + 10)]
        self.assertIn("UPDATE workspace_empresas", bloque)
        self.assertIn("SET rol = ?", bloque)
        # Solo si el caller pidió un rol explícito: si no, no se pisa el que haya.
        self.assertIn('if str(payload.get("rol") or "").strip():', bloque)


if __name__ == "__main__":
    unittest.main()
