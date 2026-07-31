"""El panel de configuración pendiente de la home.

La home es una pantalla de paso: lo operativo vive dentro de cada CRM. Lo único
que se gana el sitio a este nivel es lo que está sin terminar de configurar.

Criterio de diseño, medido contra producción el 2026-07-31: solo entran avisos
**raros y accionables**. El 100% de las empresas no tenía IBAN ni dirección
fiscal, el 90% no tenía teléfono y el 80% no tenía email — avisar de eso no
señala un descuido, señala campos que no se usan. Un panel que abre siempre con
diez alarmas se ignora la primera semana.
"""

import sqlite3
import unittest
from pathlib import Path

from web import server

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
CSS = (RAIZ / "web" / "styles.css").read_text(encoding="utf-8")
INDEX = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

SCHEMA = """
CREATE TABLE empresas (id TEXT PRIMARY KEY, nombre TEXT, nif TEXT, iban TEXT, telefono TEXT, activo INTEGER DEFAULT 1);
CREATE TABLE workspaces (id TEXT PRIMARY KEY, nombre TEXT, slug TEXT, estado TEXT);
CREATE TABLE workspace_empresas (id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT, rol TEXT);
CREATE TABLE workspace_companies (workspace_id TEXT, legacy_empresa_id TEXT, activo INTEGER DEFAULT 1, nombre TEXT);
CREATE TABLE workspace_registro_personal (id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT, activo INTEGER);
CREATE TABLE clientes (id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT, nombre TEXT);
CREATE TABLE clientes_empresas (id TEXT PRIMARY KEY, cliente_id TEXT, empresa_id TEXT, workspace_id TEXT, servicio TEXT);
"""

WS = "ws-modernia"


def _conn(*, con_empresas=True, con_nif=True, con_huerfano=False):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO workspaces VALUES (?, 'Modernia', 'modernia', 'Activo')", (WS,))
    if con_empresas:
        conn.execute(
            "INSERT INTO empresas (id, nombre, nif, iban, telefono) VALUES ('e1', 'Fincas', ?, '', '')",
            ("B12345678" if con_nif else "",),
        )
        conn.execute("INSERT INTO workspace_empresas VALUES ('l1', ?, 'e1', 'operativa')", (WS,))
    if con_huerfano:
        conn.execute("INSERT INTO clientes VALUES ('c1', NULL, NULL, 'Sin ámbito')")
    conn.commit()
    return conn


def _claves(conn, ws=WS):
    return [a["clave"] for a in server.fetch_workspace_setup_status(conn, ws)]


class QueAvisaTests(unittest.TestCase):
    def test_todo_en_orden_no_dice_nada(self):
        # El estado normal es el silencio. Si esto empieza a fallar, el panel
        # ha dejado de ser útil.
        conn = _conn()
        self.assertEqual(server.fetch_workspace_setup_status(conn, WS), [])
        conn.close()

    def test_workspace_sin_empresas(self):
        conn = _conn(con_empresas=False)
        avisos = server.fetch_workspace_setup_status(conn, WS)
        self.assertIn("workspace_sin_empresas", [a["clave"] for a in avisos])
        self.assertEqual([a["severidad"] for a in avisos if a["clave"] == "workspace_sin_empresas"], ["alta"])
        conn.close()

    def test_clientes_sin_asignar(self):
        conn = _conn(con_huerfano=True)
        avisos = server.fetch_workspace_setup_status(conn, WS)
        cliente = next(a for a in avisos if a["clave"] == "clientes_sin_asignar")
        self.assertIn("1 cliente sin asignar", cliente["titulo"])
        conn.close()

    def test_el_plural_concuerda(self):
        conn = _conn()
        conn.executemany(
            "INSERT INTO clientes (id, workspace_id, empresa_id, nombre) VALUES (?, NULL, NULL, ?)",
            [("c1", "Uno"), ("c2", "Dos")],
        )
        conn.commit()
        avisos = server.fetch_workspace_setup_status(conn, WS)
        self.assertIn("2 clientes sin asignar", next(a for a in avisos if a["clave"] == "clientes_sin_asignar")["titulo"])
        conn.close()

    def test_empresas_sin_nif(self):
        conn = _conn(con_nif=False)
        self.assertIn("empresas_sin_nif", _claves(conn))
        conn.close()

    def test_un_cliente_con_vinculo_de_empresa_no_cuenta_como_huerfano(self):
        conn = _conn(con_huerfano=True)
        conn.execute("INSERT INTO clientes_empresas VALUES ('ce1', 'c1', 'e1', NULL, 'gestoria')")
        conn.commit()
        self.assertNotIn("clientes_sin_asignar", _claves(conn))
        conn.close()

    def test_sin_workspace_no_inventa_avisos(self):
        conn = _conn()
        self.assertEqual(server.fetch_workspace_setup_status(conn, ""), [])
        conn.close()


class QueNoAvisaTests(unittest.TestCase):
    """Lo que se dejó fuera a propósito, y por qué."""

    def test_no_avisa_de_iban_ni_telefono(self):
        # En producción los tenían vacíos el 100% y el 90% de las empresas: no es
        # configuración pendiente, es que no se usan esos campos.
        conn = _conn()
        conn.execute("UPDATE empresas SET iban = '', telefono = ''")
        conn.commit()
        self.assertEqual(server.fetch_workspace_setup_status(conn, WS), [])
        conn.close()

    def test_la_funcion_no_menciona_esos_campos(self):
        bloque = SERVER[SERVER.index("def fetch_workspace_setup_status") : SERVER.index("def fetch_empresa_ids_visible_for_session")]
        for campo in ("iban", "direccion_fiscal", "cnae"):
            self.assertNotIn(f"{campo}, ''", bloque, f"se coló un aviso por {campo}")


class FilasTipoPostgresTests(unittest.TestCase):
    """En producción el panel salía vacío y en local funcionaba.

    Postgres devuelve las filas como diccionarios; SQLite como tuplas indexables.
    Leer la cuenta por índice (`row[0]`) funciona en SQLite y devuelve None en
    Postgres, así que los avisos desaparecían justo donde importaban.
    """

    class _ConnDictRow:
        """Envuelve SQLite devolviendo dicts, como hace psycopg."""

        def __init__(self, conn):
            self._conn = conn

        def execute(self, sql, params=()):
            cur = self._conn.execute(sql, params)
            filas = [dict(f) for f in cur.fetchall()]
            return _Cursor(filas)

        def __getattr__(self, n):
            return getattr(self._conn, n)

    def test_los_avisos_salen_tambien_con_filas_diccionario(self):
        conn = _conn(con_huerfano=True, con_nif=False)
        envuelta = self._ConnDictRow(conn)
        claves = [a["clave"] for a in server.fetch_workspace_setup_status(envuelta, WS)]
        self.assertIn("clientes_sin_asignar", claves)
        self.assertIn("empresas_sin_nif", claves)
        conn.close()

    def test_la_cuenta_se_pide_con_alias(self):
        bloque = SERVER[SERVER.index("def fetch_workspace_setup_status") : SERVER.index("def fetch_empresa_ids_visible_for_session")]
        self.assertNotIn("SELECT COUNT(*)\n", bloque, "la cuenta necesita alias para leerse por nombre")
        self.assertIn("SELECT COUNT(*) AS total", bloque)
        self.assertIn('row_value(fila, "total")', bloque)


class _Cursor:
    def __init__(self, filas):
        self._filas = filas

    def fetchone(self):
        return self._filas[0] if self._filas else None

    def fetchall(self):
        return self._filas


class EndpointTests(unittest.TestCase):
    def test_existe_y_exige_workspace(self):
        i = SERVER.index('if path == "/api/workspace_setup_status":')
        bloque = SERVER[i : SERVER.index('if path == "/api/workspaces":', i)]
        self.assertIn("workspace_id requerido", bloque)
        self.assertIn("status=400", bloque)
        self.assertIn("fetch_workspace_setup_status", bloque)


class HomeDeUnaColumnaTests(unittest.TestCase):
    def _regla_shell(self):
        i = CSS.index("body.theme-operativa .hero-shell {")
        return CSS[i : CSS.index("}", i)]

    def test_la_home_es_de_una_columna(self):
        regla = self._regla_shell()
        self.assertIn("grid-template-columns: minmax(0, 1fr);", regla)
        # Y con ancho contenido, para que no se estire en pantallas grandes.
        self.assertIn("max-width", regla)

    def test_el_panel_arranca_oculto(self):
        self.assertIn('id="homeSetupStatus"', INDEX)
        self.assertIn("hidden", INDEX[INDEX.index('id="homeSetupStatus"') : INDEX.index('id="homeSetupStatus"') + 220])

    def test_se_pide_una_vez_por_workspace(self):
        bloque = APP[APP.index("const loadHomeSetupStatus") : APP.index("const renderHomeGuidance")]
        self.assertIn("_setupStatusPedidoPara === ws", bloque)

    def test_sin_avisos_el_panel_se_esconde(self):
        bloque = APP[APP.index("const renderHomeSetupStatus") : APP.index("const loadHomeSetupStatus")]
        self.assertIn("host.hidden = true", bloque)

    def test_la_severidad_no_es_solo_color(self):
        # La franja de color es refuerzo; el texto ya dice qué pasa.
        bloque = APP[APP.index("const renderHomeSetupStatus") : APP.index("const loadHomeSetupStatus")]
        self.assertIn("setup-status-item-title", bloque)
        self.assertIn('aria-hidden="true"', bloque)


if __name__ == "__main__":
    unittest.main()
