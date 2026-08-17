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


class ElExpedienteYSuClienteTests(unittest.TestCase):
    """`gestoria` guardaba el cliente como texto libre y nada más.

    548 expedientes en producción, sin `cliente_id`: no se podían cruzar con la
    ficha, ni saber si dos son de la misma persona. Tampoco tienen precio ni
    cuota en ninguna fila, y la tabla no se escribe desde el 26 de enero.
    """

    def test_la_columna_existe_en_una_base_nueva(self):
        import tempfile
        from pathlib import Path as P
        with tempfile.TemporaryDirectory() as tmp:
            db = P(tmp) / "n.sqlite"
            S.ensure_tables(db)
            conn = S.open_sqlite_conn(str(db), with_row_factory=True)
            cols = {r[1] for r in conn.execute("pragma table_info(gestoria)")}
            self.assertIn("cliente_id", cols)
            self.assertIn("cliente", cols)
            conn.close()


class LoQueEntraEnUnaDeclaracionTests(unittest.TestCase):
    """La limpieza, en el embudo de escritura y no a mano.

    Los tres destrozos que había en producción entraron porque nadie miraba lo
    que se guardaba en `renta_detalles`. `sanitize_renta_entry` es el sitio por el
    que pasan todas las escrituras —pantalla, OCR e importación masiva—, así que
    es ahí donde se comprueba.
    """

    def _entrada(self, **campos):
        base = {"id": "renta-2024-declarante", "ejercicio": "2024"}
        base.update(campos)
        return S.sanitize_renta_entry(base)

    # --- el estado civil ----------------------------------------------------
    def test_el_volcado_del_ocr_no_se_guarda(self):
        """77 declaraciones lo tenían; la mayor, 10.286 caracteres, con NIF de
        hijos y cónyuges dentro."""
        volcado = ("Casado/a 0007 Fecha de nacimiento 18/11/1971 0010 Cónyuge NIF 25060974J "
                   "0013 Apellidos y nombre NUÑEZ BALLESTEROS JOAQUIN 0014 Sexo del cónyuge "
                   "Hombre 0059 Hijos NIF 10217856Z 0075 NUÑEZ BEJAR JOAQUIN")
        e = self._entrada(estado_civil=volcado)
        self.assertEqual(e["estado_civil"], "Casado/a")
        self.assertNotIn("25060974J", e["estado_civil"])
        self.assertNotIn("NUÑEZ", e["estado_civil"])

    def test_ni_el_ruido_pequeno(self):
        for crudo, limpio in (("Casado/a [ooo7]", "Casado/a"),
                              ("Soltero/a [ooos|", "Soltero/a"),
                              ("Viudo/a 0008", "Viudo/a"),
                              ("Divorciado/a 0 separado/a legalmente [ooo9]",
                               "Divorciado/a o separado/a legalmente")):
            with self.subTest(crudo=crudo):
                self.assertEqual(self._entrada(estado_civil=crudo)["estado_civil"], limpio)

    def test_el_largo_gana_al_corto_que_lleva_dentro(self):
        """«Divorciado/a o separado/a legalmente» empieza por «Divorciado/a»."""
        self.assertEqual(
            self._entrada(estado_civil="Divorciado/a o separado/a legalmente")["estado_civil"],
            "Divorciado/a o separado/a legalmente")

    def test_un_valor_corto_que_no_conocemos_se_respeta(self):
        """Puede ser algo escrito a mano; no lo tiramos."""
        self.assertEqual(self._entrada(estado_civil="Pareja de hecho")["estado_civil"],
                         "Pareja de hecho")

    def test_uno_largo_que_no_es_un_estado_civil_no_se_guarda(self):
        self.assertEqual(self._entrada(estado_civil="x" * 200)["estado_civil"], "")

    # --- las cuentas --------------------------------------------------------
    def test_el_texto_del_modelo_100_no_es_una_cuenta(self):
        """2.158 de 3.165 «cuentas detectadas» eran esto."""
        e = self._entrada(cuentas_detectadas=[
            "ESTATALCORRESPONDIENTEAL", "ESIMPUESTOSOBRELARENTADE",
            "ES1121000418450200051332"])
        self.assertEqual(e["cuentas_detectadas"], ["ES1121000418450200051332"])

    def test_la_cuenta_se_guarda_normalizada_y_sin_repetir(self):
        e = self._entrada(cuentas_detectadas=[
            "ES11 2100 0418 4502 0005 1332", "ES1121000418450200051332"])
        self.assertEqual(e["cuentas_detectadas"], ["ES1121000418450200051332"])

    # --- las rutas ----------------------------------------------------------
    def test_no_se_guarda_la_ruta_del_ordenador_de_nadie(self):
        """Las 1.091 rutas de producción eran de un disco local."""
        e = self._entrada(source_files=["/Volumes/Mac Satecchi/Mac/x/Renta 2025.pdf",
                                        "/Users/alguien/Downloads/Otra.pdf"],
                          notas_ocr={"source_files": ["/Volumes/z/Tercera.pdf"], "score": 85})
        self.assertEqual(e["source_files"], ["Renta 2025.pdf", "Otra.pdf"])
        self.assertEqual(e["notas_ocr"]["source_files"], ["Tercera.pdf"])
        self.assertEqual(e["notas_ocr"]["score"], 85, "lo demás de notas_ocr no se toca")

    def test_un_nombre_suelto_se_queda_como_está(self):
        self.assertEqual(self._entrada(source_files=["Renta 2025.pdf"])["source_files"],
                         ["Renta 2025.pdf"])

    # --- y lo que no debe tocar ---------------------------------------------
    def test_el_dato_bueno_sigue_intacto(self):
        e = self._entrada(estado_civil="Casado/a [ooo7]", resultado_declaracion=2332.65,
                          casilla_505=21666.01, cliente_nif="74866767L",
                          presentacion_fecha="2025-06-13")
        self.assertEqual(e["resultado_declaracion"], 2332.65)
        self.assertEqual(e["casilla_505"], 21666.01)
        self.assertEqual(e["cliente_nif"], "74866767L")
        self.assertEqual(e["presentacion_fecha"], "2025-06-13")


class LaOtraMitadDelModuloTests(BaseGestoria):
    """Los endpoints que la primera pasada no pudo probar.

    De los 22 bloques sin comprobación de ámbito se demostraron ocho agujeros y se
    cerraron. Los demás se quedaron sin probar por una razón tonta: sus tablas
    están **a cero en producción** —sociedades, socios, actas, lotes de
    importación— y no había con qué probarlos. Que no se usen hoy no significa que
    no vayan a usarse, y el día que se usen el agujero estaría ahí.

    Aquí se siembran a mano y se prueba lo mismo: que el gestor de un workspace no
    alcance lo del otro.
    """

    def setUp(self):
        super().setUp()
        base = dict(created_at=AHORA, updated_at=AHORA)
        for suf in ("a", "b"):
            emp = f"emp-{suf}"
            self._ins("gestoria_sociedades", dict(
                id=f"soc-{suf}", empresa_id=emp, denominacion=f"Sociedad {suf.upper()} SL",
                cif=f"B1234567{suf}", tipo_social="SL", capital_social=3000, estado="Activa", **base))
            self._ins("gestoria_socios", dict(
                id=f"sio-{suf}", sociedad_id=f"soc-{suf}", empresa_id=emp,
                nombre=f"Socio {suf.upper()}", documento=f"1111111{suf}", rol="Administrador",
                porcentaje=100, **base))
            self._ins("gestoria_actas", dict(
                id=f"act-{suf}", sociedad_id=f"soc-{suf}", empresa_id=emp,
                titulo=f"Junta {suf.upper()}", tipo_acta="Ordinaria", numero_acta="1",
                fecha_acta="2026-06-30", estado="Borrador", requiere_firma=1, **base))
            self._ins("gestoria_acta_firmas", dict(
                id=f"fir-{suf}", acta_id=f"act-{suf}", empresa_id=emp, sociedad_id=f"soc-{suf}",
                firmante_nombre=f"Firmante {suf.upper()}", firmante_documento=f"2222222{suf}",
                firmante_rol="Administrador", metodo_firma="click", acepta_terminos=1, **base))
            self._ins("gestoria_cuentas_bancarias", dict(
                id=f"cta-{suf}", empresa_id=emp, iban=f"ES112100041845020005133{suf[0]}",
                banco_nombre=f"Banco {suf.upper()}", titular=f"Titular {suf.upper()}",
                es_principal=1, **base))
            self._ins("gestoria_movimientos_bancarios", dict(
                id=f"mov-{suf}", empresa_id=emp, cuenta_bancaria_id=f"cta-{suf}",
                fecha_operacion="2026-07-01", concepto=f"Transferencia {suf.upper()}",
                importe=1000.0, **base))
            self._ins("gestoria_asientos", dict(
                id=f"asi-{suf}", empresa_id=emp, cliente_id=f"cli-{suf}", fecha="2026-07-01",
                concepto=f"Asiento {suf.upper()}", diario="General",
                total_debe=1000.0, total_haber=1000.0, punteado_banco=0, **base))
            # El diario se arma de las líneas, no del asiento: sin ellas
            # `/api/gestoria_libros` devolvía vacío también para el suyo y el test
            # no probaba nada.
            self._ins("gestoria_asiento_lineas", dict(
                id=f"lin-{suf}", asiento_id=f"asi-{suf}", cuenta="43000000",
                descripcion=f"Cliente {suf.upper()}", debe=1000.0, haber=0.0, **base))
            self._ins("gestoria_asiento_lineas", dict(
                id=f"lin2-{suf}", asiento_id=f"asi-{suf}", cuenta="70500000",
                descripcion=f"Prestación de servicios {suf.upper()}", debe=0.0, haber=1000.0, **base))
            self._ins("gestoria_facturas", dict(
                id=f"fac-{suf}", empresa_id=emp, cliente_id=f"cli-{suf}", tipo="Emitida",
                numero=f"F-{suf}-1", fecha_emision="2026-07-01", descripcion=f"Minuta {suf.upper()}",
                base_imponible=1000.0, cuota_iva=210.0, total=1210.0, **base))
            self._ins("gestoria_import_lotes", dict(
                id=f"lot-{suf}", empresa_id=emp, cliente_id=f"cli-{suf}", origen="excel",
                estado="Pendiente", periodo="2026-T2", total_documentos=1, total_ok=1,
                total_revisar=0, total_duplicado=0, total_error=0, **base))

    def _no_ve(self, ruta, ajeno, que):
        r = self._get(ruta, self.cookie_a)
        crudo = json.dumps(r["json"], ensure_ascii=False)
        self.assertNotIn(ajeno, crudo, f"{que}: el gestor A ha visto {ajeno} en {ruta}")

    def test_las_sociedades(self):
        self._no_ve("/api/gestoria_sociedades?empresa_id=emp-b", "Sociedad B SL", "sociedades")

    def test_los_socios(self):
        self._no_ve("/api/gestoria_socios?empresa_id=emp-b&sociedad_id=soc-b", "Socio B", "socios")

    def test_las_actas(self):
        self._no_ve("/api/gestoria_actas?empresa_id=emp-b&sociedad_id=soc-b", "Junta B", "actas")

    def test_las_firmas_de_un_acta(self):
        self._no_ve("/api/gestoria_acta_firmas?empresa_id=emp-b&acta_id=act-b",
                    "Firmante B", "firmas")

    def test_las_cuentas_bancarias(self):
        """Un IBAN ajeno es de lo peor que se puede filtrar."""
        self._no_ve("/api/gestoria_cuentas_bancarias?empresa_id=emp-b",
                    "ES112100041845020005133b", "cuentas")

    def test_los_movimientos_bancarios(self):
        self._no_ve("/api/gestoria_movimientos_bancarios?empresa_id=emp-b",
                    "Transferencia B", "movimientos")

    def test_los_asientos(self):
        self._no_ve("/api/gestoria_asientos?empresa_id=emp-b", "Asiento B", "asientos")

    def test_un_asiento_suelto(self):
        self._no_ve("/api/gestoria_asiento?asiento_id=asi-b", "Asiento B", "asiento")

    def test_las_facturas(self):
        self._no_ve("/api/gestoria_facturas?empresa_id=emp-b&cliente_id=cli-b",
                    "F-b-1", "facturas")

    def test_los_lotes_de_importacion(self):
        self._no_ve("/api/gestoria_import_lotes?empresa_id=emp-b", "lot-b", "lotes")

    def test_los_libros(self):
        self._no_ve("/api/gestoria_libros?empresa_id=emp-b&cliente_id=cli-b"
                    "&desde=2026-01-01&hasta=2026-12-31", "Asiento B", "libros")

    def test_la_plantilla_de_excel(self):
        """Ésta no se puede mirar por su contenido: devuelve un Excel binario, así
        que buscar un texto dentro pasaría siempre y no probaría nada. Se mira lo
        que sí dice: 403 para lo ajeno, y para lo propio no."""
        ajena = self._get("/api/gestoria_excel_plantilla?empresa_id=emp-b&cliente_id=cli-b",
                          self.cookie_a)
        self.assertEqual(ajena["estado"], 403)
        propia = self._get("/api/gestoria_excel_plantilla?empresa_id=emp-a&cliente_id=cli-a",
                           self.cookie_a)
        self.assertEqual(propia["estado"], 200)

    CONTROLES = (
        ("/api/gestoria_sociedades?empresa_id=emp-a", "Sociedad A SL"),
        ("/api/gestoria_socios?empresa_id=emp-a&sociedad_id=soc-a", "Socio A"),
        ("/api/gestoria_actas?empresa_id=emp-a&sociedad_id=soc-a", "Junta A"),
        ("/api/gestoria_acta_firmas?empresa_id=emp-a&acta_id=act-a", "Firmante A"),
        ("/api/gestoria_cuentas_bancarias?empresa_id=emp-a", "ES112100041845020005133a"),
        ("/api/gestoria_movimientos_bancarios?empresa_id=emp-a", "Transferencia A"),
        ("/api/gestoria_asientos?empresa_id=emp-a", "Asiento A"),
        ("/api/gestoria_asiento?asiento_id=asi-a", "Asiento A"),
        ("/api/gestoria_facturas?empresa_id=emp-a&cliente_id=cli-a", "F-a-1"),
        ("/api/gestoria_import_lotes?empresa_id=emp-a", "lot-a"),
        ("/api/gestoria_libros?empresa_id=emp-a&cliente_id=cli-a"
         "&desde=2026-01-01&hasta=2026-12-31", "Asiento A"),
    )

    def test_lo_propio_sí_se_ve(self):
        """El control, y no es un adorno: cuatro de las pruebas de arriba pasaban
        porque el endpoint devolvía vacío también para el suyo —una firma que no
        sembré, un parámetro que se llamaba `asiento_id` y no `id`, unas fechas que
        faltaban—. Un test negativo que pasa por vacío es peor que no tenerlo."""
        for ruta, esperado in self.CONTROLES:
            with self.subTest(ruta=ruta):
                r = self._get(ruta, self.cookie_a)
                self.assertIn(esperado, json.dumps(r["json"], ensure_ascii=False),
                              f"{ruta} no devuelve ni lo propio")


class LasEscriturasContablesTests(LaOtraMitadDelModuloTests):
    """Los hermanos del asiento que se leía, y lo que salió al buscarlos.

    Si `/api/gestoria_asiento` dejaba **leer** el asiento del otro workspace, lo
    siguiente era ver si sus hermanos dejan cambiarlo. Resultó que no se les puede
    ni llegar: `gestoria_asiento_update`, `_punteo_banco` y
    `cuentas_bancarias_save` están declaradas como rutas POST válidas pero
    implementadas en `handle_api`, que sólo se llama desde el GET. Ahí no existe
    `payload`, así que por GET revientan con 500; y por POST no tenían rama propia
    y caían en el `else` del final de la cadena, que era la firma de hipotecas.

    Un POST a `/api/gestoria_asiento_update` con `id` y `fecha_firma` contestaba
    `{"ok": true}` y dejaba la hipoteca firmada. Sólo la propia —el aislamiento de
    esa rama ya se comprobaba— pero firmada igual, desde un botón de gestoría.

    Quince rutas estaban así, seis de gestoría y nueve de otros módulos.
    """

    # Las cinco de gestoría ya tienen rama propia —se movieron a la cadena de
    # POST—, así que aquí se vigila lo que sigue importando: que ninguna de ellas
    # acabe firmando una hipoteca. Y para el 404 se usa una de las nueve que
    # siguen huérfanas en otros módulos.
    ANTES_HUERFANAS = (
        "/api/gestoria_asiento_update",
        "/api/gestoria_asiento_punteo_banco",
        "/api/gestoria_cuentas_bancarias_save",
        "/api/gestoria_movimientos_bancarios_import",
        "/api/gestoria_movimientos_bancarios_import_preview",
    )
    SIGUE_HUERFANA = "/api/legal_radar_counts"

    def _hipoteca(self):
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("hipotecas", dict(id="hip-a", empresa_id="emp-a", cliente="Cliente A",
                                    estado="Estudio", **base))
        return lambda: dict(self.conn.execute(
            "SELECT estado, fecha_firma FROM hipotecas WHERE id = 'hip-a'").fetchone())

    def test_ninguna_ruta_de_gestoria_firma_una_hipoteca(self):
        lee = self._hipoteca()
        for ruta in self.ANTES_HUERFANAS:
            with self.subTest(ruta=ruta):
                self._post(ruta, {"empresa_nombre": "Empresa A", "id": "hip-a",
                                  "fecha_firma": "2026-08-16", "estado": "Firmada"},
                           self.cookie_a)
                self.assertEqual(lee()["estado"], "Estudio",
                                 f"{ruta} ha firmado la hipoteca")

    def test_una_ruta_sin_rama_propia_da_404_y_no_firma(self):
        """Quedan nueve así en auditoría, legal, fincas, convenios y copiloto."""
        lee = self._hipoteca()
        r = self._post(self.SIGUE_HUERFANA,
                       {"empresa_nombre": "Empresa A", "id": "hip-a",
                        "fecha_firma": "2026-08-16", "estado": "Firmada"}, self.cookie_a)
        self.assertEqual(r["estado"], 404)
        self.assertNotEqual(r["json"].get("ok"), True)
        self.assertEqual(lee()["estado"], "Estudio")

    def test_firmar_una_hipoteca_sigue_funcionando(self):
        """El control que impide que el arreglo rompa lo que sí debe pasar."""
        base = dict(created_at=AHORA, updated_at=AHORA)
        lee = self._hipoteca()
        self._ins("usuarios", dict(id="u-fin", nombre="Fina", usuario="fina",
                                   email="f@x.test", rol="Administrador",
                                   servicio="Financiación", activo=1,
                                   password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wm-fin", workspace_id=self.ws_a,
                                             usuario_id="u-fin", rol="Owner", **base))
        r = self._post("/api/hipotecas/firmar",
                       {"empresa_nombre": "Empresa A", "id": "hip-a",
                        "fecha_firma": "2026-08-16", "estado": "Firmada"},
                       self._login("fina"))
        self.assertEqual(r["estado"], 200)
        self.assertEqual(lee(), {"estado": "Firmada", "fecha_firma": "2026-08-16"})

    def test_una_ruta_inventada_sigue_dando_404(self):
        r = self._post("/api/esto_no_existe", {"empresa_nombre": "Empresa A"}, self.cookie_a)
        self.assertEqual(r["estado"], 404)

    # --- y los modelos, que sí tienen rama propia ---------------------------
    def test_no_se_edita_un_modelo_ajeno(self):
        self._post("/api/gestoria_modelos_update",
                   {"empresa_nombre": "Empresa A", "id": "mod-b", "estado": "Presentado"},
                   self.cookie_a)
        self.assertEqual(self.conn.execute(
            "SELECT estado FROM gestoria_modelos WHERE id='mod-b'").fetchone()["estado"],
            "Pendiente")

    def test_ni_diciendo_que_uno_es_la_otra_empresa(self):
        r = self._post("/api/gestoria_modelos_update",
                       {"empresa_nombre": "Empresa B", "id": "mod-b", "estado": "Presentado"},
                       self.cookie_a)
        self.assertEqual(r["estado"], 403)
        self.assertEqual(self.conn.execute(
            "SELECT estado FROM gestoria_modelos WHERE id='mod-b'").fetchone()["estado"],
            "Pendiente")

    def test_el_propio_sí_se_edita(self):
        self._post("/api/gestoria_modelos_update",
                   {"empresa_nombre": "Empresa A", "id": "mod-a", "estado": "Presentado"},
                   self.cookie_a)
        self.assertEqual(self.conn.execute(
            "SELECT estado FROM gestoria_modelos WHERE id='mod-a'").fetchone()["estado"],
            "Presentado")

    def test_no_se_borra_un_modelo_ajeno(self):
        self._post("/api/gestoria_modelos_delete",
                   {"empresa_nombre": "Empresa A", "id": "mod-b"}, self.cookie_a)
        self.assertTrue(self._existe("gestoria_modelos", "mod-b"))


class LosCincoQueNoSeAlcanzabanTests(LaOtraMitadDelModuloTests):
    """Los endpoints que la interfaz llama y que no llegaban a ninguna parte.

    `gestoria_asiento_update`, `_punteo_banco`, `cuentas_bancarias_save` y los dos
    de importación de movimientos vivían en `handle_api`, que sólo se llama desde
    el GET: por ahí reventaban con 500 porque `payload` no existe, y por POST
    caían en la rama de firmar hipotecas. Cuatro botones de gestoría —editar un
    asiento, cuadrarlo con el banco, guardar una cuenta e importar movimientos—
    no hacían lo que decían.

    Movidos a la cadena de POST, con la guarda de ámbito que no tenían.
    """

    def _punteado(self, id_):
        return self.conn.execute(
            "SELECT punteado_banco FROM gestoria_asientos WHERE id = ?", (id_,)).fetchone()[0]

    def _banco(self, id_):
        return self.conn.execute(
            "SELECT banco_nombre, es_principal FROM gestoria_cuentas_bancarias WHERE id = ?",
            (id_,)).fetchone()

    # --- cuadrar un asiento con el banco ------------------------------------
    def test_se_puede_puntear_el_propio(self):
        r = self._post("/api/gestoria_asiento_punteo_banco",
                       {"empresa_nombre": "Empresa A", "asiento_id": "asi-a",
                        "punteado_banco": 1}, self.cookie_a)
        self.assertEqual(r["estado"], 200)
        self.assertEqual(self._punteado("asi-a"), 1)

    def test_y_despuntearlo(self):
        self._post("/api/gestoria_asiento_punteo_banco",
                   {"empresa_nombre": "Empresa A", "asiento_id": "asi-a",
                    "punteado_banco": 1}, self.cookie_a)
        self._post("/api/gestoria_asiento_punteo_banco",
                   {"empresa_nombre": "Empresa A", "asiento_id": "asi-a",
                    "punteado_banco": False}, self.cookie_a)
        self.assertEqual(self._punteado("asi-a"), 0)

    def test_no_el_del_otro_workspace(self):
        r = self._post("/api/gestoria_asiento_punteo_banco",
                       {"empresa_nombre": "Empresa A", "asiento_id": "asi-b",
                        "punteado_banco": 1}, self.cookie_a)
        self.assertEqual(r["estado"], 403)
        self.assertEqual(self._punteado("asi-b"), 0)

    # --- guardar una cuenta bancaria ----------------------------------------
    def test_se_guarda_la_cuenta_propia(self):
        r = self._post("/api/gestoria_cuentas_bancarias_save",
                       {"empresa_nombre": "Empresa A", "id": "cta-a", "empresa_id": "emp-a",
                        "iban": "ES1121000418450200051332", "banco_nombre": "Banco A renombrado",
                        "es_principal": True}, self.cookie_a)
        self.assertEqual(r["estado"], 200)
        f = self._banco("cta-a")
        self.assertEqual(f["banco_nombre"], "Banco A renombrado")
        self.assertEqual(f["es_principal"], 1)

    def test_no_se_reescribe_el_iban_de_otro(self):
        r = self._post("/api/gestoria_cuentas_bancarias_save",
                       {"empresa_nombre": "Empresa A", "id": "cta-b", "empresa_id": "emp-b",
                        "iban": "ES9900000000000000000000", "banco_nombre": "COLADO"},
                       self.cookie_a)
        self.assertEqual(r["estado"], 403)
        self.assertEqual(self._banco("cta-b")["banco_nombre"], "Banco B")


class ElSiONoQueVieneEnElCuerpoTests(unittest.TestCase):
    """Un sí/no de un JSON leído como si viniera en la barra de direcciones.

    `_bool_param` hace `params.get(key, [""])[0]`. Sobre `{"punteado_banco": 1}`
    eso revienta, la excepción se traga y devuelve el valor por defecto: lo que
    mandara el cliente daba igual. Estaba así en cinco sitios de gestoría, y el
    efecto era que no se podía marcar un asiento como cuadrado con el banco, ni
    cerrar un lote de importación, ni marcar una cuenta como principal.
    """

    def test_un_entero(self):
        self.assertTrue(S.bool_del_cuerpo({"x": 1}, "x"))
        self.assertFalse(S.bool_del_cuerpo({"x": 0}, "x"))

    def test_un_booleano(self):
        self.assertTrue(S.bool_del_cuerpo({"x": True}, "x"))
        self.assertFalse(S.bool_del_cuerpo({"x": False}, "x"))

    def test_una_cadena(self):
        for v in ("1", "true", "si", "sí", "on", "yes", "TRUE"):
            self.assertTrue(S.bool_del_cuerpo({"x": v}, "x"), v)
        for v in ("0", "false", "no", "", "cualquier cosa"):
            self.assertFalse(S.bool_del_cuerpo({"x": v}, "x"), v)

    def test_si_no_viene_manda_el_valor_por_defecto(self):
        self.assertTrue(S.bool_del_cuerpo({}, "x", default=True))
        self.assertFalse(S.bool_del_cuerpo({}, "x", default=False))

    def test_pero_si_viene_manda_lo_que_viene(self):
        """Éste es el caso que fallaba: mandar `False` contra un default `True`."""
        self.assertFalse(S.bool_del_cuerpo({"x": False}, "x", default=True))
        self.assertFalse(S.bool_del_cuerpo({"x": 0}, "x", default=True))
        self.assertTrue(S.bool_del_cuerpo({"x": 1}, "x", default=False))
