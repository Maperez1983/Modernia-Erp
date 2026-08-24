#!/usr/bin/env python3
"""Contrasta lo que la pantalla recibe contra lo que hay en la base.

Por qué
-------
Las simulaciones de uso comprueban que el CRM **hace** lo que debe. Esto comprueba otra
cosa: que lo que llega a la pantalla **dice** lo que hay guardado. Es la clase de fallo
que más tarde se descubre, porque el dato está bien y sólo se lee mal — el último que
salió así fue el punteo bancario, que pintaba en verde un emparejamiento con cero de
confianza porque la tabla leía uno de los tres campos que le llegaban.

Se siembra una base con importes y estados escogidos a mano, se levanta el servidor
encima, y por cada pantalla se comparan las cifras de la respuesta con las de la base.
No hace falta navegador: el fallo de esta familia está casi siempre en el salto entre la
consulta y lo que se sirve, y ahí sí se puede mirar.

Qué NO hace
-----------
No mira el HTML ni el CSS. Un número correcto que se pinta fuera de su columna, o una
etiqueta con el color cambiado, esto no lo ve: eso hay que mirarlo en el navegador.

Uso
---
    python scripts/contrasta_pantalla_con_la_base.py

Levanta su propio servidor sobre una base temporal. No toca producción. Sale con
código 1 si alguna cifra no cuadra.
"""

import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from web import server as S  # noqa: E402

CLAVE = "Auditoria1234!"
AHORA = "2026-08-24 09:00:00"

fallos = []


def comprueba(etiqueta, condicion, detalle=""):
    print(f"  {'OK ' if condicion else 'MAL'}  {etiqueta}"
          f"{('  ·  ' + str(detalle)[:100]) if detalle else ''}")
    if not condicion:
        fallos.append(etiqueta)


def main():
    tmp = tempfile.TemporaryDirectory()
    db = Path(tmp.name) / "contraste.sqlite"
    S.ensure_tables(db)
    conn = S.open_sqlite_conn(str(db), with_row_factory=True)
    for fn in ("ensure_workspace_core_tables", "ensure_workspace_product_tables",
               "ensure_anuncio_schema"):
        try:
            getattr(S, fn)(conn)
        except Exception:
            pass
    ws = conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
    b = dict(created_at=AHORA, updated_at=AHORA)

    def ins(tb, d):
        cols = {c[1] for c in conn.execute(f"pragma table_info({tb})")}
        d = {k: v for k, v in d.items() if k in cols}
        conn.execute(f"INSERT OR REPLACE INTO {tb} ({','.join(d)}) "
                     f"VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        conn.commit()

    def fresco(sql, args=()):
        c = S.open_sqlite_conn(str(db), with_row_factory=True)
        try:
            return [dict(x) for x in c.execute(sql, args).fetchall()]
        finally:
            c.close()

    ins("empresas", dict(id="emp1", nombre="Grupo Modernia", nif="B29123456", activo=1,
                         administra_fincas=1, **b))
    ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **b))
    ins("usuarios", dict(id="u1", nombre="Ana Auditora", usuario="ana", email="a@x.test",
                         rol="Administrador", servicio="Todos", activo=1,
                         password_hash=S.hash_password(CLAVE), **b))
    ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="u1",
                                   rol="Owner", **b))

    # --- conciliación: los cuatro estados que importan -------------------------------
    ins("gestoria_cuentas_bancarias", dict(id="cb1", empresa_id="emp1",
                                           banco_nombre="Banco Ejemplo",
                                           iban="ES9121000418450200051332", **b))
    ins("gestoria_asientos", dict(id="asi1", empresa_id="emp1", fecha="2026-08-10",
                                  concepto="Factura 2026/001", referencia="A-001",
                                  total_debe=1210.0, total_haber=1210.0, **b))
    MOVS = [
        ("mv1", "Transferencia ACME", 1210.0, 1, "auto", 92.0),
        ("mv2", "Compra Apple.com", -9.99, 1, "pendiente", 0.0),
        ("mv3", "Recibo luz", -84.30, 0, "", 0.0),
        ("mv4", "Cuota gestoría", -150.0, 1, "auto", 40.0),
    ]
    for mid, concepto, importe, punteado, estado, conf in MOVS:
        ins("gestoria_movimientos_bancarios", dict(
            id=mid, empresa_id="emp1", cuenta_bancaria_id="cb1",
            fecha_operacion="2026-08-10", concepto=concepto, importe=importe,
            punteado=punteado, asiento_id="asi1" if punteado else None,
            conciliacion_estado=estado or None, conciliacion_confianza=conf, **b))

    # --- contabilidad de gestoría: importes con decimales de verdad -------------------
    APUNTES = [("Minuta agosto", 2450.75), ("Tasa", 100.0), ("Suplido registro", 1234.56)]
    for i, (concepto, importe) in enumerate(APUNTES, start=1):
        ins("gestoria_contabilidad", dict(id=f"gc{i}", empresa_id="emp1",
                                          fecha="2026-08-10", concepto=concepto,
                                          tipo="Gasto", importe=importe, **b))

    S.Handler.db_path = str(db)
    httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    puerto = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    cookie = {"v": None}

    def pide(ruta, cuerpo=None, **params):
        url = f"http://127.0.0.1:{puerto}{ruta}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        rq = urllib.request.Request(
            url, data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
            headers={"Content-Type": "application/json"},
            method="POST" if cuerpo is not None else "GET")
        if cookie["v"]:
            rq.add_header("Cookie", cookie["v"])
        try:
            with urllib.request.urlopen(rq, timeout=60) as r:
                crudo = r.read()
                try:
                    return r.status, json.loads(crudo or b"{}"), r.headers
                except Exception:
                    return r.status, crudo, r.headers
        except urllib.error.HTTPError as e:
            crudo = e.read()
            try:
                return e.code, json.loads(crudo or b"{}"), e.headers
            except Exception:
                return e.code, crudo, e.headers

    _, _, cab = pide("/api/login", {"usuario": "ana", "password": CLAVE})
    cookie["v"] = cab.get("Set-Cookie").split(";")[0]

    # ------------------------------------------------- 1. los movimientos bancarios
    print("\n=== 1. Movimientos bancarios: la pantalla necesita los tres campos")
    _, r, _ = pide("/api/gestoria_movimientos_bancarios", None, empresa_id="emp1")
    filas = {f["id"]: f for f in (r.get("rows") or [])} if isinstance(r, dict) else {}
    comprueba("llegan los cuatro movimientos", len(filas) == 4, f"{len(filas)}")
    for mid, concepto, importe, punteado, estado, conf in MOVS:
        f = filas.get(mid) or {}
        bien = (abs(float(f.get("importe") or 0) - importe) < 0.01
                and int(f.get("punteado") or 0) == punteado
                and str(f.get("conciliacion_estado") or "") == estado
                and abs(float(f.get("conciliacion_confianza") or 0) - conf) < 0.01)
        comprueba(f"  {concepto}: {importe:,.2f} € · punteado={punteado} · {estado or '—'} · {conf:.0f} %",
                  bien, {k: f.get(k) for k in ("importe", "punteado", "conciliacion_estado",
                                               "conciliacion_confianza")})
    # Lo que la pantalla tiene que poder distinguir, con los datos que recibe.
    por_revisar = [f for f in filas.values()
                   if int(f.get("punteado") or 0) == 1
                   and (str(f.get("conciliacion_estado") or "") == "pendiente"
                        or float(f.get("conciliacion_confianza") or 0) < 55)]
    comprueba("se pueden distinguir los que hay que revisar", len(por_revisar) == 2,
              f"{len(por_revisar)} de 4: el de confianza 0 y el del 40 %")

    # ------------------------------------------ 2. la contabilidad y lo que suma
    print("\n=== 2. Contabilidad de gestoría: los importes y su suma")
    _, r, _ = pide("/api/gestoria_contabilidad", None, empresa_id="emp1")
    filas = (r.get("rows") or []) if isinstance(r, dict) else []
    comprueba("llegan los tres apuntes", len(filas) == 3, f"{len(filas)}")
    for concepto, importe in APUNTES:
        f = next((x for x in filas if str(x.get("concepto")) == concepto), {})
        comprueba(f"  {concepto}: {importe:,.2f} €",
                  abs(float(f.get("importe") or 0) - importe) < 0.01, f.get("importe"))
    suma_api = round(sum(float(f.get("importe") or 0) for f in filas), 2)
    suma_db = round(fresco("SELECT COALESCE(SUM(importe),0) AS s "
                           "FROM gestoria_contabilidad")[0]["s"], 2)
    comprueba(f"la suma cuadra con la base: {suma_db:,.2f} €",
              abs(suma_api - suma_db) < 0.01 and abs(suma_db - 3785.31) < 0.01,
              f"API {suma_api} · base {suma_db}")
    # Y que los importes lleguen como número, no como texto: es lo que rompía la suma.
    tipos = {type(f.get("importe")).__name__ for f in filas}
    comprueba("y llegan como número, no como texto", tipos <= {"int", "float"}, tipos)

    print(f"\n{'=' * 68}")
    print(f"{len(fallos)} cifras que no cuadran")
    for f in fallos:
        print("   MAL ·", f)
    httpd.shutdown()
    tmp.cleanup()
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
