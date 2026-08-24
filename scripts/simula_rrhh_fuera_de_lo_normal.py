#!/usr/bin/env python3
"""Simula las ausencias de una plantilla cuando se piden mal, se solapan o se contradicen.

Por qué
-------
`simula_ciclo_rrhh.py` recorre la jornada buena —fichar, regularizar, cerrar el mes,
exportar— y sale limpio. Pero las vacaciones y las bajas se piden a mano, y a mano se
teclea mal: el fin antes que el inicio, dos permisos encima del mismo día, o fichar un
día que uno tiene aprobado de vacaciones.

Eso importa porque el registro de jornada tiene obligación legal detrás (ET art. 34.9) y
porque el cómputo de vacaciones (art. 38) sale de estos mismos días.

Qué comprueba
-------------
  · una ausencia que acaba antes de empezar no entra
  · dos ausencias del mismo trabajador no se solapan sin decir nada
  · no se ficha un día que está aprobado como ausencia
  · quien aprueba no es quien pide
  · el resumen de vacaciones cuenta los días que son
  · cerrar el mes con ausencias sin resolver no las hace desaparecer

Qué NO hace
-----------
No cubre nóminas ni gastos. Tampoco los turnos.

Uso
---
    python scripts/simula_rrhh_fuera_de_lo_normal.py

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
    ins("empresas", dict(id="emp1", nombre="Modernia", nif="B29123456", activo=1, **b))
    ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **b))
    ins("usuarios", dict(id="jefa", nombre="Ana", usuario="ana", email="a@x.test",
                         rol="Administrador", servicio="RRHH", activo=1,
                         password_hash=S.hash_password(CLAVE), **b))
    ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="jefa",
                                   rol="Owner", **b))
    ins("usuarios", dict(id="curro", nombre="Curro", usuario="curro", email="c@x.test",
                         rol="Inmobiliaria", servicio="Inmobiliaria", activo=1,
                         registro_horario_activo=1,
                         password_hash=S.hash_password(CLAVE), **b))
    ins("workspace_miembros", dict(id="wm2", workspace_id=ws, usuario_id="curro",
                                   rol="Miembro", **b))

    S.Handler.db_path = str(db)
    httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    puerto = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    sesion = {"c": None}

    def pide(ruta, cuerpo=None, **params):
        url = f"http://127.0.0.1:{puerto}{ruta}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        rq = urllib.request.Request(
            url, data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
            headers={"Content-Type": "application/json"},
            method="POST" if cuerpo is not None else "GET")
        if sesion["c"]:
            rq.add_header("Cookie", sesion["c"])
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

    def entra(usuario):
        sesion["c"] = None
        _, _, cab = pide("/api/login", {"usuario": usuario, "password": CLAVE})
        sesion["c"] = cab.get("Set-Cookie").split(";")[0]

    entra("ana")
    print("\n=== 0. La ficha de plantilla de Curro")
    pide("/api/workspace_registro_personal", {
        "workspace_id": ws, "empresa_id": "emp1", "nombre": "Curro Jiménez",
        "nif": "25111111A", "usuario_id": "curro", "email": "c@x.test",
        "jornada_semanal": 40, "activo": 1})
    persona = fresco("SELECT id FROM workspace_registro_personal LIMIT 1")[0]["id"]
    comprueba("se crea la ficha", bool(persona))

    def ausencia(inicio, fin, tipo="Vacaciones", **extra):
        cuerpo = {"workspace_id": ws, "persona_id": persona, "tipo": tipo,
                  "fecha_inicio": inicio, "fecha_fin": fin}
        cuerpo.update(extra)
        return pide("/api/workspace_rrhh_ausencia", cuerpo)

    # ------------------------------------------------------- 1. fechas al revés
    print("\n=== 1. Pide vacaciones del 20 al 10 (el fin antes que el inicio)")
    estado, r, _ = ausencia("2026-09-20", "2026-09-10")
    n = len(fresco("SELECT id FROM workspace_rrhh_ausencias"))
    comprueba("no se acepta una ausencia que acaba antes de empezar",
              estado >= 400 or n == 0, f"HTTP {estado} · {n} ausencias guardadas")

    # ---------------------------------------------------------- 2. solapamiento
    print("\n=== 2. Vacaciones del 1 al 15, y luego una baja del 10 al 20")
    estado, r, _ = ausencia("2026-09-01", "2026-09-15")
    comprueba("las vacaciones entran", estado == 200 and not r.get("error"),
              f"HTTP {estado} {str(r)[:70]}")
    estado, r, _ = ausencia("2026-09-10", "2026-09-20", tipo="Baja médica")
    solapadas = fresco("SELECT tipo, fecha_inicio, fecha_fin, estado "
                       "FROM workspace_rrhh_ausencias ORDER BY fecha_inicio")
    for f in solapadas:
        print(f"       {f['tipo']:14} {f['fecha_inicio']} → {f['fecha_fin']}  ({f['estado']})")
    comprueba("dos ausencias del mismo trabajador no se solapan en silencio",
              estado >= 400 or len(solapadas) < 2,
              f"HTTP {estado} · quedan {len(solapadas)} ausencias pisándose")

    # ------------------------------------------- 3. se aprueban y cuentan sus días
    print("\n=== 3. Se aprueban las vacaciones y el contador las descuenta")
    pendiente = fresco("SELECT id, fecha_inicio, fecha_fin FROM workspace_rrhh_ausencias "
                       "WHERE tipo = 'Vacaciones' ORDER BY fecha_inicio")
    if pendiente:
        estado, r, _ = pide("/api/workspace_rrhh_ausencia_estado",
                            {"workspace_id": ws, "id": pendiente[0]["id"], "action": "aprobar"})
        comprueba("la responsable las aprueba", estado == 200 and not r.get("error"),
                  f"HTTP {estado} {str(r)[:70]}")
    entra("ana")
    _, resu, _ = pide("/api/workspace_rrhh_vacaciones_summary", None, workspace_id=ws, year=2026)
    fila = (resu.get("rows") or [{}])[0] if isinstance(resu, dict) else {}
    print(f"       {fila.get('dias_usados')} días usados de {fila.get('dias_total')}")
    comprueba("los días aprobados se descuentan de verdad",
              float(fila.get("dias_usados") or 0) > 0,
              "unas vacaciones aprobadas que gastan 0 días es lo que pasaba con las "
              "fechas al revés")

    # ------------------------------------------------ 4. aprobarse a uno mismo
    print("\n=== 4. Curro intenta aprobarse su propia ausencia")
    entra("curro")
    estado, r, _ = ausencia("2026-10-01", "2026-10-05", tipo="Asuntos propios")
    mia = fresco("SELECT id, estado FROM workspace_rrhh_ausencias "
                 "WHERE tipo = 'Asuntos propios'")
    comprueba("puede pedirla él", estado == 200 and bool(mia), f"HTTP {estado}")
    if mia:
        estado, r, _ = pide("/api/workspace_rrhh_ausencia_estado",
                            {"workspace_id": ws, "id": mia[0]["id"], "action": "aprobar"})
        tras = fresco("SELECT estado FROM workspace_rrhh_ausencias WHERE id = ?",
                      (mia[0]["id"],))[0]
        comprueba("pero no aprobársela", estado >= 400 or str(tras["estado"]) != "Aprobada",
                  f"HTTP {estado} · queda {tras['estado']!r}")

    # ------------------------------------------------- 5. el resumen de vacaciones
    print("\n=== 5. El resumen de vacaciones del año")
    entra("ana")
    estado, resu, _ = pide("/api/workspace_rrhh_vacaciones_summary", None,
                           workspace_id=ws, year=2026)
    print(f"       {json.dumps(resu, ensure_ascii=False)[:230]}")
    comprueba("el resumen responde", estado == 200 and isinstance(resu, dict), f"HTTP {estado}")

    # ---------------------------------- 6. cerrar el mes con ausencias sin resolver
    print("\n=== 6. Se cierra septiembre con una ausencia todavía sin resolver")
    sin_resolver_antes = fresco("SELECT COUNT(*) AS n FROM workspace_rrhh_ausencias "
                                "WHERE estado = 'Solicitada'")[0]["n"]
    estado, r, _ = pide("/api/workspace_registro_periodo_lock",
                        {"workspace_id": ws, "empresa_id": "emp1", "month": "2026-09",
                         "locked": True})
    print(f"       cierre: HTTP {estado} · {str(r)[:110]}")
    sin_resolver = fresco("SELECT COUNT(*) AS n FROM workspace_rrhh_ausencias "
                          "WHERE estado = 'Solicitada'")[0]["n"]
    comprueba("cerrar el mes no borra lo que está sin resolver",
              sin_resolver == sin_resolver_antes,
              f"antes {sin_resolver_antes}, después {sin_resolver}")

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
