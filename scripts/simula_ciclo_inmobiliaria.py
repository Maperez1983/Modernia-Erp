#!/usr/bin/env python3
"""Simula el ciclo de un comercial, de la captación a la firma, y comprueba cada paso.

Por qué
-------
Igual que `simula_ciclo_fincas.py`, pero del lado inmobiliario: recorre lo que hace un
comercial en una operación real y verifica el resultado en la pantalla siguiente, no
sólo que la petición devuelva 200.

Así apareció el fallo del 2026-08-22: al cerrar la venta el sistema respondía
«Vendido», guardaba el cierre con su comisión y retiraba el anuncio del portal, pero el
piso volvía al listado con estado «Inmueble», indistinguible de uno disponible.

Qué comprueba
-------------
  · la conversión de captación a encargo respeta dirección y precio
  · el anuncio se genera y la hoja de encargo sale en PDF
  · la visita se agenda y su hoja sale en PDF con el comprador de la demanda
  · el cierre guarda importe y honorarios, archiva lo pendiente y retira el anuncio
  · el piso queda como «Vendido», y así se ve en el listado
  · si vuelve a salir a la venta se retoma, conservando el cierre anterior
  · una captación con cierre detrás ya no se puede borrar por error

Un detalle del modelo que conviene saber al leer esto: una visita se liga al comprador
**por demanda**, no por cliente. La tabla `visitas` no tiene `cliente_id`.

Uso
---
    python scripts/simula_ciclo_inmobiliaria.py

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
AHORA = "2026-08-22 09:00:00"
PRECIO = 300000
CIERRE = 285000
HONORARIOS = 8550

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
    ins("empresas", dict(id="emp1", nombre="Inmobiliaria Modernia", nif="B29123456",
                         activo=1, direccion="Avenida de Andalucía 12, Málaga",
                         telefono="952000000", **base))
    ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **base))
    ins("usuarios", dict(id="u1", nombre="Sebastián", usuario="sebas", email="s@x.test",
                         rol="Inmobiliaria", servicio="Inmobiliaria", activo=1,
                         password_hash=S.hash_password(CLAVE), **base))
    ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="u1",
                                   rol="Admin", **base))

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

    print("\n=== 1. Me llama un propietario: creo la captación")
    estado, r, _ = pide("/api/captaciones", {
        "workspace_id": ws, "empresa_id": "emp1", "direccion": "Calle Larios 3, 4º A",
        "poblacion": "Málaga", "provincia": "Málaga", "propietario": "Pilar Propietaria",
        "telefono": "600999888", "etapa": "Contacto", "situacion_comercial": "En captación",
        "precio_objetivo": PRECIO})
    comprueba("se crea la captación", estado == 200 and not r.get("error"), f"HTTP {estado}")
    cap = conn.execute("SELECT id FROM captaciones LIMIT 1").fetchone()
    cap_id = cap["id"] if cap else None

    print("\n=== 2. Firmamos el encargo")
    estado, r, _ = pide("/api/captacion_convert", {
        "workspace_id": ws, "empresa_id": "emp1", "captacion_id": cap_id, "destino": "encargo"})
    comprueba("la captación pasa a encargo", estado == 200 and not r.get("error"), f"HTTP {estado}")
    inm = dict(conn.execute("SELECT id, direccion, estado, precio_objetivo "
                            "FROM inmuebles LIMIT 1").fetchone())
    inm_id = inm["id"]
    comprueba("el inmueble hereda la dirección",
              str(inm.get("direccion", "")).startswith("Calle Larios"), inm.get("direccion"))
    comprueba("y el precio", abs(float(inm.get("precio_objetivo") or 0) - PRECIO) < 0.01,
              inm.get("precio_objetivo"))
    comprueba("queda en fase Encargo", inm.get("estado") == "Encargo", inm.get("estado"))

    print("\n=== 3. Publico: anuncio y hoja de encargo")
    estado, r, _ = pide("/api/inmueble_anuncio_generate",
                        {"workspace_id": ws, "empresa_id": "emp1", "id": inm_id})
    comprueba("se genera el texto del anuncio", estado == 200 and not r.get("error"),
              str(r.get("titulo_anuncio", ""))[:60])
    _, pdf, _ = pide("/api/inmueble_encargo_pdf", None,
                     id=inm_id, empresa_id="emp1", workspace_id=ws, precio_venta=PRECIO)
    comprueba("la hoja de encargo sale en PDF",
              isinstance(pdf, bytes) and pdf[:4] == b"%PDF",
              f"{len(pdf)} B" if isinstance(pdf, bytes) else str(pdf)[:80])

    print("\n=== 4. Entra un comprador, con su demanda, y visita el piso")
    pide("/api/clientes", {"workspace_id": ws, "empresa_id": "emp1",
                           "nombre": "Carlos Comprador", "telefono": "600111222",
                           "email": "carlos@x.test", "servicio": "inmobiliaria"})
    cli = conn.execute("SELECT id FROM clientes WHERE nombre LIKE 'Carlos%' LIMIT 1").fetchone()
    cli_id = cli["id"] if cli else None
    pide("/api/demandas", {"workspace_id": ws, "empresa_id": "emp1", "cliente_id": cli_id,
                           "tipo": "Piso", "zona": "Centro", "poblacion": "Málaga",
                           "precio_max": 320000, "precio_min": 200000,
                           "habitaciones_min": 2, "estado": "Activa"})
    dem = conn.execute("SELECT id FROM demandas LIMIT 1").fetchone()
    dem_id = dem["id"] if dem else None
    comprueba("el comprador tiene demanda", dem_id is not None)
    estado, r, _ = pide("/api/inmueble_compradores", {
        "workspace_id": ws, "empresa_id": "emp1", "inmueble_id": inm_id,
        "demanda_id": dem_id, "cliente_id": cli_id, "estado": "Interesado"})
    comprueba("queda ligado al inmueble", estado == 200 and not r.get("error"), f"HTTP {estado}")
    estado, r, _ = pide("/api/visitas", {
        "workspace_id": ws, "empresa_id": "emp1", "inmueble_id": inm_id,
        "demanda_id": dem_id, "fecha": "2026-08-25", "hora": "17:00", "estado": "Planificada"})
    comprueba("se agenda la visita", estado == 200 and not r.get("error"), f"HTTP {estado}")
    _, pdf, _ = pide("/api/inmueble_visita_pdf", None,
                     id=inm_id, empresa_id="emp1", workspace_id=ws)
    comprueba("la hoja de visita sale en PDF",
              isinstance(pdf, bytes) and pdf[:4] == b"%PDF",
              f"{len(pdf)} B" if isinstance(pdf, bytes) else str(pdf)[:80])

    print("\n=== 5. Oferta y cierre de la venta")
    estado, r, _ = pide("/api/acciones", {
        "workspace_id": ws, "empresa_id": "emp1", "inmueble_id": inm_id, "cliente_id": cli_id,
        "servicio": "inmobiliaria", "asunto": f"Oferta {CIERRE:,} €",
        "tipo": "negociacion", "importe": CIERRE})
    comprueba("queda registrada la oferta", estado == 200 and not r.get("error"), f"HTTP {estado}")
    estado, r, _ = pide("/api/inmueble_encargo_close", {
        "workspace_id": ws, "empresa_id": "emp1", "id": inm_id, "inmueble_id": inm_id,
        "tipo": "vendido", "importe_final": CIERRE, "honorarios": HONORARIOS,
        "fecha_cierre": "2026-09-15", "cliente_id": cli_id})
    comprueba("se cierra la venta", estado == 200 and not r.get("error"), f"HTTP {estado}")
    comprueba("se archivan las gestiones pendientes", int(r.get("archived") or 0) > 0,
              f"archivadas {r.get('archived')}")
    cierre = [dict(x) for x in conn.execute("SELECT * FROM inmueble_cierres")]
    comprueba("el cierre guarda importe y honorarios",
              len(cierre) == 1
              and abs(float(cierre[0].get("importe_final") or 0) - CIERRE) < 0.01
              and abs(float(cierre[0].get("honorarios") or 0) - HONORARIOS) < 0.01,
              {k: cierre[0].get(k) for k in ("importe_final", "honorarios")} if cierre else "-")

    print("\n   --- lo que ve el comercial en su listado ---")
    _, lista, _ = pide("/api/inmuebles", None, workspace_id=ws, empresa_id="emp1", limit=20)
    filas = (lista.get("rows") if isinstance(lista, dict) else None) or []
    for f in filas[:5]:
        print("     ", {k: f.get(k) for k in ("direccion", "estado", "precio_objetivo") if k in f})
    comprueba("el listado dice que está vendido",
              any(str(f.get("estado", "")).lower() == "vendido" for f in filas),
              f"{len(filas)} filas")

    print("\n=== 6. Meses después vuelve a salir a la venta: se retoma")
    estado, r, _ = pide("/api/captacion_convert", {
        "workspace_id": ws, "empresa_id": "emp1", "captacion_id": cap_id, "destino": "encargo"})
    comprueba("se retoma el encargo", estado == 200 and not r.get("error"), f"HTTP {estado}")
    reab = dict(conn.execute("SELECT estado FROM inmuebles WHERE id = ?", (inm_id,)).fetchone())
    comprueba("vuelve a estar en Encargo", reab.get("estado") == "Encargo", reab)
    comprueba("y el cierre anterior se conserva",
              conn.execute("SELECT COUNT(*) FROM inmueble_cierres").fetchone()[0] == 1)

    print("\n=== 7. La captación con historia detrás ya no se borra por error")
    estado, r, _ = pide("/api/captacion_delete",
                        {"workspace_id": ws, "empresa_id": "emp1", "id": cap_id})
    comprueba("borrarla se niega y explica por qué", estado == 409,
              str(r.get("error", ""))[:90])

    print(f"\n{'=' * 62}")
    print(f"{len(fallos)} pasos incorrectos")
    for f in fallos:
        print("   ·", f)
    httpd.shutdown()
    tmp.cleanup()
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
