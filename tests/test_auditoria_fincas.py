"""Autoauditoría del CRM de fincas y del portal del comunero.

Misma forma que la de inmobiliaria: monta una comunidad entera —ocho propietarios con
coeficientes que suman 100, tres meses de recibos con dos morosos, contabilidad, una
junta con sus votos, proveedor y presupuesto aprobado— y la recorre por HTTP con una
sesión de verdad.

Vigila cuatro cosas:

1. **Que nada reviente.** Los 62 endpoints del módulo, desnudos y con datos.
2. **Que los documentos salgan.** Convocatoria, acta, mandato SEPA y los dos
   certificados. Y que la remesa cuadre con lo que dice cobrar.
3. **Que las cuentas sean las cuentas.** Cifras conocidas sembradas, sumas comparadas.
4. **Que el portal no enseñe de más.** Un comunero ve lo suyo y las cuentas de la
   comunidad; de los demás, nada.

Dos trampas que costaron falsos positivos escribiendo esto y que quedan documentadas
porque volverán a morder a quien toque esto después:

- `iban_valido` comprueba el dígito de control de verdad. Con cuentas inventadas la
  remesa se niega a generarse, y eso parece un fallo del sistema cuando es un fallo de
  la prueba. Los IBAN de aquí llevan el dígito calculado.
- `cuota_mensual` **no** es lo que paga cada vecino: es el importe mensual que se
  reparte entre todos por coeficiente. Con cuota 60 y coeficiente 13,5 %, a ese
  propietario le tocan 8,10 €, no 60. Y el panel de la comunidad usa por defecto el
  mes en curso, no el ejercicio: pedirle datos sin `periodo` devuelve ceros correctos.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

from web import server as S  # noqa: E402

AHORA = "2026-08-13 09:00:00"
CLAVE = "Fincas1234!"

# Coeficientes que suman exactamente 100: la condición del artículo 5. IBAN con dígito
# de control correcto, que el sistema lo comprueba.
VECINOS = [
    ("v1", "ANTONIO LOBATO BARRAGAN", "25111111A", "1 A", 13.50, "ES2321000418400000000001"),
    ("v2", "ANA PEREZ VILLAMIL",      "25222222B", "1 B", 12.25, "ES9321000418400000000002"),
    ("v3", "CARMEN TORRES TORRES",    "25333333C", "2 A", 13.50, "ES6621000418400000000003"),
    ("v4", "MANUEL RUIZ GALVEZ",      "25444444D", "2 B", 12.25, "ES3921000418400000000004"),
    ("v5", "SABRINA VERGARA SANZ",    "25555555E", "3 A", 13.50, ""),          # sin cuenta
    ("v6", "JOSE MARIA CANO LEIVA",   "25666666F", "3 B", 12.25, "ES8221000418400000000006"),
    ("v7", "LUCIA MOLINA SERRANO",    "25777777G", "4 A", 11.50, "ES5521000418400000000007"),
    ("v8", "PEDRO NAVAS ORTEGA",      "25888888H", "4 B", 11.25, "ES2821000418400000000008"),
]
CUOTA = 60.0
PERIODOS = ["2026-05", "2026-06", "2026-07"]
IMPAGADOS = {("v5", p) for p in PERIODOS} | {("v8", "2026-07")}
GASTOS = [("Limpieza portal", 320.0), ("Electricidad zonas comunes", 145.50),
          ("Seguro del edificio", 780.0), ("Ascensor: mantenimiento", 410.0)]
INGRESOS = [("Derrama obras fachada", 2400.0)]


class Comunidad(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "fincas.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        self.descartadas = {}
        self._sembrar()
        self._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.cookie = self._post("/api/login", {"usuario": "administradora", "password": CLAVE},
                                 cookie=False)["cookie"]

    def tearDown(self):
        self.httpd.shutdown(); self.conn.close()
        if self._prev is not None: S.Handler.db_path = self._prev
        self.tmp.cleanup()

    def _ins(self, tabla, datos):
        validas = {r[1] for r in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in validas}
        sobran = set(datos) - set(d)
        if sobran: self.descartadas.setdefault(tabla, set()).update(sobran)
        self.conn.execute(
            f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})",
            tuple(d.values()))
        self.conn.commit()

    def _sembrar(self):
        ws, base = self.ws, dict(created_at=AHORA, updated_at=AHORA)
        self._ins("empresas", dict(id="emp1", nombre="Fincas Velazquez", nif="B29123456",
                                   direccion="Calle Velázquez 11, Málaga", activo=1, **base))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **base))
        self._ins("usuarios", dict(id="u1", nombre="Ana Administradora", usuario="administradora",
                                   email="ana@fincas.test", rol="Administrador", servicio="Fincas",
                                   activo=1, password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="u1",
                                             rol="Owner", **base))
        self.com = "com1"
        self._ins("workspace_fincas_comunidades", dict(
            id=self.com, workspace_id=ws, empresa_id="emp1",
            nombre="C.P Urbanización Barceló Bl 4", cif="H29123456",
            direccion="Avenida Europa 110, Málaga", presidente=VECINOS[0][1],
            secretario=VECINOS[1][1], estado="Activa", num_vecinos=len(VECINOS),
            num_locales=0, num_trasteros=8, num_aparcamientos=8,
            cuota_sugerida=CUOTA, cuota_mensual=CUOTA,
            referencia_catastral="0027104UF7602N", iban="ES9121000418450200051332",
            acreedor_sepa="ES12ZZZH29123456", **base))
        for vid, nombre, nif, piso, coef, iban in VECINOS:
            self._ins("workspace_fincas_vecinos", dict(
                id=vid, workspace_id=ws, comunidad_id=self.com, nombre=nombre, nif=nif,
                piso=piso, coeficiente=coef, iban=iban, telefono="600000010",
                email=f"{vid}@vecinos.test", **base))
        n = 0
        for periodo in PERIODOS:
            for vid, *_ in VECINOS:
                impagado = (vid, periodo) in IMPAGADOS
                n += 1
                self._ins("workspace_fincas_recibos", dict(
                    id=f"r{n}", workspace_id=ws, comunidad_id=self.com, vecino_id=vid,
                    periodo=periodo, concepto=f"Cuota ordinaria {periodo}", importe=CUOTA,
                    estado="Pendiente" if impagado else "Cobrado",
                    fecha_emision=f"{periodo}-01",
                    fecha_cobro="" if impagado else f"{periodo}-05", **base))
        m = 0
        for concepto, importe in GASTOS:
            m += 1
            self._ins("workspace_fincas_contabilidad", dict(
                id=f"g{m}", workspace_id=ws, comunidad_id=self.com, fecha="2026-06-10",
                tipo="Gasto", concepto=concepto, importe=importe, estado="Contabilizado", **base))
        for concepto, importe in INGRESOS:
            m += 1
            self._ins("workspace_fincas_contabilidad", dict(
                id=f"g{m}", workspace_id=ws, comunidad_id=self.com, fecha="2026-04-02",
                tipo="Ingreso", concepto=concepto, importe=importe, estado="Contabilizado", **base))
        self._ins("workspace_fincas_juntas", dict(
            id="j1", workspace_id=ws, comunidad_id=self.com, fecha="2026-09-18", tipo="ordinaria",
            estado="Planificada", hora="18:00", lugar="Portal del edificio",
            convocada_por="El presidente", segunda_convocatoria=1, **base))
        for aid, orden, titulo, clave in (
                ("a1", 1, "Aprobación de cuentas del ejercicio 2025", "simple"),
                ("a2", 2, "Instalación de ascensor", "tres_quintos")):
            self._ins("workspace_fincas_junta_acuerdos", dict(
                id=aid, workspace_id=ws, junta_id="j1", orden=orden, titulo=titulo,
                descripcion="", mayoria_clave=clave, **base))
        for k, (aid, vid, voto) in enumerate([
                ("a1", "v1", "favor"), ("a1", "v2", "favor"), ("a1", "v3", "favor"),
                ("a1", "v4", "contra"), ("a2", "v1", "favor"), ("a2", "v2", "favor"),
                ("a2", "v3", "contra"), ("a2", "v4", "abstencion")]):
            self._ins("workspace_fincas_junta_votos", dict(
                id=f"vt{k}", workspace_id=ws, acuerdo_id=aid, vecino_id=vid, voto=voto, **base))
        for k, vid in enumerate(("v1", "v2", "v3", "v4")):
            self._ins("workspace_fincas_junta_asistentes", dict(
                id=f"as{k}", workspace_id=ws, junta_id="j1", vecino_id=vid,
                asiste=1, representado_por="", **base))
        self._ins("workspace_fincas_presupuesto_anual", dict(
            id="pa1", workspace_id=ws, comunidad_id=self.com, ejercicio=2026, estado="Aprobado",
            fondo_reserva_pct=10.0, fecha_aprobacion="2026-01-15", **base))

    # --- HTTP ---------------------------------------------------------------
    def _get(self, ruta, cookie=True):
        req = urllib.request.Request(self.base + ruta, method="GET")
        if cookie: req.add_header("Cookie", self.cookie)
        return self._lanzar(req)

    def _post(self, ruta, cuerpo, cookie=True):
        req = urllib.request.Request(self.base + ruta, data=json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        if cookie: req.add_header("Cookie", self.cookie)
        return self._lanzar(req)

    def _lanzar(self, req):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                cuerpo, galleta = r.read(), r.headers.get("Set-Cookie")
                return {"estado": r.status, "cuerpo": cuerpo,
                        "cookie": galleta.split(";")[0] if galleta else None,
                        "json": self._json(cuerpo)}
        except urllib.error.HTTPError as e:
            cuerpo = e.read()
            return {"estado": e.code, "cuerpo": cuerpo, "cookie": None, "json": self._json(cuerpo)}

    @staticmethod
    def _json(cuerpo):
        try: return json.loads(cuerpo.decode("utf-8"))
        except Exception: return None

    @staticmethod
    def _texto_pdf(cuerpo):
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(cuerpo)).pages)

    def _token_portal(self, vecino="v1"):
        r = self._post("/api/workspace_fincas_portal_alta",
                       {"workspace_id": self.ws, "comunidad_id": self.com, "vecino_id": vecino})
        self.assertEqual(r["estado"], 200, r["json"])
        return r["json"]["url"].split("token=")[-1]


class NingunEndpointRevientaTests(Comunidad):
    def _rutas(self):
        import re
        return sorted({r for r in re.findall(r'"(/api/[a-z_0-9]+)"', SERVER)
                       if "fincas" in r and len(r) > 20})

    def test_ninguno_devuelve_5xx(self):
        """Ni sin parámetros ni con ellos. El 500 del portal del comprador vivía justo
        detrás de unos parámetros válidos."""
        import urllib.parse
        saco = "?" + urllib.parse.urlencode({
            "workspace_id": self.ws, "empresa_id": "emp1", "comunidad_id": self.com,
            "id": self.com, "vecino_id": "v1", "junta_id": "j1", "acuerdo_id": "a1",
            "ejercicio": "2026", "anio": "2026", "periodo": "2026-07", "limit": "50"})
        rotos = []
        for ruta in self._rutas():
            for q in ("", saco):
                r = self._get(ruta + q)
                if r["estado"] >= 500:
                    rotos.append((ruta, bool(q), r["estado"], str(r["json"])[:120]))
        self.assertEqual(rotos, [], f"endpoints que revientan: {rotos}")


class LosDocumentosSalenTests(Comunidad):
    def test_los_cinco_documentos_se_generan(self):
        from pypdf import PdfReader
        w = f"workspace_id={self.ws}"
        for nombre, ruta in [
                ("Convocatoria", f"/api/workspace_fincas_convocatoria?{w}&id=j1"),
                ("Acta", f"/api/workspace_fincas_acta?{w}&id=j1"),
                ("Mandato SEPA", f"/api/workspace_fincas_mandato?{w}&id=v1"),
                ("Certificado de deuda",
                 f"/api/workspace_fincas_certificado_deuda?{w}&comunidad_id={self.com}&vecino_id=v5"),
                ("Certificado al corriente",
                 f"/api/workspace_fincas_certificado_deuda?{w}&comunidad_id={self.com}&vecino_id=v1")]:
            with self.subTest(nombre):
                r = self._get(ruta)
                self.assertEqual(r["estado"], 200, r["json"])
                self.assertEqual(r["cuerpo"][:4], b"%PDF")
                self.assertGreaterEqual(len(PdfReader(BytesIO(r["cuerpo"])).pages), 1)
                self.assertGreater(len(self._texto_pdf(r["cuerpo"]).strip()), 400)

    def test_el_certificado_distingue_deber_de_estar_al_corriente(self):
        """El mismo endpoint emite dos documentos que dicen lo contrario. Confundirlos
        es entregarle a un vendedor un papel que no puede llevar a la notaría."""
        w = f"workspace_id={self.ws}&comunidad_id={self.com}"
        moroso = self._texto_pdf(self._get(f"/api/workspace_fincas_certificado_deuda?{w}&vecino_id=v5")["cuerpo"])
        limpio = self._texto_pdf(self._get(f"/api/workspace_fincas_certificado_deuda?{w}&vecino_id=v1")["cuerpo"])
        self.assertIn("CERTIFICADO DE ESTAR AL CORRIENTE DE PAGO", limpio)
        self.assertNotIn("CERTIFICADO DE ESTAR AL CORRIENTE DE PAGO", moroso)
        self.assertIn("SABRINA VERGARA SANZ", moroso)


class LaRemesaSepaCuadraTests(Comunidad):
    def test_no_se_domicilia_a_quien_no_tiene_cuenta(self):
        """v5 no tiene IBAN. Meterlo en la remesa es un adeudo devuelto y una comisión."""
        r = self._post("/api/workspace_fincas_remesa_generar",
                       {"workspace_id": self.ws, "comunidad_id": self.com, "periodo": "2026-07"})
        self.assertEqual(r["estado"], 200, r["json"])
        self.assertEqual(r["json"]["incluidos"], 1)
        self.assertEqual(r["json"]["excluidos_sin_iban"], 1)

    def test_el_xml_dice_la_verdad_sobre_si_mismo(self):
        """`CtrlSum` y `NbOfTxs` los valida el banco antes que nadie: si no cuadran con
        los adeudos que lleva dentro, el fichero se rechaza entero."""
        import re
        rid = self._post("/api/workspace_fincas_remesa_generar",
                         {"workspace_id": self.ws, "comunidad_id": self.com,
                          "periodo": "2026-07"})["json"]["id"]
        x = self._get(f"/api/workspace_fincas_remesa_sepa?workspace_id={self.ws}&id={rid}")
        self.assertEqual(x["estado"], 200)
        t = x["cuerpo"].decode("utf-8")
        adeudos = t.count("<DrctDbtTxInf>")
        self.assertEqual(adeudos, 1)
        self.assertEqual(re.findall(r"<NbOfTxs>([^<]*)</NbOfTxs>", t), [str(adeudos)] * 2)
        self.assertEqual(re.findall(r"<CtrlSum>([^<]*)</CtrlSum>", t), ["60.00"] * 2)
        self.assertEqual(sorted(set(re.findall(r"<SeqTp>([^<]*)</SeqTp>", t))), ["FRST"])

    def test_una_cuenta_con_digito_de_control_malo_no_se_cobra(self):
        """`iban_valido` no es cosmético: comprueba el módulo 97."""
        self.assertTrue(S.iban_valido("ES2321000418400000000001"))
        self.assertFalse(S.iban_valido("ES6621000418401234567898"))
        self.conn.execute("UPDATE workspace_fincas_vecinos SET iban='ES6621000418401234567898' "
                          "WHERE id='v8'")
        self.conn.commit()
        r = self._post("/api/workspace_fincas_remesa_generar",
                       {"workspace_id": self.ws, "comunidad_id": self.com, "periodo": "2026-07"})
        self.assertEqual(r["estado"], 400, r["json"])


class LasCuentasSonLasCuentasTests(Comunidad):
    def _q(self):
        return f"?workspace_id={self.ws}&comunidad_id={self.com}&ejercicio=2026"

    def test_la_morosidad_cuenta_deudores_recibos_e_importe(self):
        r = self._get("/api/workspace_fincas_morosidad" + self._q())
        res = r["json"]["resumen"]
        self.assertEqual(res["deudores"], 2)
        self.assertEqual(res["recibos_impagados"], len(IMPAGADOS))
        self.assertAlmostEqual(res["deuda_total"], len(IMPAGADOS) * CUOTA, places=2)

    def test_la_memoria_no_se_contradice_a_si_misma(self):
        """El gasto caía a la contabilidad simple cuando no hay partida doble, pero el
        ingreso no, y el resultado se calculaba con los del libro. Una comunidad que
        lleve las cuentas sin asientos veía «gastado 1.655,50 · ingresado 0 ·
        resultado 0»: tres números que no se relacionan entre sí, en el documento que
        se lleva a la junta."""
        m = self._get("/api/workspace_fincas_balance" + self._q())["json"]["memoria"]
        self.assertAlmostEqual(m["gastado"], sum(i for _, i in GASTOS), places=2)
        self.assertAlmostEqual(m["ingresado"], sum(i for _, i in INGRESOS), places=2)
        self.assertAlmostEqual(m["resultado"], m["ingresado"] - m["gastado"], places=2)
        self.assertAlmostEqual(m["desviacion"], m["presupuestado"] - m["gastado"], places=2)

    def test_los_recibos_cobrados_y_pendientes_suman_lo_emitido(self):
        m = self._get("/api/workspace_fincas_balance" + self._q())["json"]["memoria"]
        emitido = len(PERIODOS) * len(VECINOS) * CUOTA
        self.assertAlmostEqual(m["recibos_cobrados"] + m["recibos_pendientes"], emitido, places=2)

    def test_los_coeficientes_suman_cien(self):
        """Si no suman 100 el reparto no es el del artículo 5, y el panel tiene que
        poder decirlo."""
        d = self._get(f"/api/workspace_fincas_comunidad_dashboard?workspace_id={self.ws}"
                      f"&comunidad_id={self.com}&periodo=2026-07")["json"]
        self.assertAlmostEqual(d["censo"]["suma_coeficientes"], 100.0, places=2)
        self.assertEqual(d["censo"]["sin_coeficiente"], 0)

    def test_el_panel_del_mes_ve_los_recibos_de_ese_mes(self):
        """Sin `periodo` el panel usa el mes en curso: pedirle el ejercicio entero y
        leer ceros es un error de quien pregunta, no del panel."""
        d = self._get(f"/api/workspace_fincas_comunidad_dashboard?workspace_id={self.ws}"
                      f"&comunidad_id={self.com}&periodo=2026-07")["json"]
        self.assertEqual(d["recibos"]["recibos"], len(VECINOS))
        self.assertAlmostEqual(d["recibos"]["emitido"], len(VECINOS) * CUOTA, places=2)


class ElRepartoPorCoeficienteTests(Comunidad):
    def test_la_cuota_mensual_se_reparte_no_se_cobra_a_cada_uno(self):
        """`cuota_mensual` es el importe que se reparte entre todos por coeficiente, no
        lo que paga cada vecino. Con 60 € y un coeficiente del 13,5 %, a ese propietario
        le tocan 8,10 €. Quien lea el campo como «cuota por vecino» multiplicará por
        ocho el recibo de la comunidad."""
        r = self._post("/api/workspace_fincas_recibos_emitir",
                       {"workspace_id": self.ws, "comunidad_id": self.com, "periodo": "2026-08",
                        "concepto": "Cuota ordinaria 2026-08"})
        self.assertEqual(r["estado"], 200, r["json"])
        self.assertEqual(r["json"]["creados"], len(VECINOS))
        filas = self.conn.execute(
            "SELECT vecino_id, importe FROM workspace_fincas_recibos WHERE periodo='2026-08'"
        ).fetchall()
        importes = {f["vecino_id"]: f["importe"] for f in filas}
        self.assertAlmostEqual(importes["v1"], round(CUOTA * 13.50 / 100, 2), places=2)
        self.assertAlmostEqual(sum(importes.values()), CUOTA, places=2)

    def test_el_portal_anuncia_lo_que_de_verdad_se_le_va_a_cobrar(self):
        """El aviso de próximos recibos y el emisor tienen que decir lo mismo, o el
        propietario descubre la diferencia en el banco."""
        avance = self._get(f"/api/workspace_fincas_portal_public?token={self._token_portal('v1')}",
                           cookie=False)["json"]["avance"]
        self._post("/api/workspace_fincas_recibos_emitir",
                   {"workspace_id": self.ws, "comunidad_id": self.com, "periodo": "2026-08"})
        emitido = self.conn.execute(
            "SELECT importe FROM workspace_fincas_recibos WHERE periodo='2026-08' AND vecino_id='v1'"
        ).fetchone()["importe"]
        self.assertAlmostEqual(avance["estimacion"], emitido, places=2)


class ElPortalDelComuneroTests(Comunidad):
    def test_se_sirve_sin_sesion_y_un_token_inventado_no(self):
        t = self._token_portal()
        self.assertEqual(self._get(f"/api/workspace_fincas_portal_public?token={t}",
                                   cookie=False)["estado"], 200)
        self.assertEqual(self._get("/api/workspace_fincas_portal_public?token=noexiste",
                                   cookie=False)["estado"], 404)

    def test_el_comunero_ve_lo_suyo(self):
        j = self._get(f"/api/workspace_fincas_portal_public?token={self._token_portal('v1')}",
                      cookie=False)["json"]
        self.assertEqual(j["propietario"]["nombre"], VECINOS[0][1])
        self.assertEqual(j["propietario"]["piso"], VECINOS[0][3])
        self.assertAlmostEqual(j["propietario"]["coeficiente"], VECINOS[0][4], places=2)
        for bloque in ("balance", "avance", "documentos", "juntas", "incidencias", "recibos"):
            with self.subTest(bloque=bloque):
                self.assertIn(bloque, j)

    def test_no_ve_a_los_demas_propietarios(self):
        """El artículo 20 le da derecho a la información de la comunidad, no a la ficha
        de sus vecinos: ni nombres, ni NIF, ni cuentas."""
        crudo = json.dumps(self._get(
            f"/api/workspace_fincas_portal_public?token={self._token_portal('v1')}",
            cookie=False)["json"], ensure_ascii=False)
        for vid, nombre, nif, piso, coef, iban in VECINOS[1:]:
            with self.subTest(vid):
                self.assertNotIn(nombre, crudo)
                self.assertNotIn(nif, crudo)
                if iban: self.assertNotIn(iban, crudo)

    def test_tampoco_ve_su_propia_cuenta_bancaria(self):
        """No la necesita para nada y el enlace viaja por correo."""
        crudo = json.dumps(self._get(
            f"/api/workspace_fincas_portal_public?token={self._token_portal('v1')}",
            cookie=False)["json"], ensure_ascii=False)
        self.assertNotIn(VECINOS[0][5], crudo)

    def test_ve_las_cuentas_de_la_comunidad(self):
        b = self._get(f"/api/workspace_fincas_portal_public?token={self._token_portal('v1')}",
                      cookie=False)["json"]["balance"]
        self.assertAlmostEqual(b["gastado"], sum(i for _, i in GASTOS), places=2)
        self.assertAlmostEqual(b["ingresado"], sum(i for _, i in INGRESOS), places=2)


if __name__ == "__main__":
    unittest.main()
