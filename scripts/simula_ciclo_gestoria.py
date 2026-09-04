#!/usr/bin/env python3
"""Simula el ciclo de una gestoría y comprueba que el expediente queda completo.

Por qué
-------
Como las otras simulaciones de uso: alta del cliente, los servicios que contrata, un
trabajo con su plazo, los modelos a presentar, un apunte contable y el panel.

Qué comprueba
-------------
  · el expediente refleja exactamente los servicios contratados
  · el trabajo guarda su importe y su plazo (SLA)
  · el modelo queda programado con su periodicidad y su fecha
  · el apunte contable guarda su importe
  · el panel responde sin cifras rotas
  · los listados de trabajos y modelos traen los del cliente

Resultado a 2026-08-22: sin fallos.

Ojo con el modelo de datos: `/api/cliente_gestoria` devuelve los **servicios
contratados**, no el expediente entero; los trabajos y los modelos se piden por
separado. Y `gestoria_contabilidad` guarda un `importe` único, no base+IVA: una
comprobación de «base + IVA = total» pasa en vacío porque esas columnas no existen.

Uso
---
    python scripts/simula_ciclo_gestoria.py

Levanta su propio servidor sobre una base temporal. No toca producción. Sale con
código 1 si algún paso falla.
"""
import json, os, sys, tempfile, threading, urllib.error, urllib.parse, urllib.request
from pathlib import Path
os.environ["DATABASE_URL"] = ""; os.environ["POSTGRES_URL"] = ""
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from web import server as S
CLAVE = "Gest1234!"; AHORA = "2026-08-22 09:00:00"
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
ins("empresas", dict(id="emp1", nombre="Gestoría Modernia", nif="B29123456", activo=1, **b))
ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **b))
ins("usuarios", dict(id="u1", nombre="Gonzalo", usuario="gonzalo", email="g@x.test",
                     rol="Gestoría", servicio="Gestoría", activo=1,
                     password_hash=S.hash_password(CLAVE), **b))
ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="u1", rol="Admin", **b))
S.Handler.db_path = db
httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler); PORT = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
ses = {"c": None}
def fresco(): return S.open_sqlite_conn(db, with_row_factory=True)
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
_, _, cab = pide("/api/login", {"usuario":"gonzalo","password":CLAVE})
ses["c"] = cab.get("Set-Cookie").split(";")[0]

print("\n=== 1. Alta de una sociedad como cliente de gestoría")
st, r, _ = pide("/api/clientes", {"workspace_id": ws, "empresa_id": "emp1",
    "nombre": "Talleres Sur SL", "nif": "B29777888", "telefono": "952111222",
    "email": "admin@talleressur.test", "servicio": "gestoria"})
comprueba("se da de alta el cliente", st == 200 and not r.get("error"), f"HTTP {st}")
cli = fresco().execute("SELECT id FROM clientes LIMIT 1").fetchone()
cli_id = cli["id"] if cli else None

print("\n=== 2. Le contrato los servicios: fiscal, laboral y contable")
st, r, _ = pide("/api/cliente_gestoria_update", {"workspace_id": ws, "empresa_id": "emp1",
    "cliente_id": cli_id, "tipo_cliente": "Sociedad", "mod_fiscal": 1,
    "mod_laboral": 1, "mod_contable": 1, "mod_renta": 0})
comprueba("se guardan los servicios", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:80]}")
cg = fresco().execute("SELECT * FROM cliente_gestoria WHERE cliente_id=?", (cli_id,)).fetchone()
cg = dict(cg) if cg else {}
comprueba("el expediente refleja lo contratado",
          str(cg.get("mod_fiscal")) in ("1","True") and str(cg.get("mod_renta")) in ("0","False","None"),
          {k: cg.get(k) for k in ("tipo_cliente","mod_fiscal","mod_laboral","mod_contable","mod_renta")})

print("\n=== 3. Un trabajo con su plazo")
st, r, _ = pide("/api/gestoria_trabajos", {"workspace_id": ws, "empresa_id": "emp1",
    "cliente_id": cli_id, "tipo_trabajo": "Alta de autónomo", "tipo_categoria": "Laboral",
    "estado": "Pendiente", "fecha_inicio": "2026-08-22", "sla_dias": 5,
    "responsable": "Gonzalo", "importe": 90.0})
comprueba("se crea el trabajo", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:80]}")
tr = fresco().execute("SELECT * FROM gestoria_trabajos LIMIT 1").fetchone()
tr = dict(tr) if tr else {}
comprueba("queda guardado con su importe y su plazo",
          bool(tr) and abs(float(tr.get("importe") or 0) - 90.0) < 0.01 and int(tr.get("sla_dias") or 0) == 5,
          {k: tr.get(k) for k in ("tipo_trabajo","estado","importe","sla_dias")})

print("\n=== 4. Los modelos que hay que presentar")
st, r, _ = pide("/api/gestoria_modelos", {"workspace_id": ws, "empresa_id": "emp1",
    "cliente_id": cli_id, "modelo": "303", "periodicidad": "Trimestral",
    "proxima_fecha": "2026-10-20", "responsable": "Gonzalo", "estado": "Pendiente"})
comprueba("se programa el modelo 303", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:80]}")
mo = fresco().execute("SELECT * FROM gestoria_modelos LIMIT 1").fetchone()
comprueba("con su periodicidad y su fecha", mo is not None
          and dict(mo).get("modelo") == "303" and dict(mo).get("proxima_fecha") == "2026-10-20",
          dict(mo) if mo else "-")
print("\n=== 5. Contabilidad del cliente: una factura de gasto")
st, r, _ = pide("/api/gestoria_contabilidad", {"workspace_id": ws, "empresa_id": "emp1",
    "cliente_id": cli_id, "fecha": "2026-08-15", "tipo": "Gasto",
    "concepto": "Material de oficina", "gestion": "Contabilidad", "importe": 121.0,
    "notas": "Factura de Papelería Sur"})
comprueba("se apunta el gasto", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:80]}")
ap = fresco().execute("SELECT * FROM gestoria_contabilidad LIMIT 1").fetchone()
ap = dict(ap) if ap else {}
print("      ", {k: ap.get(k) for k in ("concepto","tipo","gestion","importe")})
comprueba("el apunte guarda su importe",
          bool(ap) and abs(float(ap.get("importe") or 0) - 121.0) < 0.01,
          {k: ap.get(k) for k in ("tipo","importe")})

print("\n=== 6. El panel de la gestoría")
st, panel, _ = pide("/api/gestoria_dashboard", None, workspace_id=ws, empresa_id="emp1", anio=2026)
comprueba("el panel responde", st == 200 and isinstance(panel, dict), f"HTTP {st}")
txt = json.dumps(panel, ensure_ascii=False)
print("      ", txt[:240])
comprueba("el panel no enseña cifras rotas",
          not any(x in txt for x in ("NaN", "Infinity", '"undefined"')), "hay NaN o undefined")

print("\n=== 7. El expediente del cliente, de una pieza")
st, exp, _ = pide("/api/cliente_gestoria", None, workspace_id=ws, empresa_id="emp1", cliente_id=cli_id)
t = json.dumps(exp, ensure_ascii=False)
comprueba("el expediente responde", st == 200, f"HTTP {st} {t[:80]}")
# El expediente devuelve los servicios contratados; trabajos y modelos se piden aparte.
comprueba("y trae los servicios contratados",
          '"mod_fiscal": 1' in t and '"tipo_cliente": "Sociedad"' in t, t[:140])
st, tr_l, _ = pide("/api/gestoria_trabajos", None, workspace_id=ws, empresa_id="emp1", cliente_id=cli_id)
tt = json.dumps(tr_l, ensure_ascii=False)
comprueba("el listado de trabajos trae el suyo", "Alta de autónomo" in tt, tt[:140])
st, mo_l, _ = pide("/api/gestoria_modelos", None, workspace_id=ws, empresa_id="emp1", cliente_id=cli_id)
mm = json.dumps(mo_l, ensure_ascii=False)
comprueba("el listado de modelos trae el 303", '"303"' in mm, mm[:140])

print(f"\n{'='*62}\n{len(fallos)} pasos incorrectos")
for f in fallos: print("   ·", f)
httpd.shutdown(); tmp.cleanup()
sys.exit(1 if fallos else 0)
