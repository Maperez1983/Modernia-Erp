#!/usr/bin/env python3
"""Qué le pasa al CRM cuando la base deja de tener cuatro filas.

Por qué
-------
Todo lo que se ha auditado en esta campaña se probó con cuatro vecinos y tres clientes.
Producción tiene **2.262 clientes**, 318 vecinos en 14 comunidades y 16.528 reglas de
importación. Un listado que tarda 40 ms con tres filas puede tardar ocho segundos con
dos mil, y una consulta con un `LIMIT` de más puede estar escondiendo la mitad del
fichero sin decirlo. Nada de eso se ve con datos de juguete.

Esto siembra la base a escala de producción —y a varios múltiplos por encima, para ver
la curva— y luego **usa el CRM por la puerta de delante**: llama a los endpoints que
alimentan cada pantalla y mide qué tarda, cuánto pesa la respuesta y **cuántas filas
faltan**.

La siembra va directa a la base, que es montaje. La medición va por HTTP, que es lo que
hace un usuario.

Qué busca
---------
Tres cosas, y las tres devuelven 200 OK:

  · **Listas cortadas en silencio.** Un `LIMIT` sin aviso: la pantalla enseña 500 de
    2.262 y no hay nada que lo diga.
  · **Listas sin cortar.** Lo contrario, y también problema: mandar 2.262 fichas
    completas en cada carga.
  · **Tiempos que se disparan.** Si al doblar los datos el tiempo se cuadruplica, hay
    una consulta por fila escondida y a diez mil no se abre.

Uso
---
    CRM_POSTGRES_PRUEBAS=postgresql://postgres@127.0.0.1:55432/crm_pruebas \
        python scripts/mide_el_volumen.py

    ... --escalas 100,1000,2262,10000     # la curva que se quiera

Sin la variable usa SQLite en memoria; sirve para ver la forma de la curva, pero los
tiempos buenos son los de Postgres, que es lo que corre en producción.
"""

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

# La escala de producción medida el 2026-08-25. Sirve de referencia y de escala por
# defecto: lo que aguante esto es lo que aguanta hoy.
PRODUCCION = {
    "clientes": 2262,
    "vecinos": 318,
    "comunidad_mayor": 59,
    "comunidades": 14,
    "seguros": 408,
    "gestoria_asientos": 1225,
}


def _prepara_entorno(dsn):
    """Antes de importar nada del servidor: si no hay Postgres de pruebas, SQLite."""
    if dsn:
        os.environ["DATABASE_URL"] = dsn
        os.environ["APP_DB_BACKEND"] = "postgres"
    else:
        os.environ["DATABASE_URL"] = ""
        os.environ["POSTGRES_URL"] = ""
        os.environ["APP_DB_BACKEND"] = "sqlite"


class Cliente:
    """Un navegador de mentira: guarda la cookie y cronometra cada petición."""

    def __init__(self, base):
        self.base = base
        self.cookies = {}

    def pide(self, ruta, cuerpo=None):
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(self.base + ruta, data=datos,
                                     method="POST" if datos else "GET")
        req.add_header("Content-Type", "application/json")
        if self.cookies:
            req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()))
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                bruto = r.read()
                for cab in r.headers.get_all("Set-Cookie") or []:
                    k, _, v = cab.split(";")[0].partition("=")
                    self.cookies[k.strip()] = v.strip()
                ms = (time.perf_counter() - t0) * 1000
                return r.status, bruto, ms
        except urllib.error.HTTPError as e:
            return e.code, e.read() or b"", (time.perf_counter() - t0) * 1000


def cuenta_filas(bruto):
    """Cuántos registros trae la respuesta, sea cual sea la forma que le hayan dado."""
    try:
        datos = json.loads(bruto or b"null")
    except Exception:
        return None
    if isinstance(datos, list):
        return len(datos)
    if isinstance(datos, dict):
        for clave in ("items", "rows", "clientes", "data", "resultados", "vecinos", "recibos"):
            if isinstance(datos.get(clave), list):
                return len(datos[clave])
        listas = [v for v in datos.values() if isinstance(v, list)]
        if len(listas) == 1:
            return len(listas[0])
    return None


def siembra(conn, cuantos, workspace_id, empresa_id):
    """Mete `cuantos` clientes de golpe. Esto es montaje, no medición."""
    ahora = "2026-08-25T10:00:00"
    lote = []
    for i in range(cuantos):
        lote.append((
            uuid.uuid4().hex,
            # Repartidos por el abecedario: un ORDER BY c.nombre con LIMIT corta por
            # la letra, así que sembrarlos todos con el mismo prefijo escondería el
            # corte en vez de enseñarlo.
            f"{chr(65 + i % 26)}{i:06d} Cliente de volumen",
            f"{10000000 + i}Z",
            f"6{i:08d}"[:9],
            f"volumen{i}@ejemplo.test",
            empresa_id,
            workspace_id,
            ahora,
            ahora,
        ))
    conn.executemany(
        """INSERT INTO clientes (id, nombre, nif, telefono, email, empresa_id,
                                 workspace_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        lote,
    )
    vinculos = [(uuid.uuid4().hex, c[0], empresa_id, workspace_id, "gestoria", ahora, ahora)
                for c in lote]
    try:
        conn.executemany(
            """INSERT INTO clientes_empresas (id, cliente_id, empresa_id, workspace_id,
                                              servicio, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            vinculos,
        )
    except Exception as e:
        print(f"    (sin vincular a empresa: {str(e).splitlines()[0][:70]})")
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--escalas", default="100,1000,2262,10000",
                    help="cuántos clientes en cada vuelta")
    ap.add_argument("--puerto", type=int, default=8823)
    args = ap.parse_args()

    dsn = (os.environ.get("CRM_POSTGRES_PRUEBAS") or "").strip()
    if dsn:
        import urllib.parse
        host = urllib.parse.urlparse(dsn).hostname or ""
        if host.lower() not in ("127.0.0.1", "localhost", "::1", ""):
            print(f"  CRM_POSTGRES_PRUEBAS apunta a «{host}», que no es local. "
                  f"Esto siembra decenas de miles de filas: no contra una base remota.")
            return 2
    _prepara_entorno(dsn)

    from web import server as S

    # Sin esto, `get_db` fuerza SQLite aunque haya Postgres: la salida de emergencia
    # para pruebas mira si `db_path` es un Path.
    S.Handler.db_path = ":volumen:" if dsn else ":memory:"

    print(f"\n  base: {'Postgres local' if dsn else 'SQLite en memoria'}")
    print(f"  escala de producción hoy: {PRODUCCION['clientes']:,} clientes, "
          f"{PRODUCCION['vecinos']} vecinos en {PRODUCCION['comunidades']} comunidades\n")

    escalas = [int(x) for x in args.escalas.split(",") if x.strip().isdigit()]
    resultados = []

    srv = S.ThreadingHTTPServer(("127.0.0.1", args.puerto), S.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    nav = Cliente(f"http://127.0.0.1:{args.puerto}")

    try:
        t0 = time.perf_counter()
        conn = prepara_esquema(S, dsn)
        print(f"  · esquema levantado ({(time.perf_counter() - t0):.1f}s)")
        empresa_id, workspace_id = prepara_cuenta(S, conn, nav)

        sembrados = 0
        for objetivo in escalas:
            faltan = objetivo - sembrados
            if faltan > 0:
                t0 = time.perf_counter()
                siembra(conn, faltan, workspace_id, empresa_id)
                sembrados = objetivo
                print(f"  · sembrados {sembrados:,} clientes "
                      f"({(time.perf_counter() - t0):.1f}s)")

            reales = cuantos_hay(conn, "clientes")
            for etiqueta, ruta in rutas(workspace_id, empresa_id):
                estado, bruto, ms = nav.pide(ruta)
                resultados.append({
                    "escala": reales, "pantalla": etiqueta, "estado": estado,
                    "ms": ms, "bytes": len(bruto), "filas": cuenta_filas(bruto),
                })
        informe(resultados)
    finally:
        srv.shutdown()
    return 0


def rutas(workspace_id, empresa_id):
    w = f"workspace_id={workspace_id}&empresa_id={empresa_id}"
    return [
        # La pantalla de clientes. No acepta búsqueda: se trae la lista entera y el
        # navegador filtra. Por eso importa lo que pesa, no sólo lo que tarda.
        ("lista de clientes", f"/api/clientes_list?{w}"),
        # El desplegable de «elegir cliente» de las altas. Éste sí busca, y éste sí
        # tiene un LIMIT.
        ("selector de cliente", f"/api/clientes?{w}"),
        ("selector, buscando", f"/api/clientes?{w}&q=Z00"),
        ("contadores del panel", f"/api/clientes_stats?{w}"),
    ]


def cuantos_hay(conn, tabla):
    """La conexión de la aplicación devuelve diccionarios en Postgres y `Row` en SQLite."""
    fila = conn.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()
    try:
        return fila["n"]
    except Exception:
        return fila[0]


def prepara_esquema(S, dsn):
    """Lo que hace `main()` al arrancar, que aquí no pasa porque el servidor se monta
    a mano: crear las tablas."""
    from web import db_backend as D

    conn = S.get_db(S.Handler.db_path)
    if dsn:
        D.ensure_postgres_sqlite_compat(conn)
        conn.commit()
    S.ensure_tables(S.Handler.db_path)
    S.ensure_workspace_core_tables(conn)
    S.ensure_workspace_product_tables(conn)
    S.ensure_anuncio_schema(conn)
    conn.commit()
    return conn


def prepara_cuenta(S, conn, nav):
    """Una empresa, un workspace y un usuario que pueda entrar."""
    ahora = "2026-08-25T09:00:00"
    empresa_id, workspace_id, user_id = "e-vol", "w-vol", "u-vol"
    conn.execute("INSERT INTO empresas (id, nombre, activo, created_at, updated_at) "
                 "VALUES (?, ?, 1, ?, ?)", (empresa_id, "Volumen S.L.", ahora, ahora))
    conn.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, "
                 "updated_at) VALUES (?, ?, ?, ?, ?)",
                 (uuid.uuid4().hex, workspace_id, empresa_id, ahora, ahora))
    conn.execute(
        "INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, activo, "
        "password_hash, created_at, updated_at) VALUES (?,?,?,?,?,?,?,1,?,?,?)",
        (user_id, "Ana", "Volumen", "ana", "ana@ejemplo.test", "Gestoria", "Administrador",
         S.hash_password("Clave1234!"), ahora, ahora))
    conn.execute("INSERT INTO workspace_miembros (id, workspace_id, usuario_id, rol, created_at, "
                 "updated_at) VALUES (?,?,?,?,?,?)",
                 (uuid.uuid4().hex, workspace_id, user_id, "Administrador", ahora, ahora))
    conn.commit()
    estado, bruto, _ = nav.pide("/api/login", {"usuario": "ana", "password": "Clave1234!"})
    if estado != 200:
        raise SystemExit(f"  no se pudo entrar: {estado} {bruto[:200]!r}")
    return empresa_id, workspace_id


def informe(resultados):
    print(f"\n{'=' * 78}")
    print(f"  {'pantalla':24}{'filas en base':>14}{'devuelve':>10}{'tarda':>10}{'pesa':>11}")
    print(f"  {'-' * 74}")
    por_pantalla = {}
    for r in resultados:
        por_pantalla.setdefault(r["pantalla"], []).append(r)
    for pantalla, filas in por_pantalla.items():
        for i, r in enumerate(filas):
            nombre = pantalla if i == 0 else ""
            devuelve = "—" if r["filas"] is None else f"{r['filas']:,}"
            if r["estado"] != 200:
                devuelve = f"HTTP {r['estado']}"
            peso = (f"{r['bytes'] / 1_048_576:.1f} MB" if r["bytes"] > 1_048_576
                    else f"{r['bytes'] / 1024:.0f} KB")
            print(f"  {nombre:24}{r['escala']:>14,}{devuelve:>10}{r['ms']:>9.0f}ms{peso:>11}")
        print()

    print(f"  {'=' * 74}")
    print("  Lo que hay que mirar:")
    for pantalla, filas in por_pantalla.items():
        cortadas = [r for r in filas if r["filas"] is not None and r["filas"] < r["escala"]]
        if cortadas and all(r["filas"] == cortadas[0]["filas"] for r in cortadas) \
                and len(cortadas) > 1:
            r = cortadas[-1]
            print(f"    · «{pantalla}» se queda en {r['filas']:,} filas "
                  f"teniendo {r['escala']:,} en la base. Faltan {r['escala'] - r['filas']:,}.")
        lentas = [r for r in filas if r["ms"] > 1000]
        if lentas:
            print(f"    · «{pantalla}» pasa del segundo a partir de "
                  f"{lentas[0]['escala']:,} filas ({lentas[-1]['ms']:.0f} ms al final).")
        gordas = [r for r in filas if r["bytes"] > 1_048_576]
        if gordas:
            print(f"    · «{pantalla}» manda {gordas[-1]['bytes'] / 1_048_576:.1f} MB "
                  f"en una carga.")
    print()


if __name__ == "__main__":
    sys.exit(main())
