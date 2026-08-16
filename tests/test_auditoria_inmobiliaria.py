"""Autoauditoría del CRM inmobiliario y de la web pública.

No prueba una pantalla concreta: monta una inmobiliaria entera —clientes, encargos,
pisos, demandas, visitas, operaciones escrituradas y alquileres— y la recorre con una
sesión de verdad, por HTTP, como la usa una asesora.

Vigila cuatro cosas, que son las cuatro formas en que este módulo se rompe sin avisar:

1. **Que nada reviente.** El portal del comprador estuvo tres horas devolviendo 500 en
   producción porque un `return` nombraba dos variables borradas, y ninguna prueba
   llamaba al endpoint. Aquí se barren los del módulo entero: un 5xx es un fallo.
2. **Que los documentos salgan y salgan llenos.** La nota de encargo se firma. Que el
   PDF se genere no basta: hay que mirar lo que pone.
3. **Que los números del dashboard sean los números.** Se siembran importes conocidos y
   se comprueba la suma, no que «haya algo».
4. **Que la web pública no enseñe lo que no debe.** Un piso vendido fuera del escaparate,
   y ningún dato interno en el anuncio.

Sobre el punto 3, una trampa que costó dos falsos positivos escribiendo esto: la
facturación de ventas sale de `operaciones_inmobiliarias` y la de alquileres de la tabla
`alquileres`, que son tablas distintas con columnas distintas. Sembrar en la que no es
da un cero que parece un fallo de cálculo y es un fallo de la prueba. Por eso `_ins`
avisa de las columnas que descarta.
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
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")

from web import server as S  # noqa: E402

AHORA = "2026-08-12 09:00:00"
CLAVE = "Auditoria1234!"

VENTAS_2026 = [("op1", "inm3", 320000, 9600), ("op2", "inm1", 285000, 8550),
               ("op3", "inm2", 198000, 5940)]
ALQUILERES_2026 = [("alq_a", 1200.0), ("alq_b", 950.0), ("alq_c", 780.0)]


class Agencia(unittest.TestCase):
    """Una inmobiliaria con datos, servida por el servidor real."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "auditoria.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        for fn in ("ensure_demanda_portal_schema", "ensure_portal_consentimientos_schema"):
            try:
                getattr(S, fn)(self.conn)
            except Exception:
                pass
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        self.descartadas = {}
        self._sembrar()
        self._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.cookie = self._post("/api/login", {"usuario": "asesora", "password": CLAVE},
                                 cookie=False)["cookie"]

    def tearDown(self):
        self.httpd.shutdown()
        self.conn.close()
        if self._prev is not None:
            S.Handler.db_path = self._prev
        self.tmp.cleanup()

    # --- semilla -------------------------------------------------------------
    def _ins(self, tabla, datos):
        validas = {r[1] for r in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in validas}
        sobran = set(datos) - set(d)
        if sobran:
            self.descartadas.setdefault(tabla, set()).update(sobran)
        self.conn.execute(
            f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})",
            tuple(d.values()))
        self.conn.commit()

    def _sembrar(self):
        ws, base = self.ws, dict(created_at=AHORA, updated_at=AHORA)
        self._ins("empresas", dict(id="emp1", nombre="Inmobiliaria Modernia", nif="B29123456",
                                   direccion="Avenida de Andalucía 12, Málaga", activo=1,
                                   telefono="952000000", **base))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=ws, empresa_id="emp1", **base))
        self._ins("usuarios", dict(id="u1", nombre="Ana Asesora", usuario="asesora",
                                   email="ana@modernia.test", rol="Administrador",
                                   servicio="Inmobiliaria", activo=1,
                                   password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=ws, usuario_id="u1",
                                             rol="Owner", **base))
        for cid, nombre, tel in (("cli1", "Carlos Comprador", "600111222"),
                                 ("cli2", "Pilar Propietaria", "600999888"),
                                 ("cli5", "Inés Inversora", "600777888")):
            self._ins("clientes", dict(id=cid, nombre=nombre, telefono=tel, empresa_id="emp1",
                                       workspace_id=ws, poblacion="Málaga", **base))

        for iid, dir_, estado, precio, m2, hab, tipo in (
                ("inm1", "Calle Larios 3, 4º A", "Encargo", 285000, 95, 3, "Piso"),
                ("inm2", "Calle Compás 8, 2º B", "Encargo", 198000, 78, 2, "Piso"),
                ("inm3", "Avenida Europa 110, 6º C", "Vendido", 320000, 110, 4, "Piso"),
                ("inm4", "Camino del Colmenar 14", "Noticia", 450000, 210, 5, "Chalet"),
                ("inm5", "Calle Victoria 21, bajo", "Encargo", 120000, 60, 0, "Local")):
            self._ins("inmuebles", dict(
                id=iid, workspace_id=ws, empresa_id="emp1", direccion=dir_, poblacion="Málaga",
                provincia="Málaga", estado=estado, tipo_inmueble=tipo, tipo_operacion="venta",
                m2=m2, habitaciones=hab, banos=max(1, hab - 1), precio_objetivo=precio,
                descripcion=f"Inmueble en {dir_}", propietario_telefono="600999888", **base))

        for cid, iid, etapa in (("cap1", "inm1", "Encargo"), ("cap2", "inm2", "Encargo"),
                                ("cap3", "inm4", "Noticia"), ("cap4", "inm3", "Vendido")):
            self._ins("captaciones", dict(id=cid, workspace_id=ws, empresa_id="emp1",
                                          inmueble_id=iid, etapa=etapa, situacion_comercial=etapa,
                                          propietario="Pilar Propietaria",
                                          responsable="Ana Asesora", **base))

        self._ins("demandas", dict(id="dem1", empresa_id="emp1", workspace_id=ws,
                                   cliente_id="cli1", tipo="Piso", tipologia="Piso", zona="Centro",
                                   precio_max=300000, habitaciones_min=3, estado="Activa",
                                   responsable="Ana Asesora", **base))
        self._ins("visitas", dict(id="vis0", workspace_id=ws, empresa_id="emp1",
                                  inmueble_id="inm1", demanda_id="dem1", fecha="2026-08-05 17:00:00",
                                  estado="Realizada", **base))
        self._ins("acciones", dict(id="acc1", empresa_id="emp1", workspace_id=ws,
                                   servicio="Inmobiliaria", cliente_id="cli1", inmueble_id="inm1",
                                   cliente_nombre="Carlos Comprador", fecha="2026-08-10",
                                   hora="17:00", asunto="Oferta sobre Larios 3", tipo="Negociación",
                                   documento_tipo="oferta", importe_propuesta=270000,
                                   responsable="Ana Asesora", estado="Abierta", **base))
        self._ins("acciones", dict(id="acc2", empresa_id="emp1", workspace_id=ws,
                                   servicio="Inmobiliaria", cliente_id="cli1", inmueble_id="inm1",
                                   cliente_nombre="Carlos Comprador", fecha="2026-08-11",
                                   hora="12:00", asunto="Honorarios", tipo="Honorarios",
                                   documento_tipo="honorarios", importe_propuesta=8100,
                                   responsable="Ana Asesora", estado="Abierta", **base))

        # Ventas escrituradas: la facturación sale de aquí, no de `inmueble_cierres`.
        for oid, iid, precio, hon in VENTAS_2026:
            self._ins("operaciones_inmobiliarias", dict(
                id=oid, empresa_id="emp1", workspace_id=ws, tipo_operacion="venta",
                estado="Cerrada", anio=2026, mes=6, inmueble_id=iid, direccion="x",
                fecha_escritura="2026-06-15", precio_escritura=precio, honorarios=hon,
                agente="Ana Asesora", responsable_gestion="Ana Asesora", **base))
        # Una de otro año: no debe colarse en el ejercicio en curso.
        self._ins("operaciones_inmobiliarias", dict(
            id="op0", empresa_id="emp1", workspace_id=ws, tipo_operacion="venta", estado="Cerrada",
            anio=2025, mes=3, inmueble_id="inm4", direccion="y", fecha_escritura="2025-03-01",
            precio_escritura=500000, honorarios=15000, agente="Ana Asesora", **base))

        # Alquileres: otra tabla, otras columnas. La comisión es `importe_comision`.
        for n, (aid, com) in enumerate(ALQUILERES_2026):
            self._ins("alquileres", dict(id=aid, empresa_id="emp1", fecha=f"2026-0{n + 3}-10",
                                         direccion=f"Piso alquilado {n + 1}", precio=850,
                                         importe_comision=com, agente="Ana Asesora", **base))
        self._ins("alquileres", dict(id="alq_viejo", empresa_id="emp1", fecha="2025-11-02",
                                     direccion="De otro año", importe_comision=9999,
                                     agente="Ana Asesora", **base))

    # --- cliente HTTP --------------------------------------------------------
    def _get(self, ruta, cookie=True):
        req = urllib.request.Request(self.base + ruta, method="GET")
        if cookie:
            req.add_header("Cookie", self.cookie)
        return self._lanzar(req)

    def _post(self, ruta, cuerpo, cookie=True):
        req = urllib.request.Request(self.base + ruta, data=json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        if cookie:
            req.add_header("Cookie", self.cookie)
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
        try:
            return json.loads(cuerpo.decode("utf-8"))
        except Exception:
            return None

    @staticmethod
    def _texto_pdf(cuerpo):
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(cuerpo)).pages)

    @classmethod
    def _frase_pdf(cls, cuerpo):
        """El mismo texto con los saltos de línea deshechos. El motor parte las frases
        por ancho de página, así que buscar una cláusula entera en el texto crudo falla
        por dónde cayó el corte, no por lo que dice el contrato."""
        import re
        return re.sub(r"\s+", " ", cls._texto_pdf(cuerpo))


class NingunEndpointRevientaTests(Agencia):
    """El 500 del portal del comprador no lo vio nadie hasta producción."""

    OTROS_MODULOS = ("fincas", "gestoria", "seguro", "hipoteca", "irpf", "nomina", "laboral",
                     "conta", "libro", "modelo_", "asiento", "factura_e", "sii", "verifactu",
                     "tpv", "banco_", "sepa")

    def _rutas(self):
        import re
        return sorted({r for r in re.findall(r'"(/api/[a-z_0-9]+)"', SERVER)
                       if not any(o in r for o in self.OTROS_MODULOS)})

    def test_ninguno_devuelve_5xx_sin_parametros(self):
        """Sin parámetros hay que contestar «te falta un dato», no reventar."""
        rotos = [(r, self._get(r)["estado"]) for r in self._rutas()]
        rotos = [(r, c) for r, c in rotos if c >= 500]
        self.assertEqual(rotos, [], f"endpoints que revientan: {rotos}")

    def test_ninguno_devuelve_5xx_con_los_parametros_puestos(self):
        """Y con datos válidos tampoco: ahí es donde vivía el NameError."""
        import urllib.parse
        saco = urllib.parse.urlencode({
            "workspace_id": self.ws, "empresa_id": "emp1", "id": "inm1", "inmueble_id": "inm1",
            "cliente_id": "cli1", "persona_id": "cli1", "demanda_id": "dem1",
            "captacion_id": "cap1", "usuario_id": "u1", "action_id": "acc1",
            "servicio": "Inmobiliaria", "year": "2026", "anio": "2026", "area": "inmobiliaria",
            "q": "Carlos", "limit": "50",
        })
        rotos = []
        for ruta in self._rutas():
            r = self._get(f"{ruta}?{saco}")
            if r["estado"] >= 500:
                rotos.append((ruta, r["estado"], str(r["json"] or r["cuerpo"][:120])[:140]))
        self.assertEqual(rotos, [], f"endpoints que revientan con datos: {rotos}")

    def test_un_parametro_que_falta_no_se_responde_como_falta_de_permiso(self):
        """Un 403 dice «no puedes». Si lo que pasa es que falta un dato, el front no
        puede distinguir un permiso denegado de una llamada mal montada."""
        r = self._get("/api/demanda_portal_accesos")
        self.assertEqual(r["estado"], 400, r["json"])
        self.assertIn("demanda_id", str(r["json"]))
        self.assertNotIn("inmueble_id", str(r["json"]))


class NingunaEscrituraRevientaTests(Agencia):
    """La primera auditoría barrió sólo los GET: 189 endpoints contestaron 404 porque
    son POST y no se probó ni uno, o sea el 32 % del módulo. Al barrer las escrituras
    salieron tres fallos en el primer minuto, uno de ellos cerrando la conexión sin
    contestar nada."""

    OTROS_MODULOS = NingunEndpointRevientaTests.OTROS_MODULOS

    def test_ningun_post_revienta_ni_deja_al_cliente_colgado(self):
        import re
        import urllib.error
        rutas = sorted({r for r in re.findall(r'"(/api/[a-z_0-9]+)"', SERVER)
                        if not any(o in r for o in self.OTROS_MODULOS)
                        and "catastro" not in r})   # el Catastro es un servicio externo
        cuerpo = {
            "workspace_id": self.ws, "empresa_id": "emp1", "id": "inm1",
            "inmueble_id": "inm1", "cliente_id": "cli1", "demanda_id": "dem1",
            "nombre": "Prueba", "telefono": "600111222", "email": "p@x.test",
            "direccion": "Calle 1", "precio": 200000, "estado": "Activa", "tipo": "Piso",
        }
        rotos = []
        for ruta in rutas:
            try:
                r = self._post(ruta, cuerpo)
            except Exception as e:
                rotos.append((ruta, f"conexión cortada: {type(e).__name__}")); continue
            if r["estado"] >= 500:
                rotos.append((ruta, f'{r["estado"]} {str(r["json"])[:90]}'))
        self.assertEqual(rotos, [], f"escrituras que revientan: {rotos}")


class ElDerechoDeSupresionFuncionaTests(Agencia):
    """`cliente_suprimir` es el artículo 17 del RGPD y estaba roto: borraba las demandas
    antes que los cruces que apuntan a ellas, la clave ajena saltaba y la supresión se
    caía entera. En Postgres, además, ese fallo deja la transacción abortada, así que
    todo lo que viniera después en la misma petición reventaba también —eso es el
    `InFailedSqlTransaction` que se veía en pantalla."""

    def test_se_suprime_sin_romper_las_claves_ajenas(self):
        r = self._post("/api/cliente_suprimir",
                       {"workspace_id": self.ws, "cliente_id": "cli1"})
        self.assertEqual(r["estado"], 200, r["json"])
        self.assertTrue(r["json"]["ok"])

    def test_la_ficha_deja_de_identificar_a_nadie(self):
        self._post("/api/cliente_suprimir", {"workspace_id": self.ws, "cliente_id": "cli1"})
        fila = self.conn.execute(
            "SELECT nombre, telefono, email FROM clientes WHERE id = 'cli1'").fetchone()
        self.assertNotIn("Carlos", fila["nombre"])
        self.assertFalse(fila["telefono"])
        self.assertFalse(fila["email"])

    def test_lo_que_se_conserva_suelta_el_vinculo_pero_no_se_borra(self):
        """Una visita no está en la lista de lo que se borra, así que se queda. Lo que no
        puede es seguir apuntando a una demanda suprimida: la clave ajena lo impediría."""
        antes = self.conn.execute("SELECT COUNT(*) c FROM visitas").fetchone()["c"]
        self.assertGreater(antes, 0)
        r = self._post("/api/cliente_suprimir", {"workspace_id": self.ws, "cliente_id": "cli1"})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM visitas").fetchone()["c"], antes)
        self.assertEqual(r["json"]["desvinculado"].get("visitas"), antes)
        self.assertIsNone(self.conn.execute(
            "SELECT demanda_id FROM visitas LIMIT 1").fetchone()["demanda_id"])

    def test_los_hijos_se_borran_antes_que_sus_padres(self):
        """El orden de la lista es la corrección: si alguien vuelve a poner `demandas`
        por delante de `inmueble_compradores`, esto lo dice antes que producción."""
        tablas = [t for t, _ in S.RGPD_TABLAS_A_BORRAR]
        self.assertLess(tablas.index("inmueble_compradores"), tablas.index("demandas"))


class LasRespuestasLleganTests(Agencia):
    """`fin_checklist_update` hacía el UPDATE y volvía sin `commit` y sin responder: el
    cambio se perdía al devolver la conexión al pool y el navegador se quedaba colgado
    esperando una respuesta que no llegaba nunca. Un fallo silencioso es malo; una
    petición que no contesta lo es más, porque ni siquiera se puede reintentar."""

    def _con_checklist(self):
        self._ins("asesoramientos_financiacion",
                  dict(id="fa1", empresa_id="emp1", workspace_id=self.ws, cliente_id="cli2",
                       created_at=AHORA, updated_at=AHORA))
        self._ins("fin_checklist", dict(id="fc1", asesoramiento_id="fa1", tarea="Nóminas",
                                        estado="Pendiente", created_at=AHORA, updated_at=AHORA))

    def test_contesta_y_guarda(self):
        self._con_checklist()
        r = self._post("/api/fin_checklist_update", {"id": "fc1", "estado": "Hecho"})
        self.assertEqual(r["estado"], 200, r["json"])
        self.assertTrue(r["json"]["ok"])
        self.assertEqual(self.conn.execute(
            "SELECT estado FROM fin_checklist WHERE id = 'fc1'").fetchone()["estado"], "Hecho")

    def test_el_copiloto_del_encargo_no_revienta_con_una_fila_de_sqlite(self):
        """Leía las filas de la base con `.get`, que en Postgres funciona y en SQLite
        lanza AttributeError. Ahora contesta lo que falta en vez de caerse."""
        r = self._post("/api/ai_inmo_encargo_copilot", {"inmueble_id": "inm1", "task": "rellenar"})
        self.assertLess(r["estado"], 500, r["json"])


class LosDocumentosSalenYSalenLlenosTests(Agencia):
    DOCUMENTOS = [
        ("Nota de encargo (venta)", "/api/inmueble_encargo_pdf?id=inm1&tipo_operacion=venta"),
        ("Nota de encargo (alquiler)", "/api/inmueble_encargo_pdf?id=inm1&tipo_operacion=alquiler"),
        ("Hoja de visita", "/api/inmueble_visita_pdf?id=inm1&demanda_id=dem1"),
        ("Oferta de negociación", "/api/inmueble_negociacion_pdf?action_id=acc1"),
        ("Acuse de honorarios", "/api/inmueble_honorarios_pdf?action_id=acc2"),
        ("Ficha de venta", "/api/inmueble_consumo_pdf?id=inm1&kind=venta_ficha"),
        ("Nota de precio", "/api/inmueble_consumo_pdf?id=inm1&kind=venta_precio"),
        ("Hoja de alquiler por día", "/api/inmueble_consumo_pdf?id=inm1&kind=alquiler_dia"),
    ]

    def test_los_ocho_documentos_se_generan(self):
        from pypdf import PdfReader
        for nombre, ruta in self.DOCUMENTOS:
            with self.subTest(nombre):
                r = self._get(ruta)
                self.assertEqual(r["estado"], 200, r["json"])
                self.assertEqual(r["cuerpo"][:4], b"%PDF", "no es un PDF")
                self.assertGreaterEqual(len(PdfReader(BytesIO(r["cuerpo"])).pages), 1)

    def test_la_nota_de_encargo_lleva_el_precio_en_cifra_y_en_letra(self):
        """Un encargo sin precio no es un encargo."""
        texto = self._frase_pdf(
            self._get("/api/inmueble_encargo_pdf?id=inm1&precio_venta=285000")["cuerpo"])
        self.assertIn("precio de venta del inmueble en 285.000 € "
                      "(doscientos ochenta y cinco mil euros)", texto)

    def test_la_clausula_de_honorarios_dice_un_porcentaje_y_no_una_palabra(self):
        """«serán del Pendiente del precio de venta» no fija honorarios ningunos. El
        formulario los exige, pero el endpoint es una URL y se puede llamar sin ellos."""
        texto = self._frase_pdf(self._get(
            "/api/inmueble_encargo_pdf?id=inm1&precio_venta=285000&honorarios_pct=3&iva_pct=21"
        )["cuerpo"])
        self.assertIn("serán del 3% + IVA del precio de venta", texto)

    def test_sin_cargas_declaradas_la_frase_no_termina_en_un_hueco(self):
        """Decía «...cargas o gravámenes a excepción de NADA.», que en un contrato que
        se firma se lee como una plantilla sin rellenar. El formulario no pide las
        cargas, así que ese texto salía en el caso normal: cuando no hay ninguna."""
        texto = self._texto_pdf(self._get(
            "/api/inmueble_encargo_pdf?id=inm1&mode=final&precio_venta=285000"
            "&honorarios_pct=3&iva_pct=21")["cuerpo"])
        self.assertNotIn("a excepción de NADA", texto)
        self.assertIn("cargas o gravámenes.", texto)

    def test_con_cargas_declaradas_se_enumeran(self):
        texto = self._frase_pdf(self._get(
            "/api/inmueble_encargo_pdf?id=inm1&precio_venta=285000&honorarios_pct=3&iva_pct=21"
            "&cargas=Hipoteca%20con%20Unicaja")["cuerpo"])
        self.assertIn("a excepción de las siguientes: Hipoteca con Unicaja", texto)

    def test_la_nota_de_precio_no_inventa_un_cero(self):
        """Sin precio en la ficha imprimía «Precio de venta de la vivienda: 0,00 €». En
        un papel que se entrega al comprador eso no es un cero: es un hueco disfrazado
        de cifra."""
        self.conn.execute("UPDATE inmuebles SET precio_objetivo = NULL WHERE id = 'inm1'")
        self.conn.commit()
        texto = self._frase_pdf(self._get(
            "/api/inmueble_consumo_pdf?id=inm1&kind=venta_precio")["cuerpo"])
        self.assertNotIn("Precio de venta de la vivienda: 0,00 €", texto)
        self.assertIn("Precio de venta de la vivienda: ....", texto)

    def test_con_precio_lo_dice(self):
        texto = self._frase_pdf(self._get(
            "/api/inmueble_consumo_pdf?id=inm1&kind=venta_precio")["cuerpo"])
        self.assertIn("Precio de venta de la vivienda: 285.000,00 €", texto)

    def test_no_se_imprime_un_xx_xx_xxxx_en_un_contrato(self):
        """El resto del documento deja los huecos con puntos suspensivos. Aquí salía un
        `xx/xx/xxxx`, que no parece un hueco: parece plantilla olvidada. Y el formulario
        tampoco exige esa fecha, así que salía sin que nadie se diera cuenta."""
        texto = self._texto_pdf(self._get(
            "/api/inmueble_encargo_pdf?id=inm1&mode=final&precio_venta=285000"
            "&honorarios_pct=3&iva_pct=21")["cuerpo"])
        self.assertNotIn("xx/xx/xxxx", texto)


class AbrirElCrmInmobiliarioNoDejaLaPantallaEnBlancoTests(unittest.TestCase):
    """Pulsar «Inmobiliaria» en la portada abría la última vista usada, fuera de la
    vertical que fuera. Quien había estado en Financiaciones aterrizaba en `crmViewFin`
    —un panel de dos píxeles y vacío— y ahí se quedaba. Se reprodujo en el navegador las
    tres veces que se intentó, con el perfil limpio.

    No se vio leyendo el código: se vio entrando en el módulo."""

    def _cuerpo(self):
        i = APP.index("const openCrmInmobiliario = ()")
        return APP[i: APP.index("\nconst ", i + 10)]

    def test_no_se_reabre_una_vista_de_otra_vertical(self):
        cuerpo = self._cuerpo()
        self.assertIn("VISTAS_DE_OTRA_VERTICAL", cuerpo)
        for vista in ("fin", "seguros", "gestoria"):
            with self.subTest(vista=vista):
                self.assertIn(f'"{vista}"', cuerpo)

    def test_la_url_se_fija_antes_de_elegir_la_vista(self):
        """`setCrmWorkspaceView` deduce la vertical del `?crm=` de la URL; si se escribe
        después, la deduce de la vista anterior."""
        cuerpo = self._cuerpo()
        self.assertLess(cuerpo.index('currentParams.set("crm", "inmo")'),
                        cuerpo.index("setCrmWorkspaceView("))

    def test_la_version_del_cargador_sube_cuando_cambia_app_js(self):
        """El navegador cachea `app.js?v=NNN`. Sin subir ese número, un arreglo del
        front no llega a quien ya tiene la página abierta —ni a quien vuelve mañana."""
        import re
        m = re.search(r'"app\.js\?v=(\d+)"', HTML)
        self.assertIsNotNone(m, "el cargador ya no referencia app.js con versión")
        self.assertGreaterEqual(int(m.group(1)), 896)


class LosPortalesEscribenLasFechasEnCastellanoTests(unittest.TestCase):
    """Los tres portales los abre un cliente, no un informático. Las fechas viajan en
    ISO porque el servidor ordena y compara con ellas —«¿esta cita es futura?»— pero al
    llegar a la pantalla tienen que leerse como se escriben aquí.

    El arreglo va en la capa que pinta, no en `_fecha_corta`: ese ayudante alimenta
    ordenaciones (`key=lambda x: x["fecha"]`) y comparaciones (`fecha >= hoy`), y
    cambiarlo a dd/mm/aaaa habría ordenado mal la agenda y clasificado como pasadas
    citas futuras, sin que nada lo dijera."""

    PORTALES = {
        "comprador": 'if parsed.path == "/portal-busqueda":',
        "propietario": 'if parsed.path == "/portal-venta":',
        "comunero": 'if parsed.path == "/portal-comunidad":',
    }

    def _cuerpo(self, portal):
        i = SERVER.index(self.PORTALES[portal])
        siguientes = [SERVER.index(m) for m in self.PORTALES.values() if SERVER.index(m) > i]
        return SERVER[i: min(siguientes) if siguientes else i + 60000]

    def test_cada_portal_sabe_dar_formato_a_una_fecha(self):
        for portal in self.PORTALES:
            with self.subTest(portal=portal):
                cuerpo = self._cuerpo(portal)
                self.assertTrue(
                    "const fecha = (" in cuerpo or "const fechaCorta = (" in cuerpo,
                    f"el portal del {portal} no tiene con qué formatear una fecha")

    def test_ninguna_fecha_se_pinta_en_crudo(self):
        """`esc(x.fecha)` manda a la pantalla el ISO tal cual. Tiene que pasar por el
        formateador."""
        import re
        for portal in self.PORTALES:
            cuerpo = self._cuerpo(portal)
            crudas = re.findall(
                r'esc\(\s*(?!fecha\(|fechaCorta\(|haceCuanto\()[a-zA-Z_.]*\.'
                r'(?:fecha|fecha_limite|caduca|fecha_firma|fecha_escritura)\b[^)]*\)', cuerpo)
            with self.subTest(portal=portal):
                self.assertEqual(crudas, [], f"fechas sin formatear en el portal del {portal}: {crudas}")

    def test_el_ayudante_del_servidor_sigue_dando_iso(self):
        """Si alguien «arregla» esto en `_fecha_corta`, la agenda se ordena mal."""
        self.assertEqual(S._fecha_corta("2026-09-05T18:00:00"), "2026-09-05")
        self.assertEqual(S._fecha_corta("2026-09-05 18:00"), "2026-09-05")


class ElDashboardCalculaLoQueDiceTests(Agencia):
    """Que el panel pinte números no es que los números estén bien."""

    def _kpis(self):
        r = self._get(f"/api/inmo_inicio_dashboard?workspace_id={self.ws}&year=2026")
        self.assertEqual(r["estado"], 200, r["json"])
        return r["json"]["kpis"]

    def test_la_facturacion_de_ventas_es_la_suma_de_los_honorarios(self):
        self.assertAlmostEqual(self._kpis()["facturado_ventas"],
                               sum(h for *_, h in VENTAS_2026), places=2)

    def test_la_facturacion_de_alquileres_sale_de_su_propia_tabla(self):
        """Ventas y alquileres se facturan desde tablas distintas. Si alguien unifica
        una sin la otra, esto lo dice."""
        self.assertAlmostEqual(self._kpis()["facturado_alquileres"],
                               sum(c for _, c in ALQUILERES_2026), places=2)

    def test_el_total_es_la_suma_de_los_dos(self):
        k = self._kpis()
        self.assertAlmostEqual(k["facturado"],
                               k["facturado_ventas"] + k["facturado_alquileres"], places=2)

    def test_el_ejercicio_anterior_no_se_cuela(self):
        """Hay sembrada una venta de 2025 de 15.000 € y un alquiler de 2025 de 9.999 €."""
        k = self._kpis()
        self.assertNotIn(15000, (k["facturado_ventas"], k["facturado"]))
        self.assertLess(k["facturado"], 15000 + sum(h for *_, h in VENTAS_2026))

    def test_cuenta_las_ventas_y_los_encargos(self):
        k = self._kpis()
        self.assertEqual(k["ventas"], len(VENTAS_2026))
        self.assertEqual(k["encargos"], 2)       # cap1 y cap2, en etapa Encargo
        self.assertEqual(k["adquisiciones"], 4)  # las cuatro captaciones

    def test_los_ratios_derivados_cuadran_con_sus_sumandos(self):
        k = self._kpis()
        self.assertAlmostEqual(k["ratio_adquisicion_encargo"],
                               k["encargos"] / k["adquisiciones"], places=4)
        self.assertAlmostEqual(k["rentabilidad"], k["facturado"] - k["gastos"], places=2)

    def test_sin_facturacion_el_margen_no_revienta(self):
        """Dividir entre cero es la forma más tonta de tumbar un panel."""
        self.conn.execute("DELETE FROM operaciones_inmobiliarias")
        self.conn.execute("DELETE FROM alquileres")
        self.conn.commit()
        k = self._kpis()
        self.assertEqual(k["facturado"], 0)
        self.assertEqual(k["margen"], 0)


class LaWebPublicaNoEnsenaDeMasTests(Agencia):
    """El escaparate lo ve cualquiera, sin sesión."""

    def _publicar_todo(self):
        self.conn.execute("UPDATE inmuebles SET portal_publicado = 1")
        self.conn.execute("UPDATE captaciones SET noticia_verificada = 1")
        self.conn.commit()

    def test_se_sirve_sin_sesion(self):
        self._publicar_todo()
        r = self._get("/api/portal_inmuebles", cookie=False)
        self.assertEqual(r["estado"], 200)
        self.assertGreater(r["json"]["count"], 0)

    def test_un_piso_vendido_no_sigue_anunciado(self):
        """Lo peor que puede hacer un escaparate: enseñar lo que ya no está."""
        self._publicar_todo()
        ids = {f["id"] for f in self._get("/api/portal_inmuebles", cookie=False)["json"]["rows"]}
        self.assertNotIn("inm3", ids)
        self.assertEqual(self._get("/api/portal_inmueble?id=inm3", cookie=False)["estado"], 404)

    def test_sin_noticia_verificada_no_se_publica(self):
        """inm5 no tiene captación, así que nadie ha verificado que exista el encargo."""
        self._publicar_todo()
        ids = {f["id"] for f in self._get("/api/portal_inmuebles", cookie=False)["json"]["rows"]}
        self.assertNotIn("inm5", ids)
        self.assertLessEqual({"inm1", "inm2", "inm4"}, ids)

    def test_el_anuncio_lleva_precio_y_lo_esencial(self):
        self._publicar_todo()
        uno = [f for f in self._get("/api/portal_inmuebles", cookie=False)["json"]["rows"]
               if f["id"] == "inm1"][0]
        self.assertEqual(uno["precio"], 285000.0)
        for clave in ("direccion", "m2", "habitaciones", "banos", "tipo_inmueble"):
            with self.subTest(clave=clave):
                self.assertTrue(uno.get(clave), f"el anuncio no trae {clave}")

    def test_no_se_filtra_el_telefono_del_propietario(self):
        """Está en la ficha del inmueble; en el anuncio no pinta nada."""
        self._publicar_todo()
        crudo = json.dumps(self._get("/api/portal_inmuebles", cookie=False)["json"],
                           ensure_ascii=False)
        for secreto in ("600999888", "Pilar Propietaria", "honorarios"):
            with self.subTest(secreto):
                self.assertNotIn(secreto, crudo)


class LaMigracionDeEmpresasNoSeQuedaAMediasTests(Agencia):
    """`workspace_companies` es la tabla a la que se está migrando el ámbito del
    cliente. El backfill desde la tabla vieja pedía `e.primary_color` y `e.accent_color`
    a `empresas`, que no las tiene: la consulta fallaba entera, el `except` de arriba se
    tragaba el error y la migración no ocurría nunca. En producción quedaban 17 empresas
    en la tabla vieja y cero migradas, sin un solo síntoma visible."""

    def test_el_backfill_migra_de_verdad(self):
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) c FROM workspace_companies").fetchone()["c"], 0)
        r = self._get(f"/api/workspace_detail?id={self.ws}")
        self.assertEqual(r["estado"], 200, r["json"])
        migradas = self.conn.execute(
            "SELECT legacy_empresa_id, nombre FROM workspace_companies WHERE workspace_id = ?",
            (self.ws,)).fetchall()
        self.assertEqual([r["legacy_empresa_id"] for r in migradas], ["emp1"])
        self.assertEqual(migradas[0]["nombre"], "Inmobiliaria Modernia")

    def test_no_se_piden_columnas_que_la_tabla_no_tiene(self):
        cols = {r[1] for r in self.conn.execute("pragma table_info(empresas)")}
        i = SERVER.index("FROM workspace_empresas we")
        consulta = SERVER[SERVER.rindex("SELECT", 0, i): i]
        for pedida in {c.split(".")[1] for c in __import__("re").findall(r"\be\.[a-z_]+", consulta)}:
            with self.subTest(pedida):
                self.assertIn(pedida, cols, f"la consulta pide empresas.{pedida}, que no existe")

    def test_el_color_no_se_rellena_con_el_id_de_la_empresa(self):
        """`row_value` cae a `row[0]` cuando la clave no está, así que leer un color
        ausente colaba el `empresa_id` como si fuera un color."""
        self._get(f"/api/workspace_detail?id={self.ws}")
        fila = self.conn.execute(
            "SELECT primary_color, accent_color FROM workspace_companies WHERE workspace_id = ?",
            (self.ws,)).fetchone()
        self.assertEqual((fila["primary_color"], fila["accent_color"]), ("", ""))


class TodaVistaTieneComoLlegarseAEllaTests(unittest.TestCase):
    """Una pantalla a la que no se puede llegar es maquetación que se arrastra. Los
    paneles del CRM se abren desde la barra, desde tarjetas del panel y desde atajos
    del código; esta prueba compara la lista de paneles con la de sitios que llevan a
    ellos, y exige que no sobre ninguno por ningún lado."""

    def _vistas_alcanzables(self):
        import re
        return (set(re.findall(r'data-crm-view="([^"]+)"', HTML))
                | set(re.findall(r'crmView:\s*"([^"]+)"', APP))
                | set(re.findall(r'dataset\.crmView\s*=\s*"([^"]+)"', APP))
                | set(re.findall(r'setCrmWorkspaceView\("([a-z_]+)"\)', APP)))

    def _panel(self, vista):
        return "crmView" + "".join(t.capitalize() for t in vista.split("_"))

    def test_ningun_enlace_apunta_a_un_panel_que_no_existe(self):
        import re
        paneles = set(re.findall(r'id="(crmView[A-Za-z]+)"', HTML))
        rotos = sorted(v for v in self._vistas_alcanzables()
                       if self._panel(v) not in paneles and v != "inmueble_ficha")
        self.assertEqual(rotos, [], f"enlaces a paneles inexistentes: {rotos}")

    def test_no_queda_ningun_panel_sin_camino(self):
        """Análisis, Edificios, Informadores y Relaciones se retiraron del CRM en su día,
        pero sólo se les quitó la entrada: quedaban los paneles en el HTML, sus nombres en
        el mapa de vistas y en las listas de permitidas, y —salvo Análisis, que era un
        cascarón— los cargadores, las tablas, los buscadores y hasta un botón de imprimir.
        Código completo que no ejecutaba nadie y que parecía vivo al leerlo.

        Ya no están. Esta prueba impide que vuelva a quedarse a medias: si se retira una
        vista y se olvida la maquetación, o si se añade una y se olvida el enlace, salta."""
        import re
        paneles = set(re.findall(r'id="(crmView[A-Za-z]+)"', HTML))
        alcanzables = {self._panel(v) for v in self._vistas_alcanzables()}
        sin_camino = sorted(p for p in paneles if p not in alcanzables)
        self.assertEqual(sin_camino, [], f"paneles a los que no se puede llegar: {sin_camino}")

    def test_no_quedan_restos_de_las_vistas_retiradas(self):
        """Los restos de una retirada a medias no dan error: dan peso muerto. Se vigilan
        por nombre porque «relaciones» sigue existiendo, y con razón, en la ficha del
        cliente y en la del inmueble: eso es otra cosa y no se toca."""
        for resto in ("crmViewAnalisis", "crmViewEdificios", "crmViewInformadores",
                      "crmViewRelaciones", "crmRelacionesTable", "crmEdificiosTable",
                      "crmInformadoresTable", "loadCrmRelacionesCruce", "loadCrmEdificios",
                      "loadCrmInformadores"):
            with self.subTest(resto):
                self.assertNotIn(resto, HTML)
                self.assertNotIn(resto, APP)

    def test_la_ficha_del_cliente_conserva_sus_relaciones(self):
        """La pestaña «Relaciones» de la ficha de un cliente no tiene nada que ver con la
        vista retirada del CRM más allá del nombre. Si una limpieza se la lleva por
        delante, esto lo dice."""
        self.assertIn('data-tab="relaciones"', APP + HTML)
        self.assertIn("clienteTabRelaciones", APP)

if __name__ == "__main__":
    unittest.main()
