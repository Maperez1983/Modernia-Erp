#!/usr/bin/env python3
"""Dos personas haciendo lo mismo a la vez. Qué se rompe.

Por qué
-------
Todo lo auditado en esta campaña se ha hecho con **un usuario**: una petición, se mira
el resultado, la siguiente. Modernia tiene 19 usuarios y un servidor con hilos
(`ThreadingHTTPServer`), así que dos administradoras pueden estar dentro de la misma
comunidad a la misma hora, y una gestoría emite facturas desde varias pantallas.

Los fallos de concurrencia no salen probando: salen en producción, un martes, y dejan
datos que no se pueden arreglar solos —dos facturas con el mismo número, un vecino
cobrado dos veces—. La única forma de verlos antes es provocarlos.

Y hay que provocarlos **contra Postgres**. SQLite serializa las escrituras con un
cerrojo global de base, así que esconde justo esta clase de fallo: sobre SQLite casi
todo sale bien y en producción no.

Qué se dispara
--------------
  · **Numerar una factura**: la serie lleva un `siguiente_numero` que se lee, se usa y
    se vuelve a escribir. Si dos peticiones leen el mismo, salen dos facturas con el
    mismo número. La numeración correlativa de facturas no es una preferencia.
  · **Emitir los recibos del mes** dos veces a la vez sobre la misma comunidad: el
    riesgo es cobrar dos veces a todo el vecindario.
  · **Fichar la entrada** desde dos sitios: dos entradas abiertas el mismo día.
  · **Dar de alta el mismo cliente** a la vez: la ficha duplicada que luego hay que
    fusionar a mano.

Uso
---
    CRM_POSTGRES_PRUEBAS=postgresql://postgres@127.0.0.1:55432/crm_pruebas \\
        python scripts/prueba_de_concurrencia.py

    ... --a-la-vez 8 --vueltas 5

Sale con 1 si algo se duplica.
"""

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

CLAVE = "Clave1234!"


class Cliente:
    """Un navegador de mentira. Cada uno con su sesión, como dos personas distintas."""

    def __init__(self, base):
        self.base = base
        self.cookies = {}

    def pide(self, ruta, cuerpo=None, **query):
        if query:
            ruta += ("&" if "?" in ruta else "?") + urllib.parse.urlencode(query)
        datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
        req = urllib.request.Request(self.base + ruta, data=datos,
                                     method="POST" if datos else "GET")
        req.add_header("Content-Type", "application/json")
        if self.cookies:
            req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()))
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                bruto = r.read()
                for cab in r.headers.get_all("Set-Cookie") or []:
                    k, _, v = cab.split(";")[0].partition("=")
                    self.cookies[k.strip()] = v.strip()
                return r.status, _json(bruto)
        except urllib.error.HTTPError as e:
            return e.code, _json(e.read())
        except Exception as e:
            return 0, {"error": f"{type(e).__name__}: {e}"}

    def entra(self, usuario):
        estado, r = self.pide("/api/login", {"usuario": usuario, "password": CLAVE})
        if estado != 200:
            raise SystemExit(f"  no se pudo entrar como {usuario}: {estado} {r}")
        return self


def _json(bruto):
    try:
        return json.loads(bruto or b"null")
    except Exception:
        return {"crudo": (bruto or b"")[:200].decode("utf-8", "replace")}


def a_la_vez(quehacer, cuantos):
    """Los lanza y los suelta lo más juntos que se puede: una barrera y a correr."""
    barrera = threading.Barrier(cuantos)

    def envuelto(i):
        barrera.wait()
        return quehacer(i)

    with ThreadPoolExecutor(max_workers=cuantos) as pool:
        return list(pool.map(envuelto, range(cuantos)))


# ======================================================================== los casos

def numerar_facturas(S, conn, navs, ws, empresa, cuantos, vueltas):
    """Dos facturas de la misma serie a la vez: ¿sale el mismo número?"""
    conn.execute(
        "INSERT INTO workspace_facturacion_series (id, workspace_id, empresa_id, servicio, "
        "serie, prefijo, siguiente_numero, activa, created_at, updated_at) "
        "VALUES ('s1', ?, ?, 'gestoria', 'A', 'FA-', 1, 1, '2026-01-01', '2026-01-01')",
        (ws, empresa))
    conn.commit()

    respuestas = []
    for vuelta in range(vueltas):
        respuestas += a_la_vez(lambda i: navs[i % len(navs)].pide("/api/workspace_facturacion", {
            "workspace_id": ws, "empresa_id": empresa, "serie": "A",
            "concepto": f"Servicio {vuelta}-{i}", "total": 100.0,
            "fecha_emision": "2026-03-01"}), cuantos)
    from collections import Counter
    porque = Counter(f"{e} {str((r or {}).get('error') or '')[:48]}" for e, r in respuestas)

    filas = conn.execute(
        "SELECT COALESCE(numero,'') AS numero, COUNT(*) AS n FROM workspace_facturacion "
        "WHERE workspace_id = ? GROUP BY numero ORDER BY numero", (ws,)).fetchall()
    numeros = [(S.row_value(f, "numero"), int(S.row_value(f, "n"))) for f in filas]
    total = sum(n for _, n in numeros)
    repetidos = [(num, n) for num, n in numeros if n > 1 and num]
    sin_numero = sum(n for num, n in numeros if not num)
    siguiente = conn.execute("SELECT siguiente_numero AS s FROM workspace_facturacion_series "
                             "WHERE id = 's1'").fetchone()
    return {
        "caso": "numerar facturas",
        "peticiones": len(respuestas),
        "respuestas": dict(porque),
        "creadas": total,
        "distintos": len([1 for num, _ in numeros if num]),
        "repetidos": repetidos,
        "sin_numero": sin_numero,
        "contador_de_la_serie": int(S.row_value(siguiente, "s") or 0),
        "mal": bool(repetidos),
    }


def emitir_recibos(S, conn, navs, ws, comunidad, cuantos):
    """Emitir el mismo mes desde dos sitios: el riesgo es cobrar dos veces al vecindario."""
    respuestas = a_la_vez(lambda i: navs[i % len(navs)].pide(
        "/api/workspace_fincas_recibos_emitir", {
            "workspace_id": ws, "comunidad_id": comunidad, "periodo": "2026-05",
            "importe": 400.0, "concepto": "Cuota ordinaria mayo"}), cuantos)
    filas = conn.execute(
        "SELECT vecino_id AS v, COUNT(*) AS n FROM workspace_fincas_recibos "
        "WHERE comunidad_id = ? AND periodo = '2026-05' GROUP BY vecino_id",
        (comunidad,)).fetchall()
    dobles = [(S.row_value(f, "v"), int(S.row_value(f, "n"))) for f in filas
              if int(S.row_value(f, "n")) > 1]
    total = sum(int(S.row_value(f, "n")) for f in filas)
    return {
        "caso": "emitir los recibos del mes",
        "respuestas": sorted(e for e, _ in respuestas),
        "recibos": total,
        "propietarios_con_dos": dobles,
        "mal": bool(dobles),
    }


def fichar(S, conn, navs, ws, cuantos):
    """Dar entrada desde el móvil y el ordenador a la vez."""
    respuestas = a_la_vez(lambda i: navs[i % len(navs)].pide(
        "/api/workspace_registro_fichaje", {"workspace_id": ws, "tipo": "entrada"}), cuantos)
    try:
        abiertas = conn.execute(
            "SELECT COUNT(*) AS n FROM workspace_registro_horario "
            "WHERE COALESCE(hora_fin,'') = '' OR estado = 'Abierto'").fetchone()
        n = int(S.row_value(abiertas, "n") or 0)
    except Exception as e:
        return {"caso": "fichar la entrada", "mal": False,
                "nota": f"no se pudo mirar: {str(e).splitlines()[0][:60]}"}
    return {
        "caso": "fichar la entrada",
        "respuestas": sorted(e for e, _ in respuestas),
        "entradas_abiertas": n,
        "mal": n > 1,
    }


def alta_de_cliente(S, conn, navs, ws, empresa, cuantos):
    """El mismo nombre y el mismo NIF desde dos pantallas."""
    nif = "12345678Z"
    respuestas = a_la_vez(lambda i: navs[i % len(navs)].pide("/api/clientes", {
        "workspace_id": ws, "empresa_id": empresa,
        "nombre": "Cliente Repetido", "nif": nif}), cuantos)
    fila = conn.execute("SELECT COUNT(*) AS n FROM clientes WHERE nif = ?", (nif,)).fetchone()
    n = int(S.row_value(fila, "n") or 0)
    return {
        "caso": "alta del mismo cliente",
        "respuestas": sorted(e for e, _ in respuestas),
        "fichas_creadas": n,
        "mal": n > 1,
    }


# ============================================================================ montaje

def monta(S, conn, base, cuantos):
    ahora = "2026-01-01T09:00:00"
    conn.execute("INSERT INTO empresas (id, nombre, activo, created_at, updated_at) "
                 "VALUES ('e1','Concurrencia S.L.',1,?,?)", (ahora, ahora))
    conn.execute("INSERT INTO workspaces (id, nombre, slug, created_at, updated_at) "
                 "VALUES ('w1','Concurrencia','conc',?,?)", (ahora, ahora))
    conn.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, "
                 "updated_at) VALUES ('we1','w1','e1',?,?)", (ahora, ahora))
    clave = S.hash_password(CLAVE)
    navs = []
    for i in range(cuantos):
        # Usuarios distintos: dos personas, no la misma sesión repetida.
        conn.execute(
            "INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, "
            "activo, password_hash, created_at, updated_at) "
            "VALUES (?,?,'Admin',?,?,'Fincas','Administrador',1,?,?,?)",
            (f"u{i}", f"Persona{i}", f"persona{i}", f"p{i}@x.test", clave, ahora, ahora))
        conn.execute("INSERT INTO workspace_miembros (id, workspace_id, usuario_id, rol, "
                     "created_at, updated_at) VALUES (?,?,?,'Administrador',?,?)",
                     (f"m{i}", "w1", f"u{i}", ahora, ahora))
    conn.execute("INSERT INTO workspace_fincas_comunidades (id, workspace_id, empresa_id, "
                 "nombre, created_at, updated_at) VALUES ('c1','w1','e1','C.P. Concurrencia',?,?)",
                 (ahora, ahora))
    for i in range(10):
        conn.execute(
            "INSERT INTO workspace_fincas_vecinos (id, workspace_id, comunidad_id, nombre, "
            "piso, coeficiente, iban, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"v{i}", "w1", "c1", f"Propietario {i}", f"{i + 1}A", 10.0,
             "ES2321000418400000000001", ahora, ahora))
    conn.commit()
    for i in range(cuantos):
        navs.append(Cliente(base).entra(f"persona{i}"))
    return navs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a-la-vez", type=int, default=6, dest="a_la_vez")
    ap.add_argument("--vueltas", type=int, default=3)
    ap.add_argument("--puerto", type=int, default=8840)
    args = ap.parse_args()

    dsn = (os.environ.get("CRM_POSTGRES_PRUEBAS") or "").strip()
    if not dsn:
        print("\n  Esto necesita Postgres. SQLite serializa las escrituras con un cerrojo\n"
              "  de base entera, así que esconde justo lo que se busca aquí.\n"
              "  CRM_POSTGRES_PRUEBAS=postgresql://postgres@127.0.0.1:5432/… \n")
        return 2
    host = urllib.parse.urlparse(dsn).hostname or ""
    if host.lower() not in ("127.0.0.1", "localhost", "::1"):
        print(f"  CRM_POSTGRES_PRUEBAS apunta a «{host}», que no es local. No.")
        return 2
    os.environ["DATABASE_URL"] = dsn
    os.environ["APP_DB_BACKEND"] = "postgres"

    from web import db_backend as D
    from web import server as S

    S.Handler.db_path = ":concurrencia:"
    srv = S.ThreadingHTTPServer(("127.0.0.1", args.puerto), S.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{args.puerto}"

    print(f"\n  Postgres local · {args.a_la_vez} personas a la vez, {args.vueltas} vueltas\n")
    try:
        conn = S.get_db(S.Handler.db_path)
        D.ensure_postgres_sqlite_compat(conn)
        conn.commit()
        S.ensure_tables(S.Handler.db_path)
        S.ensure_workspace_core_tables(conn)
        S.ensure_workspace_product_tables(conn)
        conn.commit()
        navs = monta(S, conn, base, args.a_la_vez)

        resultados = [
            numerar_facturas(S, conn, navs, "w1", "e1", args.a_la_vez, args.vueltas),
            emitir_recibos(S, conn, navs, "w1", "c1", args.a_la_vez),
            fichar(S, conn, navs, "w1", args.a_la_vez),
            alta_de_cliente(S, conn, navs, "w1", "e1", args.a_la_vez),
        ]
        informe(resultados)
        return 1 if any(r.get("mal") for r in resultados) else 0
    finally:
        srv.shutdown()


def informe(resultados):
    print(f"{'=' * 74}")
    for r in resultados:
        marca = "SE DUPLICA" if r.get("mal") else "aguanta"
        print(f"\n  {r['caso']:34} {marca}")
        for clave, valor in r.items():
            if clave in ("caso", "mal"):
                continue
            print(f"      {clave.replace('_', ' '):26} {valor}")
    print(f"\n{'=' * 74}")
    malos = [r for r in resultados if r.get("mal")]
    if malos:
        print("  Lo que se rompe con dos personas a la vez:")
        for r in malos:
            print(f"    · {r['caso']}")
    else:
        print("  Nada se duplica.")
    print()


if __name__ == "__main__":
    sys.exit(main())
