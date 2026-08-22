#!/usr/bin/env python3
"""Los tres portales de cliente, de punta a punta: enlace, consentimiento y acciones.

Por qué
-------
Los portales son lo único del CRM que ve alguien de fuera. Se auditaron por separado,
pero no como el recorrido completo de un cliente: recibe un enlace, entra sin cuenta,
acepta, mira lo suyo y hace algo.

Qué comprueba
-------------
  · la agencia genera los tres enlaces (propietario, comprador, comunero)
  · antes de aceptar el consentimiento NO se enseña ningún dato
  · tras aceptar y firmar, cada uno ve lo suyo
  · **y sólo lo suyo**: el propietario no ve otro piso ni el teléfono del comprador,
    el comprador no ve el del propietario, el comunero no ve a su vecina
  · un token inventado no abre nada
  · el token de un portal no vale en otro
  · el comprador pide visita y la cita aparece en su portal y en la agenda de la agencia
  · un enlace revocado deja de funcionar y lo dice con claridad

Resultado a 2026-08-22: sin fallos.

Detalle del contrato público, por si despista: el portal del comprador identifica cada
inmueble **por su índice `i` en la lista**, no por id, para no exponer identificadores
internos. Las acciones viajan con `{token, i, ...}`.

Uso
---
    python scripts/simula_portales.py

Levanta su propio servidor sobre una base temporal. No toca producción. Sale con
código 1 si algún paso falla.
"""
import json, os, re, sys, tempfile, threading, urllib.error, urllib.parse, urllib.request
from pathlib import Path
os.environ["DATABASE_URL"] = ""; os.environ["POSTGRES_URL"] = ""
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from web import server as S
CLAVE = "Portal1234!"; AHORA = "2026-08-22 09:00:00"
tmp = tempfile.TemporaryDirectory(); db = os.path.join(tmp.name, "a.sqlite")
S.ensure_tables(db); conn = S.open_sqlite_conn(db, with_row_factory=True)
for fn in ("ensure_workspace_core_tables","ensure_workspace_product_tables",
           "ensure_demanda_portal_schema","ensure_portal_consentimientos_schema"):
    try: getattr(S, fn)(conn)
    except Exception: pass
ws = conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
def ins(t, d):
    cols = {c[1] for c in conn.execute(f"pragma table_info({t})")}
    d = {k: v for k, v in d.items() if k in cols}
    conn.execute(f"INSERT OR REPLACE INTO {t} ({','.join(d)}) VALUES ({','.join('?'*len(d))})", tuple(d.values())); conn.commit()
b = dict(created_at=AHORA, updated_at=AHORA)
ins("empresas", dict(id="emp1", nombre="Inmobiliaria Modernia", nif="B29123456", activo=1,
                     direccion="Avenida de Andalucía 12, Málaga", telefono="952000000",
                     email_rgpd="rgpd@modernia.test", **b))
ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **b))
ins("usuarios", dict(id="u1", nombre="Ana Asesora", usuario="ana", email="a@x.test",
                     rol="Administrador", servicio="Inmobiliaria,Fincas", activo=1,
                     password_hash=S.hash_password(CLAVE), **b))
ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="u1", rol="Owner", **b))
ins("clientes", dict(id="cliP", nombre="Pilar Propietaria", telefono="600999888",
                     email="pilar@x.test", empresa_id="emp1", workspace_id=ws, **b))
ins("clientes", dict(id="cliC", nombre="Carlos Comprador", telefono="600111222",
                     email="carlos@x.test", empresa_id="emp1", workspace_id=ws, **b))
for iid, dire, precio in (("inm1","Calle Larios 3, 4º A",285000),("inm2","Alameda 20",340000)):
    ins("inmuebles", dict(id=iid, workspace_id=ws, empresa_id="emp1", direccion=dire,
                          poblacion="Málaga", provincia="Málaga", estado="Encargo",
                          tipo_inmueble="Piso", tipo_operacion="venta", m2=95, habitaciones=3,
                          banos=2, precio_objetivo=precio, portal_publicado=1,
                          descripcion=f"Piso luminoso en {dire}", propietario_telefono="600999888", **b))
    ins("captaciones", dict(id=f"cap_{iid}", workspace_id=ws, empresa_id="emp1", inmueble_id=iid,
                            etapa="Encargo", situacion_comercial="Encargo",
                            propietario="Pilar Propietaria", **b))
ins("inmueble_propietarios", dict(id="ip1", empresa_id="emp1", workspace_id=ws, inmueble_id="inm1",
                                  cliente_id="cliP", nombre="Pilar Propietaria",
                                  telefono="600999888", email="pilar@x.test", porcentaje=100, **b))
ins("demandas", dict(id="dem1", empresa_id="emp1", workspace_id=ws, cliente_id="cliC",
                     tipo="Piso", tipologia="Piso", zona="Centro", poblacion="Málaga",
                     precio_max=350000, precio_min=150000, habitaciones_min=2,
                     estado="Activa", responsable="Ana Asesora", **b))
for n, iid in enumerate(("inm1","inm2")):
    ins("inmueble_compradores", dict(id=f"ic{n}", empresa_id="emp1", workspace_id=ws,
                                     inmueble_id=iid, demanda_id="dem1", cliente_id="cliC",
                                     estado="Interesado", **b))
ins("workspace_fincas_comunidades", dict(id="com1", workspace_id=ws, empresa_id="emp1",
                                         nombre="C.P Los Naranjos", cif="H29123456",
                                         direccion="Avenida Europa 110", estado="Activa",
                                         num_vecinos=2, cuota_mensual=1200, **b))
for vid, nom, piso, coef in (("v1","ANTONIO LOBATO","1 A",60.0), ("v2","ANA PEREZ","1 B",40.0)):
    ins("workspace_fincas_vecinos", dict(id=vid, workspace_id=ws, comunidad_id="com1", nombre=nom,
                                         piso=piso, coeficiente=coef, nif="25111111A",
                                         email=f"{vid}@x.test", telefono="600000010", **b))
for n, (per, est) in enumerate((("2026-06","Cobrado"),("2026-07","Cobrado"),("2026-08","Pendiente"))):
    for vid, coef in (("v1",60.0),("v2",40.0)):
        ins("workspace_fincas_recibos", dict(id=f"r{n}{vid}", workspace_id=ws, comunidad_id="com1",
            vecino_id=vid, periodo=per, concepto=f"Cuota {per}", importe=round(1200*coef/100,2),
            estado=est, fecha_emision=f"{per}-01", **b))
S.Handler.db_path = db
httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler); PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
ses = {"c": None}
def pide(ruta, cuerpo=None, cookie=True, **params):
    url = f"http://127.0.0.1:{PORT}{ruta}"
    if params: url += "?" + urllib.parse.urlencode(params)
    rq = urllib.request.Request(url, data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                headers={"Content-Type":"application/json"},
                                method="POST" if cuerpo is not None else "GET")
    if cookie and ses["c"]: rq.add_header("Cookie", ses["c"])
    try:
        with urllib.request.urlopen(rq, timeout=90) as r:
            crudo = r.read()
            try: return r.status, json.loads(crudo or b"{}"), r.headers
            except Exception: return r.status, crudo, r.headers
    except urllib.error.HTTPError as e:
        crudo = e.read()
        try: return e.code, json.loads(crudo or b"{}"), e.headers
        except Exception: return e.code, crudo, e.headers
def fresco_visitas():
    o = S.open_sqlite_conn(db, with_row_factory=True)
    return o.execute("SELECT COUNT(*) FROM visitas").fetchone()[0]

fallos = []
def comprueba(e, c, d=""):
    print(f"  {'OK ' if c else 'MAL'}  {e}{('  ·  ' + str(d)[:110]) if d else ''}")
    if not c: fallos.append(e)
_, _, cab = pide("/api/login", {"usuario":"ana","password":CLAVE})
ses["c"] = cab.get("Set-Cookie").split(";")[0]

print("\n=== La agencia genera los tres enlaces")
st, r1, _ = pide("/api/inmueble_portal_acceso", {"workspace_id": ws, "empresa_id": "emp1",
                 "inmueble_id": "inm1", "nombre": "Pilar Propietaria"})
comprueba("enlace del propietario", st == 200 and r1.get("enlace"), f"HTTP {st} {str(r1)[:80]}")
st, r2, _ = pide("/api/demanda_portal_acceso", {"workspace_id": ws, "empresa_id": "emp1",
                 "demanda_id": "dem1", "nombre": "Carlos Comprador"})
comprueba("enlace del comprador", st == 200 and r2.get("enlace"), f"HTTP {st} {str(r2)[:80]}")
st, r3, _ = pide("/api/workspace_fincas_portal_alta", {"workspace_id": ws, "comunidad_id": "com1",
                 "vecino_id": "v1"})
comprueba("enlace del comunero", st == 200 and not r3.get("error"), f"HTTP {st} {str(r3)[:90]}")
def token_de(d):
    m = re.search(r"token=([^&\"']+)", json.dumps(d, ensure_ascii=False))
    return m.group(1) if m else ""
TOK = {"propietario": token_de(r1), "comprador": token_de(r2), "comunero": token_de(r3)}
print("      tokens:", {k: (v[:10] + "…") if v else "(vacío)" for k, v in TOK.items()})

print("\n=== 1. El propietario abre su enlace (sin sesión, como un cliente)")
st, v, _ = pide("/api/portal_venta", None, cookie=False, token=TOK["propietario"])
comprueba("el portal responde con su inmueble", st == 200 and not v.get("error"),
          f"HTTP {st} {json.dumps(v, ensure_ascii=False)[:110]}")
comprueba("lo primero es el consentimiento, no los datos",
          v.get("estado") == "consentimiento_requerido", v.get("estado"))
tv0 = json.dumps(v, ensure_ascii=False)
comprueba("y antes de aceptar no se enseña nada del inmueble", "Larios" not in tv0, tv0[:110])

print("\n   Acepta la información y firma")
st, r, _ = pide("/api/portal_venta_consentimiento",
                {"token": TOK["propietario"], "nombre": "Pilar Propietaria", "nif": "25111111A",
                 "acepta_informacion": True, "acepta_comercial": False,
                 "firma": "data:image/png;base64,iVBORw0KGgo="}, cookie=False)
comprueba("se registra el consentimiento", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:90]}")
st, v, _ = pide("/api/portal_venta", None, cookie=False, token=TOK["propietario"])
tv = json.dumps(v, ensure_ascii=False)
comprueba("ahora sí ve la dirección de SU piso", "Larios" in tv, tv[:120])
comprueba("y no ve el piso de otro", "Alameda" not in tv, "aparece un inmueble ajeno")
comprueba("no se le enseña el teléfono del comprador", "600111222" not in tv, "hay datos de terceros")

print("\n=== 2. Un token inventado no abre nada")
st, r, _ = pide("/api/portal_venta", None, cookie=False, token="inventado-1234")
comprueba("con un token falso se niega", st != 200 or bool(r.get("error")), f"HTTP {st} {str(r)[:70]}")

print("\n=== 3. El token del comprador no vale en el portal del propietario")
st, r, _ = pide("/api/portal_venta", None, cookie=False, token=TOK["comprador"])
comprueba("no se cruzan los portales", st != 200 or bool(r.get("error")), f"HTTP {st} {str(r)[:70]}")

print("\n=== 4. El comprador abre el suyo y pide una visita")
st, c, _ = pide("/api/portal_busqueda", None, cookie=False, token=TOK["comprador"])
comprueba("el portal del comprador responde", st == 200 and not c.get("error"),
          f"HTTP {st} {json.dumps(c, ensure_ascii=False)[:110]}")
comprueba("también le pide consentimiento primero",
          c.get("estado") == "consentimiento_requerido", c.get("estado"))
st, r, _ = pide("/api/portal_busqueda_consentimiento",
                {"token": TOK["comprador"], "nombre": "Carlos Comprador", "nif": "25222222B",
                 "acepta_informacion": True, "acepta_comercial": True,
                 "firma": "data:image/png;base64,iVBORw0KGgo="}, cookie=False)
comprueba("acepta y firma", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:90]}")
st, c, _ = pide("/api/portal_busqueda", None, cookie=False, token=TOK["comprador"])
tc = json.dumps(c, ensure_ascii=False)
comprueba("ve los inmuebles que le encajan", "Larios" in tc or "Alameda" in tc, tc[:120])
comprueba("no se le enseña el teléfono del propietario", "600999888" not in tc, "hay datos de terceros")
listado = c.get("inmuebles") or c.get("seleccion") or c.get("items") or []
print("      lo que ve en su portal:")
for x in (listado if isinstance(listado, list) else [])[:2]:
    print("        ", json.dumps(x, ensure_ascii=False)[:300])
# El portal identifica el inmueble por su índice en la lista, no por id: así el
# payload público nunca expone identificadores internos.
indice = listado[0].get("i") if listado else 0
st, r, _ = pide("/api/portal_busqueda_visita",
                {"token": TOK["comprador"], "i": indice, "fecha": "2026-08-29",
                 "franja": "tarde", "comentario": "¿Puedo verlo el sábado?"}, cookie=False)
comprueba(f"puede pedir visita del inmueble que ve (i={indice})",
          st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:100]}")
st, c2, _ = pide("/api/portal_busqueda", None, cookie=False, token=TOK["comprador"])
lst2 = c2.get("inmuebles") or []
cita = (lst2[0].get("cita") if lst2 else None)
comprueba("la cita aparece en su portal", bool(cita), f"cita={cita}")
comprueba("y la agencia la ve en su agenda",
          fresco_visitas() >= 1, f"{fresco_visitas()} visitas en la base")

print("\n=== 5. El comunero ve sus recibos y sólo los suyos")
st, k, _ = pide("/api/workspace_fincas_portal_public", None, cookie=False, token=TOK["comunero"])
comprueba("el portal del comunero responde", st == 200 and not k.get("error"),
          f"HTTP {st} {json.dumps(k, ensure_ascii=False)[:110]}")
tk = json.dumps(k, ensure_ascii=False)
comprueba("ve su nombre", "ANTONIO" in tk.upper(), tk[:110])
comprueba("no ve a su vecina", "ANA PEREZ" not in tk.upper(), "salen datos de otro vecino")
comprueba("ve el importe de su recibo (720 €, el 60 %)", "720" in tk, tk[:150])

print("\n=== 6. Se revoca el enlace del propietario")
st, r, _ = pide("/api/inmueble_portal_acceso_revoke", {"workspace_id": ws, "empresa_id": "emp1",
                                                       "inmueble_id": "inm1"})
comprueba("se revoca", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:80]}")
st, r, _ = pide("/api/portal_venta", None, cookie=False, token=TOK["propietario"])
comprueba("el enlace revocado deja de funcionar", st != 200 or bool(r.get("error")),
          f"HTTP {st} {str(r)[:80]}")

print(f"\n{'='*62}\n{len(fallos)} pasos incorrectos")
for f in fallos: print("   ·", f)
httpd.shutdown(); tmp.cleanup()
sys.exit(1 if fallos else 0)
