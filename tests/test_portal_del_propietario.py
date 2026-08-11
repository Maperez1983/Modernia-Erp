"""El propietario sigue su venta desde fuera, sin ver de más.

Un vendedor pregunta cuatro cosas, siempre las mismas: en qué punto va, cuánta gente
ha venido a verlo, qué falta por su parte y qué ha firmado. Todo estaba ya en el
expediente; faltaba una puerta hacia fuera.

La mitad de este fichero es lo que **no** puede salir por esa puerta. Un enlace que
se reenvía por WhatsApp acaba en manos que no son las del propietario, así que lo que
haya detrás tiene que poder leerlo un desconocido sin que eso sea un problema:

- **Quién es el comprador.** No ha consentido que su nombre y su teléfono viajen al
  vendedor. Que haya una oferta sobre la casa no da derecho a saber de quién.
- **Los honorarios de la agencia.** Es su casa, no la contabilidad de la inmobiliaria.
- **Las notas internas y las acciones de gestión.** Sólo las que le afectan.
- **Los identificadores internos**: con el enlace basta; un id de empresa o de
  workspace sólo sirve para probar suerte en otros endpoints.

Y el acceso en sí: revocable, caducable, rotable, y cerrado solo cuando la venta
termina.
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
os.environ["POSTGRES_URL"] = ""

from web import server as S  # noqa: E402

AHORA = "2026-08-11 09:00:00"
CLAVE = "Portal1234!"


class BasePortal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "portal.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        S.ensure_inmueble_portal_schema(self.conn)
        self.conn.commit()
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        self._seed()
        self._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        req = urllib.request.Request(
            self.base + "/api/login",
            data=json.dumps({"usuario": "portal", "password": CLAVE}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            self.cookie = r.headers.get("Set-Cookie").split(";")[0]

    def tearDown(self):
        self.httpd.shutdown()
        self.conn.close()
        if self._prev is not None:
            S.Handler.db_path = self._prev
        self.tmp.cleanup()
        os.environ.pop("SIGNATURE_WHATSAPP_WEBHOOK_URL", None)
        os.environ.pop("SIGNATURE_SMS_WEBHOOK_URL", None)

    def _ins(self, tabla, datos):
        validas = {r[1] for r in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in validas}
        self.conn.execute(
            f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        self.conn.commit()

    def _seed(self):
        self._ins("empresas", {"id": "emp1", "nombre": "Agencia Propia", "activo": 1,
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("empresas", {"id": "empX", "nombre": "Agencia Ajena", "activo": 1,
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_empresas", {"id": "we1", "workspace_id": self.ws, "empresa_id": "emp1",
                                         "created_at": AHORA, "updated_at": AHORA})
        self._ins("usuarios", {"id": "u1", "nombre": "Asesora", "usuario": "portal",
                               "email": "p@x.test", "rol": "Administrador", "servicio": "Inmobiliaria",
                               "activo": 1, "password_hash": S.hash_password(CLAVE),
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_miembros", {"id": "wm1", "workspace_id": self.ws, "usuario_id": "u1",
                                         "rol": "Owner", "created_at": AHORA, "updated_at": AHORA})
        self._ins("clientes", {"id": "prop1", "empresa_id": "emp1", "workspace_id": self.ws,
                               "nombre": "Lucía Vendedora", "nif": "11111111H",
                               "telefono": "+34600111222", "created_at": AHORA, "updated_at": AHORA})
        self._ins("clientes", {"id": "comp1", "empresa_id": "emp1", "workspace_id": self.ws,
                               "nombre": "Comprador Secreto", "nif": "22222222J",
                               "telefono": "+34699888777", "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmuebles", {"id": "inm1", "workspace_id": self.ws, "empresa_id": "emp1",
                                "direccion": "Calle Portal 1", "poblacion": "Málaga",
                                "tipo_inmueble": "Piso", "m2": 90, "habitaciones": 3,
                                "precio_objetivo": 250000, "honorarios": 7500,
                                "estado": "Encargo", "asesor": "Asesora",
                                "created_at": AHORA, "updated_at": AHORA})
        # La agencia ajena cuelga de su propio workspace, como en producción: una
        # empresa suelta sin workspace no existe y probar contra eso no prueba nada.
        self._ins("workspaces", {"id": "ws2", "nombre": "Otro", "slug": "otro",
                                 "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_empresas", {"id": "we2", "workspace_id": "ws2", "empresa_id": "empX",
                                         "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmuebles", {"id": "inmX", "empresa_id": "empX", "workspace_id": "ws2",
                                "direccion": "Calle Ajena 99", "estado": "Encargo",
                                "created_at": AHORA, "updated_at": AHORA})
        self._ins("clientes", {"id": "propX", "empresa_id": "empX", "workspace_id": "ws2",
                               "nombre": "Dueño Ajeno", "telefono": "+34611000000",
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmueble_propietarios", {"id": "ipX", "inmueble_id": "inmX", "cliente_id": "propX",
                                            "empresa_id": "empX", "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmueble_propietarios", {"id": "ip1", "inmueble_id": "inm1", "cliente_id": "prop1",
                                            "empresa_id": "emp1", "created_at": AHORA, "updated_at": AHORA})
        self._ins("captaciones", {"id": "cap1", "workspace_id": self.ws, "empresa_id": "emp1",
                                  "inmueble_id": "inm1", "direccion": "Calle Portal 1",
                                  "etapa": "Encargo", "notas": "El vendedor tiene prisa, aprieta el precio",
                                  "created_at": AHORA, "updated_at": AHORA})
        # Movimiento del expediente.
        self._ins("visitas", {"id": "v1", "workspace_id": self.ws, "empresa_id": "emp1",
                              "inmueble_id": "inm1", "fecha": "2026-08-01", "hora": "17:00",
                              "estado": "Realizada", "created_at": AHORA, "updated_at": AHORA})
        self._ins("visitas", {"id": "v2", "workspace_id": self.ws, "empresa_id": "emp1",
                              "inmueble_id": "inm1", "fecha": "2026-08-20", "hora": "11:00",
                              "estado": "Prevista", "created_at": AHORA, "updated_at": AHORA})
        self._ins("acciones", {"id": "a1", "workspace_id": self.ws, "empresa_id": "emp1",
                               "inmueble_id": "inm1", "servicio": "inmobiliaria", "fecha": "2026-08-02",
                               "tipo": "Seguimiento", "asunto": "Llamar al propietario para bajar precio",
                               "estado": "Completada", "created_at": AHORA, "updated_at": AHORA})
        self._ins("acciones", {"id": "a2", "workspace_id": self.ws, "empresa_id": "emp1",
                               "inmueble_id": "inm1", "servicio": "inmobiliaria", "fecha": "2026-08-03",
                               "tipo": "Lead portal", "asunto": "Contacto desde el portal",
                               "estado": "Completada", "created_at": AHORA, "updated_at": AHORA})
        self._ins("demandas", {"id": "dem1", "workspace_id": self.ws, "empresa_id": "emp1",
                               "cliente_id": "comp1", "tipo": "Piso", "estado": "Activa",
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmueble_compradores", {"id": "ic1", "empresa_id": "emp1", "inmueble_id": "inm1",
                                           "demanda_id": "dem1", "cliente_id": "comp1",
                                           "estado": "Interesado", "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmueble_checklist", {"id": "c1", "inmueble_id": "inm1", "empresa_id": "emp1",
                                         "etapa": "Encargo", "tarea": "Traer la nota simple",
                                         "responsable": "Propietario", "estado": "Pendiente",
                                         "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmueble_checklist", {"id": "c2", "inmueble_id": "inm1", "empresa_id": "emp1",
                                         "etapa": "Encargo", "tarea": "Revisar margen de honorarios",
                                         "responsable": "Asesora", "estado": "Pendiente",
                                         "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmueble_docs", {"id": "d1", "inmueble_id": "inm1", "empresa_id": "emp1",
                                    "nombre": "Informe interno de valoración", "url": "/uploads/x.pdf",
                                    "created_at": AHORA, "updated_at": AHORA})

    # ---------- utilidades ----------

    def _post(self, ruta, cuerpo, con_sesion=True):
        req = urllib.request.Request(self.base + ruta, data=json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        if con_sesion:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            cuerpo = e.read().decode()
            try:
                return e.code, json.loads(cuerpo or "{}")
            except Exception:
                return e.code, {"raw": cuerpo}

    def _get(self, ruta, con_sesion=False):
        req = urllib.request.Request(self.base + ruta)
        if con_sesion:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def _abre_portal(self, inmueble_id="inm1"):
        estado, d = self._post("/api/inmueble_portal_acceso", {"inmueble_id": inmueble_id, "avisar": False})
        self.assertEqual(estado, 200, d)
        return d

    def _token(self, enlace):
        return enlace.split("token=", 1)[1]

    def _vista(self, token):
        estado, cuerpo = self._get(f"/api/portal_venta?token={token}")
        self.assertEqual(estado, 200, cuerpo)
        return json.loads(cuerpo)


class AbrirYCerrarElAccesoTests(BasePortal):
    def test_el_asesor_lo_abre_y_devuelve_un_enlace(self):
        d = self._abre_portal()
        self.assertIn("/portal-venta?token=", d["enlace"])
        self.assertEqual(d["propietario"], "Lucía Vendedora")

    def test_el_token_no_se_guarda_en_claro(self):
        """Quien lea la base no puede entrar en el portal de nadie."""
        token = self._token(self._abre_portal()["enlace"])
        fila = self.conn.execute("SELECT * FROM inmueble_portal_accesos").fetchone()
        for valor in tuple(fila):
            self.assertNotEqual(str(valor), token)
        self.assertEqual(fila["token_hash"], S.hash_portal_token(token))

    def test_el_telefono_vuelve_enmascarado(self):
        self.assertNotIn("600111222", json.dumps(self._abre_portal()))

    def test_sin_propietario_enlazado_no_se_puede_abrir(self):
        self._ins("inmuebles", {"id": "inm2", "workspace_id": self.ws, "empresa_id": "emp1",
                                "direccion": "Sin dueño", "estado": "Encargo",
                                "created_at": AHORA, "updated_at": AHORA})
        estado, d = self._post("/api/inmueble_portal_acceso", {"inmueble_id": "inm2", "avisar": False})
        self.assertEqual(estado, 400, d)

    def test_un_comercial_no_puede_abrir_el_de_otra_agencia(self):
        """El rol Administrador cruza workspaces a propósito —está decidido así—,
        de modo que la comprobación de que lo ajeno sigue cerrado hay que hacerla
        con un rol que no lo cruce. Si no, el test pasa sin probar nada."""
        self._ins("usuarios", {"id": "u2", "nombre": "Comercial", "usuario": "comercial",
                               "email": "c@x.test", "rol": "Comercial", "servicio": "Inmobiliaria",
                               "activo": 1, "password_hash": S.hash_password(CLAVE),
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_miembros", {"id": "wm2", "workspace_id": self.ws, "usuario_id": "u2",
                                         "rol": "Miembro", "created_at": AHORA, "updated_at": AHORA})
        req = urllib.request.Request(
            self.base + "/api/login",
            data=json.dumps({"usuario": "comercial", "password": CLAVE}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            cookie = r.headers.get("Set-Cookie").split(";")[0]
        req = urllib.request.Request(
            self.base + "/api/inmueble_portal_acceso",
            data=json.dumps({"inmueble_id": "inmX", "avisar": False}).encode(),
            headers={"Content-Type": "application/json", "Cookie": cookie}, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                self.fail(f"ha dejado abrir el portal de otra agencia: {r.read()}")
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (403, 404), e.read())

    def test_abrirlo_otra_vez_anula_el_enlace_anterior(self):
        """Dos llaves vivas para la misma persona es una llave de más en WhatsApp."""
        viejo = self._token(self._abre_portal()["enlace"])
        nuevo = self._token(self._abre_portal()["enlace"])
        self.assertNotEqual(viejo, nuevo)
        self.assertEqual(self._get(f"/api/portal_venta?token={viejo}")[0], 403)
        self.assertEqual(self._get(f"/api/portal_venta?token={nuevo}")[0], 200)

    def test_revocar_lo_cierra(self):
        token = self._token(self._abre_portal()["enlace"])
        self.assertEqual(self._get(f"/api/portal_venta?token={token}")[0], 200)
        estado, d = self._post("/api/inmueble_portal_acceso_revoke", {"inmueble_id": "inm1"})
        self.assertEqual(estado, 200, d)
        self.assertEqual(d["revocados"], 1)
        self.assertEqual(self._get(f"/api/portal_venta?token={token}")[0], 403)

    def test_un_enlace_caducado_no_vale(self):
        token = self._token(self._abre_portal()["enlace"])
        self.conn.execute("UPDATE inmueble_portal_accesos SET expires_at = '2020-01-01'")
        self.conn.commit()
        self.assertEqual(self._get(f"/api/portal_venta?token={token}")[0], 403)

    def test_un_token_inventado_no_vale(self):
        self.assertEqual(self._get("/api/portal_venta?token=loquesea")[0], 404)

    def test_la_ficha_ve_quien_tiene_acceso_pero_no_el_token(self):
        self._abre_portal()
        estado, cuerpo = self._get("/api/inmueble_portal_accesos?inmueble_id=inm1", con_sesion=True)
        self.assertEqual(estado, 200, cuerpo)
        d = json.loads(cuerpo)
        self.assertEqual(d["rows"][0]["propietario"], "Lucía Vendedora")
        self.assertNotIn("token", cuerpo)

    def test_esa_lista_no_es_publica(self):
        self.assertIn(self._get("/api/inmueble_portal_accesos?inmueble_id=inm1")[0], (401, 403))


class LoQueVeElPropietarioTests(BasePortal):
    def setUp(self):
        super().setUp()
        self.d = self._vista(self._token(self._abre_portal()["enlace"]))

    def test_su_inmueble_y_su_precio(self):
        self.assertEqual(self.d["inmueble"]["direccion"], "Calle Portal 1")
        self.assertEqual(self.d["inmueble"]["precio"], 250000)

    def test_en_que_punto_va(self):
        self.assertEqual(self.d["etapa"]["titulo"], "En venta")
        self.assertEqual(self.d["etapa"]["paso"], 1)

    def test_cuanta_gente_ha_venido(self):
        r = self.d["resumen"]
        self.assertEqual(r["visitas_hechas"], 1)
        self.assertEqual(r["visitas_previstas"], 1)
        self.assertEqual(r["interesados"], 1)
        self.assertEqual(r["contactos_portal"], 1)

    def test_que_falta_por_su_parte(self):
        tareas = [t["tarea"] for t in self.d["pendiente_de_ti"]]
        self.assertEqual(tareas, ["Traer la nota simple"])

    def test_la_cronologia_trae_las_visitas(self):
        titulos = [x["titulo"] for x in self.d["cronologia"]]
        self.assertIn("Visita realizada", titulos)
        self.assertIn("Visita agendada", titulos)


class LoQueNoPuedeSalirTests(BasePortal):
    def setUp(self):
        super().setUp()
        estado, self.crudo = self._get(f"/api/portal_venta?token={self._token(self._abre_portal()['enlace'])}")
        self.assertEqual(estado, 200)
        self.d = json.loads(self.crudo)

    def test_ni_el_nombre_del_comprador(self):
        self.assertNotIn("Comprador Secreto", self.crudo)

    def test_ni_su_telefono(self):
        self.assertNotIn("699888777", self.crudo)

    def test_ni_los_honorarios_de_la_agencia(self):
        self.assertNotIn("7500", self.crudo)

    def test_ni_las_notas_internas(self):
        self.assertNotIn("aprieta el precio", self.crudo)

    def test_ni_las_tareas_que_no_son_suyas(self):
        self.assertNotIn("margen de honorarios", self.crudo)

    def test_ni_las_acciones_de_gestion_interna(self):
        self.assertNotIn("bajar precio", self.crudo)

    def test_ni_los_identificadores_internos(self):
        for id_interno in ("emp1", "inm1", "cap1", "comp1", "dem1", self.ws):
            with self.subTest(id_interno):
                self.assertNotIn(id_interno, self.crudo)

    def test_ni_los_documentos_que_nadie_ha_compartido(self):
        self.assertNotIn("Informe interno", self.crudo)

    def test_pero_uno_marcado_visible_si_sale(self):
        self.conn.execute("UPDATE inmueble_docs SET visible_portal = 1, nombre = 'Nota de encargo' WHERE id='d1'")
        self.conn.commit()
        d = self._vista(self._token(self._abre_portal()["enlace"]))
        self.assertEqual([x["nombre"] for x in d["documentos"]], ["Nota de encargo"])


class ElSegundoFactorTests(BasePortal):
    """Con canal de mensajes configurado, el enlace por sí solo no basta."""

    def setUp(self):
        super().setUp()
        os.environ["SIGNATURE_SMS_WEBHOOK_URL"] = "https://ejemplo.invalido/sms"
        self.token = self._token(self._abre_portal()["enlace"])

    def test_el_enlace_solo_pide_codigo(self):
        estado, cuerpo = self._get(f"/api/portal_venta?token={self.token}")
        self.assertEqual(estado, 200, cuerpo)
        d = json.loads(cuerpo)
        self.assertEqual(d["estado"], "codigo_requerido")
        self.assertNotIn("Calle Portal", cuerpo)

    def test_con_el_codigo_correcto_se_entra(self):
        # El envío real se ignora: lo que se prueba es la comprobación.
        acceso = self.conn.execute("SELECT * FROM inmueble_portal_accesos WHERE revocado=0").fetchone()
        S.manda_codigo_de_portal(self.conn, acceso)
        codigo = "123456"
        self.conn.execute("UPDATE inmueble_portal_accesos SET codigo_hash = ? WHERE id = ?",
                          (S.hash_portal_token(codigo), acceso["id"]))
        self.conn.commit()
        estado, d = self._post("/api/portal_venta_codigo", {"token": self.token, "codigo": codigo},
                               con_sesion=False)
        self.assertEqual(estado, 200, d)
        vista = json.loads(self._get(f"/api/portal_venta?token={self.token}&s={d['sesion']}")[1])
        self.assertEqual(vista["estado"], "ok")

    def test_un_codigo_equivocado_no_entra(self):
        acceso = self.conn.execute("SELECT * FROM inmueble_portal_accesos WHERE revocado=0").fetchone()
        S.manda_codigo_de_portal(self.conn, acceso)
        estado, d = self._post("/api/portal_venta_codigo", {"token": self.token, "codigo": "000000"},
                               con_sesion=False)
        self.assertEqual(estado, 400, d)

    def test_a_la_sexta_se_corta(self):
        """Seis cifras se prueban solas si nadie lleva la cuenta."""
        acceso = self.conn.execute("SELECT * FROM inmueble_portal_accesos WHERE revocado=0").fetchone()
        S.manda_codigo_de_portal(self.conn, acceso)
        codigos = [self._post("/api/portal_venta_codigo", {"token": self.token, "codigo": f"00000{i}"},
                              con_sesion=False)[0] for i in range(6)]
        self.assertEqual(codigos[-1], 429, codigos)

    def test_una_sesion_de_otro_enlace_no_sirve(self):
        self._ins("clientes", {"id": "prop2", "empresa_id": "emp1", "workspace_id": self.ws,
                               "nombre": "Otro", "telefono": "+34600999000",
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmuebles", {"id": "inm3", "workspace_id": self.ws, "empresa_id": "emp1",
                                "direccion": "Calle Otra 3", "estado": "Encargo",
                                "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmueble_propietarios", {"id": "ip3", "inmueble_id": "inm3", "cliente_id": "prop2",
                                            "empresa_id": "emp1", "created_at": AHORA, "updated_at": AHORA})
        otro = self._token(self._abre_portal("inm3")["enlace"])
        acceso = self.conn.execute(
            "SELECT * FROM inmueble_portal_accesos WHERE inmueble_id='inm3' AND revocado=0").fetchone()
        self.conn.execute("UPDATE inmueble_portal_accesos SET codigo_hash = ?, codigo_expira = '2099-01-01' WHERE id = ?",
                          (S.hash_portal_token("111111"), acceso["id"]))
        self.conn.commit()
        _, d = self._post("/api/portal_venta_codigo", {"token": otro, "codigo": "111111"}, con_sesion=False)
        vista = json.loads(self._get(f"/api/portal_venta?token={self.token}&s={d['sesion']}")[1])
        self.assertEqual(vista["estado"], "codigo_requerido")

    def test_sin_canal_no_hay_segundo_factor_y_se_dice(self):
        """Fingir una seguridad que no existe es peor que no tenerla: se informa."""
        os.environ.pop("SIGNATURE_SMS_WEBHOOK_URL", None)
        d = self._vista(self.token)
        self.assertEqual(d["estado"], "ok")
        self.assertFalse(d["segundo_factor"])


class LaPaginaTests(BasePortal):
    def test_se_sirve_sin_sesion(self):
        estado, html = self._get("/portal-venta?token=loquesea")
        self.assertEqual(estado, 200)
        self.assertIn("Mi venta", html)

    def test_no_se_indexa(self):
        req = urllib.request.Request(self.base + "/portal-venta")
        with urllib.request.urlopen(req) as r:
            self.assertIn("noindex", r.headers.get("X-Robots-Tag", ""))
            self.assertEqual(r.headers.get("Referrer-Policy"), "no-referrer")

    def test_no_carga_el_javascript_del_crm(self):
        """Que el mismo código que sabe de honorarios no llegue a su navegador."""
        _, html = self._get("/portal-venta")
        self.assertNotIn("app.js", html)
        self.assertNotIn("app-auth.js", html)


if __name__ == "__main__":
    unittest.main()
