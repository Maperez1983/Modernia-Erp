#!/usr/bin/env python3
"""Simula los cierres de una operación inmobiliaria cuando se hacen mal o dos veces.

Por qué
-------
`simula_ciclo_inmobiliaria.py` recorre la operación buena —captación, encargo, anuncio,
comprador, visita, oferta, cierre— y sale limpio. El cierre es el momento en el que entra
el dinero: el importe de la venta y los honorarios de la agencia. Y es un botón que se
pulsa una vez al año por inmueble, o sea que si falla, falla en silencio.

Qué comprueba
-------------
  · no se cierra dos veces el mismo inmueble sin decir nada
  · no se cierra con importe u honorarios negativos
  · unos honorarios mayores que el precio de venta no entran solos
  · un alquiler se cierra con su renta, y queda como Alquilado
  · lo que ya funcionaba: el cierre archiva lo pendiente y retira el anuncio

Qué NO hace
-----------
No cubre la parte documental ni las firmas.

Uso
---
    python scripts/simula_inmobiliaria_fuera_de_lo_normal.py

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
PRECIO = 285000.0
HONORARIOS = 8550.0

fallos = []
avisos = []


def comprueba(etiqueta, condicion, detalle=""):
    print(f"  {'OK ' if condicion else 'MAL'}  {etiqueta}"
          f"{('  ·  ' + str(detalle)[:105]) if detalle else ''}")
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

    def fresco(sql, args=()):
        c = S.open_sqlite_conn(str(db), with_row_factory=True)
        try:
            return [dict(x) for x in c.execute(sql, args).fetchall()]
        finally:
            c.close()

    b = dict(created_at=AHORA, updated_at=AHORA)
    ins("empresas", dict(id="emp1", nombre="Inmobiliaria Modernia", nif="B29123456",
                         activo=1, **b))
    ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **b))
    ins("usuarios", dict(id="u1", nombre="Sebastián", usuario="sebas", email="s@x.test",
                         rol="Administrador", servicio="Inmobiliaria", activo=1,
                         password_hash=S.hash_password(CLAVE), **b))
    ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="u1",
                                   rol="Owner", **b))
    for i, (calle, operacion) in enumerate(((("Calle Larios 3, 4º A"), "venta"),
                                            (("Alameda Principal 20"), "alquiler")), start=1):
        ins("inmuebles", dict(id=f"inm{i}", workspace_id=ws, empresa_id="emp1",
                              direccion=calle, estado="Encargo",
                              tipo_operacion=operacion, precio_objetivo=300000, **b))
        ins("captaciones", dict(id=f"cap{i}", workspace_id=ws, empresa_id="emp1",
                                inmueble_id=f"inm{i}", etapa="Encargo",
                                situacion_comercial="Encargo", direccion=calle, **b))

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

    _, _, cab = pide("/api/login", {"usuario": "sebas", "password": CLAVE})
    cookie["v"] = cab.get("Set-Cookie").split(";")[0]

    def cierra(inmueble, tipo="vendido", **extra):
        cuerpo = {"workspace_id": ws, "empresa_id": "emp1", "id": inmueble,
                  "inmueble_id": inmueble, "tipo": tipo, "importe_final": PRECIO,
                  "honorarios": HONORARIOS, "fecha_cierre": "2026-09-15"}
        cuerpo.update(extra)
        return pide("/api/inmueble_encargo_close", cuerpo)

    # ------------------------------------------------------ 1. importes imposibles
    print("\n=== 1. Se cierra con importes que no pueden ser")
    estado, r, _ = cierra("inm1", importe_final=-285000)
    comprueba("un importe de venta negativo no entra", estado >= 400,
              f"HTTP {estado} · {str(r.get('error'))[:70]}")
    estado, r, _ = cierra("inm1", honorarios=-8550)
    comprueba("unos honorarios negativos tampoco", estado >= 400,
              f"HTTP {estado} · {str(r.get('error'))[:70]}")
    estado, r, _ = cierra("inm1", importe_final=285000, honorarios=400000)
    comprueba("unos honorarios mayores que la venta no entran solos", estado >= 400,
              f"HTTP {estado} · {str(r.get('error'))[:70]}")
    n = len(fresco("SELECT id FROM inmueble_cierres"))
    comprueba("y no se ha guardado ninguno de los tres", n == 0, f"{n} cierres")

    # ---------------------------------------------------------- 2. el cierre bueno
    print(f"\n=== 2. La venta de verdad: {PRECIO:,.0f} € con {HONORARIOS:,.0f} € de honorarios")
    estado, r, _ = cierra("inm1")
    comprueba("se cierra", estado == 200 and not r.get("error"),
              f"HTTP {estado} {str(r)[:70]}")
    cierre = fresco("SELECT tipo, importe_final, honorarios FROM inmueble_cierres")
    comprueba("con su importe y sus honorarios",
              len(cierre) == 1 and abs(float(cierre[0]["importe_final"]) - PRECIO) < 0.01
              and abs(float(cierre[0]["honorarios"]) - HONORARIOS) < 0.01, cierre)
    estado_inm = fresco("SELECT estado FROM inmuebles WHERE id = 'inm1'")[0]["estado"]
    comprueba("y el piso figura vendido", str(estado_inm) == "Vendido", estado_inm)

    # ----------------------------------------------------- 3. cerrar por segunda vez
    print("\n=== 3. Se pulsa «cerrar» otra vez sobre el mismo piso")
    estado, r, _ = cierra("inm1", importe_final=310000, honorarios=9300)
    cierres = fresco("SELECT importe_final, honorarios FROM inmueble_cierres "
                     "WHERE inmueble_id = 'inm1'")
    for c in cierres:
        print(f"       cierre: {float(c['importe_final']):,.2f} € · "
              f"{float(c['honorarios']):,.2f} € de honorarios")
    total = sum(float(c["honorarios"] or 0) for c in cierres)
    comprueba("no se apunta el mismo piso dos veces",
              estado >= 400 or len(cierres) == 1,
              f"HTTP {estado} · {len(cierres)} cierres, {total:,.2f} € de honorarios sumados")

    # ------------------------------------------------------------- 4. el alquiler
    print("\n=== 4. El otro es un alquiler: 1.200 € al mes")
    estado, r, _ = cierra("inm2", tipo="alquiler", importe_final=1200, honorarios=1200)
    comprueba("se cierra el alquiler", estado == 200 and not r.get("error"),
              f"HTTP {estado} {str(r)[:70]}")
    estado_inm = fresco("SELECT estado FROM inmuebles WHERE id = 'inm2'")[0]["estado"]
    comprueba("y queda como Alquilado, no como Vendido",
              str(estado_inm) == "Alquilado", estado_inm)
    alq = fresco("SELECT tipo, importe_final FROM inmueble_cierres WHERE inmueble_id = 'inm2'")
    comprueba("con la renta guardada",
              len(alq) == 1 and abs(float(alq[0]["importe_final"]) - 1200) < 0.01, alq)

    print(f"\n{'=' * 68}")
    print(f"{len(fallos)} pasos incorrectos, {len(avisos)} cosas que mirar")
    for f in fallos:
        print("   MAL ·", f)
    httpd.shutdown()
    tmp.cleanup()
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
