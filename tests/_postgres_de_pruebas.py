"""Abrir un Postgres para pruebas sin poder abrir el de producción.

Por qué existe
--------------
Importar `web.db_backend` carga `.env` en `os.environ` —lo hace a propósito, para que
el servidor arranque sin exportar nada a mano—. El efecto colateral es que, dentro de la
suite, **`os.environ["DATABASE_URL"]` es la base de producción** aunque nadie la haya
exportado.

Una prueba que quisiera un Postgres de verdad y leyera `DATABASE_URL` se conectaba a
Frankfurt. Así estaba escrita `test_puntos_de_retorno_postgres.py`: se salvó de hacer
daño porque trabaja sobre una tabla temporal y deshace, pero era el patrón que iban a
copiar las siguientes. Y la suite crea y borra tablas.

El candado de `main()` protege el arranque del servidor. Este protege la suite.

La regla
--------
El DSN se lee de una variable propia, `CRM_POSTGRES_PRUEBAS`, que nadie tiene puesta por
accidente; nunca de `DATABASE_URL` ni de `.env`. Y aun así se comprueba que apunte al
bucle local: si el host no es 127.0.0.1 o localhost, no se salta la prueba —se **falla**,
porque una variable de pruebas apuntando fuera es un error que hay que ver, no una
circunstancia que tolerar.

Cómo se levanta uno
-------------------
    initdb -D /ruta/pgdata -U postgres --auth=trust      # LC_ALL=en_US.UTF-8
    pg_ctl -D /ruta/pgdata -o "-p 55432 -k /tmp/crmpg -c listen_addresses=127.0.0.1" start
    createdb -h 127.0.0.1 -p 55432 -U postgres crm_pruebas

    export CRM_POSTGRES_PRUEBAS=postgresql://postgres@127.0.0.1:55432/crm_pruebas
"""

import os
import unittest
import urllib.parse

VARIABLE = "CRM_POSTGRES_PRUEBAS"

_LOCALES = {"127.0.0.1", "::1", "localhost", ""}


def dsn_de_pruebas():
    """El DSN si está declarado y es local. `None` si no hay. Revienta si apunta fuera."""
    dsn = (os.environ.get(VARIABLE) or "").strip()
    if not dsn:
        return None
    host = urllib.parse.urlparse(dsn).hostname or ""
    if host.lower() not in _LOCALES:
        raise AssertionError(
            f"{VARIABLE} apunta a «{host}», que no es local. Las pruebas crean y borran "
            f"tablas: contra una base remota eso destruye datos. Apúntala a 127.0.0.1."
        )
    return dsn


def salta_si_no_hay(caso):
    """Deja la prueba lista con una conexión, o la salta si no hay Postgres a mano."""
    # `dsn_de_pruebas` revienta a propósito si apunta fuera: eso NO se convierte en
    # salto. Saltar dejaría creer que se probó.
    dsn = dsn_de_pruebas()
    if not dsn:
        raise unittest.SkipTest(
            f"sin Postgres de pruebas; se pide con {VARIABLE}=postgresql://…@127.0.0.1:…/…")
    try:
        import psycopg
    except ImportError:
        raise unittest.SkipTest("falta psycopg")

    # Se abre por el adaptador de la aplicación, no en crudo: lo que se prueba es lo
    # que corre en producción, traducción y puntos de retorno incluidos.
    from web.db_backend import PostgresCompatConnection

    crudo = psycopg.connect(dsn, autocommit=False)
    conexion = PostgresCompatConnection(crudo)
    caso.addCleanup(crudo.close)
    caso.addCleanup(crudo.rollback)
    return conexion


def base_de_ensayo(caso):
    """Una base entera de usar y tirar, y `DATABASE_URL` apuntada a ella mientras dure.

    Hace falta para lo que abre su propia conexión —`ensure_tables` construye las 156
    tablas por su cuenta y no hereda ningún `search_path`—, así que aislar por esquema
    no vale. Y montarlo sobre la base de pruebas tal cual tampoco: habría que vaciarla,
    y vaciar una base que alguien pudo usar para otra cosa es justo lo que no se hace.

    Devuelve el DSN. La base se borra al terminar el caso, salga bien o mal.
    """
    dsn = dsn_de_pruebas()
    if not dsn:
        raise unittest.SkipTest(f"sin Postgres de pruebas; se pide con {VARIABLE}=…")
    try:
        import psycopg
    except ImportError:
        raise unittest.SkipTest("falta psycopg")

    partes = urllib.parse.urlparse(dsn)
    # El nombre lleva el pid: dos ejecuciones a la vez no se pisan.
    nombre = f"crm_ensayo_{os.getpid()}_{abs(hash(caso.id())) % 100000}"
    raiz = urllib.parse.urlunparse(partes._replace(path="/postgres"))

    def manda(sql):
        with psycopg.connect(raiz, autocommit=True) as c:
            c.execute(sql)

    manda(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')
    manda(f'CREATE DATABASE "{nombre}"')
    caso.addCleanup(manda, f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')

    nuevo = urllib.parse.urlunparse(partes._replace(path=f"/{nombre}"))
    previo = {k: os.environ.get(k) for k in ("DATABASE_URL", "APP_DB_BACKEND")}

    def restaura():
        for k, v in previo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    caso.addCleanup(restaura)
    os.environ["DATABASE_URL"] = nuevo
    os.environ["APP_DB_BACKEND"] = "postgres"
    return nuevo
