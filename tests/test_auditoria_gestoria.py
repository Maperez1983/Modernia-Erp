"""Auditoría del CRM de Gestoría: quién puede leer y escribir qué.

En producción esto **no** es un único inquilino. Hay cuatro workspaces —Modernia,
Modernia Centro, DEMOCASA y Verifika²— y nueve empresas, y los datos de gestoría
están repartidos: los 548 expedientes y los 832 trabajos son de Fincas Velazquez,
los 1.225 asientos de Estudio Velazquez, y de los 656 apuntes de contabilidad hay
50 de ANSA INMOASESORES, que es la única empresa de *otro* workspace. Así que
«sólo hay una empresa» no vale como respuesta.

De los 35 bloques que atienden rutas del módulo, **22 no comprueban ningún
ámbito**: leen y escriben con el `empresa_id`, el `cliente_id` o el
`workspace_id` que venga en la petición, sin contrastarlo con la sesión. Estos
tests montan dos workspaces de verdad y comprueban, uno a uno, que el de un lado
no alcanza lo del otro.

Los borrados son los que más duelen, y son los que menos miran: tres de ellos
hacen `DELETE ... WHERE id = ?` a secas, y el de documentos además borra el
fichero de S3.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""

from web import server as S  # noqa: E402

AHORA = "2026-08-15 09:00:00"
CLAVE = "Contrasena1!"


class BaseGestoria(unittest.TestCase):
    """Dos casas distintas: cada workspace con su empresa, su cliente y su gestor.

    `otra` es un workspace aparte, no otra empresa del mismo: es la frontera que
    de verdad tiene que aguantar.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "g.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        self.ws_a = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        base = dict(created_at=AHORA, updated_at=AHORA)
        self.ws_b = "ws-otra"
        self._ins("workspaces", dict(id=self.ws_b, nombre="Otra Casa", slug="otra-casa",
                                     estado="Activo", plan="Enterprise", kind="Directo",
                                     kiosk_pin_required=0, **base))

        for suf, ws in (("a", self.ws_a), ("b", self.ws_b)):
            self._ins("empresas", dict(id=f"emp-{suf}", nombre=f"Empresa {suf.upper()}",
                                       activo=1, **base))
            self._ins("workspace_empresas", dict(id=f"we-{suf}", workspace_id=ws,
                                                 empresa_id=f"emp-{suf}", **base))
            # Rol «Gestor», no Administrador: el Administrador cruza workspaces por
            # diseño y taparía justo lo que hay que medir.
            self._ins("usuarios", dict(id=f"u-{suf}", nombre=f"Gestor {suf.upper()}",
                                       usuario=f"gestor{suf}", email=f"g{suf}@x.test",
                                       rol="Gestor", servicio="Gestoría", activo=1,
                                       password_hash=S.hash_password(CLAVE), **base))
            self._ins("workspace_miembros", dict(id=f"wm-{suf}", workspace_id=ws,
                                                 usuario_id=f"u-{suf}", rol="Miembro", **base))
            self._ins("clientes", dict(id=f"cli-{suf}", nombre=f"Cliente {suf.upper()}",
                                       nif=f"1234567{suf}", empresa_id=f"emp-{suf}",
                                       workspace_id=ws, **base))
            self._ins("clientes_empresas", dict(id=f"ce-{suf}", cliente_id=f"cli-{suf}",
                                                empresa_id=f"emp-{suf}", servicio="gestoria",
                                                **base))
            self._siembra_gestoria(suf)

        self._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.cookie_a = self._login("gestora")
        self.cookie_b = self._login("gestorb")

    def _siembra_gestoria(self, suf):
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("gestoria_docs", dict(id=f"doc-{suf}", empresa_id=f"emp-{suf}",
                                        cliente_id=f"cli-{suf}", nombre=f"Nómina {suf.upper()}",
                                        tipo="Gestoria", referencia_tipo="gestoria",
                                        estado="Recibido", doc_key=f"s3/{suf}.pdf", **base))
        self._ins("gestoria_trabajos", dict(id=f"tra-{suf}", empresa_id=f"emp-{suf}",
                                            cliente_id=f"cli-{suf}", tipo_trabajo="Modelo 303",
                                            estado="Pendiente", importe=150.0, **base))
        self._ins("gestoria_contabilidad", dict(id=f"con-{suf}", empresa_id=f"emp-{suf}",
                                                cliente_id=f"cli-{suf}", fecha="2026-08-01",
                                                concepto=f"Minuta {suf.upper()}", tipo="Ingreso",
                                                importe=300.0, **base))
        self._ins("gestoria_modelos", dict(id=f"mod-{suf}", cliente_id=f"cli-{suf}",
                                           modelo="303", periodicidad="Trimestral",
                                           estado="Pendiente", **base))

    def tearDown(self):
        self.httpd.shutdown()
        self.conn.close()
        if self._prev is not None:
            S.Handler.db_path = self._prev
        self.tmp.cleanup()

    # --- utilidades ---------------------------------------------------------
    def _ins(self, tabla, datos):
        validas = {r[1] for r in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in validas}
        self.conn.execute(
            f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})",
            tuple(d.values()))
        self.conn.commit()

    def _login(self, usuario):
        return self._lanza(urllib.request.Request(
            self.base + "/api/login", method="POST",
            data=json.dumps({"usuario": usuario, "password": CLAVE}).encode(),
            headers={"Content-Type": "application/json"}))["cookie"]

    def _get(self, ruta, cookie):
        req = urllib.request.Request(self.base + ruta)
        req.add_header("Cookie", cookie)
        return self._lanza(req)

    def _post(self, ruta, cuerpo, cookie):
        req = urllib.request.Request(self.base + ruta, method="POST",
                                     data=json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json"})
        req.add_header("Cookie", cookie)
        return self._lanza(req)

    def _lanza(self, req):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                cuerpo, galleta = r.read(), r.headers.get("Set-Cookie")
                return {"estado": r.status, "json": self._json(cuerpo),
                        "cookie": galleta.split(";")[0] if galleta else None}
        except urllib.error.HTTPError as e:
            return {"estado": e.code, "json": self._json(e.read()), "cookie": None}

    @staticmethod
    def _json(cuerpo):
        try:
            return json.loads(cuerpo.decode() or "{}")
        except Exception:
            return {}

    def _existe(self, tabla, id_):
        return bool(self.conn.execute(
            f"SELECT 1 FROM {tabla} WHERE id = ?", (id_,)).fetchone())

    def _filas(self, respuesta):
        d = respuesta["json"]
        for clave in ("rows", "items", "docs", "trabajos", "registros", "data"):
            if isinstance(d.get(clave), list):
                return d[clave]
        return []

    def assertNoAlcanza(self, respuesta, ajeno, que):
        """Ni un 200 con datos del otro, ni un 403/404: cualquiera vale, verlo no."""
        ids = {str(f.get("id") or "") for f in self._filas(respuesta)}
        self.assertNotIn(ajeno, ids, f"{que}: el gestor A ha visto {ajeno}")


class LoQueSeLeeTests(BaseGestoria):
    def test_los_documentos_de_otro_workspace(self):
        """`/api/gestoria_docs` filtra por el `cliente_id` que llegue en la
        petición y no mira la sesión en sus 252 líneas."""
        r = self._get("/api/gestoria_docs?cliente_id=cli-b", self.cookie_a)
        self.assertNoAlcanza(r, "doc-b", "documentos")

    def test_ni_pidiendolos_por_empresa(self):
        r = self._get("/api/gestoria_docs?empresa_id=emp-b", self.cookie_a)
        self.assertNoAlcanza(r, "doc-b", "documentos por empresa")

    def test_ni_pidiendolos_por_workspace(self):
        r = self._get("/api/gestoria_docs?workspace_id=ws-otra", self.cookie_a)
        self.assertNoAlcanza(r, "doc-b", "documentos por workspace")

    def test_los_trabajos(self):
        r = self._get("/api/gestoria_trabajos?empresa_id=emp-b", self.cookie_a)
        self.assertNoAlcanza(r, "tra-b", "trabajos")

    def test_la_contabilidad(self):
        r = self._get("/api/gestoria_contabilidad?empresa_id=emp-b", self.cookie_a)
        self.assertNoAlcanza(r, "con-b", "contabilidad")

    def test_los_modelos_presentados(self):
        """`gestoria_modelos` ni siquiera tiene columna de empresa: su único
        ámbito es el cliente."""
        r = self._get("/api/gestoria_modelos?cliente_id=cli-b", self.cookie_a)
        self.assertNoAlcanza(r, "mod-b", "modelos")

    def test_la_ficha_de_gestoria_del_cliente(self):
        r = self._get("/api/cliente_gestoria?cliente_id=cli-b", self.cookie_a)
        self.assertNotEqual(r["estado"], 200,
                            "el gestor A ha leído la ficha de gestoría del cliente B")


class LaMediaCarteraSinEmpresaTests(BaseGestoria):
    """El riesgo de cerrar el ámbito: dejar fuera a quien sí tiene derecho.

    En producción **1.170 de 2.261 clientes tienen `clientes.empresa_id` vacío** y
    1.166 están vinculados por `clientes_empresas` —1.154 a Fincas Velazquez—. De
    esos clientes cuelgan las **754 declaraciones de la renta** que también tienen
    la empresa en blanco. Si la guarda mira sólo la columna, media gestoría deja
    de verse y las rentas presentadas se pierden de vista.
    """

    def setUp(self):
        super().setUp()
        base = dict(created_at=AHORA, updated_at=AHORA)
        # Como los de verdad: sin empresa en la columna, con vínculo en la tabla.
        self._ins("clientes", dict(id="cli-suelto", nombre="ARJONA RUIZ AMELIA",
                                   nif="11111111H", workspace_id=self.ws_a, **base))
        self._ins("clientes_empresas", dict(id="ce-suelto", cliente_id="cli-suelto",
                                            empresa_id="emp-a", servicio="gestoria", **base))
        self._ins("gestoria_docs", dict(id="doc-renta", cliente_id="cli-suelto",
                                        nombre="Renta 2025 · Presentada.pdf", tipo="Modelo 100",
                                        referencia_tipo="gestoria", estado="Recibido", **base))

    def test_su_gestor_sigue_viendo_la_renta(self):
        r = self._get("/api/gestoria_docs?cliente_id=cli-suelto", self.cookie_a)
        self.assertEqual(r["estado"], 200)
        self.assertIn("doc-renta", {str(f.get("id") or "") for f in self._filas(r)})

    def test_y_puede_borrarla(self):
        """La fila tampoco tiene empresa: el ámbito sale de su cliente."""
        self._post("/api/gestoria_docs_delete", {"id": "doc-renta"}, self.cookie_a)
        self.assertFalse(self._existe("gestoria_docs", "doc-renta"))

    def test_pero_el_del_otro_workspace_no(self):
        r = self._get("/api/gestoria_docs?cliente_id=cli-suelto", self.cookie_b)
        self.assertNoAlcanza(r, "doc-renta", "renta de otro workspace")
        self._post("/api/gestoria_docs_delete", {"id": "doc-renta"}, self.cookie_b)
        self.assertTrue(self._existe("gestoria_docs", "doc-renta"))

    def test_un_cliente_sin_empresa_por_ningun_lado_no_se_abre_a_todos(self):
        """Son cuatro fichas en producción y ninguna tiene documentos. Sin nadie a
        quien preguntar, la respuesta es no."""
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("clientes", dict(id="cli-nadie", nombre="MUÑOZ BALLESTEROS, NATALIA",
                                   workspace_id=self.ws_a, **base))
        r = self._get("/api/gestoria_docs?cliente_id=cli-nadie", self.cookie_a)
        self.assertEqual(r["estado"], 403)


class LoQueSeBorraTests(BaseGestoria):
    def test_un_trabajo_ajeno(self):
        """`DELETE FROM gestoria_trabajos WHERE id = ?`, sin más."""
        self._post("/api/gestoria_trabajos_delete", {"id": "tra-b"}, self.cookie_a)
        self.assertTrue(self._existe("gestoria_trabajos", "tra-b"),
                        "el gestor A ha borrado un trabajo del otro workspace")

    def test_un_documento_ajeno(self):
        """Y éste, además, borra el objeto de S3 si nadie más lo referencia."""
        self._post("/api/gestoria_docs_delete", {"id": "doc-b"}, self.cookie_a)
        self.assertTrue(self._existe("gestoria_docs", "doc-b"),
                        "el gestor A ha borrado un documento del otro workspace")

    def test_un_apunte_contable_ajeno(self):
        self._post("/api/gestoria_contabilidad_delete", {"id": "con-b"}, self.cookie_a)
        self.assertTrue(self._existe("gestoria_contabilidad", "con-b"),
                        "el gestor A ha borrado un apunte del otro workspace")

    def test_lo_propio_sí_se_borra(self):
        """La guarda no puede romper el uso normal."""
        self._post("/api/gestoria_trabajos_delete", {"id": "tra-a"}, self.cookie_a)
        self.assertFalse(self._existe("gestoria_trabajos", "tra-a"))


class LoQueSeEscribeTests(BaseGestoria):
    def test_no_se_edita_un_trabajo_ajeno(self):
        self._post("/api/gestoria_trabajos_update",
                   {"id": "tra-b", "estado": "Presentado", "importe": 9999}, self.cookie_a)
        fila = self.conn.execute(
            "SELECT estado, importe FROM gestoria_trabajos WHERE id = 'tra-b'").fetchone()
        self.assertEqual(fila["estado"], "Pendiente")
        self.assertEqual(fila["importe"], 150.0)

    def test_no_se_edita_un_documento_ajeno(self):
        self._post("/api/gestoria_docs_update",
                   {"id": "doc-b", "nombre": "Cambiado", "estado": "Entregado"}, self.cookie_a)
        fila = self.conn.execute(
            "SELECT nombre FROM gestoria_docs WHERE id = 'doc-b'").fetchone()
        self.assertEqual(fila["nombre"], "Nómina B")

    def test_no_se_cuelga_un_documento_del_cliente_de_otro(self):
        """Crear también cuenta: si acepta el `cliente_id` que le manden, se puede
        dejar un documento en el expediente de un cliente ajeno."""
        self._post("/api/gestoria_docs",
                   {"cliente_id": "cli-b", "empresa_id": "emp-b", "nombre": "Colado",
                    "tipo": "Gestoria"}, self.cookie_a)
        n = self.conn.execute(
            "SELECT count(*) c FROM gestoria_docs WHERE cliente_id = 'cli-b'").fetchone()["c"]
        self.assertEqual(n, 1, "se ha colado un documento en el expediente ajeno")

    def test_lo_propio_sí_se_edita(self):
        self._post("/api/gestoria_trabajos_update",
                   {"id": "tra-a", "estado": "Presentado"}, self.cookie_a)
        self.assertEqual(self.conn.execute(
            "SELECT estado FROM gestoria_trabajos WHERE id = 'tra-a'").fetchone()["estado"],
            "Presentado")


class ElCuadroDeMandoTests(BaseGestoria):
    def test_el_dashboard_no_suma_lo_ajeno(self):
        """838 líneas que arrancan del `empresa_id` de la petición."""
        r = self._get("/api/gestoria_dashboard?empresa_id=emp-b", self.cookie_a)
        crudo = json.dumps(r["json"])
        self.assertNotIn("Minuta B", crudo)
        self.assertNotIn("300", crudo.replace('"300"', ""))

    def test_ni_el_de_renta(self):
        r = self._get("/api/gestoria_renta_dashboard?empresa_id=emp-b", self.cookie_a)
        self.assertNotIn("Cliente B", json.dumps(r["json"]))


if __name__ == "__main__":
    unittest.main()


class ElRegistroDeConciliacionTests(BaseGestoria):
    """214.583 validaciones para 342 movimientos bancarios.

    La conciliación convergente reprocesa **todos** los movimientos —hasta cinco
    pasadas— cuando el histórico está cerrado, y cada pasada dejaba otra fila
    idéntica. En producción hay 894 filas iguales del mismo movimiento contra el
    mismo asiento y la misma confianza, repartidas por un mes; 80.057 en un solo
    día. Un registro que anota 894 veces lo mismo no sirve para auditar nada, y
    la tabla crece sin techo.
    """

    def _valida(self, **cambios):
        datos = dict(movimiento_id="mov-1", asiento_id="asi-1", factura_id=None,
                     empresa_id="emp-a", estado="auto", confianza=585.0, regla_id=None,
                     validado_por=None, notas=None, now=AHORA)
        datos.update(cambios)
        S.record_gestoria_conciliacion_validacion(self.conn, **datos)
        self.conn.commit()

    def _cuantas(self):
        return self.conn.execute(
            "SELECT count(*) c FROM gestoria_conciliacion_validaciones").fetchone()["c"]

    def test_la_primera_se_anota(self):
        self._valida()
        self.assertEqual(self._cuantas(), 1)

    def test_la_misma_cinco_veces_se_anota_una(self):
        for _ in range(5):
            self._valida()
        self.assertEqual(self._cuantas(), 1)

    def test_pero_un_cambio_sí_se_anota(self):
        self._valida()
        self._valida(asiento_id="asi-2")
        self._valida(estado="manual")
        self._valida(confianza=90.0)
        self.assertEqual(self._cuantas(), 4)

    def test_y_volver_al_estado_anterior_también(self):
        """Si vuelve a lo de antes es un cambio, y tiene que quedar."""
        self._valida()
        self._valida(asiento_id="asi-2")
        self._valida()
        self.assertEqual(self._cuantas(), 3)

    def test_cada_movimiento_lleva_su_cuenta(self):
        self._valida(movimiento_id="mov-1")
        self._valida(movimiento_id="mov-2")
        self._valida(movimiento_id="mov-1")
        self._valida(movimiento_id="mov-2")
        self.assertEqual(self._cuantas(), 2)


class ElRolDeLecturaTests(BaseGestoria):
    """Quien sólo puede mirar, que no escriba.

    Ya pasó en otro módulo —el rol «Lectura» escribía igual— y en Gestoría hay
    834 trabajos, 5.041 documentos y 656 apuntes contables, con dinero: los
    trabajos suman 352.921,40 € y los apuntes 757.234,29 €.
    """

    def setUp(self):
        super().setUp()
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("usuarios", dict(id="u-lec", nombre="Sólo Mira", usuario="mirona",
                                   email="lec@x.test", rol="Lectura", servicio="Gestoría",
                                   activo=1, password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wm-lec", workspace_id=self.ws_a,
                                             usuario_id="u-lec", rol="Miembro", **base))
        self.cookie_lec = self._login("mirona")

    def test_puede_leer(self):
        """El control: si no lee, el test de escritura no probaría nada."""
        r = self._get("/api/gestoria_docs?cliente_id=cli-a", self.cookie_lec)
        self.assertEqual(r["estado"], 200)

    def test_no_borra_un_trabajo(self):
        self._post("/api/gestoria_trabajos_delete", {"id": "tra-a"}, self.cookie_lec)
        self.assertTrue(self._existe("gestoria_trabajos", "tra-a"))

    def test_no_borra_un_documento(self):
        self._post("/api/gestoria_docs_delete", {"id": "doc-a"}, self.cookie_lec)
        self.assertTrue(self._existe("gestoria_docs", "doc-a"))

    def test_no_borra_un_apunte_contable(self):
        self._post("/api/gestoria_contabilidad_delete", {"id": "con-a"}, self.cookie_lec)
        self.assertTrue(self._existe("gestoria_contabilidad", "con-a"))

    def test_no_cambia_el_importe_de_un_trabajo(self):
        self._post("/api/gestoria_trabajos_update",
                   {"id": "tra-a", "importe": 99999}, self.cookie_lec)
        self.assertEqual(self.conn.execute(
            "SELECT importe FROM gestoria_trabajos WHERE id='tra-a'").fetchone()["importe"], 150.0)

    def test_no_cambia_un_apunte_contable(self):
        self._post("/api/gestoria_contabilidad_update",
                   {"id": "con-a", "importe": 99999, "concepto": "Colado"}, self.cookie_lec)
        f = self.conn.execute(
            "SELECT importe, concepto FROM gestoria_contabilidad WHERE id='con-a'").fetchone()
        self.assertEqual(f["importe"], 300.0)
        self.assertEqual(f["concepto"], "Minuta A")


class ElDetectorDeIbanTests(unittest.TestCase):
    """Un IBAN escrito como se imprime.

    De las 3.165 cadenas guardadas como «cuenta detectada» en las declaraciones de
    renta, 2.158 no son un IBAN —«ESTATALCORRESPONDIENTEAL», «ESIMPUESTOSOBRELA-
    RENTADE»—, pero eso viene de la importación masiva y el detector de hoy ya no
    las produce. Lo que sí fallaba hoy es el caso contrario: `ES 11 2100 …`, con un
    espacio entre el país y los dígitos de control, no se reconocía.
    """

    FORMATOS = (
        "ES1121000418450200051332",
        "ES11 2100 0418 4502 0005 1332",
        "ES 11 2100 0418 4502 0005 1332",
        "ES11-2100-0418-4502-0005-1332",
        "Domiciliación en ES1121000418450200051332.",
        "IBAN ES 11 2100 0418 4502 0005 1332 del titular",
    )

    def test_todos_los_formatos_habituales(self):
        for texto in self.FORMATOS:
            with self.subTest(texto=texto):
                self.assertIn("ES1121000418450200051332",
                              S.extraer_ibans_de_texto(texto), texto)

    def test_no_se_inventa_cuentas_con_palabras_que_empiezan_por_es(self):
        """Lo que llenó la base: texto del propio modelo 100 leído como cuenta."""
        for texto in ("IMPUESTO SOBRE LA RENTA DE LAS PERSONAS FISICAS EJERCICIO 2024",
                      "ESTATAL CORRESPONDIENTE AL EJERCICIO 2024",
                      "ESPECIE INGRESOS A CUENTA DE"):
            self.assertEqual(S.extraer_ibans_de_texto(texto), [], texto)

    def test_ni_un_numero_corto_ni_uno_largo(self):
        self.assertEqual(S.extraer_ibans_de_texto("ES112100041845020005"), [])
        self.assertEqual(S.extraer_ibans_de_texto("ES112100041845020005133299"), [])
