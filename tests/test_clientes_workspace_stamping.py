"""Los clientes nuevos tienen que nacer con `workspace_id`.

El backfill arregla los 2014 clientes que ya estaban huérfanos, pero si las altas
siguen insertando sin ámbito el problema se regenera solo. Los flujos de seguros,
inmobiliaria, financiaciones y presupuestos insertaban en `clientes` sin
`workspace_id`, y esos clientes desaparecían de cualquier lista acotada por
workspace aunque siguieran en la tabla.

Aquí se fija que todas esas altas pasan por `insert_cliente_scoped` y estampan el
ámbito, y que cuando el ámbito no se puede saber con certeza NO se inventa.
"""

import sqlite3
import unittest
from pathlib import Path

from web import server

REPO_ROOT = Path(__file__).resolve().parents[1]

WS = "6e63e1d1205c4c2a85dde7e20d5409f0"
EMPRESA = "emp-1"

SCHEMA = """
CREATE TABLE clientes (
  id TEXT PRIMARY KEY,
  workspace_id TEXT,
  empresa_id TEXT,
  nombre TEXT,
  tipo_persona TEXT,
  nif TEXT,
  telefono TEXT,
  movil TEXT,
  otro_telefono TEXT,
  email TEXT,
  fecha_nacimiento TEXT,
  direccion TEXT,
  procedencia_canal TEXT,
  procedencia_detalle TEXT,
  procedencia_user_id TEXT,
  estado TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE TABLE clientes_empresas (
  id TEXT PRIMARY KEY,
  cliente_id TEXT,
  empresa_id TEXT,
  workspace_id TEXT,
  servicio TEXT,
  captado_por_user_id TEXT,
  procedencia_canal TEXT,
  procedencia_cliente_id TEXT,
  estado TEXT,
  fecha_inicio TEXT,
  fecha_fin TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE TABLE workspace_empresas (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  empresa_id TEXT NOT NULL,
  rol TEXT,
  created_at TEXT,
  updated_at TEXT
);
CREATE TABLE workspace_companies (
  workspace_id TEXT NOT NULL,
  legacy_empresa_id TEXT,
  activo INTEGER NOT NULL DEFAULT 1,
  nombre TEXT
);
"""

AHORA = "2026-07-31T10:00:00+00:00"


def _conn(*, vinculo="v1"):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    if vinculo == "v1":
        conn.execute(
            "INSERT INTO workspace_empresas (id, workspace_id, empresa_id) VALUES (?, ?, ?)",
            ("we-1", WS, EMPRESA),
        )
    elif vinculo == "v2":
        conn.execute(
            "INSERT INTO workspace_companies (workspace_id, legacy_empresa_id, activo, nombre) VALUES (?, ?, 1, ?)",
            (WS, EMPRESA, "Modernia"),
        )
    conn.commit()
    return conn


class ResolveWorkspaceForEmpresaTests(unittest.TestCase):
    def test_resuelve_por_workspace_empresas(self):
        conn = _conn(vinculo="v1")
        self.assertEqual(server.resolve_workspace_id_for_empresa(conn, EMPRESA), WS)
        conn.close()

    def test_resuelve_por_workspace_companies(self):
        conn = _conn(vinculo="v2")
        self.assertEqual(server.resolve_workspace_id_for_empresa(conn, EMPRESA), WS)
        conn.close()

    def test_empresa_desconocida_no_resuelve(self):
        conn = _conn(vinculo="v1")
        self.assertEqual(server.resolve_workspace_id_for_empresa(conn, "emp-fantasma"), "")
        self.assertEqual(server.resolve_workspace_id_for_empresa(conn, ""), "")
        conn.close()

    def test_empresa_en_dos_workspaces_no_adivina(self):
        # Estampar el workspace equivocado sería una fuga entre tenants, y a
        # diferencia de dejarlo vacío no se puede deshacer.
        conn = _conn(vinculo="v1")
        conn.execute(
            "INSERT INTO workspace_empresas (id, workspace_id, empresa_id) VALUES (?, ?, ?)",
            ("we-2", "ws-otro", EMPRESA),
        )
        conn.commit()
        self.assertEqual(server.resolve_workspace_id_for_empresa(conn, EMPRESA), "")
        conn.close()

    def test_company_inactiva_no_cuenta(self):
        conn = _conn(vinculo="v2")
        conn.execute(
            "INSERT INTO workspace_companies (workspace_id, legacy_empresa_id, activo, nombre) VALUES (?, ?, 0, ?)",
            ("ws-apagado", EMPRESA, "Vieja"),
        )
        conn.commit()
        self.assertEqual(server.resolve_workspace_id_for_empresa(conn, EMPRESA), WS)
        conn.close()


class WorkspaceIdParaEscrituraTests(unittest.TestCase):
    def test_el_ambito_explicito_de_la_peticion_manda(self):
        conn = _conn(vinculo="v1")
        # El explícito ya pasó por enforce_workspace_membership: gana al deducido.
        self.assertEqual(
            server.cliente_workspace_id_for_write(conn, workspace_id="ws-explicito", empresa_id=EMPRESA),
            "ws-explicito",
        )
        conn.close()

    def test_sin_explicito_se_deduce_de_la_empresa(self):
        conn = _conn(vinculo="v1")
        self.assertEqual(server.cliente_workspace_id_for_write(conn, empresa_id=EMPRESA), WS)
        conn.close()


class InsertClienteScopedTests(unittest.TestCase):
    def test_estampa_el_workspace(self):
        conn = _conn(vinculo="v1")
        server.insert_cliente_scoped(
            conn,
            ["id", "nombre", "created_at", "updated_at"],
            ["c1", "Quien Sea", AHORA, AHORA],
            empresa_id=EMPRESA,
        )
        fila = conn.execute("SELECT workspace_id, created_at FROM clientes WHERE id = 'c1'").fetchone()
        self.assertEqual(fila["workspace_id"], WS)
        # created_at/updated_at siguen pasando por datetime(), como antes del helper.
        self.assertTrue(fila["created_at"])
        conn.close()

    def test_sin_ambito_resoluble_deja_el_cliente_sin_asignar(self):
        conn = _conn(vinculo="v1")
        server.insert_cliente_scoped(
            conn,
            ["id", "nombre", "created_at", "updated_at"],
            ["c1", "Quien Sea", AHORA, AHORA],
            empresa_id="emp-fantasma",
        )
        self.assertIsNone(conn.execute("SELECT workspace_id FROM clientes WHERE id = 'c1'").fetchone()[0])
        conn.close()

    def test_base_antigua_sin_la_columna_no_revienta(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            "CREATE TABLE clientes (id TEXT PRIMARY KEY, nombre TEXT, created_at TEXT, updated_at TEXT);"
        )
        server.insert_cliente_scoped(
            conn,
            ["id", "nombre", "created_at", "updated_at"],
            ["c1", "Quien Sea", AHORA, AHORA],
            empresa_id=EMPRESA,
        )
        self.assertEqual(conn.execute("SELECT nombre FROM clientes WHERE id = 'c1'").fetchone()[0], "Quien Sea")
        conn.close()

    def test_columnas_y_valores_descuadrados_fallan_pronto(self):
        conn = _conn(vinculo="v1")
        with self.assertRaises(ValueError):
            server.insert_cliente_scoped(conn, ["id", "nombre"], ["c1"], empresa_id=EMPRESA)
        conn.close()


class AltasDeServicioEstampanElAmbitoTests(unittest.TestCase):
    """La regresión de verdad: las altas de cada vertical."""

    def _workspace_del_unico_cliente(self, conn):
        filas = conn.execute("SELECT workspace_id FROM clientes").fetchall()
        self.assertEqual(len(filas), 1, "se esperaba exactamente un cliente nuevo")
        return filas[0][0]

    def test_alta_desde_seguros(self):
        conn = _conn(vinculo="v1")
        cid = server.ensure_cliente_for_seguro(conn, EMPRESA, "Ana Pérez", "12345678Z", AHORA)
        self.assertTrue(cid)
        self.assertEqual(self._workspace_del_unico_cliente(conn), WS)
        conn.close()

    def test_alta_desde_inmobiliaria(self):
        conn = _conn(vinculo="v1")
        cid = server.ensure_cliente_for_inmobiliaria(conn, EMPRESA, "Ana Pérez", "12345678Z", AHORA)
        self.assertTrue(cid)
        self.assertEqual(self._workspace_del_unico_cliente(conn), WS)
        conn.close()

    def test_alta_desde_financiaciones(self):
        conn = _conn(vinculo="v1")
        cid = server.ensure_cliente_for_financiacion(conn, EMPRESA, "Ana Pérez", "12345678Z", AHORA)
        self.assertTrue(cid)
        self.assertEqual(self._workspace_del_unico_cliente(conn), WS)
        conn.close()

    def test_el_ambito_explicito_gana_al_de_la_empresa(self):
        conn = _conn(vinculo="v1")
        server.ensure_cliente_for_inmobiliaria(
            conn, EMPRESA, "Ana Pérez", "12345678Z", AHORA, workspace_id="ws-explicito"
        )
        self.assertEqual(self._workspace_del_unico_cliente(conn), "ws-explicito")
        conn.close()


class NingunInsertDirectoSeSaltaElHelperTests(unittest.TestCase):
    def test_no_quedan_inserts_literales_en_clientes(self):
        """Si alguien añade un `INSERT INTO clientes` a mano, vuelve el bug.

        Solo se admiten dos: el del propio `insert_cliente_scoped` y el del
        endpoint `/api/clientes`, que ya estampa el ámbito montando las columnas
        dinámicamente. Cualquier otro nace huérfano.
        """
        texto = (REPO_ROOT / "web" / "server.py").read_text(encoding="utf-8")
        sitios = [
            linea.strip()
            for linea in texto.splitlines()
            if "INSERT INTO clientes " in linea or "INSERT INTO clientes(" in linea
        ]
        permitidos = [
            "join(cols)",  # insert_cliente_scoped
            "join(insert_cols)",  # endpoint /api/clientes
        ]
        colados = [s for s in sitios if not any(p in s for p in permitidos)]
        self.assertEqual(colados, [], "hay un INSERT INTO clientes que no pasa por insert_cliente_scoped")
        self.assertEqual(len(sitios), 2, f"cambió el número de INSERT sobre clientes: {sitios}")


if __name__ == "__main__":
    unittest.main()
