"""Dos agujeros encontrados midiendo producción el 2026-07-31.

1. `/api/empresas` era un `SELECT ... FROM empresas` **sin WHERE**. Servía las 10
   empresas del grupo a cualquier sesión y para cualquier `workspace_id`, incluido
   uno inexistente, con NIF, IBAN y BIC dentro. El frontend nunca le pasa
   `workspace_id`, así que acotar por el parámetro no habría arreglado nada: hay
   que acotar por la sesión.

2. Los clientes que no cuelgan de ningún workspace ni de ninguna empresa vinculada
   a uno no aparecían en ninguna lista acotada. En producción eran 5. Ahora hay un
   cubo "sin asignar" para encontrarlos, restringido a actores de plataforma
   porque no pertenecen a ningún tenant.
"""

import sqlite3
import unittest
from pathlib import Path

from web import server

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")

WS_A = "ws-alfa"
WS_B = "ws-beta"

SCHEMA = """
CREATE TABLE empresas (id TEXT PRIMARY KEY, nombre TEXT, activo INTEGER NOT NULL DEFAULT 1);
CREATE TABLE workspaces (
  id TEXT PRIMARY KEY, nombre TEXT, slug TEXT, estado TEXT, plan TEXT, kind TEXT,
  descripcion TEXT, logo_url TEXT, primary_color TEXT, accent_color TEXT
);
CREATE TABLE workspace_empresas (
  id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, empresa_id TEXT NOT NULL,
  rol TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE workspace_companies (
  workspace_id TEXT NOT NULL, legacy_empresa_id TEXT, activo INTEGER NOT NULL DEFAULT 1, nombre TEXT
);
CREATE TABLE workspace_modulos (workspace_id TEXT, modulo_key TEXT, enabled INTEGER);
CREATE TABLE workspace_miembros (workspace_id TEXT, usuario_id TEXT, rol TEXT);
CREATE TABLE usuarios (id TEXT PRIMARY KEY, usuario TEXT, email TEXT, activo INTEGER NOT NULL DEFAULT 1);
CREATE TABLE clientes (id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT, nombre TEXT);
CREATE TABLE clientes_empresas (id TEXT PRIMARY KEY, cliente_id TEXT, empresa_id TEXT, workspace_id TEXT, servicio TEXT);
"""


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO empresas (id, nombre) VALUES (?, ?)",
        [("emp-1", "Empresa Uno"), ("emp-2", "Empresa Dos"), ("emp-3", "Empresa Tres")],
    )
    for ws, nombre in ((WS_A, "Alfa"), (WS_B, "Beta")):
        conn.execute(
            "INSERT INTO workspaces (id, nombre, slug, estado) VALUES (?, ?, ?, 'Activo')",
            (ws, nombre, ws),
        )
    # Alfa tiene emp-1 y emp-2; Beta solo emp-3. (En producción se solapan, aquí
    # los separamos para que el test detecte de verdad si se filtra o no.)
    conn.executemany(
        "INSERT INTO workspace_empresas (id, workspace_id, empresa_id) VALUES (?, ?, ?)",
        [("we-1", WS_A, "emp-1"), ("we-2", WS_A, "emp-2"), ("we-3", WS_B, "emp-3")],
    )
    conn.execute("INSERT INTO usuarios (id, usuario, email) VALUES ('u-1', 'pepe', 'pepe@x.com')")
    conn.execute("INSERT INTO workspace_miembros (workspace_id, usuario_id, rol) VALUES (?, 'u-1', 'gestor')", (WS_A,))
    conn.commit()
    return conn


class EmpresasVisiblesPorSesionTests(unittest.TestCase):
    def setUp(self):
        self.conn = _conn()
        self.sesion = {"user_id": "u-1", "usuario": "pepe", "email": "pepe@x.com", "rol": "gestor"}

    def tearDown(self):
        self.conn.close()

    def test_el_miembro_solo_ve_las_empresas_de_su_workspace(self):
        ids = server.fetch_empresa_ids_visible_for_session(self.conn, self.sesion)
        self.assertIsNotNone(ids, "un usuario no privilegiado no puede ver el catálogo entero")
        self.assertEqual(sorted(ids), ["emp-1", "emp-2"])
        self.assertNotIn("emp-3", ids)

    def test_acotar_por_workspace_concreto(self):
        ids = server.fetch_empresa_ids_visible_for_session(self.conn, self.sesion, workspace_id=WS_B)
        self.assertEqual(sorted(ids), ["emp-3"])

    def test_workspace_inexistente_no_devuelve_el_catalogo(self):
        # Antes, un workspace inventado devolvía las 10 empresas.
        ids = server.fetch_empresa_ids_visible_for_session(self.conn, self.sesion, workspace_id="no-existe")
        self.assertEqual(ids, [])

    def test_sin_sesion_no_ve_nada(self):
        ids = server.fetch_empresa_ids_visible_for_session(self.conn, None)
        self.assertEqual(ids, [])

    def test_lista_vacia_no_se_confunde_con_ver_todo(self):
        # `None` = ve todo (privilegiado); `[]` = no ve ninguna. Son distintos y el
        # handler tiene que distinguirlos, o el fail-closed se convierte en fail-open.
        vacio = server.fetch_empresa_ids_visible_for_session(self.conn, None)
        self.assertIsNotNone(vacio)
        self.assertEqual(vacio, [])


class EndpointEmpresasTests(unittest.TestCase):
    def test_ya_no_queda_el_select_sin_filtro(self):
        marcador = 'if path == "/api/empresas":'
        bloque = SERVER[SERVER.index(marcador) : SERVER.index('if path == "/api/convenios_catalog":')]
        self.assertIn("fetch_empresa_ids_visible_for_session", bloque)
        self.assertIn("{filtro_empresas}", bloque)
        # El SELECT desnudo sobre `empresas` no puede volver.
        self.assertNotIn("FROM empresas\n                ORDER BY nombre", bloque)

    def test_devuelve_vacio_en_vez_del_catalogo_cuando_no_ve_ninguna(self):
        marcador = 'if path == "/api/empresas":'
        bloque = SERVER[SERVER.index(marcador) : SERVER.index('if path == "/api/convenios_catalog":')]
        self.assertIn("is not None and not empresa_ids_visibles", bloque)


class CuboSinAsignarTests(unittest.TestCase):
    def _bloque(self):
        inicio = SERVER.index('if path == "/api/clientes_list":')
        return SERVER[inicio : SERVER.index('if path == "/api/fin_inmobiliarias":', inicio)]

    def test_existe_y_solo_para_actores_de_plataforma(self):
        bloque = self._bloque()
        self.assertIn('params.get("sin_asignar"', bloque)
        marcador = 'params.get("sin_asignar"'
        cola = bloque[bloque.index(marcador) :]
        # La comprobación de privilegio va antes de la consulta.
        self.assertLess(
            cola.index("workspace_actor_is_privileged"),
            cola.index("SELECT"),
            "hay que comprobar el privilegio antes de devolver clientes de nadie",
        )
        self.assertIn("status=403", cola[: cola.index("SELECT")])

    def test_la_consulta_busca_los_invisibles_de_verdad(self):
        bloque = self._bloque()
        cola = bloque[bloque.index('params.get("sin_asignar"') :]
        consulta = cola[: cola.index("fetchall()")]
        # Sin workspace propio Y sin empresa que cuelgue de ningún workspace: esa
        # combinación es justo la que no sale en ninguna lista acotada.
        self.assertIn("c.workspace_id", consulta)
        self.assertIn("NOT EXISTS", consulta)
        self.assertIn("JOIN workspace_empresas we ON we.empresa_id = ce.empresa_id", consulta)

    def test_la_consulta_encuentra_al_huerfano_y_no_a_los_demas(self):
        conn = _conn()
        conn.executemany(
            "INSERT INTO clientes (id, workspace_id, nombre) VALUES (?, ?, ?)",
            [("c-huerfano", None, "Huérfano"), ("c-con-ws", WS_A, "Con workspace"), ("c-con-empresa", None, "Con empresa")],
        )
        conn.execute(
            "INSERT INTO clientes_empresas (id, cliente_id, empresa_id) VALUES ('ce-1', 'c-con-empresa', 'emp-1')"
        )
        conn.commit()
        filas = conn.execute(
            """
            SELECT c.id
            FROM clientes c
            WHERE COALESCE(TRIM(COALESCE(c.workspace_id, '')), '') = ''
              AND NOT EXISTS (
                SELECT 1
                FROM clientes_empresas ce
                JOIN workspace_empresas we ON we.empresa_id = ce.empresa_id
                WHERE ce.cliente_id = c.id
              )
            ORDER BY c.nombre
            """
        ).fetchall()
        self.assertEqual([r[0] for r in filas], ["c-huerfano"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
