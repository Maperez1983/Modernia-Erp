#!/usr/bin/env python3
"""Recorre TODOS los endpoints del CRM inmobiliario y marca los que revientan.

Por qué
-------
Revisar un endpoint leyendo su código es mucho más débil que ejecutarlo. En esta
misma auditoría, dos barridos por patrones no encontraron lo que buscaban —el fondo
de las tarjetas escondido dentro de la definición de una variable, y las paradas de
un degradado en hexadecimal— y sólo aparecieron al mirar la pantalla de verdad.

Este script levanta el servidor sobre una base sembrada y llama a los 66 endpoints
del módulo con datos plausibles. No juzga si la respuesta es *correcta*: juzga si el
servidor se cae. Un **500 es siempre un fallo**: significa que una excepción de
Python llegó al cliente. Un 400/403/404 puede ser la respuesta correcta a una
petición incompleta, y se informa aparte para revisarlo a ojo.

Qué NO hace
-----------
No sustituye a probar el módulo a mano. Comprueba que ningún camino revienta y que
los que deben denegar, deniegan. La calidad de lo que devuelven —si el cruce de
demandas acierta, si los honorarios cuadran— eso hay que mirarlo caso a caso.

Uso
---
    python scripts/auditoria_endpoints_inmo.py
    python scripts/auditoria_endpoints_inmo.py --verbose
"""

import argparse
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""

from web import server as S  # noqa: E402

AHORA = "2026-08-10 09:00:00"
CLAVE = "Auditoria1234!"


class Banco:
    """Una base sembrada con un expediente inmobiliario completo."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "auditoria.sqlite"
        S.ensure_tables(self.db)
        self.cx = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        self.ws = self.cx.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        self._sembrar()

    def cols(self, tabla):
        return [r[1] for r in self.cx.execute(f"pragma table_info({tabla})")]

    def ins(self, tabla, datos):
        validas = set(self.cols(tabla))
        d = {k: v for k, v in datos.items() if k in validas}
        hueco = ",".join("?" * len(d))
        try:
            self.cx.execute(f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({hueco})", tuple(d.values()))
            self.cx.commit()
        except Exception as exc:
            print(f"   (no se pudo sembrar {tabla}: {str(exc)[:70]})")

    def _sembrar(self):
        self.ins("empresas", {"id": "empPlat", "nombre": "Verifika2", "activo": 1,
                              "created_at": AHORA, "updated_at": AHORA})
        self.ins("empresas", {"id": "emp1", "nombre": "Grupo Modernia", "activo": 1,
                              "cif": "B29000001", "created_at": AHORA, "updated_at": AHORA})
        for i, eid in enumerate(("empPlat", "emp1")):
            self.ins("workspace_empresas", {"id": f"we{i}", "workspace_id": self.ws,
                                            "empresa_id": eid, "created_at": AHORA, "updated_at": AHORA})
        self.ins("usuarios", {"id": "u1", "nombre": "Auditora", "apellido": "Uno",
                              "usuario": "auditor", "email": "auditor@x.test",
                              "rol": "Administrador", "servicio": "Inmobiliaria", "activo": 1,
                              "password_hash": S.hash_password(CLAVE),
                              "created_at": AHORA, "updated_at": AHORA})
        self.ins("workspace_miembros", {"id": "wm1", "workspace_id": self.ws, "usuario_id": "u1",
                                        "rol": "Owner", "created_at": AHORA, "updated_at": AHORA})
        self.ins("clientes", {"id": "cli1", "empresa_id": "emp1", "workspace_id": self.ws,
                              "nombre": "Propietaria Uno", "nif": "11111111H",
                              "telefono": "600111222", "email": "prop@x.test",
                              "created_at": AHORA, "updated_at": AHORA})
        self.ins("clientes", {"id": "cli2", "empresa_id": "emp1", "workspace_id": self.ws,
                              "nombre": "Comprador Dos", "nif": "22222222J",
                              "telefono": "600333444", "email": "comp@x.test",
                              "created_at": AHORA, "updated_at": AHORA})
        self.ins("inmuebles", {"id": "inm1", "workspace_id": self.ws, "empresa_id": "emp1",
                               "referencia": "REF-001", "direccion": "Calle Goya 12",
                               "referencia_catastral": "3269702UF7636N0010OQ",
                               "codigo_postal": "29010", "poblacion": "Málaga",
                               "provincia": "Málaga", "zona": "Centro", "tipo_inmueble": "Piso",
                               "subtipologia": "ÁTICO", "m2": 95, "habitaciones": 3, "banos": 2,
                               "precio_objetivo": 250000, "precio_encargo": 260000,
                               "honorarios": 3.0, "estado": "Encargo", "tipo_operacion": "venta",
                               "portal_publicado": 1, "created_at": AHORA, "updated_at": AHORA})
        self.ins("inmueble_propietarios", {"id": "ip1", "inmueble_id": "inm1", "cliente_id": "cli1",
                                           "empresa_id": "emp1", "created_at": AHORA, "updated_at": AHORA})
        self.ins("captaciones", {"id": "cap1", "workspace_id": self.ws, "empresa_id": "emp1",
                                 "inmueble_id": "inm1", "direccion": "Calle Goya 12",
                                 "etapa": "Encargo", "noticia_verificada": 1,
                                 "necesidad_venta_alquiler": "Venta",
                                 "precio_objetivo": 250000, "created_at": AHORA, "updated_at": AHORA})
        self.ins("demandas", {"id": "dem1", "workspace_id": self.ws, "empresa_id": "emp1",
                              "cliente_id": "cli2", "tipo": "Piso", "zona": "Centro",
                              "fase": "Activa", "estado": "Activa", "presupuesto_max": 300000,
                              "created_at": AHORA, "updated_at": AHORA})
        self.ins("inmueble_compradores", {"id": "ic1", "empresa_id": "emp1", "inmueble_id": "inm1",
                                          "demanda_id": "dem1", "cliente_id": "cli2",
                                          "estado": "Pendiente", "created_at": AHORA, "updated_at": AHORA})
        self.ins("visitas", {"id": "vis1", "workspace_id": self.ws, "empresa_id": "emp1",
                             "inmueble_id": "inm1", "cliente_id": "cli2", "fecha": "2026-08-20",
                             "estado": "Realizada", "created_at": AHORA, "updated_at": AHORA})
        self.ins("acciones", {"id": "acc1", "workspace_id": self.ws, "empresa_id": "emp1",
                              "inmueble_id": "inm1", "servicio": "inmobiliaria",
                              "fecha": "2026-08-20", "hora": "10:00", "asunto": "Visita",
                              "tipo": "Visita", "estado": "Pendiente", "responsable": "auditor",
                              "created_at": AHORA, "updated_at": AHORA})
        self.ins("operaciones_inmobiliarias", {"id": "op1", "workspace_id": self.ws,
                                               "empresa_id": "emp1", "inmueble_id": "inm1",
                                               "direccion": "Calle Goya 12", "anio": 2026,
                                               "tipo_operacion": "compraventa",
                                               "precio_escritura": 245000,
                                               "created_at": AHORA, "updated_at": AHORA})

    def cerrar(self):
        self.cx.close()
        self.tmp.cleanup()


def arranca(banco):
    S.Handler.db_path = str(banco.db)
    httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, base


def peticion(base, ruta, cuerpo=None, cookie=None, metodo=None):
    url = base + ruta
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo or ("POST" if datos else "GET"))
    if datos:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()[:400]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:400]
    except Exception as exc:
        return 0, str(exc).encode()[:200]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    banco = Banco()
    httpd, base = arranca(banco)
    ws = banco.ws

    estado, cuerpo, = peticion(base, "/api/login", {"usuario": "auditor", "password": CLAVE})[0], None
    # La cookie hay que sacarla de la cabecera; se repite la llamada con urlopen directo.
    req = urllib.request.Request(base + "/api/login", data=json.dumps({"usuario": "auditor", "password": CLAVE}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        cookie = (r.headers.get("Set-Cookie") or "").split(";")[0]
    print(f"Login: {estado}\n")

    GETS = [
        ("/api/inmuebles", {"workspace_id": ws}),
        ("/api/inmueble", {"id": "inm1"}),
        ("/api/inmueble_timeline", {"inmueble_id": "inm1"}),
        ("/api/inmueble_matching", {"inmueble_id": "inm1"}),
        ("/api/inmueble_compradores", {"inmueble_id": "inm1"}),
        ("/api/inmueble_checklist", {"inmueble_id": "inm1"}),
        ("/api/inmueble_docs", {"inmueble_id": "inm1"}),
        ("/api/inmueble_ensure", {"direccion": "Calle Nueva 5", "workspace_id": ws}),
        ("/api/inmueble_expediente_docs", {"inmueble_id": "inm1", "empresa_nombre": "Grupo Modernia"}),
        ("/api/inmueble_signature_requests", {"inmueble_id": "inm1"}),
        ("/api/inmueble_signature_config", {}),
        ("/api/inmueble_encargo_pdf", {"inmueble_id": "inm1", "empresa_nombre": "Grupo Modernia"}),
        ("/api/inmueble_honorarios_pdf", {"inmueble_id": "inm1", "empresa_nombre": "Grupo Modernia"}),
        ("/api/inmueble_consumo_pdf", {"inmueble_id": "inm1", "empresa_nombre": "Grupo Modernia"}),
        ("/api/inmueble_negociacion_pdf", {"inmueble_id": "inm1", "empresa_nombre": "Grupo Modernia"}),
        ("/api/inmueble_visita_pdf", {"inmueble_id": "inm1", "empresa_nombre": "Grupo Modernia", "demanda_id": "dem1"}),
        ("/api/inmueble_visita_docs", {"inmueble_id": "inm1", "empresa_nombre": "Grupo Modernia", "demanda_id": "dem1"}),
        ("/api/inmueble_portal_feed", {"limit": "5"}),
        ("/api/portal_inmuebles", {"limit": "5"}),
        ("/api/portal_inmueble", {"id": "inm1"}),
        ("/api/portal_empresa_logo", {"id": "emp1"}),
        ("/api/portal_publish_preview", {"id": "inm1"}),
        ("/api/demandas", {"workspace_id": ws}),
        ("/api/visitas", {"workspace_id": ws}),
        ("/api/compraventas", {"workspace_id": ws}),
        ("/api/workspace_portal", {"workspace_id": ws}),
        ("/api/workspace_portal_requerimientos", {"workspace_id": ws}),
    ]

    POSTS = [
        ("/api/inmueble_update", {"id": "inm1", "workspace_id": ws, "zona": "Centro Alto"}),
        ("/api/inmueble_servicios_update", {"inmueble_id": "inm1", "workspace_id": ws, "servicios": ["inmobiliaria"]}),
        ("/api/inmueble_propietarios_update", {"inmueble_id": "inm1", "workspace_id": ws, "propietarios": ["cli1"]}),
        ("/api/inmueble_propietario_create", {"inmueble_id": "inm1", "nombre": "Propietario Nuevo", "nif": "33333333P"}),
        ("/api/inmueble_checklist_generate", {"inmueble_id": "inm1", "workspace_id": ws}),
        ("/api/inmueble_checklist_update", {"inmueble_id": "inm1", "workspace_id": ws, "etapa": "Captacion", "estado": "Hecho"}),
        ("/api/inmueble_compradores", {"inmueble_id": "inm1", "demanda_id": "dem1", "estado": "Pendiente"}),
        ("/api/inmueble_guided_prepare", {"inmueble_id": "inm1", "workspace_id": ws}),
        ("/api/inmueble_anuncio_generate", {"inmueble_id": "inm1", "empresa_nombre": "Grupo Modernia"}),
        ("/api/inmueble_archive_pending_actions", {"inmueble_id": "inm1", "workspace_id": ws}),
        ("/api/inmueble_renovar", {"inmueble_id": "inm1", "workspace_id": ws, "meses": 6}),
        ("/api/inmueble_catastro_sync", {"inmueble_id": "inm1", "workspace_id": ws}),
        ("/api/portal_publish_update", {"id": "inm1", "empresa_nombre": "Grupo Modernia", "publicado": 1}),
        ("/api/captaciones", {"workspace_id": ws, "direccion": "Calle Auditoria 1",
                              "propietario": "Nuevo Propietario", "propietario_nif": "44444444A"}),
        ("/api/captaciones_update", {"id": "cap1", "workspace_id": ws, "etapa": "Encargo"}),
        ("/api/captacion_update", {"id": "cap1", "workspace_id": ws, "zona": "Centro"}),
        ("/api/demandas", {"workspace_id": ws, "cliente_id": "cli2", "tipo": "Piso", "zona": "Centro"}),
        ("/api/demandas_update", {"id": "dem1", "workspace_id": ws, "fase": "En visita"}),
        ("/api/visitas", {"workspace_id": ws, "inmueble_id": "inm1", "cliente_id": "cli2",
                          "fecha": "2026-08-25", "estado": "Prevista"}),
        ("/api/compraventas", {"empresa_nombre": "Grupo Modernia", "direccion": "Calle Auditoria 9",
                               "precio_escritura": 200000, "propietario1_nombre": "Vendedor Test",
                               "propietario1_nif": "55555555K"}),
        ("/api/inmueble_signature_request", {"inmueble_id": "inm1", "empresa_nombre": "Grupo Modernia",
                                             "signer_nombre": "Firmante", "signer_email": "f@x.test",
                                             "doc_nombre": "encargo.pdf"}),
    ]

    resultados = {"ok": [], "rechazo": [], "roto": []}
    print("── GET ──")
    for ruta, params in GETS:
        qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
        estado, cuerpo = peticion(base, f"{ruta}?{qs}" if qs else ruta, cookie=cookie)
        destino = "roto" if estado >= 500 or estado == 0 else ("ok" if estado < 400 else "rechazo")
        resultados[destino].append((ruta, estado, cuerpo[:150]))
        if args.verbose or destino == "roto":
            print(f"   {estado:>3}  {ruta}")

    print("\n── POST ──")
    for ruta, cuerpo_json in POSTS:
        estado, cuerpo = peticion(base, ruta, cuerpo_json, cookie=cookie)
        destino = "roto" if estado >= 500 or estado == 0 else ("ok" if estado < 400 else "rechazo")
        resultados[destino].append((ruta, estado, cuerpo[:150]))
        if args.verbose or destino == "roto":
            print(f"   {estado:>3}  {ruta}")

    print(f"\n{'═' * 74}")
    print(f"correctos (2xx/3xx): {len(resultados['ok'])}")
    print(f"rechazos (4xx):      {len(resultados['rechazo'])}")
    print(f"ROTOS (5xx o caída): {len(resultados['roto'])}")
    if resultados["roto"]:
        print("\nLos que revientan:")
        for ruta, estado, cuerpo in resultados["roto"]:
            print(f"   {estado}  {ruta}")
            print(f"        {cuerpo.decode('utf-8', 'replace')[:150]}")
    if resultados["rechazo"]:
        print("\nRechazos, para mirarlos a ojo (pueden ser correctos):")
        for ruta, estado, cuerpo in resultados["rechazo"]:
            print(f"   {estado}  {ruta:<44} {cuerpo.decode('utf-8', 'replace')[:80]}")

    httpd.shutdown()
    banco.cerrar()
    return 1 if resultados["roto"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
