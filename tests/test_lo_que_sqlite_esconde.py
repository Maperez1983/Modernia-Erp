"""La suite corre sobre SQLite; producción es Postgres. Esto mide la distancia.

Las 3.000 pruebas del CRM abren SQLite. Producción no: es un Postgres en Frankfurt. Y
SQLite es permisivo justo donde Postgres no lo es —acepta texto en una columna de
números, compara texto con enteros, reemplaza filas sin preguntar—, así que hay una
clase entera de fallos que la suite **no puede ver por construcción**.

Ya nos costó uno: el importe de gestoría. Escribir «2.450,75» en el campo cantidad
guardaba 2,45 en SQLite y en Postgres **rechazaba el apunte**. Se diagnosticó primero
contra SQLite y se contó mal.

Qué hay aquí
------------
Dos capas.

1. Lo que se comprueba siempre, sin base de datos: que el traductor de SQL avise cuando
   no sabe traducir, y que el guardián de estas pruebas no pueda abrir producción.

2. Lo que necesita un Postgres de verdad, y se salta si no lo hay: que el esquema entero
   levante, que las migraciones de agosto de 2026 apliquen, y las cinco divergencias
   medidas una por una **contra las dos bases a la vez**, para que quede escrito qué
   tolera SQLite y qué no.

Se pide con la variable, apuntando al bucle local. Cómo levantar uno está en
`tests/_postgres_de_pruebas.py`:

    CRM_POSTGRES_PRUEBAS=postgresql://postgres@127.0.0.1:55432/crm_pruebas \
        .venv-test/bin/python -m pytest tests/test_lo_que_sqlite_esconde.py

Lo que esto NO es
-----------------
No es correr la suite contra Postgres. Eso hoy no se puede: de 163 ficheros de prueba,
68 abren SQLite a mano y 47 fuerzan `DATABASE_URL=""` al importarse. Esto cubre la capa
donde las dos bases se separan, que es donde estaban los fallos.
"""

import os
import unittest

from tests._postgres_de_pruebas import (VARIABLE, base_de_ensayo, dsn_de_pruebas,
                                        salta_si_no_hay)
from web.db_backend import (_rewrite_insert_or_replace, open_sqlite_conn,
                            translate_sqlite_sql_to_postgres)


# --------------------------------------------------------------------------------------
# 1. Sin base de datos
# --------------------------------------------------------------------------------------

class ElTraductorAvisaCuandoNoSabeTests(unittest.TestCase):
    """Devolver el SQL intacto no es «no hacer nada»: es emitir SQL inválido.

    `INSERT OR REPLACE` no existe en Postgres. Si el traductor lo deja pasar, el error
    aparece en el servidor, en producción, diciendo «error de sintaxis en o cerca de OR».
    """

    def test_lo_traduce_cuando_hay_id(self):
        salida = _rewrite_insert_or_replace(
            "INSERT OR REPLACE INTO t (id, a, b) VALUES (?, ?, ?)")
        self.assertIn("ON CONFLICT (id) DO UPDATE SET", salida)
        self.assertIn("a = EXCLUDED.a", salida)
        self.assertNotIn("OR REPLACE", salida)

    def test_y_revienta_cuando_la_clave_no_se_llama_id(self):
        """El caso de `crm_meta`, cuya clave primaria es `key`."""
        with self.assertRaises(ValueError) as e:
            _rewrite_insert_or_replace(
                "INSERT OR REPLACE INTO crm_meta (key, value, updated_at) VALUES (?, ?, ?)")
        self.assertIn("crm_meta", str(e.exception))
        self.assertIn("ON CONFLICT", str(e.exception))

    def test_y_cuando_la_forma_no_es_la_esperada(self):
        with self.assertRaises(ValueError):
            _rewrite_insert_or_replace("INSERT OR REPLACE INTO t SELECT * FROM otra")

    def test_lo_que_no_es_insert_or_replace_pasa_de_largo(self):
        for sql in ("SELECT 1", "INSERT INTO t (a) VALUES (?)",
                    "INSERT OR IGNORE INTO t (a) VALUES (?)", "UPDATE t SET a = 1"):
            self.assertEqual(_rewrite_insert_or_replace(sql), sql, sql)

    def test_el_traductor_completo_tambien_avisa(self):
        """Que no se cuele por otra puerta: `translate_…` llama al reescritor."""
        with self.assertRaises(ValueError):
            translate_sqlite_sql_to_postgres(
                "INSERT OR REPLACE INTO crm_meta (key, value) VALUES (?, ?)")


class ElGuardianDeEstasPruebasTests(unittest.TestCase):
    """Importar `web.db_backend` vuelca `.env` en el entorno, así que dentro de la suite
    `DATABASE_URL` **es producción**. Una prueba que la leyera se conectaba a Frankfurt.
    """

    def setUp(self):
        self.previo = os.environ.get(VARIABLE)
        self.addCleanup(self._restaura)

    def _restaura(self):
        if self.previo is None:
            os.environ.pop(VARIABLE, None)
        else:
            os.environ[VARIABLE] = self.previo

    def test_sin_la_variable_no_hay_dsn(self):
        os.environ.pop(VARIABLE, None)
        self.assertIsNone(dsn_de_pruebas())

    def test_aunque_database_url_este_puesta(self):
        """La que está puesta es la de producción. No vale como fuente."""
        os.environ.pop(VARIABLE, None)
        os.environ["DATABASE_URL"] = "postgresql://u:p@algo.frankfurt-postgres.render.com/x"
        self.addCleanup(os.environ.pop, "DATABASE_URL", None)
        self.assertIsNone(dsn_de_pruebas())

    def test_un_dsn_remoto_no_se_salta_en_silencio_sino_que_falla(self):
        """Saltar dejaría creer que se probó. Y apuntar fuera es un error, no una
        circunstancia: la suite crea y borra tablas."""
        os.environ[VARIABLE] = "postgresql://u:p@algo.frankfurt-postgres.render.com/modernia"
        with self.assertRaises(AssertionError) as e:
            dsn_de_pruebas()
        self.assertIn("no es local", str(e.exception))

    def test_y_el_aviso_no_lleva_la_contrasena(self):
        os.environ[VARIABLE] = "postgresql://usuario:secreto@remoto.example.com/base"
        with self.assertRaises(AssertionError) as e:
            dsn_de_pruebas()
        self.assertNotIn("secreto", str(e.exception))
        self.assertNotIn("usuario", str(e.exception))

    def test_el_bucle_local_si_vale(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            sitio = f"[{host}]" if host == "::1" else host
            os.environ[VARIABLE] = f"postgresql://postgres@{sitio}:55432/crm_pruebas"
            self.assertTrue(dsn_de_pruebas(), host)


# --------------------------------------------------------------------------------------
# 2. Contra Postgres de verdad
# --------------------------------------------------------------------------------------

class DivergenciasEntreLasDosBasesTests(unittest.TestCase):
    """Cada caso se ejecuta contra las dos, y se afirma qué hace cada una.

    Todo sobre tablas temporales y con `rollback` al terminar.
    """

    def setUp(self):
        self.pg = salta_si_no_hay(self)
        self.lite = open_sqlite_conn(":memory:", with_row_factory=True)
        self.addCleanup(self.lite.close)

    def _ambas(self, ddl):
        for cx in (self.lite, self.pg):
            for d in ddl:
                cx.execute(d)

    # --- el fallo que ya nos pasó ---------------------------------------------------

    def test_un_importe_con_coma_espanola_lo_traga_sqlite_y_lo_rechaza_postgres(self):
        """El apunte de gestoría. En SQLite entraba; en producción se rechazaba."""
        self._ambas(["CREATE TEMP TABLE cantidades (id text, importe numeric)"])
        self.lite.execute("INSERT INTO cantidades (id, importe) VALUES (?, ?)",
                          ("a", "2.450,75"))
        with self.assertRaises(Exception) as e:
            self.pg.execute("INSERT INTO cantidades (id, importe) VALUES (?, ?)",
                            ("a", "2.450,75"))
        self.assertIn("numeric", str(e.exception).lower())

    def test_y_el_importe_bien_escrito_entra_en_las_dos(self):
        self._ambas(["CREATE TEMP TABLE cantidades2 (id text, importe numeric)"])
        for cx in (self.lite, self.pg):
            cx.execute("INSERT INTO cantidades2 (id, importe) VALUES (?, ?)", ("a", 2450.75))
            self.assertEqual(
                float(cx.execute("SELECT importe FROM cantidades2").fetchone()[0]), 2450.75)

    # --- las demás, medidas ---------------------------------------------------------

    def test_comparar_una_columna_de_texto_con_un_numero(self):
        """SQLite dice que no hay coincidencias; Postgres dice que la consulta no existe."""
        self._ambas(["CREATE TEMP TABLE estados (id text, estado text)",
                     "INSERT INTO estados (id, estado) VALUES ('a', '1')"])
        # SQLite convierte por afinidad de tipo y empareja; Postgres ni compila la consulta.
        self.assertEqual(
            self.lite.execute("SELECT COUNT(*) FROM estados WHERE estado = 1").fetchone()[0], 1)
        with self.assertRaises(Exception):
            self.pg.execute("SELECT COUNT(*) FROM estados WHERE estado = 1")

    def test_group_concat_sobre_una_columna_de_numeros(self):
        """Hoy no ocurre: los siete GROUP_CONCAT del servidor van sobre texto. Queda
        escrito porque el octavo sobre una columna numérica no daría cero filas: daría
        un 500."""
        self._ambas(["CREATE TEMP TABLE numeros (id text, n numeric)",
                     "INSERT INTO numeros (id, n) VALUES ('a', 1)",
                     "INSERT INTO numeros (id, n) VALUES ('b', 2)"])
        self.assertTrue(self.lite.execute("SELECT GROUP_CONCAT(n) FROM numeros").fetchone()[0])
        with self.assertRaises(Exception):
            self.pg.execute("SELECT GROUP_CONCAT(n) FROM numeros").fetchall()

    def test_y_sobre_texto_funciona_igual_en_las_dos(self):
        """El control: la traducción a STRING_AGG está bien, el problema es el tipo."""
        self._ambas(["CREATE TEMP TABLE nombres (id text, t text)",
                     "INSERT INTO nombres (id, t) VALUES ('a', 'uno')",
                     "INSERT INTO nombres (id, t) VALUES ('b', 'dos')"])
        for cx in (self.lite, self.pg):
            self.assertEqual(cx.execute("SELECT GROUP_CONCAT(t) FROM nombres").fetchone()[0],
                             "uno,dos")

    def test_like_distingue_mayusculas_solo_en_postgres(self):
        """Por eso las búsquedas del CRM van con LOWER() a mano y no con LIKE pelado."""
        self._ambas(["CREATE TEMP TABLE marcas (id text, n text)",
                     "INSERT INTO marcas (id, n) VALUES ('a', 'Modernia')"])
        self.assertEqual(
            self.lite.execute("SELECT COUNT(*) FROM marcas WHERE n LIKE '%modernia%'")
            .fetchone()[0], 1)
        self.assertEqual(
            self.pg.execute("SELECT COUNT(*) FROM marcas WHERE n LIKE '%modernia%'")
            .fetchone()[0], 0)
        # Y con LOWER() las dos coinciden, que es como está escrito el servidor.
        for cx in (self.lite, self.pg):
            self.assertEqual(cx.execute(
                "SELECT COUNT(*) FROM marcas WHERE LOWER(n) LIKE '%modernia%'").fetchone()[0], 1)

    def test_insert_or_replace_solo_atiende_al_id(self):
        """Traducido va con ON CONFLICT (id). Si la unicidad de la tabla es otra, en
        SQLite reemplaza y en Postgres revienta.

        Ninguna tabla del CRM está hoy en ese caso —las tres que usan INSERT OR REPLACE
        se bifurcan a mano por backend—, pero es la trampa que deja el traductor.
        """
        self._ambas(["CREATE TEMP TABLE cargos (id text PRIMARY KEY, com text, vec text, per text)",
                     "CREATE UNIQUE INDEX cargos_u ON cargos (com, vec, per)",
                     "INSERT INTO cargos (id, com, vec, per) VALUES ('r1','c','v','2026-01')"])
        sql = "INSERT OR REPLACE INTO cargos (id, com, vec, per) VALUES (?, ?, ?, ?)"
        self.lite.execute(sql, ("r2", "c", "v", "2026-01"))
        self.assertEqual(self.lite.execute("SELECT COUNT(*) FROM cargos").fetchone()[0], 1)
        with self.assertRaises(Exception):
            self.pg.execute(sql, ("r2", "c", "v", "2026-01"))

    def test_y_cuando_el_conflicto_si_es_por_id_hace_lo_mismo_en_las_dos(self):
        self._ambas(["CREATE TEMP TABLE fichas (id text PRIMARY KEY, nombre text)",
                     "INSERT INTO fichas (id, nombre) VALUES ('f1', 'antes')"])
        for cx in (self.lite, self.pg):
            cx.execute("INSERT OR REPLACE INTO fichas (id, nombre) VALUES (?, ?)",
                       ("f1", "después"))
            self.assertEqual(cx.execute("SELECT COUNT(*) FROM fichas").fetchone()[0], 1)
            self.assertEqual(cx.execute("SELECT nombre FROM fichas").fetchone()[0], "después")


class ElEsquemaEnteroLevantaSobrePostgresTests(unittest.TestCase):
    """Las 156 tablas del CRM, creadas desde cero sobre Postgres.

    Es la prueba de humo del traductor: todo el DDL del servidor pasa por
    `translate_sqlite_sql_to_postgres` —COLLATE NOCASE fuera, claves ajenas fuera,
    `?` a `%s`— y basta una sentencia que no traduzca para que un módulo entero se
    quede sin sus tablas y responda 500 sólo en producción.

    Todo el arranque va envuelto en `try/except`, así que un fallo aquí no se ve al
    levantar: se ve el día que alguien pide la pantalla que usaba esa tabla.

    Se construye una vez, sobre una base de usar y tirar, y se mira desde varias
    pruebas: levantar el esquema entero tarda lo suyo.
    """

    @classmethod
    def setUpClass(cls):
        # `setUpClass` no tiene `addCleanup` de instancia; se usa un caso de mentira.
        cls._alias = unittest.TestCase()
        cls._alias.id = lambda: f"{cls.__module__}.{cls.__name__}"
        base_de_ensayo(cls._alias)
        cls.addClassCleanup(cls._alias.doCleanups)

        import psycopg
        from web import db_backend as D
        from web import server as S

        cls.cx = D.PostgresCompatConnection(
            psycopg.connect(os.environ["DATABASE_URL"], autocommit=False))
        cls.addClassCleanup(cls.cx.close)

        D.ensure_postgres_sqlite_compat(cls.cx)
        cls.cx.commit()
        S.ensure_tables(None)
        S.ensure_workspace_core_tables(cls.cx)
        S.ensure_workspace_product_tables(cls.cx)
        S.ensure_anuncio_schema(cls.cx)
        cls.cx.commit()

    def _tablas(self):
        return {f[0] for f in self.cx.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'").fetchall()}

    def _columnas(self, tabla):
        return {f[0] for f in self.cx.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s", (tabla,)).fetchall()}

    def test_levanta_entero(self):
        tablas = self._tablas()
        # El número exacto cambia con cada módulo nuevo; lo que no puede es desplomarse.
        self.assertGreater(len(tablas), 120, f"sólo {len(tablas)} tablas")
        for imprescindible in ("usuarios", "empresas", "clientes", "workspace_fincas_recibos",
                               "workspace_fincas_juntas", "inmuebles", "crm_meta"):
            self.assertIn(imprescindible, tablas)

    def test_las_migraciones_de_agosto_estan_aplicadas(self):
        """Las columnas que entraron en la campaña, sobre Postgres.

        Se añaden con `ensure_column` dentro de un `try/except`: si una no traduce, el
        arranque sigue tan campante y la columna no existe. Sólo se nota al usarla.
        """
        self.assertIn("nombre_comercial", self._columnas("empresas"))
        recibos = self._columnas("workspace_fincas_recibos")
        self.assertIn("vecino_nombre", recibos)
        self.assertIn("vecino_nif", recibos)
        self.assertIn("derecho_voto", self._columnas("workspace_fincas_junta_asistentes"))
        self.assertIn("acta_notificada", self._columnas("workspace_fincas_juntas"))

    def test_y_las_tablas_de_la_ley_de_propiedad_horizontal_tambien(self):
        """Discrepancias del art. 17.8 e impugnaciones del art. 18."""
        tablas = self._tablas()
        self.assertIn("workspace_fincas_junta_discrepancias", tablas)
        self.assertIn("workspace_fincas_junta_impugnaciones", tablas)

    def test_y_el_indice_de_la_derrama_es_el_ancho(self):
        """El viejo era (comunidad, vecino, periodo) y dejaba a la comunidad sin poder
        pasar una derrama en un mes que ya tenía cuota. El nuevo añade el concepto."""
        indices = {f[0]: f[1] for f in self.cx.execute(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' "
            "AND tablename = 'workspace_fincas_recibos'").fetchall()}
        self.assertIn("idx_fincas_recibos_unico_cargo", indices,
                      f"índices presentes: {sorted(indices)}")
        self.assertIn("concepto", indices["idx_fincas_recibos_unico_cargo"])
        self.assertNotIn("idx_fincas_recibos_unico", indices,
                         "el índice estrecho sigue puesto: la derrama no cabe")


if __name__ == "__main__":
    unittest.main()
