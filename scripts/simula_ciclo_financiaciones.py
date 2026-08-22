#!/usr/bin/env python3
"""Simula el ciclo de un asesor de financiación y comprueba que queda guardado.

Por qué
-------
Como las otras simulaciones de uso: recorre lo que hace una persona —estudio,
checklist, conversión en hipoteca, firma— y verifica el resultado. Aquí apareció el
patrón más traicionero de todos: **endpoints que responden «ok» y no guardan nada**.

Qué comprueba
-------------
  · el estudio se abre y da de alta al titular como cliente
  · el checklist genera sus tareas y QUEDAN GUARDADAS
  · la conversión crea la hipoteca y QUEDA GUARDADA, y el asesor la ve en su listado
  · al completar la ficha, el porcentaje financiado y la entrada salen solos
  · la firma queda con su fecha, y los paneles y el PDF de firmadas cuadran

Cada comprobación de «queda guardado» se hace con una conexión nueva a la base: la
del propio script arrastra una instantánea de SQLite que no ve lo que el servidor
escribe después, y eso me hizo dar por perdida una fila que sí estaba.

Uso
---
    python scripts/simula_ciclo_financiaciones.py

Levanta su propio servidor sobre una base temporal. No toca producción. Sale con
código 1 si algún paso falla.
"""
import json, os, sys, tempfile, threading, urllib.error, urllib.parse, urllib.request
from pathlib import Path
os.environ["DATABASE_URL"] = ""; os.environ["POSTGRES_URL"] = ""
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from web import server as S
CLAVE = "Fin1234!"; AHORA = "2026-08-22 09:00:00"
PRECIO = 285000.0; HIPOTECA = 228000.0; COMISION = 2280.0
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
ins("empresas", dict(id="emp1", nombre="Modernia Financiación", nif="B29123456", activo=1, **b))
ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **b))
ins("usuarios", dict(id="u1", nombre="Jorge", usuario="jorge", email="j@x.test",
                     rol="Financiaciones", servicio="Financiaciones", activo=1,
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
def fresco():
    """Lectura sin instantánea vieja: mi conexión no ve lo que el servidor escribe
    después de abrirla, y eso me hizo dar por perdida una fila que sí estaba."""
    return S.open_sqlite_conn(db, with_row_factory=True)

fallos = []
def comprueba(e, c, d=""):
    print(f"  {'OK ' if c else 'MAL'}  {e}{('  ·  ' + str(d)[:110]) if d else ''}")
    if not c: fallos.append(e)
_, _, cab = pide("/api/login", {"usuario":"jorge","password":CLAVE})
ses["c"] = cab.get("Set-Cookie").split(";")[0]

print("\n=== 1. Me derivan un cliente: abro el estudio de financiación")
st, r, _ = pide("/api/fin_asesoramientos", {"workspace_id": ws, "empresa_id": "emp1",
    "origen": "Inmobiliaria", "asesor": "Jorge", "fecha": "2026-08-22", "estado": "Estudio",
    "cliente1_nombre": "Carlos Comprador", "cliente1_dni": "25111111A",
    "cliente1_telefono": "600111222", "cliente1_email": "carlos@x.test",
    "cliente1_ingresos": 2400, "cliente1_tipo_contrato": "Indefinido",
    "cliente1_prestamos": 0})
comprueba("se abre el estudio", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:90]}")
ase = fresco().execute("SELECT * FROM asesoramientos_financiacion LIMIT 1").fetchone()
ase = dict(ase) if ase else {}
ase_id = ase.get("id")
comprueba("queda con su titular y sus ingresos",
          str(ase.get("cliente1_nombre","")).startswith("Carlos")
          and float(ase.get("cliente1_ingresos") or 0) == 2400,
          {k: ase.get(k) for k in ("cliente1_nombre","cliente1_ingresos","estado")})
comprueba("el titular se da de alta como cliente",
          fresco().execute("SELECT COUNT(*) FROM clientes").fetchone()[0] >= 1,
          [dict(x) for x in fresco().execute("SELECT nombre, nif FROM clientes")])

print("\n=== 2. La lista de tareas del expediente")
st, r, _ = pide("/api/fin_checklist_generate", {"workspace_id": ws, "empresa_id": "emp1",
                                                "asesoramiento_id": ase_id})
comprueba("se genera el checklist", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:90]}")
try: conn.commit()
except Exception: pass
f = fresco()
existe = f.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='fin_checklist'").fetchone()[0]
tareas = f.execute("SELECT COUNT(*) FROM fin_checklist").fetchone()[0] if existe else -1
print(f"      tabla fin_checklist existe={bool(existe)} filas={tareas}")
if existe:
    for x in f.execute("SELECT tarea, estado FROM fin_checklist LIMIT 8"): print("        ", dict(x))
comprueba("hay tareas en el expediente", tareas > 0, f"{tareas} tareas")

# ¿Están sin confirmar, o no se han escrito? Provocamos otra escritura y volvemos a mirar.
pide("/api/fin_asesoramientos_update", {"workspace_id": ws, "empresa_id": "emp1",
                                        "id": ase_id, "estado": "Bancos"})
tras = fresco().execute("SELECT COUNT(*) FROM fin_checklist").fetchone()[0]
print(f"      tras otra escritura del servidor: {tras} tareas")
comprueba("las tareas aparecen sin depender de otra escritura", tareas == tras,
          f"antes {tareas} · después {tras} — quedaban en una transacción sin confirmar")

print("\n=== 3. El expediente avanza a bancos y se convierte en hipoteca")
st, r, _ = pide("/api/fin_asesoramientos_convert", {"workspace_id": ws, "empresa_id": "emp1",
    "id": ase_id, "asesoramiento_id": ase_id, "banco": "Banco Ejemplo",
    "precio": PRECIO, "importe_hipoteca": HIPOTECA, "comision": COMISION,
    "fecha_encargo": "2026-09-01", "tipo_hipoteca": "Fija", "anio": 2026})
comprueba("se convierte en hipoteca", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:100]}")
st_l, lista, _ = pide("/api/tabla", None, tabla="hipotecas", empresa_id="emp1", workspace_id=ws)
print("      respuesta del listado:", json.dumps(lista, ensure_ascii=False)[:220])
n_api = 0
if isinstance(lista, dict):
    for clave in ("rows", "items", "registros", "hipotecas", "data"):
        if isinstance(lista.get(clave), list): n_api = max(n_api, len(lista[clave]))
n_db = fresco().execute("SELECT COUNT(*) FROM hipotecas").fetchone()[0]
print(f"      el servidor ve {n_api} hipotecas · en el fichero hay {n_db}")
comprueba("la hipoteca queda guardada y el asesor la ve en su listado",
          n_db >= 1 and n_api >= 1,
          f"listado {n_api} · base {n_db}")
hip = fresco().execute("SELECT * FROM hipotecas LIMIT 1").fetchone()
hip = dict(hip) if hip else {}
print("      ", {k: hip.get(k) for k in ("cliente","banco","precio","importe_hipoteca",
                                          "porcentaje","comision","estado","anio")})
comprueba("la hipoteca existe con su cliente", bool(hip) and "Carlos" in str(hip.get("cliente","")),
          hip.get("cliente"))

print("\n   El asesor completa la ficha con lo que le da el banco")
hip_id = hip.get("id")
st, r, _ = pide("/api/hipotecas_update", {"workspace_id": ws, "empresa_id": "emp1", "id": hip_id,
    "banco": "Banco Ejemplo", "precio": PRECIO, "importe_hipoteca": HIPOTECA,
    "comision": COMISION, "tipo_hipoteca": "Fija", "fecha_encargo": "2026-09-01"})
comprueba("se completa la ficha", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:80]}")
hip = dict(fresco().execute("SELECT * FROM hipotecas WHERE id=?", (hip_id,)).fetchone())
print("      ", {k: hip.get(k) for k in ("banco","precio","importe_hipoteca","porcentaje",
                                          "entrada","comision","estado")})

print("\n=== 4. Los números de la operación")
if hip:
    pct_esperado = round(HIPOTECA / PRECIO * 100, 2)
    pct = hip.get("porcentaje")
    comprueba(f"el porcentaje financiado es {pct_esperado} %",
              pct is not None and abs(float(pct) - pct_esperado) < 0.5, f"guardado {pct}")
    entrada_esperada = round(PRECIO - HIPOTECA, 2)
    comprueba(f"la entrada del comprador es {entrada_esperada:,.0f} €",
              hip.get("entrada") is not None and abs(float(hip.get("entrada") or 0) - entrada_esperada) < 1,
              f"guardada {hip.get('entrada')}")

print("\n=== 5. Se firma")
st, r, _ = pide("/api/hipotecas_update", {"workspace_id": ws, "empresa_id": "emp1", "id": hip_id,
    "estado": "Firmada", "fecha_firma": "2026-11-20"})
comprueba("se marca como firmada", st == 200 and not r.get("error"), f"HTTP {st} {str(r)[:80]}")
fin_ = dict(fresco().execute("SELECT estado, fecha_firma, comision FROM hipotecas WHERE id=?", (hip_id,)).fetchone())
comprueba("queda firmada con su fecha", "firm" in str(fin_.get("estado","")).lower()
          and str(fin_.get("fecha_firma")) == "2026-11-20", fin_)

print("\n=== 6. Los paneles y el PDF de firmadas")
st, kpis, _ = pide("/api/hipoteca_stats", None, workspace_id=ws, empresa_id="emp1", anio=2026)
print("      stats:", json.dumps(kpis, ensure_ascii=False)[:200])
comprueba("las cifras responden", st == 200, f"HTTP {st}")
st, pdf, _ = pide("/api/hipotecas_firmadas_pdf", None, workspace_id=ws, empresa_id="emp1",
                  anio=2026, year=2026)
comprueba("sale el PDF de firmadas", isinstance(pdf, bytes) and pdf[:4] == b"%PDF",
          f"{len(pdf)} B" if isinstance(pdf, bytes) else str(pdf)[:80])

print(f"\n{'='*62}\n{len(fallos)} pasos incorrectos")
for f in fallos: print("   ·", f)
httpd.shutdown(); tmp.cleanup()
sys.exit(1 if fallos else 0)
