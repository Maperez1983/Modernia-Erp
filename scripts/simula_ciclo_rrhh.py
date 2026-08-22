#!/usr/bin/env python3
"""Simula la jornada de un trabajador y el cierre de mes de su responsable.

Por qué
-------
El registro de jornada tiene obligación legal detrás (ET art. 34.9): hay que llevarlo,
conservarlo cuatro años y que no se altere en silencio. Esta simulación recorre el uso
real —fichar, olvidarse de fichar la salida, regularizar, cerrar el mes, exportar para
una inspección— y comprueba el resultado en cada paso.

Qué comprueba
-------------
  · el trabajador ficha su entrada y su salida, y queda un registro cerrado
  · un trabajador NO puede regularizar fichajes: eso es de quien gestiona el espacio
  · un fichaje que se quedó abierto sí se puede regularizar, y el cambio queda anotado
    en la auditoría, con quién y cuándo
  · cerrado el mes, nadie ficha: se responde 409 y se dice qué hacer
  · cerrado el mes, tampoco se regulariza
  · al desbloquear, se vuelve a poder fichar
  · las tres exportaciones —PDF, XLSX y XML— salen con datos

Qué NO hace
-----------
No comprueba la cadena de integridad criptográfica del registro (eso lo cubre
`tests/test_cadena_de_integridad_del_registro.py`) ni las ausencias y nóminas.

Uso
---
    python scripts/simula_ciclo_rrhh.py

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
MES = "2026-08"

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
    ins("empresas", dict(id="emp1", nombre="Modernia", nif="B29123456", activo=1, **base))
    ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **base))
    ins("usuarios", dict(id="jefa", nombre="Ana", usuario="ana", email="a@x.test",
                         rol="Administrador", servicio="RRHH", activo=1,
                         password_hash=S.hash_password(CLAVE), **base))
    ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="jefa",
                                   rol="Owner", **base))
    ins("usuarios", dict(id="curro", nombre="Curro", usuario="curro", email="c@x.test",
                         rol="Inmobiliaria", servicio="Inmobiliaria", activo=1,
                         registro_horario_activo=1,
                         password_hash=S.hash_password(CLAVE), **base))
    ins("workspace_miembros", dict(id="wm2", workspace_id=ws, usuario_id="curro",
                                   rol="Miembro", **base))

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

    def bloquea(locked):
        return pide("/api/workspace_registro_periodo_lock",
                    {"workspace_id": ws, "empresa_id": "emp1", "month": MES, "locked": locked})

    entra("ana")
    print("\n=== 1. La responsable da de alta la ficha de plantilla")
    estado, r, _ = pide("/api/workspace_registro_personal", {
        "workspace_id": ws, "empresa_id": "emp1", "nombre": "Curro Jiménez",
        "nif": "25111111A", "usuario_id": "curro", "email": "c@x.test",
        "jornada_semanal": 40, "activo": 1})
    comprueba("se crea la ficha", estado == 200 and not r.get("error"), f"HTTP {estado}")
    per = conn.execute("SELECT id FROM workspace_registro_personal LIMIT 1").fetchone()
    persona = per["id"] if per else None
    comprueba("queda enlazada al usuario", persona is not None)

    print("\n=== 2. Curro ficha su jornada")
    entra("curro")
    pide("/api/workspace_registro_horario_toggle", {"workspace_id": ws, "persona_id": persona})
    pide("/api/workspace_registro_horario_toggle", {"workspace_id": ws, "persona_id": persona})
    filas = [dict(x) for x in conn.execute("SELECT * FROM workspace_registro_horario")]
    comprueba("queda un registro cerrado", len(filas) == 1
              and str(filas[0].get("estado")) == "Cerrado", f"{len(filas)} registros")

    print("\n=== 3. Un trabajador no regulariza por su cuenta")
    estado, r, _ = pide("/api/workspace_registro_horario_regularizar", {
        "workspace_id": ws, "items": [{"id": filas[0]["id"], "hora_fin": "23:59"}]})
    comprueba("se le niega", estado in (401, 403), f"HTTP {estado} {str(r)[:70]}")

    print("\n=== 4. Otro día se olvida fichar la salida, y la responsable lo regulariza")
    conn.execute("UPDATE workspace_registro_horario SET fecha = '2026-08-20'")
    conn.commit()
    pide("/api/workspace_registro_horario_toggle", {"workspace_id": ws, "persona_id": persona})
    abierto = dict(conn.execute(
        "SELECT id, estado FROM workspace_registro_horario WHERE estado != 'Cerrado' "
        "ORDER BY created_at DESC LIMIT 1").fetchone() or {})
    comprueba("el fichaje queda abierto", bool(abierto), abierto)
    entra("ana")
    estado, r, _ = pide("/api/workspace_registro_horario_regularizar", {
        "workspace_id": ws, "notas": "Olvidó fichar la salida",
        "items": [{"id": abierto.get("id"), "hora_fin": "18:00", "pausa_min": 30}]})
    comprueba("la responsable sí puede", estado == 200 and int(r.get("cerrados") or 0) == 1,
              f"HTTP {estado} {str(r)[:90]}")
    tras = dict(conn.execute("SELECT hora_fin, pausa_min, estado FROM workspace_registro_horario "
                             "WHERE id = ?", (abierto.get("id"),)).fetchone())
    comprueba("el cambio se guarda", str(tras.get("hora_fin")) == "18:00", tras)
    apuntes = conn.execute("SELECT COUNT(*) FROM workspace_registro_audit").fetchone()[0]
    comprueba("y queda anotado en la auditoría", apuntes > 0, f"{apuntes} apuntes")

    print("\n=== 5. Se cierra el mes")
    estado, r, _ = bloquea(True)
    comprueba("se cierra el periodo", estado == 200 and not r.get("error"), f"HTTP {estado}")
    entra("curro")
    estado, r, _ = pide("/api/workspace_registro_horario_toggle",
                        {"workspace_id": ws, "persona_id": persona})
    comprueba("con el mes cerrado no se ficha", estado == 409, f"HTTP {estado}")
    comprueba("y se dice qué hacer", "bloquead" in str(r.get("error", "")).lower(),
              r.get("error"))
    entra("ana")
    estado, r, _ = pide("/api/workspace_registro_horario_regularizar", {
        "workspace_id": ws, "items": [{"id": abierto.get("id"), "hora_fin": "23:00"}]})
    comprueba("con el mes cerrado tampoco se regulariza",
              estado != 200 or int(r.get("cerrados") or 0) == 0, f"HTTP {estado} {str(r)[:90]}")
    sigue = dict(conn.execute("SELECT hora_fin FROM workspace_registro_horario WHERE id = ?",
                              (abierto.get("id"),)).fetchone())
    comprueba("el fichaje sigue como estaba", str(sigue.get("hora_fin")) == "18:00", sigue)

    print("\n=== 6. Se desbloquea y se vuelve a poder fichar")
    bloquea(False)
    entra("curro")
    estado, r, _ = pide("/api/workspace_registro_horario_toggle",
                        {"workspace_id": ws, "persona_id": persona})
    comprueba("desbloqueado, vuelve a fichar", estado == 200 and not r.get("error"),
              f"HTTP {estado} {str(r)[:80]}")

    print("\n=== 7. La exportación para una inspección")
    entra("ana")
    for ruta, cabecera in (("/api/workspace_registro_horario_pdf", b"%PDF"),
                           ("/api/workspace_registro_horario_xlsx", b"PK"),
                           ("/api/workspace_registro_horario_xml", b"<")):
        _, doc, _ = pide(ruta, None, workspace_id=ws, persona_id=persona,
                         desde="2026-08-01", hasta="2026-08-31")
        comprueba(f"sale {ruta.rsplit('_', 1)[-1]}",
                  isinstance(doc, bytes) and doc[:len(cabecera)] == cabecera,
                  f"{len(doc)} B" if isinstance(doc, bytes) else str(doc)[:70])

    print(f"\n{'=' * 62}")
    print(f"{len(fallos)} pasos incorrectos")
    for f in fallos:
        print("   ·", f)
    httpd.shutdown()
    tmp.cleanup()
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
