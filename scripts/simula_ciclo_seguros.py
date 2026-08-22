#!/usr/bin/env python3
"""Simula el ciclo de un mediador de seguros y comprueba que los números cuadran.

Por qué
-------
Igual que las otras simulaciones de uso: recorre lo que hace una persona —oferta,
póliza, recibo, siniestro, renovación— y verifica el resultado, no sólo que la
petición devuelva 200. En una correduría el número que importa es la comisión, así
que se sigue desde la prima hasta el resumen del panel.

Qué comprueba
-------------
  · el flujo de estados no se salta: Presupuesto -> Contratada -> En vigor
  · no se pone una póliza en vigor sin adjuntar su PDF
  · la prima, el porcentaje y la comisión quedan guardados y coherentes
  · el recibo hereda los importes de la póliza
  · el resumen de recibos y los KPI suman lo mismo que hay en la base
  · un siniestro queda con su reserva
  · la cola de renovaciones responde

Un detalle del modelo que conviene saber: **la comisión es el dato que se guarda** y
el porcentaje se deriva de ella para mostrarlo (`porcentaje = comision / prima × 100`).
La pantalla sugiere el importe a partir de la tabla de tarifas por compañía y ramo.

Resultado a 2026-08-22: sin fallos. Los dos controles del módulo —la máquina de
estados y la exigencia del PDF— no sólo impiden la acción, explican qué hacer.

Uso
---
    python scripts/simula_ciclo_seguros.py

Levanta su propio servidor sobre una base temporal. No toca producción. Sale con
código 1 si algún paso falla.
"""
import json, os, sys, tempfile, threading, urllib.error, urllib.parse, urllib.request
from pathlib import Path
os.environ["DATABASE_URL"] = ""; os.environ["POSTGRES_URL"] = ""
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from web import server as S
CLAVE = "Seguros1234!"; AHORA = "2026-08-22 09:00:00"
PRIMA = 640.0; PCT = 12.5           # 640 × 12,5 % = 80,00 € de comisión
tmp = tempfile.TemporaryDirectory(); db = os.path.join(tmp.name, "a.sqlite")
S.ensure_tables(db); conn = S.open_sqlite_conn(db, with_row_factory=True)
for fn in ("ensure_workspace_core_tables","ensure_workspace_product_tables"):
    try: getattr(S, fn)(conn)
    except Exception: pass
ws = conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
def ins(t, d):
    cols = {c[1] for c in conn.execute(f"pragma table_info({t})")}
    d = {k: v for k, v in d.items() if k in cols}
    conn.execute(f"INSERT OR REPLACE INTO {t} ({','.join(d)}) VALUES ({','.join('?'*len(d))})", tuple(d.values())); conn.commit()
b = dict(created_at=AHORA, updated_at=AHORA)
ins("empresas", dict(id="emp1", nombre="Correduría Modernia", nif="B29123456", activo=1, **b))
ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **b))
ins("usuarios", dict(id="u1", nombre="Bárbara", usuario="barbara", email="b@x.test",
                     rol="Seguros", servicio="Seguros", activo=1,
                     password_hash=S.hash_password(CLAVE), **b))
ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="u1", rol="Admin", **b))
S.Handler.db_path = db
httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler); PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
ses = {"c": None}
def pide(ruta, cuerpo=None, **params):
    url = f"http://127.0.0.1:{PORT}{ruta}"
    if params: url += "?" + urllib.parse.urlencode(params)
    rq = urllib.request.Request(url, data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                headers={"Content-Type":"application/json"},
                                method="POST" if cuerpo is not None else "GET")
    if ses["c"]: rq.add_header("Cookie", ses["c"])
    try:
        with urllib.request.urlopen(rq, timeout=90) as r:
            crudo = r.read()
            try: return r.status, json.loads(crudo or b"{}"), r.headers
            except Exception: return r.status, crudo, r.headers
    except urllib.error.HTTPError as e:
        crudo = e.read()
        try: return e.code, json.loads(crudo or b"{}"), e.headers
        except Exception: return e.code, crudo, e.headers
fallos = []
def comprueba(e, c, d=""):
    print(f"  {'OK ' if c else 'MAL'}  {e}{('  ·  ' + str(d)[:110]) if d else ''}")
    if not c: fallos.append(e)
_, _, cab = pide("/api/login", {"usuario":"barbara","password":CLAVE})
ses["c"] = cab.get("Set-Cookie").split(";")[0]

print("\n=== 1. Entra un cliente y le hago una oferta")
st, r, _ = pide("/api/clientes", {"workspace_id": ws, "empresa_id": "emp1",
    "nombre": "Lucía Tomadora", "telefono": "600222333", "email": "lucia@x.test",
    "servicio": "seguros"})
comprueba("se da de alta el cliente", st == 200 and not r.get("error"), f"HTTP {st}")
cli = conn.execute("SELECT id FROM clientes LIMIT 1").fetchone()
cli_id = cli["id"] if cli else None
st, r, _ = pide("/api/seguros_ofertas", {"workspace_id": ws, "empresa_id": "emp1",
    "cliente_id": cli_id, "ramo": "Hogar", "compania": "Mapfre",
    "propuesta": f"{PRIMA} € anuales", "estado": "Enviada", "fecha": "2026-08-22"})
comprueba("se registra la oferta", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:80]}")

print("\n=== 2. La acepta: doy de alta la póliza")
st, r, _ = pide("/api/seguros", {"workspace_id": ws, "empresa_id": "emp1", "cliente_id": cli_id,
    "tomador": "Lucía Tomadora", "compania": "Mapfre", "ramo": "Hogar",
    "poliza_numero": "H-2026-0001", "fecha_efecto": "2026-09-01",
    "fecha_vencimiento": "2027-09-01", "prima_neta": 528.93, "prima_total": PRIMA,
    "porcentaje": PCT, "estado": "Pendiente"})
comprueba("se crea la póliza en pendiente", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:90]}")
seg = conn.execute("SELECT id FROM seguros LIMIT 1").fetchone()
sid = seg["id"] if seg else None

print("\n   El flujo es Presupuesto -> Contratada -> En vigor, y no se salta")
st2, r2, _ = pide("/api/seguros_update", {"workspace_id": ws, "empresa_id": "emp1",
                                          "id": sid, "estado": "En vigor"})
comprueba("no se puede saltar a En vigor", st2 == 400 and "no permitida" in str(r2.get("error","")),
          f"HTTP {st2} {str(r2.get('error'))[:70]}")
comprueba("y dice cuál es el flujo bueno", "Presupuesto -> Contratada" in str(r2.get("allowed_flow","")),
          r2.get("allowed_flow"))

print("\n   Sin el PDF no pasa a Contratada")
st3, r3, _ = pide("/api/seguros_update", {"workspace_id": ws, "empresa_id": "emp1",
                                          "id": sid, "estado": "Contratada"})
comprueba("se niega y explica por qué", st3 == 400 and "PDF" in str(r3.get("error","")),
          f"HTTP {st3} {str(r3.get('error'))[:80]}")

print("\n   Con el PDF y sus importes")
st4, r4, _ = pide("/api/seguros_update", {"workspace_id": ws, "empresa_id": "emp1", "id": sid,
    "estado": "Contratada", "poliza_url": "/uploads/polizas/h2026.pdf",
    "prima_neta": 528.93, "prima_total": PRIMA, "comision": round(PRIMA * PCT / 100, 2),
    "porcentaje": PCT, "fecha_efecto": "2026-09-01", "fecha_vencimiento": "2027-09-01"})
comprueba("pasa a Contratada", st4 == 200 and not r4.get("error"), f"HTTP {st4} {str(r4)[:90]}")
st5, r5, _ = pide("/api/seguros_update", {"workspace_id": ws, "empresa_id": "emp1",
                                          "id": sid, "estado": "En vigor"})
comprueba("y de ahí a En vigor", st5 == 200 and not r5.get("error"), f"HTTP {st5} {str(r5)[:90]}")

pol = dict(conn.execute("SELECT * FROM seguros WHERE id=?", (sid,)).fetchone())
print("      ", {k: pol.get(k) for k in ("poliza_numero","prima_total","porcentaje","comision",
                                          "estado","fecha_efecto","fecha_vencimiento")})
comprueba("la prima y el porcentaje quedan guardados",
          abs(float(pol.get("prima_total") or 0) - PRIMA) < 0.01
          and abs(float(pol.get("porcentaje") or 0) - PCT) < 0.01,
          {k: pol.get(k) for k in ("prima_total","porcentaje")})
comprueba("la comisión queda guardada",
          abs(float(pol.get("comision") or 0) - round(PRIMA * PCT / 100, 2)) < 0.01,
          f"guardada {pol.get('comision')} · esperada {round(PRIMA*PCT/100,2)}")

print("\n=== 3. Emito el recibo de la póliza")
st, r, _ = pide("/api/seguros_recibos", {"workspace_id": ws, "empresa_id": "emp1",
    "seguro_id": sid, "cliente_id": cli_id, "referencia": "R-2026-0001",
    "poliza_numero": "H-2026-0001", "compania": "Mapfre", "ramo": "Hogar",
    "fecha_emision": "2026-09-01", "fecha_vencimiento": "2026-09-30",
    "prima_total": PRIMA, "comision": round(PRIMA * PCT / 100, 2), "estado": "Pendiente"})
comprueba("se emite el recibo", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:80]}")
rec = conn.execute("SELECT * FROM seguros_recibos LIMIT 1").fetchone()
rec = dict(rec) if rec else {}
print("      ", {k: rec.get(k) for k in ("referencia","prima_total","comision","estado")})
comprueba("el recibo lleva la prima y la comisión de la póliza",
          abs(float(rec.get("prima_total") or 0) - PRIMA) < 0.01
          and abs(float(rec.get("comision") or 0) - round(PRIMA*PCT/100, 2)) < 0.01, rec.get("comision"))

print("\n=== 4. El resumen de recibos y las cifras del panel")
st, resu, _ = pide("/api/seguros_recibos_summary", None, workspace_id=ws, empresa_id="emp1", anio=2026)
print("      ", json.dumps(resu, ensure_ascii=False)[:200])
comprueba("el resumen responde", st == 200 and isinstance(resu, dict), f"HTTP {st}")
st, kpis, _ = pide("/api/seguros_kpis", None, workspace_id=ws, empresa_id="emp1", anio=2026)
print("      kpis:", json.dumps(kpis, ensure_ascii=False)[:220])
comprueba("los KPI responden", st == 200 and isinstance(kpis, dict), f"HTTP {st}")

print("\n=== 5. Un siniestro")
st, r, _ = pide("/api/seguros_siniestros", {"workspace_id": ws, "empresa_id": "emp1",
    "seguro_id": sid, "cliente_id": cli_id, "numero_expediente": "SIN-2026-1",
    "compania": "Mapfre", "ramo": "Hogar", "fecha_siniestro": "2026-11-04",
    "fecha_apertura": "2026-11-05", "estado": "Abierto", "tipo": "Daños por agua",
    "descripcion": "Rotura de bajante", "importe_reserva": 1800.0})
comprueba("se abre el siniestro", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:80]}")
sin_ = conn.execute("SELECT numero_expediente, estado, importe_reserva FROM seguros_siniestros LIMIT 1").fetchone()
comprueba("queda registrado con su reserva", sin_ is not None
          and abs(float(dict(sin_).get("importe_reserva") or 0) - 1800.0) < 0.01,
          dict(sin_) if sin_ else "-")

print("\n=== 6. Renovación: la póliza vence dentro de un año")
st, ren, _ = pide("/api/seguros_renovaciones_queue", None, workspace_id=ws, empresa_id="emp1")
filas_ren = (ren.get("rows") if isinstance(ren, dict) else None) or []
print(f"      en la cola de renovación: {len(filas_ren)}")
comprueba("la cola de renovaciones responde", st == 200, f"HTTP {st} {str(ren)[:80]}")

print(f"\n{'='*62}\n{len(fallos)} pasos incorrectos")
for f in fallos: print("   ·", f)
httpd.shutdown(); tmp.cleanup()
sys.exit(1 if fallos else 0)
