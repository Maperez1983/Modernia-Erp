#!/usr/bin/env python3
"""Simula el mes completo de una comunidad y comprueba cada resultado con la calculadora.

Por qué
-------
Barrer endpoints buscando 500 dice si el servidor se cae, no si el CRM hace lo que
debe. Esto es lo segundo: un administrador de fincas dando de alta su comunidad,
metiendo el censo, aprobando el presupuesto, emitiendo los recibos, generando la
remesa y viendo quién le debe. Cada paso se verifica como lo verificaría él, mirando
el número que sale.

Así apareció el fallo del 2026-08-22: el día de emitir los recibos, los cuatro
vecinos figuraban como morosos. Ningún barrido de errores lo habría encontrado,
porque todas las respuestas eran 200.

Qué comprueba
-------------
  · el censo suma 100 % de coeficientes
  · las partidas del presupuesto suman lo aprobado
  · cada recibo es la cuota del mes por el coeficiente de su piso
  · los recibos suman exactamente la cuota mensual
  · el fichero SEPA es un pain.008 y su CtrlSum y NbOfTxs cuadran con los recibos
  · morosidad lista SOLO a quien de verdad debe

Qué NO hace
-----------
No mira la interfaz: comprueba la API y la base. Una pantalla puede enseñar mal un
dato correcto, y eso hay que verlo en el navegador.

Uso
---
    python scripts/simula_ciclo_fincas.py

Levanta su propio servidor sobre una base temporal. No toca producción: borra
DATABASE_URL antes de importar nada. Sale con código 1 si algún paso falla.
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

CLAVE = "Simulacion1234!"
AHORA = "2026-08-22 09:00:00"
CUOTA_MENSUAL = 1200.0
PRESUPUESTO = [("Gastos generales", 9600.0), ("Ascensor", 3000.0), ("Limpieza", 1800.0)]
CENSO = [("ANTONIO LOBATO", "1 A", 30.0), ("ANA PEREZ", "1 B", 25.0),
         ("CARMEN TORRES", "2 A", 25.0), ("MANUEL RUIZ", "2 B", 20.0)]

fallos = []


def comprueba(etiqueta, condicion, detalle=""):
    print(f"  {'OK ' if condicion else 'MAL'}  {etiqueta}"
          f"{('  ·  ' + str(detalle)[:110]) if detalle else ''}")
    if not condicion:
        fallos.append(etiqueta)


def main():
    tmp = tempfile.TemporaryDirectory()
    db = Path(tmp.name) / "simulacion.sqlite"
    S.ensure_tables(db)
    conn = S.open_sqlite_conn(str(db), with_row_factory=True)
    for fn in ("ensure_workspace_core_tables", "ensure_workspace_product_tables"):
        try:
            getattr(S, fn)(conn)
        except Exception:
            pass
    ws = conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]

    def ins(tabla, datos):
        cols = {c[1] for c in conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in cols}
        conn.execute(f"INSERT OR REPLACE INTO {tabla} ({','.join(d)}) "
                     f"VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        conn.commit()

    base = dict(created_at=AHORA, updated_at=AHORA)
    ins("empresas", dict(id="emp1", nombre="Administraciones Modernia", nif="B29123456",
                         activo=1, **base))
    ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **base))
    ins("usuarios", dict(id="u1", nombre="Ana", usuario="ana", email="a@x.test",
                         rol="Administrador", servicio="Fincas", activo=1,
                         password_hash=S.hash_password(CLAVE), **base))
    ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="u1",
                                   rol="Owner", **base))

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
            with urllib.request.urlopen(rq, timeout=90) as r:
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

    print("\n=== 1. Doy de alta la comunidad")
    estado, r, _ = pide("/api/workspace_fincas_comunidades", {
        "workspace_id": ws, "empresa_id": "emp1", "nombre": "C.P Los Naranjos",
        "cif": "H29123456", "direccion": "Avenida Europa 110, Málaga", "estado": "Activa",
        "num_vecinos": len(CENSO), "iban": "ES9121000418450200051332",
        "acreedor_sepa": "ES12ZZZH29123456"})
    comprueba("se crea la comunidad", estado == 200 and not r.get("error"), f"HTTP {estado}")
    fila = conn.execute("SELECT id FROM workspace_fincas_comunidades LIMIT 1").fetchone()
    com = fila["id"] if fila else None

    print("\n=== 2. Meto el censo con sus coeficientes")
    for i, (nombre, piso, coef) in enumerate(CENSO):
        pide("/api/workspace_fincas_vecinos", {
            "workspace_id": ws, "comunidad_id": com, "nombre": nombre, "piso": piso,
            "coeficiente": coef, "nif": f"2511111{i}A", "email": f"v{i}@x.test",
            "iban": "ES2321000418400000000001"})
    suma = conn.execute("SELECT COALESCE(SUM(coeficiente),0) FROM workspace_fincas_vecinos "
                        "WHERE comunidad_id = ?", (com,)).fetchone()[0]
    comprueba("los coeficientes suman 100 %", abs(suma - 100.0) < 0.001, f"suma={suma}")

    print(f"\n=== 3. Apruebo el presupuesto: {sum(i for _, i in PRESUPUESTO):,.0f} €")
    estado, r, _ = pide("/api/workspace_fincas_presupuesto_anual", {
        "workspace_id": ws, "comunidad_id": com, "ejercicio": 2026, "fondo_reserva_pct": 10.0,
        "partidas": [{"concepto": c, "importe": i} for c, i in PRESUPUESTO]})
    comprueba("se aprueba el presupuesto", estado == 200 and not r.get("error"), f"HTTP {estado}")
    total = conn.execute("SELECT COALESCE(SUM(importe),0) "
                         "FROM workspace_fincas_presupuesto_partidas").fetchone()[0]
    comprueba("las partidas suman lo aprobado",
              abs(total - sum(i for _, i in PRESUPUESTO)) < 0.01, f"suma={total}")

    print(f"\n=== 4. Emito los recibos del mes ({CUOTA_MENSUAL:,.0f} €)")
    estado, r, _ = pide("/api/workspace_fincas_recibos_emitir", {
        "workspace_id": ws, "comunidad_id": com, "periodo": "2026-08",
        "importe": CUOTA_MENSUAL, "concepto": "Cuota ordinaria agosto"})
    comprueba("se emiten los recibos", estado == 200 and not r.get("error"), f"HTTP {estado}")
    recibos = [dict(x) for x in conn.execute(
        "SELECT v.nombre, v.coeficiente, r.importe FROM workspace_fincas_recibos r "
        "JOIN workspace_fincas_vecinos v ON v.id = r.vecino_id "
        "WHERE r.periodo = '2026-08' ORDER BY v.piso")]
    comprueba("hay un recibo por propietario", len(recibos) == len(CENSO), f"{len(recibos)}")
    for f in recibos:
        esperado = round(CUOTA_MENSUAL * float(f["coeficiente"]) / 100.0, 2)
        comprueba(f"  {f['nombre']} ({f['coeficiente']} %) paga {esperado:.2f} €",
                  abs(float(f["importe"]) - esperado) < 0.01, f"cobrado {f['importe']}")
    comprueba("los recibos suman la cuota del mes",
              abs(sum(float(f["importe"]) for f in recibos) - CUOTA_MENSUAL) < 0.01)

    print("\n=== 5. Genero la remesa SEPA")
    estado, r, _ = pide("/api/workspace_fincas_remesa_generar",
                        {"workspace_id": ws, "comunidad_id": com, "periodo": "2026-08"})
    comprueba("se genera la remesa", estado == 200 and not r.get("error"), f"HTTP {estado}")
    rem = conn.execute("SELECT id, num_recibos FROM workspace_fincas_remesas LIMIT 1").fetchone()
    if rem:
        rem = dict(rem)
        comprueba("la remesa lleva todos los recibos",
                  int(rem.get("num_recibos") or 0) == len(CENSO), rem)
        _, xml, _ = pide("/api/workspace_fincas_remesa_sepa", None,
                         workspace_id=ws, id=rem["id"], comunidad_id=com)
        texto = xml.decode("utf-8", "replace") if isinstance(xml, bytes) else str(xml)
        comprueba("el fichero es un pain.008",
                  texto.lstrip().startswith("<?xml") and "pain.008" in texto, texto[:60])
        import re
        ctrl = re.search(r"<CtrlSum>([\d.]+)</CtrlSum>", texto)
        nb = re.search(r"<NbOfTxs>(\d+)</NbOfTxs>", texto)
        comprueba("el importe del fichero cuadra con los recibos",
                  ctrl is not None and abs(float(ctrl.group(1)) - CUOTA_MENSUAL) < 0.01,
                  ctrl.group(1) if ctrl else "sin CtrlSum")
        comprueba(f"el número de adeudos es {len(CENSO)}",
                  nb is not None and nb.group(1) == str(len(CENSO)),
                  nb.group(1) if nb else "sin NbOfTxs")
    else:
        comprueba("se ha creado la remesa", False, "no hay fila de remesa")

    print("\n=== 6. Uno devuelve el recibo: quién sale en morosidad")
    rid = conn.execute("SELECT r.id FROM workspace_fincas_recibos r "
                       "JOIN workspace_fincas_vecinos v ON v.id = r.vecino_id "
                       "WHERE v.piso = '2 B'").fetchone()
    pide("/api/workspace_fincas_recibo_estado",
         {"workspace_id": ws, "id": rid["id"], "estado": "Devuelto"})
    _, mor, _ = pide("/api/workspace_fincas_morosidad", None,
                     workspace_id=ws, comunidad_id=com)
    filas = mor.get("rows") or []
    for f in filas:
        print(f"      {f.get('nombre','?'):18s} deuda {f.get('deuda')}")
    comprueba("sólo figura moroso quien de verdad debe",
              len(filas) == 1 and "MANUEL" in str(filas[0].get("nombre", "")),
              f"{len(filas)} morosos el día de emitir")

    print(f"\n{'=' * 62}")
    print(f"{len(fallos)} pasos incorrectos")
    for f in fallos:
        print("   ·", f)
    httpd.shutdown()
    tmp.cleanup()
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
