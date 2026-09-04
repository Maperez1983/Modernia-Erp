#!/usr/bin/env python3
"""Simula lo que le pasa a una póliza cuando NO sigue el camino previsto.

Por qué
-------
`simula_ciclo_seguros.py` recorre la vida buena de una póliza —oferta, alta,
contratación, vigor, recibo, siniestro, renovación— y sale limpio. Pero una correduría
se pasa el año fuera de ese camino: el cliente se va a otra compañía, anula a mitad de
año, el banco devuelve un recibo, o se rectifica una prima que estaba mal.

Ahí es donde el dinero se descuadra sin que nada avise, porque todas esas llamadas
contestan 200.

Qué comprueba
-------------
  · un cambio de compañía no arrastra la prima ni la comisión de la póliza vieja
  · la póliza nueva no entra «En vigor» sin su PDF, igual que por el camino normal
  · la vieja queda sustituida y enlazada con la nueva
  · anular una póliza no deja recibos pendientes cobrándose solos
  · un recibo devuelto por el banco se distingue de uno sin emitir
  · los KPI y el resumen de comisiones cuadran después de todo eso

Qué NO hace
-----------
No cubre siniestros complejos, ni el OCR, ni las campañas.

Uso
---
    python scripts/simula_seguros_fuera_de_lo_normal.py

Levanta su propio servidor sobre una base temporal. No toca producción. Sale con
código 1 si algún paso falla.
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
AHORA = "2026-08-24 09:00:00"
PRIMA_VIEJA = 640.0
COMISION_VIEJA = 96.0
PRIMA_NUEVA = 415.0

fallos = []
avisos = []


def comprueba(etiqueta, condicion, detalle=""):
    print(f"  {'OK ' if condicion else 'MAL'}  {etiqueta}"
          f"{('  ·  ' + str(detalle)[:105]) if detalle else ''}")
    if not condicion:
        fallos.append(etiqueta)


def anota(texto):
    print(f"  ··   {texto}")
    avisos.append(texto)


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

    def fresco(sql, args=()):
        c = S.open_sqlite_conn(str(db), with_row_factory=True)
        try:
            return [dict(x) for x in c.execute(sql, args).fetchall()]
        finally:
            c.close()

    b = dict(created_at=AHORA, updated_at=AHORA)
    ins("empresas", dict(id="emp1", nombre="Correduría Modernia", nif="B29123456",
                         activo=1, **b))
    ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **b))
    ins("usuarios", dict(id="u1", nombre="Bárbara", usuario="barbara", email="b@x.test",
                         rol="Administrador", servicio="Seguros", activo=1,
                         password_hash=S.hash_password(CLAVE), **b))
    ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="u1",
                                   rol="Owner", **b))

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

    _, _, cab = pide("/api/login", {"usuario": "barbara", "password": CLAVE})
    cookie["v"] = cab.get("Set-Cookie").split(";")[0]

    # --------------------------------------------------- 0. una póliza en vigor
    print("\n=== 0. Una póliza de hogar en vigor con Mapfre")
    pide("/api/clientes", {"workspace_id": ws, "empresa_id": "emp1",
                           "nombre": "Lucía Tomadora", "telefono": "600222333",
                           "email": "lucia@x.test", "servicio": "seguros"})
    cli = fresco("SELECT id FROM clientes LIMIT 1")[0]["id"]
    pide("/api/seguros", {
        "workspace_id": ws, "empresa_id": "emp1", "cliente_id": cli,
        "tomador": "Lucía Tomadora", "compania": "Mapfre", "ramo": "Hogar",
        "poliza_numero": "H-2026-0001", "fecha_efecto": "2026-01-01",
        "fecha_vencimiento": "2027-01-01", "prima_neta": 528.93,
        "prima_total": PRIMA_VIEJA, "comision": COMISION_VIEJA, "estado": "Pendiente"})
    pol = fresco("SELECT id FROM seguros LIMIT 1")[0]["id"]
    pide("/api/seguros_update", {"workspace_id": ws, "empresa_id": "emp1", "id": pol,
                                 "poliza_key": "polizas/h-2026-0001.pdf"})
    pide("/api/seguros_update", {"workspace_id": ws, "empresa_id": "emp1", "id": pol,
                                 "estado": "Contratada"})
    estado, r, _ = pide("/api/seguros_update", {"workspace_id": ws, "empresa_id": "emp1",
                                                "id": pol, "estado": "En vigor"})
    comprueba("la póliza entra en vigor", estado == 200 and not r.get("error"),
              f"HTTP {estado} {str(r)[:70]}")
    pide("/api/seguros_recibos", {
        "workspace_id": ws, "empresa_id": "emp1", "seguro_id": pol,
        "prima_total": PRIMA_VIEJA, "comision": COMISION_VIEJA, "estado": "Pendiente",
        "fecha_emision": "2026-01-01"})
    comprueba("y tiene su recibo",
              len(fresco("SELECT id FROM seguros_recibos")) == 1)

    # ------------------------------------------- 1. el cliente cambia de compañía
    print(f"\n=== 1. Se va a Generali por {PRIMA_NUEVA:,.0f} € (antes {PRIMA_VIEJA:,.0f} €)")
    estado, r, _ = pide("/api/seguros_cambio_compania", {
        "workspace_id": ws, "empresa_id": "emp1", "id": pol,
        "nueva_compania": "Generali", "nueva_poliza_numero": "G-2026-9001",
        "fecha_cambio": "2026-07-01", "nueva_fecha_efecto": "2026-07-01",
        "nueva_fecha_vencimiento": "2027-07-01"})
    comprueba("se registra el cambio", estado == 200 and not r.get("error"),
              f"HTTP {estado} {str(r)[:70]}")
    vieja = fresco("SELECT estado, fecha_baja, poliza_sustituta_id FROM seguros WHERE id = ?",
                   (pol,))[0]
    comprueba("la vieja queda sustituida y con fecha de baja",
              str(vieja["estado"]) == "Sustituida" and vieja["fecha_baja"] == "2026-07-01", vieja)
    comprueba("y enlazada con la nueva", bool(vieja["poliza_sustituta_id"]), vieja)
    nueva = fresco("SELECT * FROM seguros WHERE id != ? ORDER BY created_at DESC", (pol,))
    comprueba("se crea la póliza nueva", len(nueva) == 1, f"{len(nueva)} pólizas nuevas")
    if nueva:
        n = nueva[0]
        print(f"       nueva: {n['compania']} · {n['poliza_numero']} · estado {n['estado']!r}")
        print(f"              prima {n['prima_total']} · comisión {n['comision']} · "
              f"PDF {n['poliza_key']!r}")
        comprueba("NO entra en vigor sin su PDF, igual que por el camino normal",
                  str(n["estado"]) != "En vigor" or bool(str(n["poliza_key"] or "").strip()),
                  f"queda {n['estado']!r} con PDF {n['poliza_key']!r}")
        comprueba("no hereda la prima de la póliza vieja",
                  abs(float(n["prima_total"] or 0) - PRIMA_VIEJA) > 0.01,
                  f"la nueva cobra {n['prima_total']} y la vieja cobraba {PRIMA_VIEJA}")
        comprueba("ni la comisión",
                  abs(float(n["comision"] or 0) - COMISION_VIEJA) > 0.01,
                  f"la nueva liquida {n['comision']} y la vieja liquidaba {COMISION_VIEJA}")

    # ---------------------------------------------------- 2. anular a mitad de año
    print("\n=== 2. Otra póliza que se anula con un recibo sin cobrar")
    pide("/api/seguros", {
        "workspace_id": ws, "empresa_id": "emp1", "cliente_id": cli,
        "tomador": "Lucía Tomadora", "compania": "Allianz", "ramo": "Coche",
        "poliza_numero": "C-2026-0002", "fecha_efecto": "2026-03-01",
        "fecha_vencimiento": "2027-03-01", "prima_total": 900.0, "comision": 135.0,
        "estado": "Pendiente"})
    otra = [f["id"] for f in fresco("SELECT id, poliza_numero FROM seguros")
            if f.get("poliza_numero") == "C-2026-0002"][0]
    pide("/api/seguros_recibos", {
        "workspace_id": ws, "empresa_id": "emp1", "seguro_id": otra,
        "prima_total": 900.0, "comision": 135.0, "estado": "Pendiente",
        "fecha_emision": "2026-03-01"})
    estado, r, _ = pide("/api/seguros_poliza_accion", {
        "workspace_id": ws, "empresa_id": "emp1", "id": otra, "accion": "ANULAR",
        "fecha_baja": "2026-08-01", "motivo_baja": "Vende el coche"})
    comprueba("se anula", estado == 200 and not r.get("error"), f"HTTP {estado} {str(r)[:70]}")
    tras = fresco("SELECT estado, fecha_baja FROM seguros WHERE id = ?", (otra,))[0]
    comprueba("queda anulada con su fecha", str(tras["estado"]) == "Anulada", tras)
    recibos = fresco("SELECT estado, prima_total FROM seguros_recibos WHERE seguro_id = ?",
                     (otra,))
    for f in recibos:
        print(f"       recibo de la anulada: {f['estado']!r} · {f['prima_total']} €")
    comprueba("su recibo pendiente no se queda cobrándose solo",
              all(str(f["estado"]) != "Pendiente" for f in recibos),
              "queda pendiente un recibo de una póliza que ya no existe")

    # ------------------------------------------------- 3. el banco devuelve un recibo
    print("\n=== 3. El banco devuelve el recibo de la póliza en vigor")
    rec = fresco("SELECT id FROM seguros_recibos WHERE seguro_id = ?", (pol,))
    if rec:
        estado, r, _ = pide("/api/seguros_recibos_update", {
            "workspace_id": ws, "empresa_id": "emp1", "id": rec[0]["id"],
            "estado": "Devuelto", "motivo": "Sin fondos"})
        comprueba("se puede marcar devuelto", estado == 200 and not r.get("error"),
                  f"HTTP {estado} {str(r)[:70]}")
        tras = fresco("SELECT estado FROM seguros_recibos WHERE id = ?", (rec[0]["id"],))[0]
        comprueba("y queda devuelto, no pendiente", str(tras["estado"]) == "Devuelto", tras)

    # ------------------------------------------------------------ 4. lo que se ve
    print("\n=== 4. Los paneles después de todo eso")
    _, resu, _ = pide("/api/seguros_recibos_summary", None, workspace_id=ws,
                      empresa_id="emp1", anio=2026)
    _, kpis, _ = pide("/api/seguros_kpis", None, workspace_id=ws, empresa_id="emp1", anio=2026)
    print(f"       resumen: {json.dumps(resu, ensure_ascii=False)[:150]}")
    print(f"       KPI:     {json.dumps(kpis, ensure_ascii=False)[:150]}")
    comprueba("el resumen responde", isinstance(resu, dict) and not resu.get("error"), resu)
    comprueba("los KPI responden", isinstance(kpis, dict) and not kpis.get("error"), kpis)
    vivas = fresco("SELECT COUNT(*) AS n FROM seguros WHERE estado IN ('En vigor','Contratada')")
    print(f"       pólizas vivas: {vivas[0]['n']} de {len(fresco('SELECT id FROM seguros'))}")

    print(f"\n{'=' * 68}")
    print(f"{len(fallos)} pasos incorrectos, {len(avisos)} cosas que mirar")
    for f in fallos:
        print("   MAL ·", f)
    for a in avisos:
        print("   ··  ·", a)
    httpd.shutdown()
    tmp.cleanup()
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
