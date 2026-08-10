"""Una sentencia que falla no puede llevarse por delante el trabajo de la petición.

Postgres aborta la transacción entera cuando una sentencia falla. SQLite no. El
código de la aplicación está escrito contra SQLite y envuelve escrituras accesorias
en `try/except` para seguir adelante si no salen —bitácora, contadores,
desvinculaciones—. Sobre Postgres eso significaba que una sentencia accesoria que
fallara **deshacía todo lo anterior**, y el `except` se tragaba el aviso.

No es teórico: borrar un inmueble respondía 200, borraba la ficha y dejaba su
captación, sus citas, su documento y su propietario colgando de un id que ya no
existía. Comprobado contra la base de producción, y comprobado también el control:
con el adaptador anterior, tras el fallo ni siquiera sobrevivía la tabla temporal
que se había creado en la misma transacción.

El arreglo va en el adaptador, no en cada `try`: un punto de retorno por sentencia
mientras haya trabajo sin confirmar.

Estos tests corren sin servidor, contra una conexión de mentira que imita la regla
de Postgres —tras un error, todo falla hasta que se deshaga—. Los de abajo, contra
Postgres de verdad, sólo se ejecutan pidiéndolo:

    RUN_PG_ADAPTER_TESTS=1 .venv-test/bin/python -m pytest tests/test_puntos_de_retorno_postgres.py
"""

import os
import re
import unittest

from web.db_backend import PostgresCompatConnection, _es_escritura


class TransaccionAbortada(Exception):
    """Lo que lanza Postgres mientras la transacción está abortada."""


class ConexionDeMentira:
    """Imita a Postgres en lo único que importa aquí: cómo trata los errores.

    Guarda filas en una lista. `SAVEPOINT` copia el estado; `ROLLBACK TO` lo
    restaura; un error deja la conexión abortada hasta que se deshaga algo.
    Cualquier sentencia que contenga FALLA revienta.
    """

    IDLE, INTRANS, INERROR = 0, 2, 3

    def __init__(self):
        self.filas = []
        self.estado = self.IDLE
        self.puntos = []           # [(nombre, copia de filas)]
        self.ordenes = []          # cada sentencia suelta
        self.viajes = []           # cada llamada a execute: un viaje al servidor

    class _Info:
        def __init__(self, dueno):
            self._dueno = dueno

        @property
        def transaction_status(self):
            return self._dueno.estado

    @property
    def info(self):
        return self._Info(self)

    def execute(self, sql, params=None):
        self.viajes.append(sql)
        for trozo in [t.strip() for t in sql.split(";") if t.strip()]:
            self._una(trozo)
        return self

    def cursor(self):
        return self

    def executemany(self, sql, seq):
        for p in seq:
            self.execute(sql, p)
        return self

    def fetchone(self):
        return (len(self.filas),)

    def _una(self, sql):
        self.ordenes.append(sql)
        arriba = sql.upper()

        if arriba.startswith("ROLLBACK TO SAVEPOINT"):
            nombre = sql.split()[-1]
            for i in range(len(self.puntos) - 1, -1, -1):
                if self.puntos[i][0] == nombre:
                    self.filas = list(self.puntos[i][1])
                    del self.puntos[i + 1:]
                    self.estado = self.INTRANS
                    return
            raise Exception(f"no existe el punto {nombre}")

        if self.estado == self.INERROR:
            raise TransaccionAbortada(
                "current transaction is aborted, commands ignored until end of transaction block")

        if arriba.startswith("SAVEPOINT"):
            if self.estado != self.INTRANS:
                raise Exception("SAVEPOINT can only be used in transaction blocks")
            self.puntos.append((sql.split()[-1], list(self.filas)))
            return
        if arriba.startswith("RELEASE SAVEPOINT"):
            nombre = sql.split()[-1]
            for i in range(len(self.puntos) - 1, -1, -1):
                if self.puntos[i][0] == nombre:
                    del self.puntos[i:]
                    return
            raise Exception(f"no existe el punto {nombre}")

        if "FALLA" in arriba:
            self.estado = self.INERROR
            raise Exception("undefined column")

        if arriba.startswith(("INSERT", "UPDATE", "DELETE", "CREATE")):
            self.estado = self.INTRANS
            if arriba.startswith("INSERT"):
                self.filas.append(sql)
        elif self.estado == self.IDLE:
            self.estado = self.INTRANS
        return

    def commit(self):
        self.estado = self.IDLE
        self.puntos = []

    def rollback(self):
        self.filas = []
        self.estado = self.IDLE
        self.puntos = []

    def close(self):
        pass


class ElTrabajoAnteriorSobreviveTests(unittest.TestCase):
    def setUp(self):
        self.raw = ConexionDeMentira()
        self.cx = PostgresCompatConnection(self.raw)

    def _falla_accesoria(self):
        with self.assertRaises(Exception):
            self.cx.execute("UPDATE t SET FALLA = NULL")

    def test_el_caso_del_borrado_en_cascada(self):
        """Doce borrados buenos y una actualización accesoria que revienta."""
        for i in range(12):
            self.cx.execute(f"INSERT INTO t (id) VALUES ({i})")
        self._falla_accesoria()
        self.assertEqual(len(self.raw.filas), 12, "se ha perdido el trabajo de la petición")

    def test_y_se_puede_seguir_escribiendo_despues(self):
        self.cx.execute("INSERT INTO t (id) VALUES (1)")
        self._falla_accesoria()
        self.cx.execute("INSERT INTO t (id) VALUES (2)")
        self.assertEqual(len(self.raw.filas), 2)

    def test_y_se_puede_seguir_leyendo_despues(self):
        """Sin el arreglo, la siguiente lectura moría con «transaction is aborted»."""
        self.cx.execute("INSERT INTO t (id) VALUES (1)")
        self._falla_accesoria()
        self.assertEqual(self.cx.execute("SELECT COUNT(*) FROM t").fetchone()[0], 1)

    def test_dos_fallos_seguidos_tampoco_se_llevan_nada(self):
        self.cx.execute("INSERT INTO t (id) VALUES (1)")
        self._falla_accesoria()
        self._falla_accesoria()
        self.assertEqual(len(self.raw.filas), 1)

    def test_lo_que_falla_no_se_aplica(self):
        """Acotar el daño no es tragárselo: la sentencia mala no deja rastro."""
        self.cx.execute("INSERT INTO t (id) VALUES (1)")
        with self.assertRaises(Exception):
            self.cx.execute("INSERT INTO t (id) VALUES (2) FALLA")
        self.assertEqual(len(self.raw.filas), 1)

    def test_sin_el_arreglo_se_perderia_todo(self):
        """El control: así se comportaba el adaptador hasta ahora."""
        raw = ConexionDeMentira()
        for i in range(12):
            raw.execute(f"INSERT INTO t (id) VALUES ({i})")
        try:
            raw.execute("UPDATE t SET FALLA = NULL")
        except Exception:
            raw.rollback()
        self.assertEqual(len(raw.filas), 0)

    def test_executemany_tambien_esta_protegido(self):
        self.cx.execute("INSERT INTO t (id) VALUES (0)")
        with self.assertRaises(Exception):
            self.cx.executemany("INSERT INTO t (id) VALUES (%s) FALLA", [(1,), (2,)])
        self.assertEqual(len(self.raw.filas), 1)


class LoQueCuestaTests(unittest.TestCase):
    """Un punto de retorno por sentencia es un viaje más al servidor. Que sólo lo
    paguen las peticiones que escriben, y sólo desde la primera escritura."""

    def setUp(self):
        self.raw = ConexionDeMentira()
        self.cx = PostgresCompatConnection(self.raw)

    def _puntos(self):
        """Viajes al servidor que sólo sirven para mover el punto de retorno."""
        return [v for v in self.raw.viajes
                if all(t.strip().upper().startswith(("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO"))
                       for t in v.split(";") if t.strip())]

    def test_leer_no_cuesta_nada(self):
        for _ in range(20):
            self.cx.execute("SELECT 1")
        self.assertEqual(self._puntos(), [])

    def test_la_primera_escritura_tampoco(self):
        """No hay nada anterior que proteger."""
        self.cx.execute("INSERT INTO t (id) VALUES (1)")
        self.assertEqual(self._puntos(), [])

    def test_un_solo_viaje_por_sentencia(self):
        for i in range(5):
            self.cx.execute(f"INSERT INTO t (id) VALUES ({i})")
        # 4 sentencias protegidas (la primera no), UN viaje cada una: el
        # `RELEASE` y el `SAVEPOINT` viajan juntos en la misma orden.
        self.assertEqual(len(self._puntos()), 4)
        self.assertEqual(sum(1 for v in self._puntos() if ";" in v), 3)

    def test_la_pila_de_puntos_no_crece(self):
        """Reutilizar el nombre y soltar el anterior evita que una transacción larga
        acumule miles de puntos en el servidor."""
        for i in range(200):
            self.cx.execute(f"INSERT INTO t (id) VALUES ({i})")
        self.assertLessEqual(len(self.raw.puntos), 1)

    def test_confirmar_reinicia_la_cuenta(self):
        self.cx.execute("INSERT INTO t (id) VALUES (1)")
        self.cx.commit()
        antes = len(self._puntos())
        self.cx.execute("SELECT 1")
        self.assertEqual(len(self._puntos()), antes)


class QueCuentaComoEscrituraTests(unittest.TestCase):
    def test_las_lecturas(self):
        for sql in ("SELECT 1", "  select * from t", "EXPLAIN SELECT 1", "SHOW timezone",
                    "SET statement_timeout TO '5s'", "-- nota\nSELECT 1"):
            with self.subTest(sql):
                self.assertFalse(_es_escritura(sql))

    def test_las_escrituras(self):
        for sql in ("INSERT INTO t VALUES (1)", "update t set a=1", "DELETE FROM t",
                    "CREATE TABLE t (id int)", "ALTER TABLE t ADD COLUMN a int",
                    "DROP TABLE t", "TRUNCATE t"):
            with self.subTest(sql):
                self.assertTrue(_es_escritura(sql))

    def test_un_cte_que_escribe_cuenta_como_escritura(self):
        self.assertTrue(_es_escritura("WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x"))

    def test_un_cte_que_solo_lee_no(self):
        self.assertFalse(_es_escritura("WITH x AS (SELECT 1) SELECT * FROM x"))

    def test_ante_la_duda_se_protege(self):
        """Pasarse cuesta un viaje; quedarse corto cuesta datos."""
        self.assertTrue(_es_escritura("VACUUM"))
        self.assertTrue(_es_escritura(""))


@unittest.skipUnless(
    os.environ.get("RUN_PG_ADAPTER_TESTS") == "1",
    "necesita un Postgres de verdad; se pide con RUN_PG_ADAPTER_TESTS=1")
class ContraPostgresDeVerdadTests(unittest.TestCase):
    """Sobre una tabla temporal, y la transacción se deshace siempre: no toca datos."""

    def setUp(self):
        import pathlib

        import psycopg
        dsn = (os.environ.get("DATABASE_URL") or "").strip()
        if not dsn:
            env = pathlib.Path(__file__).resolve().parents[1] / ".env"
            m = re.search(r"^DATABASE_URL=(.+)$", env.read_text(encoding="utf-8"), re.M) if env.exists() else None
            dsn = m.group(1).strip().strip('"') if m else ""
        if not dsn:
            self.skipTest("sin DATABASE_URL")
        self.raw = psycopg.connect(dsn, autocommit=False)
        self.cx = PostgresCompatConnection(self.raw)
        self.cx.execute("CREATE TEMP TABLE ensayo_puntos (id int) ON COMMIT DROP")

    def tearDown(self):
        self.raw.rollback()
        self.raw.close()

    def _cuenta(self):
        return self.cx.execute("SELECT COUNT(*) FROM ensayo_puntos").fetchone()[0]

    def test_el_trabajo_anterior_sobrevive(self):
        for i in range(12):
            self.cx.execute("INSERT INTO ensayo_puntos (id) VALUES (%s)", (i,))
        with self.assertRaises(Exception):
            self.cx.execute("UPDATE ensayo_puntos SET columna_que_no_existe = NULL")
        self.assertEqual(self._cuenta(), 12)

    def test_se_puede_seguir_trabajando(self):
        self.cx.execute("INSERT INTO ensayo_puntos (id) VALUES (1)")
        with self.assertRaises(Exception):
            self.cx.execute("UPDATE ensayo_puntos SET columna_que_no_existe = NULL")
        self.cx.execute("INSERT INTO ensayo_puntos (id) VALUES (2)")
        self.assertEqual(self._cuenta(), 2)


if __name__ == "__main__":
    unittest.main()


class NingunaEscrituraSeTragaSinDecirloTests(unittest.TestCase):
    """El punto de retorno acota el daño; esto acota el silencio.

    Un `try/except: pass` alrededor de una escritura es una decisión legítima —que
    la bitácora falle no debe tumbar la operación—, pero sin una línea en el log no
    hay forma de enterarse. Así estuvo el borrado en cascada: respondiendo 200,
    perdiendo el expediente, y sin rastro.

    Los bloques que sólo crean tablas o índices al arrancar se quedan como están:
    ahí el fallo es esperable y ruidoso no aporta.
    """

    import ast as _ast
    import pathlib as _pathlib

    VERBO = re.compile(
        r"\b(INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM|CREATE\s+TABLE"
        r"|CREATE\s+(?:UNIQUE\s+)?INDEX|ALTER\s+TABLE|DROP\s+TABLE|DROP\s+INDEX)"
        r"\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:IF\s+EXISTS\s+)?([A-Za-z_][A-Za-z_0-9]*)", re.I)
    ESQUEMA = ("CREATE TABLE", "CREATE INDEX", "CREATE UNIQUE", "ALTER TABLE",
               "DROP INDEX", "DROP TABLE")

    def _mudos(self):
        ast, pathlib = self._ast, self._pathlib
        src = (pathlib.Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        arbol = ast.parse(src)
        mudos = []
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Try) or not nodo.handlers:
                continue
            if not all(len(h.body) == 1 and isinstance(h.body[0], ast.Pass) for h in nodo.handlers):
                continue
            trozo = ast.get_source_segment(src, nodo) or ""
            ops = [re.sub(r"\s+", " ", m.group(1).upper()) for m in self.VERBO.finditer(trozo)]
            if not ops or all(o.startswith(self.ESQUEMA) for o in ops):
                continue
            mudos.append((nodo.lineno, ops[:2]))
        return mudos

    def test_no_queda_ninguno(self):
        mudos = self._mudos()
        self.assertEqual(mudos, [], f"escrituras que fallan sin decir nada: {mudos}")

    def test_el_apunte_existe_y_no_revienta(self):
        """Si el propio registro lanzara, volvería a tumbar lo que intenta salvar."""
        from web import server as S
        S.apunta_escritura_tragada("prueba/tabla", Exception("lo que sea"))
        S.apunta_escritura_tragada(None, None)
