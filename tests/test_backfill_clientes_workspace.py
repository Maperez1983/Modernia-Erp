"""El backfill de `clientes.workspace_id` tiene que funcionar contra Postgres.

Producción es Postgres en Render y el script nació hablando solo SQLite. Estos
tests fijan dos cosas distintas:

1. El comportamiento (seco / apply / idempotencia / rollback), sobre SQLite real.
2. El dialecto: que TODA sentencia que el script manda sobreviva a
   `translate_sqlite_sql_to_postgres` sin dejar `?`, PRAGMA ni `INSERT OR ...`.
   No hay Postgres en el entorno de test, así que esto es lo que sí podemos
   comprobar de forma determinista: que el SQL que emitimos es el que la capa de
   compatibilidad del servidor sabe traducir.
"""

import re
import sqlite3
import unittest
from pathlib import Path

from scripts import backfill_clientes_workspace as backfill
from web.db_backend import translate_sqlite_sql_to_postgres

WS_DEFECTO = "6e63e1d1205c4c2a85dde7e20d5409f0"
WS_VINCULO = "ws-otro-tenant"

SCHEMA = """
CREATE TABLE clientes (
  id TEXT PRIMARY KEY,
  workspace_id TEXT,
  empresa_id TEXT,
  nombre TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE clientes_empresas (
  id TEXT PRIMARY KEY,
  cliente_id TEXT NOT NULL,
  empresa_id TEXT NOT NULL,
  workspace_id TEXT,
  servicio TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def _seed(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    clientes = [(f"c{i:03d}", None, "emp-1", f"Cliente {i}", "2024-01-01", "2024-01-01") for i in range(20)]
    # Un cliente que YA tiene ámbito: el backfill no puede tocarlo jamás.
    clientes.append(("c-ya-tiene", "ws-intocable", "emp-9", "Ya tiene", "2024-01-01", "2024-01-01"))
    conn.executemany("INSERT INTO clientes VALUES (?,?,?,?,?,?)", clientes)

    enlaces = [
        # 5 clientes resolubles por vínculo hacia otro workspace.
        *[
            (f"l{i:03d}", f"c{i:03d}", "emp-1", WS_VINCULO, "seguros", "2024-01-01", "2024-01-01")
            for i in range(5)
        ],
        # Un cliente ambiguo: cuelga de dos workspaces -> no adivinamos.
        ("l-amb-a", "c010", "emp-1", "ws-a", "seguros", "2024-01-01", "2024-01-01"),
        ("l-amb-b", "c010", "emp-2", "ws-b", "inmobiliaria", "2024-01-01", "2024-01-01"),
        # Enlaces sin ámbito, que se rellenan desde el cliente.
        *[
            (f"l1{i:02d}", f"c{i:03d}", "emp-3", None, "gestoria", "2024-01-01", "2024-01-01")
            for i in range(15, 20)
        ],
        # Enlace huérfano: su cliente no existe, debe quedarse vacío.
        ("l-huerfano", "c-no-existe", "emp-1", None, "gestoria", "2024-01-01", "2024-01-01"),
    ]
    conn.executemany("INSERT INTO clientes_empresas VALUES (?,?,?,?,?,?,?)", enlaces)
    conn.commit()
    conn.close()


class BackfillComportamientoTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        self.db = str(Path(self._dir.name) / "crm.sqlite")
        _seed(self.db)

    def tearDown(self):
        self._dir.cleanup()

    def _run(self, *args):
        return backfill.main(["--backend", "sqlite", "--db", self.db, "--yes", *args])

    def _q(self, sql, params=()):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(sql, params).fetchone()[0]
        finally:
            conn.close()

    def _vacios(self, tabla="clientes"):
        return self._q(f"SELECT COUNT(*) FROM {tabla} WHERE COALESCE(workspace_id, '') = ''")  # nosec B608

    def test_en_seco_no_escribe_nada(self):
        self.assertEqual(self._run("--workspace-id", WS_DEFECTO), 0)
        self.assertEqual(self._vacios(), 20)
        tablas = {
            r[0]
            for r in sqlite3.connect(self.db).execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        # Ni siquiera las tablas de respaldo: en seco es en seco.
        self.assertNotIn(backfill.BACKUP_TABLE, tablas)
        self.assertNotIn(backfill.LINKS_BACKUP_TABLE, tablas)

    def test_apply_resuelve_por_vinculo_y_respeta_lo_ya_asignado(self):
        self.assertEqual(self._run("--workspace-id", WS_DEFECTO, "--apply"), 0)
        self.assertEqual(self._vacios(), 0)
        # Los 5 con vínculo inequívoco van a su workspace, no al de por defecto.
        self.assertEqual(self._q("SELECT COUNT(*) FROM clientes WHERE workspace_id = ?", (WS_VINCULO,)), 5)
        self.assertEqual(self._q("SELECT COUNT(*) FROM clientes WHERE workspace_id = ?", (WS_DEFECTO,)), 15)
        # El que ya tenía ámbito no se toca.
        self.assertEqual(self._q("SELECT workspace_id FROM clientes WHERE id = 'c-ya-tiene'"), "ws-intocable")

    def test_vinculo_ambiguo_cae_al_workspace_por_defecto(self):
        self._run("--workspace-id", WS_DEFECTO, "--apply")
        # c010 cuelga de ws-a y ws-b: no inventamos, va al tenant por defecto.
        self.assertEqual(self._q("SELECT workspace_id FROM clientes WHERE id = 'c010'"), WS_DEFECTO)

    def test_rellena_enlaces_pero_no_el_huerfano(self):
        self._run("--workspace-id", WS_DEFECTO, "--apply")
        self.assertEqual(
            self._q("SELECT workspace_id FROM clientes_empresas WHERE id = 'l115'"), WS_DEFECTO
        )
        # El enlace cuyo cliente no existe se queda vacío en vez de recibir NULL a ciegas.
        self.assertIsNone(self._q("SELECT workspace_id FROM clientes_empresas WHERE id = 'l-huerfano'"))

    def test_repetir_el_apply_es_idempotente(self):
        self._run("--workspace-id", WS_DEFECTO, "--apply")
        antes = self._q("SELECT COUNT(*) FROM " + backfill.BACKUP_TABLE)
        self._run("--workspace-id", WS_DEFECTO, "--apply")
        # Ni se re-respalda ni se re-asigna: el segundo pase no encuentra nada vacío.
        self.assertEqual(self._q("SELECT COUNT(*) FROM " + backfill.BACKUP_TABLE), antes)
        self.assertEqual(self._q("SELECT COUNT(*) FROM clientes WHERE workspace_id = ?", (WS_VINCULO,)), 5)

    def test_rollback_devuelve_clientes_y_enlaces_al_estado_previo(self):
        self._run("--workspace-id", WS_DEFECTO, "--apply")
        self.assertEqual(self._vacios(), 0)
        self.assertEqual(self._run("--rollback", "--apply"), 0)
        self.assertEqual(self._vacios(), 20)
        # El rollback también deshace los enlaces, no solo los clientes.
        self.assertEqual(self._vacios("clientes_empresas"), 6)
        self.assertEqual(self._q("SELECT workspace_id FROM clientes WHERE id = 'c-ya-tiene'"), "ws-intocable")

    def test_rollback_en_seco_no_escribe(self):
        self._run("--workspace-id", WS_DEFECTO, "--apply")
        self.assertEqual(self._run("--rollback"), 0)
        self.assertEqual(self._vacios(), 0)

    def test_sin_columna_workspace_id_aborta_sin_tocar_nada(self):
        conn = sqlite3.connect(self.db)
        conn.executescript("DROP TABLE clientes; CREATE TABLE clientes (id TEXT PRIMARY KEY);")
        conn.commit()
        conn.close()
        self.assertEqual(self._run("--workspace-id", WS_DEFECTO, "--apply"), 2)

    def test_falta_workspace_id(self):
        self.assertEqual(self._run("--apply"), 2)


class GuardaDeEscrituraEnPostgresTests(unittest.TestCase):
    """Escribir en Postgres es escribir en producción: que cueste un poco."""

    def test_sqlite_no_pregunta(self):
        self.assertTrue(backfill._confirm_postgres_write("sqlite", False))

    def test_postgres_con_yes_no_pregunta(self):
        self.assertTrue(backfill._confirm_postgres_write("postgres", True))

    def test_postgres_sin_terminal_aborta(self):
        # Un cron o un pipe no cuentan como confirmación.
        import builtins

        original = builtins.input

        def _sin_terminal(*_a, **_k):
            raise EOFError

        builtins.input = _sin_terminal
        try:
            self.assertFalse(backfill._confirm_postgres_write("postgres", False))
        finally:
            builtins.input = original

    def test_postgres_pide_si_explicito(self):
        import builtins

        original = builtins.input
        try:
            builtins.input = lambda *a, **k: "sí"
            self.assertTrue(backfill._confirm_postgres_write("postgres", False))
            builtins.input = lambda *a, **k: "vale"
            self.assertFalse(backfill._confirm_postgres_write("postgres", False))
        finally:
            builtins.input = original

    def test_el_dsn_no_filtra_la_contrasena(self):
        import os

        original = os.environ.get("POSTGRES_URL")
        os.environ["POSTGRES_URL"] = "postgresql://usuario:secreto@dpg-xyz.render.com/crm"
        try:
            descripcion = backfill._describe_target("postgres")
            self.assertNotIn("secreto", descripcion)
            self.assertNotIn("usuario", descripcion)
            self.assertIn("dpg-xyz.render.com/crm", descripcion)
        finally:
            if original is None:
                os.environ.pop("POSTGRES_URL", None)
            else:
                os.environ["POSTGRES_URL"] = original


class _PostgresDialectRecorder:
    """Finge ser la conexión Postgres del servidor.

    Traduce cada sentencia con la MISMA función que usa `web/server.py` en
    producción, la guarda para inspección, y ejecuta el SQL original contra
    SQLite para que el script pueda seguir su curso.
    """

    __crm_backend__ = "postgres"

    def __init__(self, sqlite_conn, registro):
        self._conn = sqlite_conn
        self.registro = registro

    def execute(self, sql, params=None):
        self.registro.append(translate_sqlite_sql_to_postgres(sql))
        # `table_columns` consulta information_schema cuando el backend es Postgres.
        # SQLite no la tiene: la respondemos con su equivalente para que el script
        # recorra de verdad la rama Postgres del detector de columnas.
        if "information_schema.columns" in sql:
            tabla = (params or ("",))[0]
            filas = self._conn.execute(f"PRAGMA table_info({tabla})").fetchall()  # nosec B608
            return _FilasFalsas([(f[1],) for f in filas])
        return self._conn.execute(sql, params or ())

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()


class _FilasFalsas:
    def __init__(self, filas):
        self._filas = filas

    def fetchall(self):
        return self._filas

    def fetchone(self):
        return self._filas[0] if self._filas else None


class BackfillDialectoPostgresTests(unittest.TestCase):
    """Lo que rompía antes: `PRAGMA table_info`, `sqlite_master` y los `?`."""

    def setUp(self):
        import tempfile

        self._dir = tempfile.TemporaryDirectory()
        self.db = str(Path(self._dir.name) / "crm.sqlite")
        _seed(self.db)
        self.registro = []

    def tearDown(self):
        self._dir.cleanup()

    def _run_como_postgres(self, *args):
        original = backfill.open_db_conn
        backfill.open_db_conn = lambda path, with_row_factory=False: _PostgresDialectRecorder(
            sqlite3.connect(self.db), self.registro
        )
        try:
            return backfill.main(["--backend", "sqlite", "--db", self.db, "--yes", *args])
        finally:
            backfill.open_db_conn = original

    def _sin_literales(self, sql):
        # Quitamos cadenas entrecomilladas antes de buscar restos de dialecto.
        return re.sub(r"'[^']*'", "''", sql)

    def test_ninguna_sentencia_deja_sintaxis_de_sqlite(self):
        self.assertEqual(self._run_como_postgres("--workspace-id", WS_DEFECTO, "--apply"), 0)
        self.assertTrue(self.registro, "el script no emitió ninguna sentencia")
        for sql in self.registro:
            desnudo = self._sin_literales(sql)
            with self.subTest(sql=sql[:80]):
                # El marcador de SQLite tiene que haberse convertido a %s.
                self.assertNotIn("?", desnudo)
                self.assertNotRegex(desnudo, r"(?i)\bPRAGMA\b")
                self.assertNotRegex(desnudo, r"(?i)\bINSERT\s+OR\s+(IGNORE|REPLACE)\b")
                self.assertNotRegex(desnudo, r"(?i)\bsqlite_master\b")
                self.assertNotRegex(desnudo, r"(?i)\bAUTOINCREMENT\b")
                self.assertNotRegex(desnudo, r"(?i)\bCOLLATE\s+NOCASE\b")

    def test_el_rollback_tampoco_deja_sintaxis_de_sqlite(self):
        self._run_como_postgres("--workspace-id", WS_DEFECTO, "--apply")
        self.registro.clear()
        self.assertEqual(self._run_como_postgres("--rollback", "--apply"), 0)
        self.assertTrue(self.registro)
        for sql in self.registro:
            desnudo = self._sin_literales(sql)
            with self.subTest(sql=sql[:80]):
                self.assertNotIn("?", desnudo)
                self.assertNotRegex(desnudo, r"(?i)\bsqlite_master\b")

    def test_la_existencia_de_tabla_no_se_consulta_por_sqlite_master(self):
        # El script antiguo miraba `sqlite_master`; en Postgres eso solo existe si
        # la capa de compatibilidad llegó a crear la vista. Ahora va por columnas.
        self._run_como_postgres("--rollback")
        self.assertTrue(any("information_schema.columns" in s for s in self.registro))


if __name__ == "__main__":
    unittest.main()


class NoMigraLaCopiaLocalCreyendoQueEsProduccionTests(unittest.TestCase):
    """Caer a SQLite en silencio teniendo el DSN puesto es una trampa.

    Pasó al lanzarlo contra producción: el nombre de la variable iba mal escrito,
    el guion no lo dijo y anunció tranquilamente "Base de datos ... SQLite". Se
    habría podido dar por migrada la producción habiendo tocado la copia local.
    """

    GUION = (Path(__file__).resolve().parents[1] / "scripts" / "backfill_clientes_workspace.py").read_text(encoding="utf-8")

    def test_avisa_si_hay_dsn_en_el_entorno_y_aun_asi_va_a_sqlite(self):
        self.assertIn('if backend == "sqlite" and args.backend != "sqlite":', self.GUION)
        self.assertIn('for nombre in ("DATABASE_URL", "POSTGRES_URL")', self.GUION)

    def test_para_en_vez_de_seguir(self):
        i = self.GUION.index('if backend == "sqlite" and args.backend != "sqlite":')
        tramo = self.GUION[i: i + 900]
        self.assertIn("return 2", tramo)
        self.assertIn("file=sys.stderr", tramo)

    def test_deja_salida_para_quien_quiera_la_copia_local(self):
        # Con --backend sqlite se trabaja en local a propósito, sin aviso.
        i = self.GUION.index('if backend == "sqlite" and args.backend != "sqlite":')
        self.assertIn("--backend sqlite", self.GUION[i: i + 900])
