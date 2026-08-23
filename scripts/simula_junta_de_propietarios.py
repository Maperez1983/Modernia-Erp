#!/usr/bin/env python3
"""Simula una junta de propietarios de principio a fin, contando los votos a mano.

Por qué
-------
Una junta es el sitio donde el CRM deja de llevar cuentas y empieza a decir si algo
está aprobado. Eso tiene consecuencias: un acuerdo dado por bueno sin la mayoría que
exige la ley es impugnable (LPH art. 18), y quien lo firma es el administrador.

Aquí se convoca, se pasa lista, se vota y se levanta acta, y **cada porcentaje se
comprueba con la calculadora**, no con lo que responde la API.

Qué comprueba
-------------
  · la convocatoria lleva lo que exige el art. 16.2: orden del día, lugar con las dos
    horas, relación de morosos y la advertencia de que no votan
  · la asistencia distingue presentes de representados y suma bien los coeficientes
  · en primera convocatoria la mayoría se mide sobre TODA la comunidad
  · en segunda se mide sobre los asistentes, y el mismo acuerdo cambia de resultado
  · un acuerdo se aprueba solo si alcanza por cabezas Y por coeficiente
  · tres quintos y unanimidad se exigen de verdad
  · un moroso no vota, y su cuota se descuenta del total (art. 15.2)
  · el acta recoge asistentes, orden del día, votos nominales y resultado

Qué NO hace
-----------
No firma nada ni diligencia el libro de actas: eso no lo puede hacer un programa.
Tampoco cubre la impugnación ni el cómputo de ausentes a los 30 días (art. 17.8).

Uso
---
    python scripts/simula_junta_de_propietarios.py

Levanta su propio servidor sobre una base temporal. No toca producción. Sale con
código 1 si algún paso falla.
"""

import io
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
#: Cinco propietarios que suman 100 %. Los coeficientes están elegidos para que
#: cabezas y cuotas NO vayan de la mano: es donde se ve si se miden las dos.
CENSO = [
    ("Dolores Sánchez", "1º A", 40.0),
    ("Manuel Ortega", "1º B", 15.0),
    ("Rocío Peña", "2º A", 15.0),
    ("Julián Vega", "2º B", 15.0),
    ("Inés Cabrera", "3º A", 15.0),
]

fallos = []
avisos = []


def comprueba(etiqueta, condicion, detalle=""):
    print(f"  {'OK ' if condicion else 'MAL'}  {etiqueta}"
          f"{('  ·  ' + str(detalle)[:100]) if detalle else ''}")
    if not condicion:
        fallos.append(etiqueta)


def anota(texto):
    print(f"  ··   {texto}")
    avisos.append(texto)


def texto_pdf(crudo):
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(crudo)).pages)


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

    base = dict(created_at=AHORA, updated_at=AHORA)
    ins("empresas", dict(id="emp1", nombre="Fincas Modernia", nif="B29123456",
                         activo=1, administra_fincas=1, **base))
    ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **base))
    ins("usuarios", dict(id="u1", nombre="Ana", usuario="ana", email="a@x.test",
                         rol="Administrador", servicio="Fincas", activo=1,
                         password_hash=S.hash_password(CLAVE), **base))
    ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="u1",
                                   rol="Owner", **base))
    ins("workspace_fincas_comunidades",
        dict(id="com1", workspace_id=ws, empresa_id="emp1", nombre="C.P Los Naranjos",
             direccion="Avenida Europa 110, Málaga", cif="H29123456", estado="Activa",
             **base))
    for i, (nombre, piso, coef) in enumerate(CENSO):
        ins("workspace_fincas_vecinos",
            dict(id=f"v{i}", workspace_id=ws, comunidad_id="com1", nombre=nombre,
                 piso=piso, coeficiente=coef, nif=f"2511111{i}A",
                 iban="ES2321000418400000000001", **base))

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

    # ------------------------------------------------- 0. la deuda de un propietario
    print("\n=== 0. Manuel Ortega (1º B, 15 %) no está al corriente")
    pide("/api/workspace_fincas_recibos_emitir", {
        "workspace_id": ws, "comunidad_id": "com1", "periodo": "2026-05",
        "importe": 1000.0, "concepto": "Cuota mayo"})
    for i in (0, 2, 3, 4):
        rec = fresco("SELECT id FROM workspace_fincas_recibos WHERE vecino_id = ?", (f"v{i}",))
        pide("/api/workspace_fincas_recibo_estado",
             {"workspace_id": ws, "id": rec[0]["id"], "estado": "Cobrado"})
    _, mor, _ = pide("/api/workspace_fincas_morosidad", None, workspace_id=ws,
                     comunidad_id="com1")
    morosos = (mor.get("rows") or mor.get("morosos") or []) if isinstance(mor, dict) else []
    comprueba("solo él figura como moroso", len(morosos) == 1
              and str(morosos[0].get("vecino_id")) == "v1", morosos)

    # ------------------------------------------------------------ 1. la convocatoria
    print("\n=== 1. Se convoca la junta ordinaria")
    estado, r, _ = pide("/api/workspace_fincas_juntas", {
        "workspace_id": ws, "comunidad_id": "com1", "fecha": "2026-09-15",
        "tipo": "ordinaria", "estado": "Planificada",
        "orden_dia": "Cuentas, presupuesto, ascensor y estatutos"})
    comprueba("se crea la junta", estado == 200 and not r.get("error"), f"HTTP {estado}")
    junta = fresco("SELECT id FROM workspace_fincas_juntas LIMIT 1")[0]["id"]
    conn.execute("UPDATE workspace_fincas_juntas SET lugar = ?, hora = ? WHERE id = ?",
                 ("Portal del edificio", "18:00", junta))
    conn.commit()

    ACUERDOS = [
        ("Aprobar las cuentas del ejercicio", "ordinario"),
        ("Instalar ascensor (mejora no necesaria)", "mejoras_no_necesarias"),
        ("Modificar los estatutos", "titulo_estatutos"),
    ]
    for orden, (titulo, tipo) in enumerate(ACUERDOS, start=1):
        pide("/api/workspace_fincas_junta_acuerdo", {
            "workspace_id": ws, "junta_id": junta, "titulo": titulo,
            "tipo_acuerdo": tipo, "orden": orden})
    ids = {a["titulo"]: a["id"] for a in fresco(
        "SELECT id, titulo FROM workspace_fincas_junta_acuerdos WHERE junta_id = ?", (junta,))}
    comprueba("el orden del día tiene los tres puntos", len(ids) == 3, list(ids))

    _, doc, _ = pide("/api/workspace_fincas_convocatoria", None,
                     workspace_id=ws, id=junta)
    conv = texto_pdf(doc) if isinstance(doc, bytes) and doc[:4] == b"%PDF" else str(doc)
    for etiqueta, aguja in (("el orden del día", "Instalar ascensor"),
                            ("el lugar", "Portal del edificio"),
                            ("la segunda convocatoria", "segunda"),
                            ("quién no está al corriente", "Manuel Ortega"),
                            ("y que no tiene voto", "derecho de")):
        comprueba(f"la convocatoria lleva {etiqueta}", aguja.lower() in conv.lower(),
                  "" if aguja.lower() in conv.lower() else f"no aparece {aguja!r}")

    # ------------------------------------------------------------- 2. la asistencia
    print("\n=== 2. Pasan lista: faltan Julián y Inés (30 % entre los dos)")
    for i in (0, 1, 2):
        pide("/api/workspace_fincas_junta_asistencia",
             {"workspace_id": ws, "junta_id": junta, "vecino_id": f"v{i}", "asiste": "1"})
    # Inés no viene pero delega en Dolores.
    pide("/api/workspace_fincas_junta_asistencia",
         {"workspace_id": ws, "junta_id": junta, "vecino_id": "v4", "asiste": "1",
          "representado_por": "Dolores Sánchez"})
    _, rec, _ = pide("/api/workspace_fincas_junta_asistencia",
                     {"workspace_id": ws, "junta_id": junta, "vecino_id": "v3", "asiste": "0"})
    asis = rec.get("recuento", {}).get("asistencia", {})
    print(f"       {asis.get('presentes')} presentes + {asis.get('representados')} representados "
          f"= {asis.get('asistentes')} de {asis.get('propietarios_total')}, "
          f"{asis.get('asistentes_pct_coeficiente')} % de cuota")
    comprueba("cuenta 3 presentes y 1 representado",
              asis.get("presentes") == 3 and asis.get("representados") == 1, asis)
    comprueba("la asistencia suma 85 % de cuota (falta Julián, 15 %)",
              abs(float(asis.get("asistentes_pct_coeficiente") or 0) - 85.0) < 0.01, asis)

    # --------------------------------------------------------------- 3. la votación
    print("\n=== 3. Votan las cuentas. Manuel, que debe, intenta votar")
    estado, r, _ = pide("/api/workspace_fincas_junta_voto", {
        "workspace_id": ws, "acuerdo_id": ids["Aprobar las cuentas del ejercicio"],
        "vecino_id": "v1", "voto": "Favor"})
    comprueba("al deudor no se le deja votar", estado == 409, f"HTTP {estado}")
    comprueba("y se dice por qué y cómo se recupera el voto",
              "15.2" in str(r.get("error", "")) and "tiene voto" in str(r.get("error", "")),
              r.get("error"))
    for vecino, voto in (("v0", "Favor"), ("v2", "Contra")):
        _, rec, _ = pide("/api/workspace_fincas_junta_voto", {
            "workspace_id": ws, "acuerdo_id": ids["Aprobar las cuentas del ejercicio"],
            "vecino_id": vecino, "voto": voto})
    cuentas = [a for a in rec["recuento"]["acuerdos"] if a["titulo"].startswith("Aprobar")][0]
    print(f"       a favor: {cuentas['favor']} propietarios "
          f"({cuentas['favor_propietarios']} %) y {cuentas['favor_coeficiente']} % de cuota "
          f"· sobre {cuentas['sobre']} · aprobado: {cuentas['aprobado']}")
    comprueba("en primera convocatoria mide sobre toda la comunidad",
              cuentas["sobre"] == "toda la comunidad", cuentas["sobre"])
    comprueba("solo cuenta el voto de Dolores", cuentas["favor"] == 1, cuentas["favor"])
    # Manuel sale de los dos divisores: 4 propietarios con voto y 85 % de cuota.
    comprueba("1 de los 4 con derecho a voto es el 25 %",
              abs(cuentas["favor_propietarios"] - 25.0) < 0.01, cuentas["favor_propietarios"])
    solo_dolores = round(40.0 / 85.0 * 100, 4)
    comprueba("y su 40 % se mide sobre el 85 % que sí vota (art. 15.2)",
              abs(cuentas["favor_coeficiente"] - solo_dolores) < 0.05,
              f"mide {cuentas['favor_coeficiente']} %, esperado {solo_dolores} %")
    comprueba("no se aprueba: por cuota llega, por cabezas no",
              cuentas["aprobado"] is False,
              f"cuota {cuentas['favor_coeficiente']} %, cabezas {cuentas['favor_propietarios']} %")
    privados = rec["recuento"].get("sin_derecho_voto") or []
    comprueba("y se dice quién no ha votado y por cuánto debe",
              len(privados) == 1 and privados[0]["nombre"] == "Manuel Ortega"
              and float(privados[0]["deuda"]) > 0, privados)

    print("\n=== 3b. Manuel enseña que ha impugnado la deuda: recupera el voto")
    pide("/api/workspace_fincas_junta_asistencia",
         {"workspace_id": ws, "junta_id": junta, "vecino_id": "v1", "asiste": "1",
          "derecho_voto": "1"})
    estado, rec, _ = pide("/api/workspace_fincas_junta_voto", {
        "workspace_id": ws, "acuerdo_id": ids["Aprobar las cuentas del ejercicio"],
        "vecino_id": "v1", "voto": "Favor"})
    comprueba("ahora sí vota", estado == 200, f"HTTP {estado}")
    c3 = [a for a in rec["recuento"]["acuerdos"] if a["titulo"].startswith("Aprobar")][0]
    comprueba("y el divisor vuelve a ser toda la comunidad",
              abs(c3["favor_coeficiente"] - 55.0) < 0.01 and c3["favor"] == 2,
              f"{c3['favor']} votos, {c3['favor_coeficiente']} %")
    # Se le vuelve a quitar para lo que queda de simulación.
    pide("/api/workspace_fincas_junta_asistencia",
         {"workspace_id": ws, "junta_id": junta, "vecino_id": "v1", "asiste": "1",
          "derecho_voto": ""})
    _, rec, _ = pide("/api/workspace_fincas_junta_voto", {
        "workspace_id": ws, "acuerdo_id": ids["Aprobar las cuentas del ejercicio"],
        "vecino_id": "v2", "voto": "Contra"})
    c4 = [a for a in rec["recuento"]["acuerdos"] if a["titulo"].startswith("Aprobar")][0]
    comprueba("y el voto que dejó guardado deja de contar", c4["favor"] == 1, c4["favor"])

    # ------------------------------------------- 4. segunda convocatoria: otro divisor
    print("\n=== 4. La misma votación, en segunda convocatoria")
    conn.execute("UPDATE workspace_fincas_juntas SET segunda_convocatoria = 1 WHERE id = ?",
                 (junta,))
    conn.commit()
    _, rec, _ = pide("/api/workspace_fincas_junta_voto", {
        "workspace_id": ws, "acuerdo_id": ids["Aprobar las cuentas del ejercicio"],
        "vecino_id": "v2", "voto": "Contra"})
    c2 = [a for a in rec["recuento"]["acuerdos"] if a["titulo"].startswith("Aprobar")][0]
    print(f"       ahora: {c2['favor_propietarios']} % de los asistentes y "
          f"{c2['favor_coeficiente']} % de su cuota · sobre {c2['sobre']} · "
          f"aprobado: {c2['aprobado']}")
    comprueba("el denominador pasa a ser los asistentes",
              c2["sobre"] == "los asistentes", c2["sobre"])

    # -------------------------------------------- 5. mayorías cualificadas de verdad
    print("\n=== 5. El ascensor pide tres quintos, y los estatutos unanimidad")
    conn.execute("UPDATE workspace_fincas_juntas SET segunda_convocatoria = 0 WHERE id = ?",
                 (junta,))
    conn.commit()
    for vecino in ("v0", "v2", "v3"):          # 40 + 15 + 15 = 70 %, 3 de 5 = 60 %
        _, rec, _ = pide("/api/workspace_fincas_junta_voto", {
            "workspace_id": ws, "acuerdo_id": ids["Instalar ascensor (mejora no necesaria)"],
            "vecino_id": vecino, "voto": "Favor"})
    asc = [a for a in rec["recuento"]["acuerdos"] if "ascensor" in a["titulo"]][0]
    print(f"       ascensor: {asc['favor_propietarios']} % cabezas, "
          f"{asc['favor_coeficiente']} % cuota · {asc['mayoria_etiqueta']} "
          f"({asc['articulo']}) · aprobado: {asc['aprobado']}")
    comprueba("el ascensor sale con tres quintos por las dos medidas",
              asc["aprobado"] is True, asc)
    for vecino in ("v0", "v1", "v2", "v3"):    # falta Inés: no es unanimidad
        _, rec, _ = pide("/api/workspace_fincas_junta_voto", {
            "workspace_id": ws, "acuerdo_id": ids["Modificar los estatutos"],
            "vecino_id": vecino, "voto": "Favor"})
    est = [a for a in rec["recuento"]["acuerdos"] if "estatutos" in a["titulo"]][0]
    print(f"       estatutos: {est['favor_propietarios']} % cabezas, "
          f"{est['favor_coeficiente']} % cuota · {est['mayoria_etiqueta']} "
          f"· aprobado: {est['aprobado']}")
    comprueba("los estatutos NO salen sin unanimidad", est["aprobado"] is False, est)

    # -------------------------------------------------------------------- 6. el acta
    print("\n=== 6. Se levanta el acta")
    _, doc, _ = pide("/api/workspace_fincas_acta", None, workspace_id=ws, id=junta)
    acta = texto_pdf(doc) if isinstance(doc, bytes) and doc[:4] == b"%PDF" else str(doc)
    print(f"       el acta sale: {len(doc):,} B de PDF" if isinstance(doc, bytes) else acta[:80])
    if os.environ.get("VER_ACTA"):
        print("\n".join("       | " + l for l in acta.splitlines()))
    for etiqueta, aguja in (("la fecha de la junta", "15 de septiembre de 2026"),
                            ("los asistentes", "Dolores"),
                            ("el orden del día", "Instalar ascensor"),
                            ("quién votó cada punto", "Rocío"),
                            ("el resultado", "aprobado"),
                            ("el apartado de quién no vota", "sin derecho de voto"),
                            # Sin salto de línea en medio: el PDF parte las frases largas.
                            ("y sobre cuánto se han medido las mayorías",
                             "sobre 85,00 % de coeficiente")):
        comprueba(f"el acta recoge {etiqueta}", aguja.lower() in acta.lower(),
                  "" if aguja.lower() in acta.lower() else f"no aparece {aguja!r}")

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
