"""Portal del cliente: seguridad del enlace y secciones de gestoría (2026-09-19).

Lo que había antes, visto al estudiarlo:
- "Pausado" solo lo miraban dos de las siete rutas públicas: un cliente pausado seguía
  viendo sus datos, subiendo documentos y bajando su Excel.
- El enlace se guardaba en claro, no caducaba y cualquier guardado (también pausar)
  generaba uno nuevo sin avisar, anulando el que el cliente tenía.
- Salían documentos que la lectura automática solo había *sugerido* para el cliente.
- Se podía abrir portal a un cliente de otro workspace.

Y lo nuevo: la gestoría decide, cliente a cliente, qué secciones ve (modelos, rentas,
documentos, resumen contable y facturas emitidas). Todas apagadas por defecto.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ["DATABASE_URL"] = ""

from web import server as S  # noqa: E402

NOW = "2026-09-19 10:00:00"
PASSWORD = "Secreto123!"


class PortalDelClienteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "portal.sqlite"
        S.ensure_tables(cls.db_path)
        cls.conn = S.open_sqlite_conn(str(cls.db_path), with_row_factory=True)
        cls.conn.execute("PRAGMA foreign_keys = OFF")
        # Los ficheros de prueba, en una carpeta temporal y no en las subidas reales.
        cls._prev_uploads = S.UPLOADS
        S.UPLOADS = Path(cls.tmp.name) / "uploads"
        cls._seed()
        cls._prev_db_path = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(cls.db_path)
        cls.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        req = urllib.request.Request(
            cls.base + "/api/login",
            data=json.dumps({"usuario": "gestor", "password": PASSWORD}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            cls.cookie = r.headers.get("Set-Cookie").split(";")[0]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.conn.close()
        S.UPLOADS = cls._prev_uploads
        if cls._prev_db_path is not None:
            S.Handler.db_path = cls._prev_db_path
        cls.tmp.cleanup()

    def setUp(self):
        S.Handler.db_path = str(self.db_path)

    @classmethod
    def _insert(cls, tabla, datos):
        validas = {r[1] for r in cls.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in validas}
        cls.conn.execute(
            f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})", tuple(d.values())
        )
        cls.conn.commit()

    @classmethod
    def _seed(cls):
        t = {"created_at": NOW, "updated_at": NOW}
        cls._insert("empresas", {"id": "empA", "nombre": "Gestoría A", "activo": 1, **t})
        cls._insert("empresas", {"id": "empB", "nombre": "Otra B", "activo": 1, **t})
        for ws, nombre, emp in (("wsA", "Modernia", "empA"), ("wsB", "Otro", "empB")):
            cls._insert("workspaces", {"id": ws, "nombre": nombre, "slug": ws.lower(), "estado": "Activo", **t})
            cls._insert("workspace_empresas", {"id": f"we-{ws}", "workspace_id": ws, "empresa_id": emp, **t})
        cls._insert("usuarios", {"id": "u1", "nombre": "Gestor", "usuario": "gestor", "email": "g@a.test",
                                 "rol": "Administrador", "servicio": "Todos", "activo": 1,
                                 "password_hash": S.hash_password(PASSWORD), **t})
        cls._insert("workspace_miembros", {"id": "wm1", "workspace_id": "wsA", "usuario_id": "u1",
                                           "rol": "Administrador", **t})
        for cid, nombre, ws, emp in (("cliA", "Cliente A", "wsA", "empA"), ("cliA2", "Cliente A2", "wsA", "empA"),
                                     ("cliB", "Cliente B", "wsB", "empB")):
            cls._insert("clientes", {"id": cid, "nombre": nombre, "workspace_id": ws, "empresa_id": emp, **t})
        # Documentos de la bandeja: uno asignado al cliente y otro solo sugerido.
        cls._insert("workspace_documentos_inbox", {"id": "inb1", "workspace_id": "wsA", "cliente_id": "cliA",
                                                   "nombre": "Asignado.pdf", "estado": "Revisado", **t})
        cls._insert("workspace_documentos_inbox", {"id": "inb2", "workspace_id": "wsA", "suggested_cliente_id": "cliA",
                                                   "nombre": "Sugerido.pdf", "estado": "Pendiente", **t})
        # Gestoría del cliente A.
        cls._insert("gestoria_modelos", {"id": "m1", "cliente_id": "cliA", "modelo": "303", "periodicidad": "Trimestral",
                                         "proxima_fecha": "2026-10-20", "estado": "Pendiente",
                                         "responsable": "Interno", "notas": "NOTA INTERNA", **t})
        cls._insert("cliente_gestoria", {"id": "cg1", "cliente_id": "cliA", "renta_detalles": json.dumps({
            "notes": "nota interna", "entries": [
                {"ejercicio": "2025", "estado_presentacion": "Presentada", "presentacion_fecha": "2026-04-21",
                 "resultado_declaracion": "-4002.9", "precio_servicio": "60", "casillas": {"0435": 1},
                 "gestion_notas": "NO ENSEÑAR", "doc_url": "/uploads/rentas/2025/cliA.pdf"},
                {"ejercicio": "2024", "estado_presentacion": "Presentada", "resultado_declaracion": "0"},
            ]}), **t})
        cls._insert("gestoria_docs", {"id": "gd1", "empresa_id": "empA", "workspace_id": "wsA", "cliente_id": "cliA",
                                      "nombre": "Escritura.pdf", "tipo": "Escritura", "referencia_tipo": "",
                                      "doc_url": "/uploads/gestoria/escritura.pdf", **t})
        cls._insert("gestoria_docs", {"id": "gd2", "empresa_id": "empA", "workspace_id": "wsA", "cliente_id": "cliA",
                                      "nombre": "Poliza.pdf", "referencia_tipo": "seguros",
                                      "doc_url": "/uploads/gestoria/poliza.pdf", **t})
        cls._insert("gestoria_docs", {"id": "gd3", "empresa_id": "empA", "workspace_id": "wsA", "cliente_id": "cliA2",
                                      "nombre": "DeOtroCliente.pdf", "doc_url": "/uploads/gestoria/otro.pdf", **t})
        for i, (fecha, tipo, importe) in enumerate((("2025-03-01", "Ingreso", 1000), ("2025-05-01", "Gasto", 300),
                                                     ("2026-01-10", "Gasto", 50))):
            cls._insert("gestoria_contabilidad", {"id": f"gc{i}", "empresa_id": "empA", "workspace_id": "wsA",
                                                  "cliente_id": "cliA", "fecha": fecha, "tipo": tipo, "importe": importe, **t})
        cls._insert("gestoria_facturas", {"id": "gf1", "empresa_id": "empA", "workspace_id": "wsA", "cliente_id": "cliA",
                                          "tipo": "venta", "numero": "F-1", "fecha_emision": "2026-02-01", "total": 121,
                                          "doc_key": "facturas_inbox/x/emitidas/f1.pdf", **t})
        cls._insert("gestoria_facturas", {"id": "gf2", "empresa_id": "empA", "workspace_id": "wsA", "cliente_id": "cliA",
                                          "tipo": "compra", "numero": "C-1", "total": 50, **t})
        # Contabilidad del cliente A. 2025: libro diario importado (LD) con apertura,
        # una venta, una compra, la liquidación del IVA, un cobro, regularización y
        # cierre; y un asiento que el CRM generó desde la factura (FACT), que duplica la
        # venta. 2026: solo contabilidad del CRM, sin regularizar.
        asientos = (
            ("as1", "2025-01-01", "ASIENTO DE APERTURA", "LD2025", (("572", "BANCO", 1000, 0), ("100", "CAPITAL", 0, 1000))),
            ("as2", "2025-02-01", "NTRA. FRA. Nº 1", "LD2025", (("4300001", "CLI UNO", 1210, 0), ("7050001", "SERVICIOS", 0, 1000), ("4770021", "IVA REP", 0, 210))),
            ("as3", "2025-02-10", "SU FRA. Nº 9", "LD2025", (("6280001", "LUZ", 100, 0), ("4720021", "IVA SOP", 21, 0), ("4100001", "PROV", 0, 121))),
            ("as4", "2025-03-31", "LIQUIDACIÓN IVA 1T", "LD2025", (("4770021", "IVA REP", 210, 0), ("4720021", "IVA SOP", 0, 21), ("4750001", "HP ACREEDORA", 0, 189))),
            ("as5", "2025-04-01", "COBRO FRA 1", "LD2025", (("572", "BANCO", 1210, 0), ("4300001", "CLI UNO", 0, 1210))),
            ("as6", "2025-12-31", "ASIENTO DE REGULARIZACIÓN", "LD2025", (("7050001", "SERVICIOS", 1000, 0), ("6280001", "LUZ", 0, 100), ("129", "RESULTADO", 0, 900))),
            ("as7", "2025-12-31", "ASIENTO DE CIERRE", "LD2025", (("100", "CAPITAL", 1000, 0), ("129", "RESULTADO", 900, 0), ("4750001", "HP ACREEDORA", 189, 0), ("4100001", "PROV", 121, 0), ("572", "BANCO", 0, 2210))),
            ("as8", "2025-02-01", "1/2025", "FACT", (("430", "CLI UNO", 1210, 0), ("700", "VENTAS", 0, 1000), ("477", "IVA", 0, 210))),
            ("as9", "2026-03-01", "2/2026", "FACT", (("430", "CLI DOS", 605, 0), ("705", "SERVICIOS", 0, 500), ("477", "IVA", 0, 105))),
        )
        for aid, fecha, concepto, diario, lineas in asientos:
            cls._insert("gestoria_asientos", {"id": aid, "empresa_id": "empA", "workspace_id": "wsA", "cliente_id": "cliA",
                                              "fecha": fecha, "concepto": concepto, "diario": diario, "referencia": aid, **t})
            for n, (cuenta, desc, debe, haber) in enumerate(lineas):
                cls._insert("gestoria_asiento_lineas", {"id": f"{aid}-{n}", "asiento_id": aid, "cuenta": cuenta,
                                                        "descripcion": desc, "debe": debe, "haber": haber, **t})
        # Ficheros reales para la descarga local.
        for rel in ("rentas/2025/cliA.pdf", "gestoria/escritura.pdf", "gestoria/poliza.pdf", "gestoria/otro.pdf"):
            ruta = S.UPLOADS / rel
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(b"%PDF-1.4 prueba")

    # ---------- utilidades ----------

    def _post(self, cuerpo):
        req = urllib.request.Request(self.base + "/api/workspace_portal", data=json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json", "Cookie": self.cookie}, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def _get(self, ruta, cookie=True, token=None):
        req = urllib.request.Request(self.base + ruta)
        if cookie:
            req.add_header("Cookie", self.cookie)
        if token:
            req.add_header("X-Access-Token", token)

        class SinRedireccion(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        opener = urllib.request.build_opener(SinRedireccion)
        try:
            with opener.open(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def _alta(self, cliente="cliA", **extra):
        status, data = self._post({"workspace_id": "wsA", "cliente_id": cliente, "estado": "Activo", **extra})
        self.assertEqual(status, 200, data)
        return data

    def _publico(self, token):
        status, cuerpo = self._get("/api/workspace_portal_public", cookie=False, token=token)
        return status, (json.loads(cuerpo.decode() or "{}") if cuerpo else {})

    def _fila(self, cliente="cliA"):
        return self.conn.execute("SELECT * FROM workspace_portal_clientes WHERE cliente_id = ?", (cliente,)).fetchone()

    def tearDown(self):
        self.conn.execute("DELETE FROM workspace_portal_clientes")
        self.conn.commit()

    # ---------- parte A: el enlace ----------

    def test_el_enlace_se_guarda_cifrado_y_caduca_en_un_anio(self):
        data = self._alta()
        self.assertTrue(data["token"])
        self.assertEqual(data["enlace"], f"/#portal_token={data['token']}")
        fila = self._fila()
        self.assertIsNone(fila["token"])
        self.assertEqual(fila["token_hash"], S.hash_portal_token(data["token"]))
        self.assertEqual(fila["expira_at"][:4], "2027")
        self.assertEqual(self._publico(data["token"])[0], 200)

    def test_guardar_no_cambia_el_enlace(self):
        data = self._alta()
        otra = self._alta(email_acceso="nuevo@c.test")
        self.assertNotIn("token", otra)
        self.assertEqual(self._fila()["token_hash"], S.hash_portal_token(data["token"]))
        self.assertEqual(self._publico(data["token"])[0], 200)

    def test_pausado_no_entra_en_ninguna_ruta_publica(self):
        data = self._alta()
        self._alta(estado="Pausado")
        token = data["token"]
        self.assertEqual(self._publico(token)[0], 404)
        self.assertIsNone(S.portal_cliente_por_token(self.conn, token))
        for ruta in ("/api/workspace_portal_facturas_excel", "/api/workspace_portal_s3_url?key=portal/x",
                     "/api/workspace_portal_gestoria_archivo?tipo=documento&id=gd1"):
            with self.subTest(ruta=ruta):
                self.assertEqual(self._get(ruta, cookie=False, token=token)[0], 404)
        # Y al activarlo vuelve el mismo enlace.
        self._alta(estado="Activo")
        self.assertEqual(self._publico(token)[0], 200)

    def test_revocar_anula_el_enlace_y_regenerar_da_uno_nuevo(self):
        viejo = self._alta()["token"]
        status, data = self._post({"workspace_id": "wsA", "cliente_id": "cliA", "accion": "revocar"})
        self.assertEqual(status, 200, data)
        self.assertEqual(self._fila()["estado"], "Revocado")
        self.assertIsNone(self._fila()["token_hash"])
        self.assertEqual(self._publico(viejo)[0], 404)
        nuevo = self._alta(accion="regenerar")["token"]
        self.assertNotEqual(nuevo, viejo)
        self.assertEqual(self._publico(nuevo)[0], 200)
        self.assertEqual(self._publico(viejo)[0], 404)

    def test_caducado_no_entra(self):
        token = self._alta(dias_validez=30)["token"]
        self.conn.execute("UPDATE workspace_portal_clientes SET expira_at = '2020-01-01 00:00:00'")
        self.conn.commit()
        self.assertEqual(self._publico(token)[0], 404)

    def test_un_enlace_antiguo_en_claro_se_acepta_y_se_cifra(self):
        self._alta()
        self.conn.execute("UPDATE workspace_portal_clientes SET token = 'antiguo123', token_hash = NULL, expira_at = NULL")
        self.conn.commit()
        self.assertEqual(self._publico("antiguo123")[0], 200)
        fila = self._fila()
        self.assertIsNone(fila["token"])
        self.assertEqual(fila["token_hash"], S.hash_portal_token("antiguo123"))
        self.assertEqual(self._publico("antiguo123")[0], 200)

    def test_no_se_abre_portal_a_un_cliente_de_otro_workspace(self):
        status, data = self._post({"workspace_id": "wsA", "cliente_id": "cliB", "estado": "Activo"})
        self.assertEqual(status, 400, data)
        self.assertIsNone(self._fila("cliB"))

    def test_la_lista_no_ensenia_el_enlace(self):
        token = self._alta()["token"]
        status, cuerpo = self._get("/api/workspace_portal?workspace_id=wsA")
        self.assertEqual(status, 200)
        texto = cuerpo.decode()
        self.assertNotIn(token, texto)
        fila = json.loads(texto)["rows"][0]
        self.assertNotIn("token", fila)
        self.assertEqual(fila["enlace_activo"], 1)
        self.assertEqual(fila["secciones"], {k: False for k in S.PORTAL_CLIENTE_SECCION_CLAVES})

    def test_solo_documentos_asignados_de_verdad(self):
        token = self._alta()["token"]
        nombres = [d["nombre"] for d in self._publico(token)[1]["docs"]]
        self.assertEqual(nombres, ["Asignado.pdf"])

    # ---------- parte B: secciones de gestoría ----------

    def test_sin_secciones_encendidas_no_sale_nada_de_gestoria(self):
        token = self._alta()["token"]
        data = self._publico(token)[1]
        self.assertEqual(data["secciones"], {k: False for k in S.PORTAL_CLIENTE_SECCION_CLAVES})
        for clave in ("gestoria_modelos", "gestoria_rentas", "gestoria_documentos",
                      "gestoria_contabilidad", "gestoria_facturas_emitidas"):
            self.assertNotIn(clave, data)
        self.assertEqual(self._get("/api/workspace_portal_gestoria_archivo?tipo=documento&id=gd1",
                                   cookie=False, token=token)[0], 404)

    def test_con_todas_las_secciones(self):
        token = self._alta(secciones={k: True for k in S.PORTAL_CLIENTE_SECCION_CLAVES})["token"]
        data = self._publico(token)[1]
        self.assertTrue(all(data["secciones"].values()))
        self.assertEqual([m["modelo"] for m in data["gestoria_modelos"]], ["303"])
        self.assertNotIn("notas", data["gestoria_modelos"][0])
        self.assertEqual(data["gestoria_rentas"][0], {"ejercicio": "2025", "estado": "Presentada",
                                                     "presentacion_fecha": "2026-04-21", "resultado": -4002.9,
                                                     "tiene_documento": True})
        self.assertNotIn("NO ENSEÑAR", json.dumps(data))
        self.assertNotIn("nota interna", json.dumps(data))
        self.assertEqual([d["nombre"] for d in data["gestoria_documentos"]], ["Escritura.pdf"])
        self.assertEqual(data["gestoria_contabilidad"], [
            {"ejercicio": "2026", "ingresos": 0.0, "gastos": 50.0, "apuntes": 1, "resultado": -50.0},
            {"ejercicio": "2025", "ingresos": 1000.0, "gastos": 300.0, "apuntes": 2, "resultado": 700.0},
        ])
        self.assertEqual([f["numero"] for f in data["gestoria_facturas_emitidas"]], ["F-1"])
        self.assertTrue(data["gestoria_facturas_emitidas"][0]["tiene_pdf"])

    def test_guardar_sin_secciones_conserva_las_que_habia(self):
        self._alta(secciones={"modelos": True})
        self._alta(estado="Activo")
        self.assertEqual(S.portal_cliente_secciones(self._fila()["secciones_json"])["modelos"], True)

    def test_descargas_solo_de_lo_suyo_y_de_secciones_encendidas(self):
        token = self._alta(secciones={"documentos_gestoria": True, "rentas": True})["token"]
        ruta = "/api/workspace_portal_gestoria_archivo?token=" + token
        status, cuerpo = self._get(ruta + "&tipo=documento&id=gd1", cookie=False)
        self.assertEqual(status, 200)
        self.assertTrue(cuerpo.startswith(b"%PDF"))
        self.assertEqual(self._get(ruta + "&tipo=renta&id=2025", cookie=False)[0], 200)
        # De otro módulo, de otro cliente o de una sección apagada: nada.
        self.assertEqual(self._get(ruta + "&tipo=documento&id=gd2", cookie=False)[0], 404)
        self.assertEqual(self._get(ruta + "&tipo=documento&id=gd3", cookie=False)[0], 404)
        self.assertEqual(self._get(ruta + "&tipo=factura&id=gf1", cookie=False)[0], 404)
        self.assertEqual(self._get(ruta + "&tipo=renta&id=2024", cookie=False)[0], 404)


    # ---------- libros contables ----------

    def test_libros_con_diario_importado(self):
        libros = S.portal_cliente_libros(self.conn, "wsA", "cliA")
        self.assertEqual(libros["ejercicios"], ["2026", "2025"])
        d = libros["por_ejercicio"]["2025"]
        self.assertEqual(d["origen"], "Libro diario importado")
        # La venta cuenta una vez: el asiento FACT duplicado no entra.
        self.assertEqual(d["pyg"]["partidas"], [
            {"clave": "cifra_negocios", "nombre": "Importe neto de la cifra de negocios", "importe": 1000.0},
            {"clave": "otros_gastos", "nombre": "Otros gastos de explotación", "importe": -100.0},
        ])
        self.assertEqual(d["pyg"]["resultado_ejercicio"], 900.0)
        # El balance, sin el asiento de cierre (que lo dejaría todo a cero).
        b = d["balance"]
        self.assertTrue(b["cuadra"])
        self.assertEqual((b["total_activo"], b["total_pasivo"]), (2210.0, 2210.0))
        self.assertEqual(b["activo"][1]["partidas"], [{"nombre": "Tesorería", "importe": 2210.0}])
        self.assertEqual(b["pasivo"][0]["partidas"], [{"nombre": "Fondos propios", "importe": 1900.0}])
        # Libro registro: la liquidación del IVA y el cobro no son facturas.
        self.assertEqual(d["facturas_emitidas"], [{"fecha": "2025-02-01", "concepto": "NTRA. FRA. Nº 1", "tercero": "CLI UNO",
                                                   "base": 1000.0, "iva": 210.0, "retencion": 0.0, "total": 1210.0}])
        self.assertEqual([(r["tercero"], r["base"], r["iva"], r["total"]) for r in d["facturas_recibidas"]],
                         [("PROV", 100.0, 21.0, 121.0)])

    def test_libros_sin_regularizar_suman_el_resultado_al_patrimonio(self):
        d = S.portal_cliente_libros(self.conn, "wsA", "cliA")["por_ejercicio"]["2026"]
        self.assertEqual(d["origen"], "Contabilidad del CRM")
        self.assertEqual(d["pyg"]["resultado_ejercicio"], 500.0)
        self.assertTrue(d["balance"]["cuadra"])
        self.assertEqual(d["balance"]["pasivo"][0]["partidas"],
                         [{"nombre": "Resultado del ejercicio (sin regularizar)", "importe": 500.0}])

    def test_dashboard_con_importe_y_porcentaje(self):
        libros = S.portal_cliente_libros(self.conn, "wsA", "cliA")
        d = libros["por_ejercicio"]["2025"]["dashboard"]
        self.assertEqual((d["facturado"], d["facturas"], d["ingresos"], d["gastos"], d["resultado"]),
                         (1000.0, 1, 1000.0, 100.0, 900.0))
        self.assertEqual(d["margen_pct"], 90.0)
        self.assertEqual(d["facturado_por_mes"][1], 1000.0)
        self.assertEqual(sum(d["facturado_por_mes"]), 1000.0)
        self.assertEqual(d["ingresos_por_categoria"], [{"nombre": "Prestación de servicios", "importe": 1000.0, "pct": 100.0}])
        self.assertEqual(d["gastos_por_tipo"], [{"nombre": "Suministros", "importe": 100.0, "pct": 100.0}])
        # Evolución entre ejercicios, del más antiguo al más reciente.
        self.assertEqual([(e["ejercicio"], e["facturado"], e["resultado"]) for e in libros["evolucion"]],
                         [("2025", 1000.0, 900.0), ("2026", 500.0, 500.0)])

    def test_reparto_agrupa_lo_pequenio_en_otros(self):
        importes = {f"Tipo {i}": float(100 - i) for i in range(12)}
        filas = S._portal_reparto(importes)
        self.assertEqual(len(filas), S.PORTAL_DASHBOARD_MAX_CATEGORIAS)
        self.assertEqual(filas[-1]["nombre"], "Otros")
        self.assertAlmostEqual(sum(f["importe"] for f in filas), sum(importes.values()), places=2)
        self.assertAlmostEqual(sum(f["pct"] for f in filas), 100.0, delta=0.2)
        self.assertEqual(S._portal_nombre_por_prefijo("6230000000001", S.PORTAL_TIPOS_GASTO, "x"), "Asesoría y profesionales")
        self.assertEqual(S._portal_nombre_por_prefijo("6080000000000", S.PORTAL_TIPOS_GASTO, "x"), "Compras de mercaderías")
        self.assertEqual(S._portal_nombre_por_prefijo("7780000000000", S.PORTAL_CATEGORIAS_INGRESO, "x"), "Ingresos excepcionales")

    def test_libros_solo_con_la_seccion_encendida(self):
        token = self._alta(secciones={"facturas_emitidas": True})["token"]
        self.assertNotIn("gestoria_libros", self._publico(token)[1])
        excel = "/api/workspace_portal_libros_excel?ejercicio=2025&token=" + token
        self.assertEqual(self._get(excel, cookie=False)[0], 404)
        self._alta(secciones={"libros": True})
        data = self._publico(token)[1]
        self.assertEqual(data["gestoria_libros"]["ejercicios"], ["2026", "2025"])
        status, cuerpo = self._get(excel, cookie=False)
        self.assertEqual(status, 200)
        self.assertTrue(cuerpo.startswith(b"PK"))
        self.assertEqual(self._get(excel.replace("2025", "1999"), cookie=False)[0], 404)


if __name__ == "__main__":
    unittest.main()
