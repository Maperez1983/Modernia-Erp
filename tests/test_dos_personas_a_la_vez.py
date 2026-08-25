"""Dos personas haciendo lo mismo a la misma hora.

Todo lo auditado en esta campaña se ha hecho con **un usuario**: una petición, se mira
el resultado, la siguiente. Modernia tiene 19 usuarios y el servidor va con hilos, así
que dos administradoras pueden estar en la misma comunidad a la vez y una gestoría puede
facturar desde dos pantallas.

Esto se prueba **contra Postgres**. SQLite serializa las escrituras con un cerrojo de
base entera, así que esconde justo esta clase de fallo. Lo que no necesita base va
siempre; lo demás se salta si no hay Postgres a mano. Se dispara con
`scripts/prueba_de_concurrencia.py`.

Lo que salió
------------
**Numerar una factura estaba roto en Postgres, y punto.** El `SELECT` pedía dos columnas
sin nombre —`COALESCE(prefijo,'')` y `COALESCE(siguiente_numero,1)`— y la fila vuelve
como diccionario: las dos se llaman «coalesce», una pisa a la otra, y `series_row[1]`
reventaba con `KeyError`. O sea que dejar el número en blanco, que es lo que dice el
formulario («Autogenerado»), devolvía un 500. En SQLite las filas se indexan por
posición y no se notaba. En producción no hay ninguna serie creada todavía, así que
nadie lo ha pisado; el primero que lo haga, sí.

**Y la numeración era una carrera.** Leer el contador, componer el número y guardar el
siguiente son tres pasos: dos peticiones leían el mismo y salían dos facturas con el
mismo número. Ahora es un `UPDATE … RETURNING`: el contador se reserva y se lee de una
vez, con la fila bloqueada mientras tanto. Más un índice único, que es lo único que no
se puede saltar.

**Dar de alta el mismo cliente a la vez creaba fichas duplicadas.** Seis altas
simultáneas con el mismo NIF dejaron cuatro fichas: la comprobación de duplicados mira
lo confirmado y no ve a las otras cinco. Y una ficha duplicada no se arregla sola, hay
que fusionarla a mano decidiendo cuál es la buena. Ahora hay un índice único con **el
mismo criterio que usa la comprobación** —NIF en mayúsculas y sin espacios, puntos ni
guiones, dentro del workspace— y el choque devuelve el 409 «Cliente duplicado» de
siempre, con el id de la ficha que ganó, para acabar en la ficha buena y no en un error.

Para poder crearlo hubo que limpiar tres NIF de producción que decían `ES`, que no es un
NIF: «Caja Diaria» y «DOMINGO ALVAREZ DE LOS SANTOS» dos veces. Se vació el campo; las
fichas no se tocaron.

**Emitir los recibos del mes a la vez daba un 500.** El bucle mira si el recibo existe y
lo inserta; con dos personas las dos pasan la comprobación y una choca con el índice
único. Que choque está bien —el índice es lo que impide cobrar dos veces al
vecindario— pero salía como error del servidor en vez de «esto acaba de emitirlo otra
persona».

Lo que sigue abierto, a propósito
---------------------------------
La fila de la serie queda bloqueada hasta que la petición confirma, o sea toda la
petición, automatizaciones incluidas. Con seis personas a la vez, medido, ocho de
cuarenta y ocho facturas no salen. Confirmar la reserva en el acto lo sube a 47 de 48
—pero una de esas 48 devolvía 200 sin guardar la factura, y no se ha encontrado por qué.
Cambiar un fallo que se ve por uno que no se ve, en facturación, es peor negocio. Está
anotado en el código y en AUDITORIA_DE_USO.md.
"""

import os
import re
import shutil
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("POSTGRES_URL", "")

from tests._postgres_de_pruebas import salta_si_no_hay  # noqa: E402
from web import server as S  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")


def base(caso):
    tmp = tempfile.mkdtemp()
    caso.addCleanup(shutil.rmtree, tmp, True)
    ruta = Path(tmp) / "conc.sqlite"
    conn = S.get_db(ruta)
    caso.addCleanup(conn.close)
    S.ensure_tables(str(ruta))
    for crear in (S.ensure_workspace_core_tables, S.ensure_workspace_product_tables):
        crear(conn)
    ahora = "2026-01-01T09:00:00"
    conn.execute("INSERT INTO empresas (id, nombre, activo, created_at, updated_at) "
                 "VALUES ('e1','X',1,?,?)", (ahora, ahora))
    conn.execute("INSERT INTO workspaces (id, nombre, slug, created_at, updated_at) "
                 "VALUES ('w1','X','x',?,?)", (ahora, ahora))
    conn.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, "
                 "updated_at) VALUES ('we1','w1','e1',?,?)", (ahora, ahora))
    conn.execute(
        "INSERT INTO workspace_facturacion_series (id, workspace_id, empresa_id, servicio, "
        "serie, prefijo, siguiente_numero, activa, created_at, updated_at) "
        "VALUES ('s1','w1','e1','gestoria','A','FA-',1,1,?,?)", (ahora, ahora))
    conn.commit()
    return conn


RESERVA = """
    UPDATE workspace_facturacion_series
    SET siguiente_numero = COALESCE(siguiente_numero, 1) + 1, updated_at = ?
    WHERE workspace_id = ? AND empresa_id = ? AND serie = ? AND COALESCE(activa, 1) = 1
    RETURNING id AS serie_id, COALESCE(prefijo, '') AS prefijo,
              COALESCE(siguiente_numero, 1) - 1 AS asignado
"""


class ReservarUnNumeroTests(unittest.TestCase):
    """Una sola sentencia: reserva y lee a la vez."""

    def setUp(self):
        self.conn = base(self)

    def _reserva(self):
        f = self.conn.execute(RESERVA, ("2026-01-01", "w1", "e1", "A")).fetchone()
        return S.row_value(f, "prefijo"), int(S.row_value(f, "asignado"))

    def test_da_el_número_y_avanza_el_contador(self):
        self.assertEqual(self._reserva(), ("FA-", 1))
        self.assertEqual(self._reserva(), ("FA-", 2))
        self.assertEqual(self._reserva(), ("FA-", 3))

    def test_se_leen_por_nombre_no_por_posición(self):
        """El fallo era éste: en Postgres la fila es un diccionario y dos columnas sin
        nombre se pisan. `series_row[1]` reventaba con KeyError."""
        f = self.conn.execute(RESERVA, ("2026-01-01", "w1", "e1", "A")).fetchone()
        for clave in ("serie_id", "prefijo", "asignado"):
            self.assertIsNotNone(S.row_value(f, clave, None), clave)

    def test_una_serie_apagada_no_da_número(self):
        self.conn.execute("UPDATE workspace_facturacion_series SET activa = 0")
        self.conn.commit()
        self.assertIsNone(self.conn.execute(RESERVA, ("2026-01-01", "w1", "e1", "A")).fetchone())


class ElCodigoNoVuelveALoDeAntesTests(unittest.TestCase):
    """Lo de antes eran tres pasos, y es fácil que alguien los reponga."""

    def test_la_reserva_es_una_sola_sentencia(self):
        i = SERVER.index("UPDATE workspace_facturacion_series")
        trozo = SERVER[i:i + 700]
        self.assertIn("RETURNING", trozo)
        self.assertIn("siguiente_numero = COALESCE(siguiente_numero, 1) + 1", trozo)

    def test_y_se_lee_por_nombre(self):
        i = SERVER.index("UPDATE workspace_facturacion_series")
        trozo = SERVER[i:i + 1400]
        self.assertIn('row_value(series_row, "prefijo"', trozo)
        # Sólo en el código: el comentario de arriba nombra `series_row[1]` a propósito,
        # para contar qué pasaba.
        self.assertNotIn("prefijo = series_row[1]", SERVER)
        self.assertNotIn("int(series_row[2]", SERVER)

    def test_hay_un_índice_que_impide_repetir_número(self):
        """Una comprobación antes de insertar no ve lo que otra petición está
        escribiendo sin confirmar. El índice sí."""
        self.assertIn("idx_workspace_facturacion_serie_numero", SERVER)
        i = SERVER.index("idx_workspace_facturacion_serie_numero")
        trozo = SERVER[i:i + 300]
        self.assertIn("workspace_id, empresa_id, serie, numero", trozo)
        self.assertIn("COALESCE(numero, '') <> ''", trozo)

    def test_emitir_recibos_no_revienta_si_otro_se_adelanta(self):
        i = SERVER.index("Otra persona ha emitido este mismo cargo")
        trozo = SERVER[i - 400:i + 1500]
        self.assertIn("ya_estaban += 1", trozo)
        self.assertIn('"code": "ya_emitido"', trozo)
        self.assertIn("emitidos_por_otro", trozo)

    def test_hay_un_índice_que_impide_la_ficha_duplicada(self):
        self.assertIn("idx_clientes_nif_unico_por_workspace", SERVER)
        i = SERVER.index("CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_nif_unico_por_workspace")
        trozo = SERVER[i:i + 420]
        # El mismo criterio que la comprobación de duplicados: si difiere, el índice
        # rechazaría altas que la aplicación considera distintas.
        self.assertIn("REPLACE(REPLACE(REPLACE(UPPER(COALESCE(nif, '')), ' ', ''), '-', ''), '.', '')",
                      trozo)
        self.assertIn("COALESCE(workspace_id, '')", trozo)
        self.assertIn("WHERE COALESCE(nif, '') <> ''", trozo)

    def test_y_si_no_se_puede_crear_se_dice(self):
        """Un `try/except` mudo aquí deja creer que el índice existe cuando no."""
        i = SERVER.index("CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_nif_unico_por_workspace")
        trozo = SERVER[i:i + 2000]
        self.assertIn("[AVISO] No se pudo crear idx_clientes_nif_unico_por_workspace", trozo)
        self.assertIn("pendientes de fusionar", trozo)

    def test_el_alta_que_choca_devuelve_la_ficha_que_ganó(self):
        i = SERVER.index("Otra persona ha dado de alta este mismo NIF")
        trozo = SERVER[i - 300:i + 1200]
        self.assertIn("resolve_cliente_duplicate_id(", trozo)
        self.assertIn('"error": "Cliente duplicado", "id": gemelo', trozo)
        self.assertIn("status=409", trozo)

    def test_y_lo_que_queda_abierto_está_escrito_donde_se_ve(self):
        """Si alguien mete el commit sin resolver la pérdida, que se encuentre la nota."""
        self.assertIn("PENDIENTE, a propósito: la reserva NO se confirma aquí", SERVER)


@unittest.skipUnless(os.environ.get("CRM_POSTGRES_PRUEBAS"), "necesita Postgres")
class ContraPostgresDeVerdadTests(unittest.TestCase):
    """El caso que rompía: sobre Postgres las filas son diccionarios."""

    def setUp(self):
        # A propósito con `dict_row`, que es como abre las conexiones la aplicación
        # (`open_postgres_conn(with_row_factory=True)`). Es esa fábrica de filas la que
        # colapsa dos columnas que se llaman igual.
        import psycopg
        from tests._postgres_de_pruebas import dsn_de_pruebas
        from web.db_backend import PostgresCompatConnection
        crudo = psycopg.connect(dsn_de_pruebas(), autocommit=False,
                                row_factory=psycopg.rows.dict_row)
        self.addCleanup(crudo.close)
        self.addCleanup(crudo.rollback)
        self.cx = PostgresCompatConnection(crudo)
        self.cx.execute("""
            CREATE TEMP TABLE series_ensayo (
              id text PRIMARY KEY, prefijo text, siguiente_numero integer
            ) ON COMMIT DROP""")
        self.cx.execute("INSERT INTO series_ensayo VALUES ('s1', 'FA-', 1)")

    def test_dos_columnas_sin_nombre_se_pisan(self):
        """Es el fallo, medido: el diccionario sólo conserva una «coalesce»."""
        f = self.cx.execute(
            "SELECT id, COALESCE(prefijo,''), COALESCE(siguiente_numero,1) "
            "FROM series_ensayo LIMIT 1").fetchone()
        self.assertEqual(len(f), 2, f"se esperaban 2 claves, no 3: {f}")
        with self.assertRaises(KeyError):
            f[1]

    def test_con_alias_no_se_pisan(self):
        f = self.cx.execute(
            "SELECT id, COALESCE(prefijo,'') AS prefijo, "
            "COALESCE(siguiente_numero,1) AS n FROM series_ensayo LIMIT 1").fetchone()
        self.assertEqual(f["prefijo"], "FA-")
        self.assertEqual(f["n"], 1)

    def test_reservar_a_la_vez_no_da_dos_veces_el_mismo(self):
        """Seis hilos, seis números distintos."""
        import psycopg
        from tests._postgres_de_pruebas import dsn_de_pruebas
        dsn = dsn_de_pruebas()
        tabla = f"series_conc_{uuid.uuid4().hex[:8]}"
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(f"CREATE TABLE {tabla} (id text PRIMARY KEY, n integer)")
            c.execute(f"INSERT INTO {tabla} VALUES ('s1', 1)")
        self.addCleanup(lambda: psycopg.connect(dsn, autocommit=True)
                        .execute(f"DROP TABLE IF EXISTS {tabla}"))

        barrera = threading.Barrier(6)

        def reserva(_):
            barrera.wait()
            with psycopg.connect(dsn, autocommit=True) as c:
                return c.execute(
                    f"UPDATE {tabla} SET n = n + 1 WHERE id = 's1' RETURNING n - 1"
                ).fetchone()[0]

        with ThreadPoolExecutor(max_workers=6) as pool:
            dados = list(pool.map(reserva, range(6)))
        self.assertEqual(sorted(dados), [1, 2, 3, 4, 5, 6], f"repetidos: {dados}")


class ElGuionDeConcurrenciaSigueAhiTests(unittest.TestCase):
    def test_existe_y_exige_postgres(self):
        guion = (RAIZ / "scripts" / "prueba_de_concurrencia.py")
        self.assertTrue(guion.exists())
        texto = guion.read_text(encoding="utf-8")
        self.assertIn("Esto necesita Postgres", texto)
        # Y que no se le pueda apuntar a la base de verdad.
        self.assertIn('("127.0.0.1", "localhost", "::1")', texto)

    def test_dispara_los_cuatro_casos(self):
        texto = (RAIZ / "scripts" / "prueba_de_concurrencia.py").read_text(encoding="utf-8")
        for caso in ("numerar_facturas", "emitir_recibos", "fichar", "alta_de_cliente"):
            self.assertIn(f"def {caso}(", texto, caso)


if __name__ == "__main__":
    unittest.main()
