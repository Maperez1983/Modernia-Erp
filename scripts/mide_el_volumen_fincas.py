#!/usr/bin/env python3
"""Una comunidad de verdad, un año entero de recibos, y qué tarda cada pantalla.

Por qué esta aparte
-------------------
Producción tiene 318 vecinos en 14 comunidades y **cero recibos**: el módulo de fincas
está cargado pero todavía no ha facturado. O sea que todo lo que se ha auditado de
fincas en esta campaña —el ciclo mensual, la derrama, la morosidad, el certificado, la
remesa SEPA— se ha probado con **cuatro vecinos** y nunca con lo que va a haber el día
que se emita de verdad.

La comunidad más grande de producción tiene 59 vecinos. Un año son 708 recibos en una
sola comunidad, y 3.816 en las catorce. Esto lo monta y lo mide antes de que pase.

Lo que se mira
--------------
  · **Emitir**: cuánto tarda emitir un mes para 59 propietarios, y si el tiempo crece
    de forma razonable al acumularse los meses anteriores.
  · **Listar**: la pantalla de recibos con 708 dentro.
  · **Morosidad**: la consulta que cruza recibos con vecinos, que es la cara.
  · **La remesa SEPA**: un `pain.008` con 59 adeudos, y que el `CtrlSum` cuadre. Un
    fichero que no cuadra lo rechaza el banco entero, no una línea.

Uso
---
    CRM_POSTGRES_PRUEBAS=postgresql://postgres@127.0.0.1:55432/crm_pruebas \\
        python scripts/mide_el_volumen_fincas.py

    ... --vecinos 59 --meses 12
"""

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

# Medido en producción el 2026-08-25.
PRODUCCION = {"vecinos_total": 318, "comunidades": 14, "comunidad_mayor": 59, "recibos": 0}


class Cliente:
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
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                bruto = r.read()
                for cab in r.headers.get_all("Set-Cookie") or []:
                    k, _, v = cab.split(";")[0].partition("=")
                    self.cookies[k.strip()] = v.strip()
                return r.status, bruto, (time.perf_counter() - t0) * 1000
        except urllib.error.HTTPError as e:
            return e.code, e.read() or b"", (time.perf_counter() - t0) * 1000

    def json(self, *a, **k):
        estado, bruto, ms = self.pide(*a, **k)
        try:
            return estado, json.loads(bruto or b"null"), ms
        except Exception:
            return estado, bruto, ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vecinos", type=int, default=PRODUCCION["comunidad_mayor"])
    ap.add_argument("--meses", type=int, default=12)
    ap.add_argument("--puerto", type=int, default=8826)
    args = ap.parse_args()

    dsn = (os.environ.get("CRM_POSTGRES_PRUEBAS") or "").strip()
    if dsn:
        host = urllib.parse.urlparse(dsn).hostname or ""
        if host.lower() not in ("127.0.0.1", "localhost", "::1", ""):
            print(f"  CRM_POSTGRES_PRUEBAS apunta a «{host}», que no es local. No.")
            return 2
        os.environ["DATABASE_URL"] = dsn
        os.environ["APP_DB_BACKEND"] = "postgres"
    else:
        os.environ["DATABASE_URL"] = ""
        os.environ["POSTGRES_URL"] = ""
        os.environ["APP_DB_BACKEND"] = "sqlite"

    from web import db_backend as D
    from web import server as S

    S.Handler.db_path = ":volumen-fincas:" if dsn else ":memory:"

    srv = S.ThreadingHTTPServer(("127.0.0.1", args.puerto), S.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    nav = Cliente(f"http://127.0.0.1:{args.puerto}")

    print(f"\n  base: {'Postgres local' if dsn else 'SQLite en memoria'}")
    print(f"  producción hoy: {PRODUCCION['vecinos_total']} vecinos en "
          f"{PRODUCCION['comunidades']} comunidades, {PRODUCCION['recibos']} recibos")
    print(f"  se monta: 1 comunidad de {args.vecinos} vecinos × {args.meses} meses = "
          f"{args.vecinos * args.meses:,} recibos\n")

    try:
        conn = S.get_db(S.Handler.db_path)
        if dsn:
            D.ensure_postgres_sqlite_compat(conn)
            conn.commit()
        S.ensure_tables(S.Handler.db_path)
        S.ensure_workspace_core_tables(conn)
        S.ensure_workspace_product_tables(conn)
        conn.commit()

        ws, com = monta(S, conn, nav, args.vecinos)
        medidas = emite_el_año(nav, ws, com, args.vecinos, args.meses)
        medidas += mide_las_pantallas(nav, ws, com, args.vecinos, args.meses)
        informe(medidas, args.vecinos, args.meses)
    finally:
        srv.shutdown()
    return 0


def monta(S, conn, nav, cuantos_vecinos):
    ahora = "2026-01-01T09:00:00"
    conn.execute("INSERT INTO empresas (id, nombre, activo, created_at, updated_at) "
                 "VALUES ('e-f', 'Fincas Volumen', 1, ?, ?)", (ahora, ahora))
    conn.execute("INSERT INTO workspaces (id, nombre, slug, created_at, updated_at) "
                 "VALUES ('w-f', 'Fincas', 'fincas-vol', ?, ?)", (ahora, ahora))
    conn.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, "
                 "updated_at) VALUES ('we-f', 'w-f', 'e-f', ?, ?)", (ahora, ahora))
    conn.execute(
        "INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, activo, "
        "password_hash, created_at, updated_at) VALUES ('u-f','Ana','Fincas','ana',"
        "'ana@x.test','Fincas','Administrador',1,?,?,?)",
        (S.hash_password("Clave1234!"), ahora, ahora))
    conn.execute("INSERT INTO workspace_miembros (id, workspace_id, usuario_id, rol, "
                 "created_at, updated_at) VALUES ('m-f','w-f','u-f','Administrador',?,?)",
                 (ahora, ahora))
    conn.commit()

    estado, r, _ = nav.json("/api/login", {"usuario": "ana", "password": "Clave1234!"})
    if estado != 200:
        raise SystemExit(f"  no se pudo entrar: {estado} {r}")

    estado, r, _ = nav.json("/api/workspace_fincas_comunidades", {
        "workspace_id": "w-f", "empresa_id": "e-f", "nombre": "C.P. Volumen",
        "direccion": "Calle Grande 1", "cif": "H12345678",
        "iban": "ES2321000418400000000001", "acreedor_sepa": "ES12ZZZH12345678",
        "cuenta_bancaria": "ES2321000418400000000001"})
    com = str((r or {}).get("id") or "")
    if not com:
        fila = conn.execute("SELECT id FROM workspace_fincas_comunidades LIMIT 1").fetchone()
        com = str(S.row_value(fila, "id") or "")
    if not com:
        raise SystemExit(f"  no se creó la comunidad: {estado} {r}")

    # Coeficientes que suman 100 exacto: si no, la emisión se niega (LPH art. 5) y
    # estaríamos midiendo el rechazo en vez de la emisión.
    base = round(100.0 / cuantos_vecinos, 4)
    coefs = [base] * cuantos_vecinos
    coefs[-1] = round(100.0 - base * (cuantos_vecinos - 1), 4)
    t0 = time.perf_counter()
    for i, coef in enumerate(coefs):
        nav.pide("/api/workspace_fincas_vecinos", {
            "workspace_id": "w-f", "comunidad_id": com,
            "nombre": f"Propietario {i:03d}", "piso": f"{i // 4 + 1} {'ABCD'[i % 4]}",
            "coeficiente": coef, "nif": f"{25000000 + i}A", "email": f"v{i}@x.test",
            "iban": "ES2321000418400000000001"})
    print(f"  · censo de {cuantos_vecinos} vecinos ({time.perf_counter() - t0:.1f}s)")
    return "w-f", com


def emite_el_año(nav, ws, com, cuantos_vecinos, meses):
    """Emitir el mes 12 con once meses ya dentro no puede costar más que el mes 1."""
    medidas = []
    cuota = 100.0 * cuantos_vecinos
    for m in range(1, meses + 1):
        periodo = f"2026-{m:02d}"
        estado, r, ms = nav.json("/api/workspace_fincas_recibos_emitir", {
            "workspace_id": ws, "comunidad_id": com, "periodo": periodo,
            "importe": cuota, "concepto": f"Cuota ordinaria {periodo}"})
        medidas.append({"paso": "emitir un mes", "acumulado": cuantos_vecinos * m,
                        "estado": estado, "ms": ms, "bytes": 0,
                        "detalle": (r or {}).get("error") if isinstance(r, dict) else ""})
    return medidas


def mide_las_pantallas(nav, ws, com, cuantos_vecinos, meses):
    total = cuantos_vecinos * meses
    medidas = []

    def mide(paso, ruta, **q):
        estado, bruto, ms = nav.pide(ruta, None, **q)
        filas = None
        try:
            datos = json.loads(bruto or b"null")
            if isinstance(datos, dict):
                for k in ("rows", "recibos", "items"):
                    if isinstance(datos.get(k), list):
                        filas = len(datos[k])
                        break
            elif isinstance(datos, list):
                filas = len(datos)
        except Exception:
            pass
        medidas.append({"paso": paso, "acumulado": total, "estado": estado, "ms": ms,
                        "bytes": len(bruto), "filas": filas, "detalle": ""})
        return bruto

    mide("listar los recibos", "/api/workspace_fincas_recibos",
         workspace_id=ws, comunidad_id=com)
    mide("morosidad", "/api/workspace_fincas_morosidad",
         workspace_id=ws, comunidad_id=com)
    mide("el censo", "/api/workspace_fincas_vecinos",
         workspace_id=ws, comunidad_id=com, limit=500)
    mide("panel de la comunidad", "/api/workspace_fincas_comunidad_dashboard",
         workspace_id=ws, comunidad_id=com)
    mide("balance", "/api/workspace_fincas_balance", workspace_id=ws, comunidad_id=com)

    estado, r, ms = nav.json("/api/workspace_fincas_remesa_generar", {
        "workspace_id": ws, "comunidad_id": com, "periodo": "2026-01"})
    medidas.append({"paso": "generar la remesa", "acumulado": total, "estado": estado,
                    "ms": ms, "bytes": 0, "filas": None,
                    "detalle": (r or {}).get("error") if isinstance(r, dict) else ""})

    # El fichero que se manda al banco: si el CtrlSum no cuadra, lo rechaza entero.
    try:
        import sqlite3  # noqa: F401
        from web import server as S
        conn = S.get_db(S.Handler.db_path)
        fila = conn.execute("SELECT id, num_recibos FROM workspace_fincas_remesas "
                            "ORDER BY created_at DESC LIMIT 1").fetchone()
        if fila:
            rid = str(S.row_value(fila, "id"))
            bruto = mide("el fichero SEPA", "/api/workspace_fincas_remesa_sepa",
                         workspace_id=ws, id=rid, comunidad_id=com)
            texto = bruto.decode("utf-8", "replace")
            nb = re.search(r"<NbOfTxs>(\d+)</NbOfTxs>", texto)
            ctrl = re.search(r"<CtrlSum>([\d.]+)</CtrlSum>", texto)
            esperado = 100.0 * cuantos_vecinos
            medidas[-1]["detalle"] = (
                f"{nb.group(1) if nb else '?'} adeudos · CtrlSum "
                f"{ctrl.group(1) if ctrl else '?'} "
                + ("cuadra" if ctrl and abs(float(ctrl.group(1)) - esperado) < 0.01
                   else f"NO CUADRA (esperado {esperado:.2f})"))
        conn.close()
    except Exception as e:
        medidas.append({"paso": "el fichero SEPA", "acumulado": total, "estado": 0,
                        "ms": 0, "bytes": 0, "filas": None,
                        "detalle": f"no se pudo: {str(e).splitlines()[0][:60]}"})
    return medidas


def informe(medidas, cuantos_vecinos, meses):
    emisiones = [m for m in medidas if m["paso"] == "emitir un mes"]
    resto = [m for m in medidas if m["paso"] != "emitir un mes"]

    print(f"\n{'=' * 80}")
    if emisiones:
        malas = [m for m in emisiones if m["estado"] != 200]
        print(f"  Emitir {meses} meses para {cuantos_vecinos} propietarios:")
        print(f"    el primero: {emisiones[0]['ms']:.0f} ms  ·  "
              f"el último (con {emisiones[-1]['acumulado'] - cuantos_vecinos:,} recibos "
              f"ya dentro): {emisiones[-1]['ms']:.0f} ms")
        peor = max(emisiones, key=lambda m: m["ms"])
        print(f"    el peor: {peor['ms']:.0f} ms  ·  total "
              f"{sum(m['ms'] for m in emisiones) / 1000:.1f} s")
        if malas:
            print(f"    NO SE EMITIERON {len(malas)} meses: "
                  f"{[(m['estado'], m['detalle']) for m in malas][:3]}")

    print(f"\n  {'pantalla':26}{'filas':>8}{'tarda':>10}{'pesa':>10}   detalle")
    print(f"  {'-' * 76}")
    for m in resto:
        filas = "—" if m.get("filas") is None else f"{m['filas']:,}"
        if m["estado"] not in (200, 0):
            filas = f"HTTP {m['estado']}"
        peso = (f"{m['bytes'] / 1_048_576:.1f} MB" if m["bytes"] > 1_048_576
                else f"{m['bytes'] / 1024:.0f} KB")
        print(f"  {m['paso']:26}{filas:>8}{m['ms']:>9.0f}ms{peso:>10}   {m['detalle'] or ''}")

    print(f"\n  {'=' * 76}")
    avisos = []
    for m in medidas:
        if m["estado"] not in (200, 0):
            avisos.append(f"«{m['paso']}» responde HTTP {m['estado']} {m['detalle'] or ''}")
        if m["ms"] > 3000:
            avisos.append(f"«{m['paso']}» tarda {m['ms'] / 1000:.1f} s")
        if "NO CUADRA" in str(m.get("detalle") or ""):
            avisos.append(f"«{m['paso']}»: {m['detalle']}")
    if emisiones and len(emisiones) > 2:
        primero, ultimo = emisiones[0]["ms"], emisiones[-1]["ms"]
        if primero > 0 and ultimo / primero > 3:
            avisos.append(f"emitir se encarece {ultimo / primero:.1f}× al acumularse "
                          f"los meses: hay trabajo por recibo existente")
    if avisos:
        print("  Lo que hay que mirar:")
        for a in dict.fromkeys(avisos):
            print(f"    · {a}")
    else:
        print("  Nada que mirar: todo responde, cuadra y va rápido.")
    print()


if __name__ == "__main__":
    sys.exit(main())
