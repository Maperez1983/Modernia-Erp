"""Seguros, RRHH, financiación y documental: los 154 endpoints que faltaban.

Inmobiliaria y fincas ya tenían su barrido; gestoría lo cubre `test_auditoria_gestoria`.
Estos cuatro módulos no los había tocado nadie, y salieron tres fallos que no se ven
leyendo el código —los tres eran el mismo tipo de descuido, no un error de lógica—:

- `hipotecas_firmadas_pdf` leía `payload` estando en el manejador de GET, donde esa
  variable no existe. Reventaba **siempre**: nadie ha podido descargar nunca ese PDF.
- `workspace_rrhh_nominas_import` convertía el mes a entero antes de validarlo, así que
  un «2026-08» —la forma en que se escribe un periodo en el resto del CRM— daba un 500
  en vez del «month inválido» que el propio código tiene diez líneas más abajo.
- `fin_checklist_generate` seguía adelante cuando el asesoramiento no existía e
  insertaba tareas colgadas de un id ausente, hasta que saltaba la clave ajena.

Un 500 no es sólo una pantalla fea: en Postgres deja la transacción abortada y todo lo
que venga después en la misma petición muere con ella.
"""

import json
import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

from web import server as S  # noqa: E402

AHORA = "2026-08-18 09:00:00"
CLAVE = "Auditoria1234!"


class Casa(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "a.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("empresas", dict(id="emp1", nombre="Grupo Modernia", nif="B29123456",
                                   activo=1, **base))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=self.ws,
                                             empresa_id="emp1", **base))
        self._ins("usuarios", dict(id="u1", nombre="Ana", usuario="auditora",
                                   email="a@x.test", rol="Administrador", activo=1,
                                   servicio="Administración,Seguros,RRHH,Financiaciones",
                                   password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=self.ws,
                                             usuario_id="u1", rol="Owner", **base))
        self._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.cookie = self._post("/api/login", {"usuario": "auditora",
                                                "password": CLAVE}, cookie=False)["cookie"]

    def tearDown(self):
        self.httpd.shutdown(); self.conn.close()
        if self._prev is not None: S.Handler.db_path = self._prev
        self.tmp.cleanup()

    def _ins(self, tabla, datos):
        validas = {r[1] for r in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in validas}
        self.conn.execute(f"INSERT INTO {tabla} ({','.join(d)}) "
                          f"VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        self.conn.commit()

    def _lanzar(self, req):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                cuerpo, g = r.read(), r.headers.get("Set-Cookie")
                return {"estado": r.status, "cuerpo": cuerpo,
                        "cookie": g.split(";")[0] if g else None, "json": self._json(cuerpo)}
        except urllib.error.HTTPError as e:
            cuerpo = e.read()
            return {"estado": e.code, "cuerpo": cuerpo, "cookie": None, "json": self._json(cuerpo)}

    def _get(self, ruta, cookie=True):
        req = urllib.request.Request(self.base + ruta, method="GET")
        # `self.cookie` puede quedar vacía tras pasar por `/api/logout`, y mandarla
        # como cabecera nula revienta el cliente antes de salir.
        if cookie and self.cookie: req.add_header("Cookie", self.cookie)
        return self._lanzar(req)

    def _post(self, ruta, cuerpo, cookie=True):
        req = urllib.request.Request(self.base + ruta, data=json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        if cookie and self.cookie: req.add_header("Cookie", self.cookie)
        return self._lanzar(req)

    @staticmethod
    def _json(cuerpo):
        try: return json.loads(cuerpo.decode("utf-8"))
        except Exception: return None


class NingunoDeLosCuatroModulosRevientaTests(Casa):
    FAMILIAS = ("seguro", "rrhh", "registro_horario", "nomina", "ausencia",
                "hipoteca", "documento", "docs", "ocr", "s3_")

    def _rutas(self):
        """Gestoría queda fuera a propósito: tiene su propia auditoría en
        `test_auditoria_gestoria`, y dos barridos editando los mismos manejadores a la
        vez se pisan. `/api/gestoria_docs` revienta con la misma clave ajena que los de
        aquí —inserta con un `cliente_id` que no comprueba— y está anotado para que lo
        arregle quien lleva ese módulo."""
        import re
        return sorted({r for r in re.findall(r'"(/api/[a-z_0-9]+)"', SERVER)
                       if (any(f in r for f in self.FAMILIAS) or r.startswith("/api/fin_"))
                       and "gestoria" not in r})

    def test_ni_con_get_ni_con_post(self):
        import urllib.parse
        saco = urllib.parse.urlencode({
            "workspace_id": self.ws, "empresa_id": "emp1", "id": "cli1",
            "cliente_id": "cli1", "persona_id": "p1", "usuario_id": "u1",
            "asesoramiento_id": "fa1", "year": "2026", "month": "2026-08",
            "periodo": "2026-08", "ejercicio": "2026", "key": "docs/x.pdf", "limit": "50"})
        cuerpo = dict(urllib.parse.parse_qsl(saco))
        cuerpo.update({"nombre": "Prueba", "email": "p@x.test", "importe": 100})
        rutas = self._rutas()
        self.assertGreater(len(rutas), 120, "no reconozco los endpoints de estos módulos")
        rotos = []
        for ruta in rutas:
            for etiqueta, r in (("GET", self._get(f"{ruta}?{saco}")),
                                ("POST", self._post(ruta, cuerpo))):
                if r["estado"] >= 500:
                    rotos.append((etiqueta, ruta, r["estado"], str(r["json"])[:110]))
        self.assertEqual(rotos, [], f"revientan: {rotos}")


class LosTransversalesTampocoRevientanTests(Casa):
    """Los 125 que no son de ningún módulo: sesión, workspace, usuarios, empresas,
    catálogos, códigos postales, auditoría.

    Con una trampa que invalidó el primer barrido entero: la lista incluye
    `/api/logout`, así que a mitad de recorrido la prueba se cerraba su propia sesión y
    todo lo que venía después contestaba 401 **sin llegar al código**. Salían 22
    respuestas buenas donde había 76, y un fallo quedó tapado. Aquí se vuelve a entrar
    en cuanto aparece un 401, que en este contexto es señal de eso y no un hallazgo."""

    def _rutas(self):
        import re
        MOD = ("seguro", "rrhh", "registro_horario", "nomina", "ausencia", "hipoteca",
               "documento", "docs", "ocr", "s3_", "gestoria", "modelo_", "asiento",
               "conta", "fincas", "inmueble", "captacion", "demanda", "cliente",
               "portal", "visita", "alquiler", "compraventa", "operacion", "fiscal",
               "iivtnu", "renta", "legal", "copilot", "catastro")
        # `logout` fuera: llamarlo a mitad del barrido cierra la sesión de la propia
        # prueba y todo lo que viene después contesta 401 sin llegar al código —así se
        # perdieron 54 respuestas buenas y quedó tapado un 500 en el primer intento—.
        # Y reintentar el acceso tampoco vale: el login tiene límite de intentos (429),
        # así que el remedio bloqueaba la cuenta. Se entra una vez y no se sale.
        return sorted({r for r in re.findall(r'"(/api/[a-z_0-9]+)"', SERVER)
                       if not any(m in r for m in MOD) and not r.startswith("/api/fin_")
                       and r not in ("/api/logout", "/api/login")})

    def test_ni_con_get_ni_con_post(self):
        import urllib.parse
        saco = urllib.parse.urlencode({
            "workspace_id": self.ws, "empresa_id": "emp1", "id": "u1", "usuario_id": "u1",
            "year": "2026", "anio": "2026", "limit": "50", "q": "a", "tabla": "clientes"})
        cuerpo = dict(urllib.parse.parse_qsl(saco))
        cuerpo.update({"nombre": "Prueba", "apellido": "Apellido", "email": "p@x.test",
                       "concepto": "prueba", "servicio": "inmobiliaria"})
        rutas = self._rutas()
        self.assertGreater(len(rutas), 100, "no reconozco los endpoints transversales")
        rotos = []
        for ruta in rutas:
            for etiqueta, r in (("GET", self._get(f"{ruta}?{saco}")),
                                ("POST", self._post(ruta, cuerpo))):
                self.assertNotEqual(r["estado"], 401,
                                    f"{etiqueta} {ruta}: la prueba ha perdido la sesión")
                if r["estado"] >= 500:
                    rotos.append((etiqueta, ruta, r["estado"], str(r["json"])[:110]))
        self.assertEqual(rotos, [], f"revientan: {rotos}")

    def test_nadie_puede_echarse_a_si_mismo(self):
        """Desactivar revoca todas las sesiones del usuario: hacerlo sobre uno mismo es
        cerrarse la puerta desde fuera, y si además eras el único administrador ya no
        queda nadie que pueda volver a abrirla."""
        r = self._post("/api/usuarios_delete", {"id": "u1", "workspace_id": self.ws})
        self.assertEqual(r["estado"], 409, r["json"])
        self.assertIn("tu propia cuenta", str(r["json"]))
        # y sigue dentro: la sesión no se ha ido a ninguna parte
        self.assertEqual(self._get("/api/me")["estado"], 200)

    def test_no_se_queda_el_espacio_sin_administrador(self):
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("usuarios", dict(id="u2", nombre="Bea", usuario="bea", email="b@x.test",
                                   rol="Administrador", activo=1,
                                   password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wm2", workspace_id=self.ws,
                                             usuario_id="u2", rol="Admin", **base))
        # Bea es la otra administradora; con dos, echar a una está permitido.
        r = self._post("/api/usuarios_delete", {"id": "u2", "workspace_id": self.ws})
        self.assertEqual(r["estado"], 200, r["json"])
        # Ahora Ana es la única. Antes del fix de 2026-09-06, cualquier `usuarios.rol`
        # legacy ("Administrador") bastaba para intentarlo desde fuera del workspace;
        # ahora ese atajo exige pertenencia real (Owner/Admin) al workspace concreto,
        # así que "root" (sólo "Miembro" aquí) ya ni siquiera llega a esta comprobación
        # de negocio — recibe 403 antes. La comprobación de "no dejar el espacio sin
        # administrador" se sigue probando aquí, pero con quien SÍ puede llegar a
        # ejercerla de verdad desde fuera: un superadmin real de la allowlist.
        self._ins("usuarios", dict(id="u3", nombre="Superadmin", usuario="root",
                                   email="r@x.test", rol="Administrador", activo=1,
                                   password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wm3", workspace_id=self.ws,
                                             usuario_id="u3", rol="Miembro", **base))
        cookie_root = self._post("/api/login", {"usuario": "root", "password": CLAVE},
                                 cookie=False)["cookie"]
        anterior, self.cookie = self.cookie, cookie_root
        prev_allowlist = S.APP_SUPERADMIN_USERNAMES
        S.APP_SUPERADMIN_USERNAMES = "root"
        try:
            r = self._post("/api/usuarios_delete", {"id": "u1", "workspace_id": self.ws})
            self.assertEqual(r["estado"], 409, r["json"])
            self.assertIn("único administrador", str(r["json"]))
        finally:
            self.cookie = anterior
            S.APP_SUPERADMIN_USERNAMES = prev_allowlist

    def test_un_administrador_legacy_ajeno_ya_ni_llega_a_intentarlo(self):
        """Antes del fix de 2026-09-06, `usuarios.rol="Administrador"` era un atajo
        GLOBAL: cualquier tenant con ese rol podía tocar usuarios de OTRO workspace.
        Confirmado en vivo ese día con una cadena completa de toma de cuenta
        cross-tenant. Ahora ese rol legacy solo cuenta si el actor YA es Owner/Admin
        real del workspace objetivo (o de alguno de los del usuario objetivo)."""
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("workspaces", dict(id="ws-ajeno", nombre="Otro tenant", slug="ws-ajeno",
                                     estado="Activo", plan="Enterprise", **base))
        self._ins("usuarios", dict(id="u9", nombre="Root ajeno", usuario="root_ajeno",
                                   email="ra@x.test", rol="Administrador", activo=1,
                                   password_hash=S.hash_password(CLAVE), **base))
        # "root_ajeno" es Administrador global pero no pertenece a self.ws en absoluto.
        cookie_root = self._post("/api/login", {"usuario": "root_ajeno", "password": CLAVE},
                                 cookie=False)["cookie"]
        anterior, self.cookie = self.cookie, cookie_root
        try:
            r = self._post("/api/usuarios_update", {"id": "u1", "password": "OtraClave123!"})
            self.assertEqual(r["estado"], 403, r["json"])
        finally:
            self.cookie = anterior

    def test_un_movimiento_sin_concepto_es_un_400(self):
        """`concepto` es NOT NULL en la tabla y nadie lo comprobaba."""
        r = self._post("/api/movimientos", {"empresa_id": "emp1", "anio": 2026,
                                            "empresa_nombre": "Grupo Modernia"})
        self.assertEqual(r["estado"], 400, r["json"])
        self.assertIn("concepto", str(r["json"]))

    def test_una_accion_sobre_un_cliente_que_no_existe_es_un_404(self):
        r = self._post("/api/acciones", {"empresa_id": "emp1", "servicio": "inmobiliaria",
                                         "cliente_id": "no-existe", "asunto": "x"})
        self.assertEqual(r["estado"], 404, r["json"])


class LosTresQueSalieronTests(Casa):
    def test_el_pdf_de_hipotecas_firmadas_no_muere_al_abrirlo(self):
        """Leía `payload` en un GET: `UnboundLocalError` en el 100 % de las llamadas."""
        r = self._get("/api/hipotecas_firmadas_pdf?empresa_id=emp1&year=2026")
        self.assertLess(r["estado"], 500, r["json"])

    def test_un_mes_mal_escrito_es_un_400_y_no_un_500(self):
        r = self._post("/api/workspace_rrhh_nominas_import",
                       {"workspace_id": self.ws, "doc_key": "x.pdf",
                        "year": "2026", "month": "2026-08"})
        self.assertEqual(r["estado"], 400, r["json"])
        self.assertIn("month", str(r["json"]))

    def test_un_asesoramiento_que_no_existe_es_un_404(self):
        """Insertaba tareas colgadas de un id ausente hasta que saltaba la clave ajena."""
        r = self._post("/api/fin_checklist_generate",
                       {"workspace_id": self.ws, "asesoramiento_id": "no-existe"})
        self.assertEqual(r["estado"], 404, r["json"])

    def test_las_expresiones_regulares_de_los_portales_van_escapadas(self):
        """El JS de los portales viaja dentro de una cadena de Python: un `\\d` suelto
        avisa hoy y será un error de sintaxis en una versión próxima."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            compile(SERVER, "server.py", "exec")


class NadieEntraEnElEspacioDelVecinoTests(Casa):
    """El barrido anterior dice que ningún transversal revienta; éste dice que ninguno
    contesta a quien no es de la casa. Un usuario que sólo pertenece al espacio B llama
    a los 123 endpoints pasando el `workspace_id` del espacio A, que es donde está todo
    lo marcado. Cualquier 200 con la marca dentro sería una fuga, y cualquier fila nueva
    en A sería peor todavía: escribir en la casa del vecino."""

    MARCA = "ZZSECRETOZZ"
    INTRUSION = "XXINTRUSIONXX"

    def _marca(self, tabla, datos):
        """Como `_ins`, pero se planta si la tabla no existe: sembrar en silencio una
        tabla ausente deja el endpoint sin probar y la prueba en verde igualmente."""
        cols = {r[1] for r in self.conn.execute(f"pragma table_info({tabla})")}
        self.assertTrue(cols, f"{tabla} no existe: la marca no se sembraría")
        self._ins(tabla, datos)

    def setUp(self):
        super().setUp()
        # Estas tablas se crean tarde, la primera vez que alguien pisa su endpoint.
        S.ensure_workspace_core_tables(self.conn)
        S.ensure_workspace_product_tables(self.conn)
        base = dict(created_at=AHORA, updated_at=AHORA)
        m = self.MARCA
        self._marca("clientes", dict(id="cliA", nombre=f"Cliente {m}", telefono="600111222",
                                   empresa_id="emp1", workspace_id=self.ws, **base))
        self._marca("acciones", dict(id="acA", empresa_id="emp1", workspace_id=self.ws,
                                   cliente_id="cliA", asunto=f"Accion {m}",
                                   servicio="inmobiliaria", **base))
        self._marca("movimientos", dict(id="movA", empresa_id="emp1", workspace_id=self.ws,
                                      anio=2026, concepto=f"Movimiento {m}", importe=100.0, **base))
        self._marca("workspace_facturacion_series", dict(id="seA", workspace_id=self.ws,
                                                         empresa_id="emp1", servicio="inmobiliaria",
                                                         serie=f"Serie {m}", prefijo="FA", **base))
        self._marca("workspace_contratos", dict(id="ctA", workspace_id=self.ws, empresa_id="emp1",
                                              titulo=f"Contrato {m}", estado="Vigente", **base))
        self._marca("workspace_presupuestos", dict(id="prA", workspace_id=self.ws, empresa_id="emp1",
                                                 titulo=f"Presupuesto {m}", numero="P-1",
                                                 estado="Borrador", total=1000.0, **base))
        self._marca("workspace_registro_personal", dict(id="peA", workspace_id=self.ws,
                                                      empresa_id="emp1", nif="25111111A",
                                                      nombre=f"Empleado {m}", **base))
        self._marca("workspace_automatizaciones", dict(id="auA", workspace_id=self.ws,
                                                     nombre=f"Regla {m}", trigger_key="alta_cliente",
                                                     modulo_key="inmobiliaria", enabled=1,
                                                     action_summary=f"Avisar a {m}", **base))
        self._marca("workspace_links", dict(id="lkA", source_workspace_id=self.ws,
                                          target_workspace_id=self.ws, link_type="socio",
                                          role="socio", notes=f"Enlace {m}", **base))
        # El vecino: dueño de su espacio y de nada más.
        self.otro = "espaciovecino00000000000000000000"
        self._ins("workspaces", dict(id=self.otro, nombre="Espacio Vecino", slug="vecino", **base))
        self._ins("empresas", dict(id="empB", nombre="Empresa Vecina", nif="B29999999",
                                   activo=1, **base))
        self._ins("workspace_empresas", dict(id="weB", workspace_id=self.otro,
                                             empresa_id="empB", **base))
        self._ins("usuarios", dict(id="uB", nombre="Intruso", usuario="intruso",
                                   email="i@x.test", rol="Usuario", activo=1,
                                   password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wmB", workspace_id=self.otro,
                                             usuario_id="uB", rol="Owner", **base))
        self.cookie = self._post("/api/login", {"usuario": "intruso", "password": CLAVE},
                                 cookie=False)["cookie"]

    def test_ni_lee_ni_escribe_en_el_espacio_ajeno(self):
        import urllib.parse
        saco = urllib.parse.urlencode({"workspace_id": self.ws, "empresa_id": "emp1",
                                       "id": "emp1", "usuario_id": "u1", "year": "2026",
                                       "anio": "2026", "limit": "50", "q": "ZZ",
                                       "tabla": "clientes"})
        rutas = LosTransversalesTampocoRevientanTests._rutas(self)
        fugas = []
        for ruta in rutas:
            cuerpo = dict(urllib.parse.parse_qsl(saco))
            cuerpo.update({"nombre": self.INTRUSION, "titulo": self.INTRUSION,
                           "concepto": self.INTRUSION, "asunto": self.INTRUSION,
                           "notes": self.INTRUSION, "descripcion": self.INTRUSION,
                           "email": "intruso@x.test", "servicio": "inmobiliaria"})
            for etiqueta, r in (("GET", self._get(f"{ruta}?{saco}")),
                                ("POST", self._post(ruta, cuerpo))):
                if r["estado"] == 200 and self.MARCA in json.dumps(r["json"], ensure_ascii=False):
                    fugas.append((etiqueta, ruta))
        self.assertEqual(fugas, [], f"se ve lo del vecino: {fugas}")

        # Control: sin esto la prueba pasaría igual aunque ningún endpoint devolviera
        # nada nunca. La dueña del espacio sí tiene que ver sus propias marcas.
        self.cookie = self._post("/api/login", {"usuario": "auditora", "password": CLAVE},
                                 cookie=False)["cookie"]
        vistos = {ruta for ruta in rutas
                  if self.MARCA in json.dumps(self._get(f"{ruta}?{saco}")["json"],
                                              ensure_ascii=False)}
        self.assertGreaterEqual(len(vistos), 8,
                                f"la dueña tampoco ve lo suyo: el barrido no prueba nada ({vistos})")

        escritas = []
        for (tabla,) in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            cols = [c[1] for c in self.conn.execute(f"pragma table_info({tabla})")]
            if not cols:
                continue
            cond = " OR ".join(f"CAST({c} AS TEXT) LIKE '%{self.INTRUSION}%'" for c in cols)
            try:
                if self.conn.execute(f"SELECT 1 FROM {tabla} WHERE {cond} LIMIT 1").fetchone():
                    escritas.append(tabla)
            except Exception:
                continue
        self.assertEqual(escritas, [], f"ha escrito en la casa ajena: {escritas}")


class TodoManejadorEstaDadoDeAltaTests(unittest.TestCase):
    """`_do_POST` filtra por una lista blanca antes de mirar los manejadores. Escribir un
    manejador nuevo y olvidarse de la lista no rompe nada visible al programar: el
    endpoint contesta 404 «Endpoint no valido», igual que si no existiera. Ya había
    pasado una vez —una tanda entera arreglada a mano— y volvió a pasar con otros tres:
    cerrar una compraventa, la preparación guiada del inmueble y reprocesar el OCR de
    una nómina, este último silencioso porque el front se lo traga en un catch vacío.

    Las excepciones de abajo son manejadores POST que existen pero se piden por GET, que
    es como los llama la interfaz; ésos no necesitan estar en la lista."""

    SE_PIDEN_POR_GET = {
        "/api/workspace_registro_horario_pdf",
        "/api/workspace_registro_horario_xml",
        "/api/ocr_job",
    }
    # Escritos pero no los llama nadie: quedan fuera a propósito, para no dar de alta
    # superficie que no se usa. Si algún día se enganchan, hay que meterlos en la lista.
    SIN_USAR = {"/api/hipotecas_fichas_pdf", "/api/hipotecas_listado_pdf"}

    def test_ningun_manejador_post_se_queda_fuera_de_la_lista(self):
        lineas = SERVER.splitlines()
        ini = next(i for i, l in enumerate(lineas) if l.strip().startswith("def _do_POST"))
        fin = next(i for i, l in enumerate(lineas) if i > ini and l.startswith("    def handle_api"))
        cuerpo = "\n".join(lineas[ini:fin])
        corte = cuerpo.index('json_response(self, {"error": "Endpoint no valido"}, status=404)')
        permitidas = set(re.findall(r'"(/api/[a-z_0-9]+)"', cuerpo[:corte]))
        self.assertGreater(len(permitidas), 200, "no reconozco la lista blanca de POST")
        manejadores = set(re.findall(r'(?:parsed\.)?path == "(/api/[a-z_0-9]+)"', cuerpo[corte:]))
        self.assertGreater(len(manejadores), 200, "no reconozco los manejadores de POST")
        huerfanos = sorted(manejadores - permitidas - self.SE_PIDEN_POR_GET - self.SIN_USAR)
        self.assertEqual(huerfanos, [], "manejador escrito que la lista no deja pasar: "
                                        f"contestará «Endpoint no valido» {huerfanos}")


if __name__ == "__main__":
    unittest.main()
