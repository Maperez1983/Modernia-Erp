#!/usr/bin/env python3
"""Simula lo que NO es el mes normal de una comunidad.

Por qué
-------
`simula_ciclo_fincas.py` recorre el camino principal —censo, presupuesto, recibos,
remesa, morosidad— y sale limpio. Pero un administrador de fincas se pasa el año fuera
de ese camino: una derrama para arreglar el ascensor, un piso que cambia de dueño en
junio, un recibo que se anula, un vecino que se marcha.

Esto recorre eso. Cada paso se comprueba con la calculadora y contra la base, no por el
código de respuesta: el patrón de esta auditoría es que los fallos que importan
contestan 200.

Qué comprueba
-------------
  · una derrama extraordinaria se puede emitir sin cargarse la cuota ordinaria del mes
  · un piso que cambia de dueño no traspasa al comprador la deuda del vendedor en el
    certificado, y lo que ya se emitió sigue diciendo a nombre de quién se emitió
  · un recibo cobrado y luego devuelto por el banco vuelve a contar como deuda
  · dar de alta un vecino nuevo descuadra los coeficientes y la emisión se niega
  · cerrar el ejercicio con recibos pendientes no los hace desaparecer

Qué NO hace
-----------
No mira la interfaz. Y no cubre juntas, actas ni conciliación bancaria.

Uso
---
    python scripts/simula_fincas_fuera_de_lo_normal.py

Levanta su propio servidor sobre una base temporal. No toca producción: borra
DATABASE_URL antes de importar nada. Sale con código 1 si algún paso falla.
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
AHORA = "2026-08-23 09:00:00"
# Cuatro pisos que suman 100 %.
CENSO = [("Dolores Sánchez", "1º A", 30.0), ("Manuel Ortega", "1º B", 25.0),
         ("Rocío Peña", "2º A", 25.0), ("Julián Vega", "2º B", 20.0)]
CUOTA = 1200.0
DERRAMA = 12000.0

fallos = []
avisos = []


def comprueba(etiqueta, condicion, detalle=""):
    print(f"  {'OK ' if condicion else 'MAL'}  {etiqueta}"
          f"{('  ·  ' + str(detalle)[:110]) if detalle else ''}")
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
        """Conexión nueva: la del script arrastra una instantánea que no ve al servidor."""
        c = S.open_sqlite_conn(str(db), with_row_factory=True)
        try:
            return [dict(x) for x in c.execute(sql, args).fetchall()]
        finally:
            c.close()

    base = dict(created_at=AHORA, updated_at=AHORA)
    ins("empresas", dict(id="emp1", nombre="Fincas Modernia", nif="B29123456",
                         activo=1, administra_fincas=1, **base))
    ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **base))
    ins("usuarios", dict(id="u1", nombre="Ana", usuario="ana", email="a@x.test",
                         rol="Administrador", servicio="Fincas", activo=1,
                         password_hash=S.hash_password(CLAVE), **base))
    ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="u1",
                                   rol="Owner", **base))

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

    _, _, cab = pide("/api/login", {"usuario": "ana", "password": CLAVE})
    cookie["v"] = cab.get("Set-Cookie").split(";")[0]

    # ---------------------------------------------------------------- preparación
    print("\n=== 0. La comunidad, su censo y la cuota de agosto")
    pide("/api/workspace_fincas_comunidades", {
        "workspace_id": ws, "empresa_id": "emp1", "nombre": "C.P Los Naranjos",
        "cif": "H29123456", "direccion": "Avenida Europa 110, Málaga", "estado": "Activa",
        "num_vecinos": len(CENSO), "iban": "ES9121000418450200051332",
        "acreedor_sepa": "ES12ZZZH29123456"})
    com = fresco("SELECT id FROM workspace_fincas_comunidades LIMIT 1")[0]["id"]
    for i, (nombre, piso, coef) in enumerate(CENSO):
        pide("/api/workspace_fincas_vecinos", {
            "workspace_id": ws, "comunidad_id": com, "nombre": nombre, "piso": piso,
            "coeficiente": coef, "nif": f"2511111{i}A", "email": f"v{i}@x.test",
            "iban": "ES2321000418400000000001"})
    estado, r, _ = pide("/api/workspace_fincas_recibos_emitir", {
        "workspace_id": ws, "comunidad_id": com, "periodo": "2026-08",
        "importe": CUOTA, "concepto": "Cuota ordinaria agosto"})
    comprueba("se emite la cuota ordinaria de agosto",
              estado == 200 and int(r.get("creados") or 0) == len(CENSO), f"HTTP {estado}")
    # Y la de mayo, que ya venció: un recibo del mes en curso todavía no es deuda —nadie
    # ha tenido ocasión de pagarlo—, así que sin esto el certificado sale «al corriente».
    pide("/api/workspace_fincas_recibos_emitir", {
        "workspace_id": ws, "comunidad_id": com, "periodo": "2026-05",
        "importe": CUOTA, "concepto": "Cuota mayo"})

    # ------------------------------------------------------------------ 1. derrama
    print(f"\n=== 1. Derrama del ascensor: {DERRAMA:,.0f} € en agosto")
    estado, r, _ = pide("/api/workspace_fincas_recibos_emitir", {
        "workspace_id": ws, "comunidad_id": com, "periodo": "2026-08",
        "importe": DERRAMA, "concepto": "Derrama ascensor (acuerdo junta 12/07)"})
    comprueba("no entra sin más: hay otro cargo ese mes y se pregunta", estado == 409,
              f"HTTP {estado}")
    comprueba("y el aviso dice qué hay y que se puede sumar",
              "otro concepto" in str(r.get("error", "")) and "aparte" in str(r.get("error", "")),
              r.get("error"))
    print("       La administradora confirma que es un cargo aparte:")
    estado, r, _ = pide("/api/workspace_fincas_recibos_emitir", {
        "workspace_id": ws, "comunidad_id": com, "periodo": "2026-08",
        "importe": DERRAMA, "concepto": "Derrama ascensor (acuerdo junta 12/07)",
        "confirmado": True})
    tras = fresco("SELECT concepto, SUM(importe) AS suma, COUNT(*) AS n "
                  "FROM workspace_fincas_recibos WHERE comunidad_id = ? AND periodo = '2026-08' "
                  "GROUP BY concepto ORDER BY concepto", (com,))
    for f in tras:
        print(f"         {f['n']} recibos · {f['concepto'][:44]!r} · {float(f['suma']):,.2f} €")
    cobrado = sum(float(f["suma"]) for f in tras)
    comprueba("la comunidad cobra la cuota Y la derrama",
              abs(cobrado - (CUOTA + DERRAMA)) < 0.01,
              f"cobra {cobrado:,.2f} € de {CUOTA + DERRAMA:,.2f} €")
    comprueba("cada propietario recibe sus dos recibos",
              all(int(f["n"]) == len(CENSO) for f in tras) and len(tras) == 2, tras)

    print("\n=== 1b. Y rehacer la cuota no se lleva la derrama por delante")
    estado, r, _ = pide("/api/workspace_fincas_recibos_emitir", {
        "workspace_id": ws, "comunidad_id": com, "periodo": "2026-08",
        "importe": 1500.0, "concepto": "Cuota ordinaria agosto", "reemitir": "1"})
    tras = fresco("SELECT concepto, SUM(importe) AS suma FROM workspace_fincas_recibos "
                  "WHERE comunidad_id = ? AND periodo = '2026-08' GROUP BY concepto "
                  "ORDER BY concepto", (com,))
    for f in tras:
        print(f"         {f['concepto'][:44]!r} · {float(f['suma']):,.2f} €")
    derrama_viva = [f for f in tras if "Derrama" in str(f["concepto"])]
    comprueba("la derrama sigue en pie tras rehacer la cuota",
              len(derrama_viva) == 1 and abs(float(derrama_viva[0]["suma"]) - DERRAMA) < 0.01,
              tras)
    cuota_viva = [f for f in tras if "Cuota" in str(f["concepto"])]
    comprueba("y la cuota se rehace con el importe nuevo",
              len(cuota_viva) == 1 and abs(float(cuota_viva[0]["suma"]) - 1500.0) < 0.01, tras)

    # ------------------------------------------- 2. el piso cambia de dueño en junio
    print("\n=== 2. El 1º A se vende: entra un comprador con deuda del vendedor detrás")
    dolores = fresco("SELECT id, nombre FROM workspace_fincas_vecinos "
                     "WHERE comunidad_id = ? AND piso = '1º A'", (com,))[0]
    deuda_previa = fresco("SELECT COUNT(*) AS n, COALESCE(SUM(importe),0) AS s "
                          "FROM workspace_fincas_recibos WHERE vecino_id = ? AND estado = 'Pendiente'",
                          (dolores["id"],))[0]
    print(f"       {dolores['nombre']} deja {deuda_previa['n']} recibo(s) sin pagar: "
          f"{float(deuda_previa['s']):,.2f} €")
    estado, r, _ = pide("/api/workspace_fincas_vecinos", {
        "workspace_id": ws, "comunidad_id": com, "id": dolores["id"],
        "nombre": "Alberto Ruiz (compra 15/06/2026)", "piso": "1º A", "coeficiente": 30.0,
        "nif": "25999999Z", "email": "alberto@x.test",
        "iban": "ES2321000418400000000009"})
    comprueba("se puede poner al comprador en el censo", estado == 200, f"HTTP {estado}")
    de_quien = fresco("SELECT v.nombre AS hoy, r.vecino_nombre AS emitido_a, r.concepto "
                      "FROM workspace_fincas_recibos r "
                      "JOIN workspace_fincas_vecinos v ON v.id = r.vecino_id "
                      "WHERE r.vecino_id = ? ORDER BY r.concepto", (dolores["id"],))
    for f in de_quien:
        print(f"         {f['concepto'][:38]!r:42} emitido a {str(f['emitido_a'])!r}")
    comprueba("los recibos siguen diciendo a quién se le emitieron",
              all("Dolores" in str(f["emitido_a"]) for f in de_quien), de_quien)
    comprueba("y la ficha del piso ya es del comprador",
              all("Alberto" in str(f["hoy"]) for f in de_quien), de_quien)
    _, cert, _ = pide("/api/workspace_fincas_certificado_deuda", None,
                      workspace_id=ws, vecino_id=dolores["id"])
    texto = ""
    if isinstance(cert, bytes) and cert[:4] == b"%PDF":
        # El PDF lleva los textos comprimidos: buscarlos en los bytes no encuentra nada
        # y da un falso «no lo dice». Hay que extraerlos.
        import io
        from pypdf import PdfReader
        texto = "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(cert)).pages)
        print(f"         el certificado sale: {len(cert):,} B de PDF, "
              f"{len(texto):,} caracteres de texto")
    comprueba("el certificado se emite a nombre del propietario de hoy",
              "Alberto" in texto, f"{len(texto)} caracteres")
    comprueba("y avisa de que parte de la deuda se emitió al anterior",
              "Dolores" in texto and "anterior" in texto,
              "el comprador no puede parecer el moroso de todo")

    # --------------------------------------------- 3. cobrado y devuelto por el banco
    print("\n=== 3. Un recibo se cobra y el banco lo devuelve")
    manuel = fresco("SELECT id FROM workspace_fincas_vecinos WHERE comunidad_id = ? AND piso = '1º B'",
                    (com,))[0]["id"]
    rec = fresco("SELECT id, importe FROM workspace_fincas_recibos WHERE vecino_id = ? LIMIT 1",
                 (manuel,))[0]
    pide("/api/workspace_fincas_recibo_estado",
         {"workspace_id": ws, "id": rec["id"], "estado": "Cobrado"})
    _, mor, _ = pide("/api/workspace_fincas_morosidad", None, workspace_id=ws, comunidad_id=com)
    filas_mor = (mor.get("rows") or mor.get("morosos") or []) if isinstance(mor, dict) else []
    comprueba("cobrado, deja de ser moroso",
              not any(str(f.get("vecino_id")) == manuel for f in filas_mor),
              f"{len(filas_mor)} morosos")
    pide("/api/workspace_fincas_recibo_estado",
         {"workspace_id": ws, "id": rec["id"], "estado": "Devuelto", "motivo": "Sin fondos"})
    tras = fresco("SELECT estado, fecha_cobro FROM workspace_fincas_recibos WHERE id = ?",
                  (rec["id"],))[0]
    comprueba("devuelto, la fecha de cobro se borra", not tras.get("fecha_cobro"), tras)
    _, mor2, _ = pide("/api/workspace_fincas_morosidad", None, workspace_id=ws, comunidad_id=com)
    filas2 = (mor2.get("rows") or mor2.get("morosos") or []) if isinstance(mor2, dict) else []
    comprueba("devuelto, vuelve a contar como deuda",
              any(str(f.get("vecino_id")) == manuel for f in filas2),
              f"{len(filas2)} morosos")

    # ------------------------------------- 4. entra un vecino y descuadra el reparto
    print("\n=== 4. Se da de alta un trastero y los coeficientes dejan de sumar 100")
    pide("/api/workspace_fincas_vecinos", {
        "workspace_id": ws, "comunidad_id": com, "nombre": "Trastero comunitario",
        "piso": "Sótano", "coeficiente": 5.0, "nif": "25000000B",
        "iban": "ES2321000418400000000002"})
    suma = fresco("SELECT COALESCE(SUM(coeficiente),0) AS s FROM workspace_fincas_vecinos "
                  "WHERE comunidad_id = ?", (com,))[0]["s"]
    print(f"       los coeficientes suman ahora {float(suma):.2f} %")
    estado, r, _ = pide("/api/workspace_fincas_recibos_emitir", {
        "workspace_id": ws, "comunidad_id": com, "periodo": "2026-09",
        "importe": CUOTA, "concepto": "Cuota ordinaria septiembre"})
    comprueba("no se emite con el reparto descuadrado", estado == 400, f"HTTP {estado}")
    comprueba("y se dice cuánto suman y qué revisar",
              "105" in str(r.get("error", "")) and "censo" in str(r.get("error", "")).lower(),
              r.get("error"))
    n = fresco("SELECT COUNT(*) AS n FROM workspace_fincas_recibos WHERE periodo = '2026-09'")[0]["n"]
    comprueba("y no se cuela ningún recibo de septiembre", int(n) == 0, f"{n} recibos")

    # ----------------------------------- 5. cerrar el ejercicio con recibos pendientes
    print("\n=== 5. Se cierra el ejercicio con recibos sin cobrar")
    pendientes_antes = fresco("SELECT COUNT(*) AS n, COALESCE(SUM(importe),0) AS s "
                              "FROM workspace_fincas_recibos WHERE estado != 'Cobrado'")[0]
    print(f"       quedan {pendientes_antes['n']} recibos sin cobrar: "
          f"{float(pendientes_antes['s']):,.2f} €")
    estado, r, _ = pide("/api/workspace_fincas_cerrar_ejercicio",
                        {"workspace_id": ws, "comunidad_id": com, "ejercicio": 2026})
    print(f"       cierre: HTTP {estado} · {json.dumps(r, ensure_ascii=False)[:170]}")
    despues = fresco("SELECT COUNT(*) AS n, COALESCE(SUM(importe),0) AS s "
                     "FROM workspace_fincas_recibos WHERE estado != 'Cobrado'")[0]
    comprueba("cerrar el ejercicio no borra lo que se debe",
              int(despues["n"]) == int(pendientes_antes["n"]),
              f"antes {pendientes_antes['n']}, después {despues['n']}")

    print(f"\n{'=' * 66}")
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
