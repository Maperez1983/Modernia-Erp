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
import re
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


class LosAvisosTests(BasePortal):
    """Un portal que hay que visitar no lo visita nadie: el producto es el aviso.

    El mensaje no lleva el enlace dentro, y es a propósito: del token sólo se guarda
    el hash, así que desde el aviso no se puede reconstruir. Guardarlo en claro para
    poder pegarlo en cada mensaje dejaría el hasheo en un adorno.
    """

    def setUp(self):
        super().setUp()
        os.environ["SIGNATURE_SMS_WEBHOOK_URL"] = "https://ejemplo.invalido/sms"
        self._abre_portal()

    def _avisos(self):
        return self.conn.execute(
            "SELECT motivo, referencia, enviado FROM inmueble_portal_avisos ORDER BY created_at").fetchall()

    def test_una_visita_nueva_avisa(self):
        estado, d = self._post("/api/visitas", {
            "empresa_nombre": "Agencia Propia", "inmueble_id": "inm1",
            "fecha": "2026-09-01", "hora": "18:00", "estado": "Prevista"})
        self.assertEqual(estado, 200, d)
        motivos = [r["motivo"] for r in self._avisos()]
        self.assertIn("visita", motivos)

    def test_la_misma_visita_no_avisa_dos_veces(self):
        for _ in range(2):
            self._post("/api/visitas", {"empresa_nombre": "Agencia Propia", "inmueble_id": "inm1",
                                        "fecha": "2026-09-01", "hora": "18:00", "estado": "Prevista"})
        self.assertEqual(len([r for r in self._avisos() if r["motivo"] == "visita"]), 1)

    def test_un_interesado_nuevo_avisa(self):
        estado, d = self._post("/api/inmueble_compradores", {
            "empresa_nombre": "Agencia Propia", "inmueble_id": "inm1",
            "demanda_id": "dem1", "cliente_id": "comp1", "estado": "Interesado"})
        self.assertEqual(estado, 200, d)
        self.assertIn("interesado", [r["motivo"] for r in self._avisos()])

    def test_el_aviso_no_lleva_el_token(self):
        self._post("/api/visitas", {"empresa_nombre": "Agencia Propia", "inmueble_id": "inm1",
                                    "fecha": "2026-09-02", "estado": "Prevista"})
        self.assertTrue(self._avisos())

    def test_un_acceso_revocado_ya_no_recibe(self):
        self._post("/api/inmueble_portal_acceso_revoke", {"inmueble_id": "inm1"})
        self._post("/api/visitas", {"empresa_nombre": "Agencia Propia", "inmueble_id": "inm1",
                                    "fecha": "2026-09-03", "estado": "Prevista"})
        self.assertEqual(self._avisos(), [])

    def test_sin_canal_no_se_intenta_nada(self):
        os.environ.pop("SIGNATURE_SMS_WEBHOOK_URL", None)
        self._post("/api/visitas", {"empresa_nombre": "Agencia Propia", "inmueble_id": "inm1",
                                    "fecha": "2026-09-04", "estado": "Prevista"})
        self.assertEqual(self._avisos(), [])

    def test_cerrar_la_venta_avisa_y_cierra_el_enlace(self):
        token = self._token(self._abre_portal()["enlace"])
        S.log_crm_stage_event(self.conn, "emp1", "inm1", "cap1", "Vendido",
                              now="2026-09-05 10:00:00")
        self.conn.commit()
        self.assertIn("etapa", [r["motivo"] for r in self._avisos()])
        self.assertEqual(self._get(f"/api/portal_venta?token={token}")[0], 403)


class SubirDocumentosTests(BasePortal):
    def setUp(self):
        super().setUp()
        self.token = self._token(self._abre_portal()["enlace"])

    def _sube(self, nombre, contenido=b"%PDF-1.4 hola", tarea="Traer la nota simple"):
        import base64
        return self._post("/api/portal_venta_doc", {
            "token": self.token, "nombre": nombre, "tarea": tarea,
            "file_base64": "data:application/pdf;base64," + base64.b64encode(contenido).decode(),
        }, con_sesion=False)

    def test_se_guarda_en_el_expediente(self):
        estado, d = self._sube("nota-simple.pdf")
        self.assertEqual(estado, 200, d)
        fila = self.conn.execute(
            "SELECT nombre, origen_tipo, visible_portal FROM inmueble_docs WHERE origen_tipo='propietario'").fetchone()
        self.assertEqual(fila["nombre"], "nota-simple.pdf")
        self.assertEqual(fila["visible_portal"], 1)

    def test_da_por_hecha_la_tarea(self):
        self._sube("nota-simple.pdf")
        fila = self.conn.execute("SELECT estado FROM inmueble_checklist WHERE id='c1'").fetchone()
        self.assertEqual(fila["estado"], "Hecho")

    def test_y_luego_lo_ve_en_su_portal(self):
        self._sube("nota-simple.pdf")
        d = self._vista(self.token)
        self.assertEqual([x["nombre"] for x in d["documentos"]], ["nota-simple.pdf"])
        self.assertTrue(d["documentos"][0]["mio"])

    def test_un_ejecutable_se_rechaza(self):
        """Sube ficheros alguien de fuera y no hay nadie revisando lo que entra."""
        self.assertEqual(self._sube("virus.exe")[0], 415)

    def test_un_html_tambien(self):
        self.assertEqual(self._sube("pagina.html")[0], 415)

    def test_uno_demasiado_grande_se_rechaza(self):
        """El límite del portal (8 MB) tiene que caber por debajo del tope de POST
        del servidor (10 MB). Si se pusiera por encima nunca llegaría a aplicarse:
        el cliente se comería un corte de conexión en vez de un error claro."""
        # base64 engorda un tercio: el fichero más grande que se admita, ya
        # codificado, tiene que seguir cabiendo en el POST.
        self.assertLess(S.INMO_PORTAL_DOC_MAX_BYTES * 4 / 3, 10 * 1024 * 1024)
        self.assertEqual(self._sube("enorme.pdf", b"x" * (S.INMO_PORTAL_DOC_MAX_BYTES + 1))[0], 413)

    def test_uno_vacio_se_rechaza(self):
        self.assertEqual(self._sube("vacio.pdf", b"")[0], 400)

    def test_el_nombre_del_fichero_lo_pone_el_servidor(self):
        """Que el nombre de origen no se use para escribir en disco."""
        estado, _ = self._sube("../../../etc/passwd.pdf")
        self.assertEqual(estado, 200)
        fila = self.conn.execute("SELECT url FROM inmueble_docs WHERE origen_tipo='propietario'").fetchone()
        self.assertNotIn("..", fila["url"])
        self.assertIn("/uploads/inmuebles/", fila["url"])

    def test_con_un_enlace_revocado_no_se_puede_subir(self):
        self._post("/api/inmueble_portal_acceso_revoke", {"inmueble_id": "inm1"})
        self.assertEqual(self._sube("nota.pdf")[0], 403)

    def test_sin_token_no_se_puede_subir(self):
        estado, _ = self._post("/api/portal_venta_doc", {"nombre": "x.pdf", "file_base64": "aGk="},
                               con_sesion=False)
        self.assertEqual(estado, 404)


class DecidirLaPropuestaTests(BasePortal):
    def setUp(self):
        super().setUp()
        self.conn.execute("UPDATE inmuebles SET estado = 'Propuesta' WHERE id='inm1'")
        self._ins("operaciones_inmobiliarias", {
            "id": "op1", "workspace_id": self.ws, "empresa_id": "emp1", "inmueble_id": "inm1",
            "direccion": "Calle Portal 1", "tipo_operacion": "compraventa",
            "precio_propuesta": 238000, "fecha_propuesta": "2026-08-09",
            "created_at": AHORA, "updated_at": AHORA})
        self.conn.commit()
        self.token = self._token(self._abre_portal()["enlace"])

    def _decide(self, decision):
        return self._post("/api/portal_venta_propuesta",
                          {"token": self.token, "decision": decision}, con_sesion=False)

    def test_ve_el_importe_de_la_oferta(self):
        d = self._vista(self.token)
        self.assertEqual(d["propuesta"]["importe"], 238000)

    def test_pero_no_quien_la_hace(self):
        _, crudo = self._get(f"/api/portal_venta?token={self.token}")
        self.assertNotIn("Comprador Secreto", crudo)

    def test_aceptar_queda_registrado(self):
        estado, d = self._decide("acepto")
        self.assertEqual(estado, 200, d)
        fila = self.conn.execute("SELECT * FROM inmueble_portal_decisiones").fetchone()
        self.assertEqual(fila["decision"], "acepto")
        self.assertEqual(float(fila["importe"]), 238000.0)

    def test_y_deja_tarea_al_asesor(self):
        self._decide("acepto")
        fila = self.conn.execute(
            "SELECT asunto, estado FROM acciones WHERE asunto LIKE '%ACEPTA%'").fetchone()
        self.assertIsNotNone(fila)
        self.assertEqual(fila["estado"], "Pendiente")

    def test_pero_no_mueve_la_ficha_de_etapa(self):
        """Cerrar una venta lo hace la agencia con el papeleo delante."""
        self._decide("acepto")
        estado = self.conn.execute("SELECT estado FROM inmuebles WHERE id='inm1'").fetchone()["estado"]
        self.assertEqual(estado, "Propuesta")

    def test_rechazar_tambien_queda(self):
        self.assertEqual(self._decide("rechazo")[0], 200)
        self.assertEqual(
            self.conn.execute("SELECT decision FROM inmueble_portal_decisiones").fetchone()["decision"], "rechazo")

    def test_una_decision_inventada_se_rechaza(self):
        self.assertEqual(self._decide("quiza")[0], 400)

    def test_la_decision_va_encadenada(self):
        self._decide("acepto")
        self._decide("rechazo")
        r = S.verifica_decisiones_del_propietario(self.conn, "inm1")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["checked"], 2)

    def test_y_tocarla_despues_se_nota(self):
        """Que el propietario diga que nunca aceptó ese precio es el escenario."""
        self._decide("acepto")
        self.conn.execute("UPDATE inmueble_portal_decisiones SET importe = '150000'")
        self.conn.commit()
        self.assertFalse(S.verifica_decisiones_del_propietario(self.conn, "inm1")["ok"])

    def test_borrar_una_de_en_medio_tambien(self):
        self._decide("acepto")
        self._decide("rechazo")
        primera = self.conn.execute(
            "SELECT id FROM inmueble_portal_decisiones ORDER BY created_at LIMIT 1").fetchone()["id"]
        self.conn.execute("DELETE FROM inmueble_portal_decisiones WHERE id = ?", (primera,))
        self.conn.commit()
        self.assertFalse(S.verifica_decisiones_del_propietario(self.conn, "inm1")["ok"])

    def test_queda_constancia_de_desde_donde(self):
        self._decide("acepto")
        fila = self.conn.execute("SELECT ip, agente, created_at FROM inmueble_portal_decisiones").fetchone()
        self.assertTrue(fila["ip"])
        self.assertTrue(fila["created_at"])


class ElEsquemaSobreviveAUnaLecturaTests(BasePortal):
    """En Postgres el DDL es transaccional.

    `ensure_inmueble_portal_schema` se llama también desde peticiones de sólo
    lectura, que no confirman nada. Las tablas se creaban, la consulta siguiente
    funcionaba porque iba en la misma transacción, y al devolver la conexión al pool
    el rollback se las llevaba. Comprobado contra producción: tras responder 200, las
    tres tablas seguían sin existir, así que el portal no habría llegado a funcionar.

    En SQLite no se ve —cada sentencia va suelta—, que es por lo que ni la suite ni
    los tests del portal lo cazaron. Este comprueba la forma: que se confirma.
    """

    def test_el_esquema_del_portal_se_confirma(self):
        fuente = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        i = fuente.index("def ensure_inmueble_portal_schema")
        self.assertIn("conn.commit()", fuente[i:i + 4000])

    def test_el_de_las_decisiones_tambien(self):
        fuente = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        i = fuente.index("def ensure_inmueble_portal_decisiones_schema")
        self.assertIn("conn.commit()", fuente[i:i + 2000])

    def test_una_lectura_deja_las_tablas_puestas(self):
        """Sobre SQLite no prueba el rollback, pero sí que la lectura las crea."""
        self.conn.execute("DROP TABLE IF EXISTS inmueble_portal_avisos")
        self.conn.commit()
        self._get("/api/inmueble_portal_accesos?inmueble_id=inm1", con_sesion=True)
        tablas = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'inmueble_portal%'")}
        self.assertIn("inmueble_portal_accesos", tablas)
        self.assertIn("inmueble_portal_avisos", tablas)


class ElCanalDeMensajesTests(unittest.TestCase):
    """El portal y la firma comparten webhook: tienen que compartir variables.

    Llegué a escribir `SIGNATURE_WEBHOOK_TOKEN` en el portal cuando la firma usaba
    `SIGNATURE_WEBHOOK_SECRET`. Dos nombres para lo mismo acaban siempre igual: uno
    se queda sin configurar y nadie entiende por qué sale la mitad de los mensajes.
    """

    @staticmethod
    def _fuente():
        return (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")

    def test_un_solo_nombre_para_el_secreto(self):
        fuente = self._fuente()
        self.assertNotIn("SIGNATURE_WEBHOOK_TOKEN", fuente)
        self.assertIn("SIGNATURE_WEBHOOK_SECRET", fuente)

    def test_el_portal_manda_por_donde_manda_la_firma(self):
        fuente = self._fuente()
        i = fuente.index("def envia_mensaje_al_propietario")
        bloque = fuente[i:i + 2000]
        self.assertIn("SIGNATURE_WHATSAPP_WEBHOOK_URL", bloque)
        self.assertIn("SIGNATURE_SMS_WEBHOOK_URL", bloque)

    def test_sin_webhook_lo_dice_en_vez_de_fallar(self):
        os.environ.pop("SIGNATURE_WHATSAPP_WEBHOOK_URL", None)
        os.environ.pop("SIGNATURE_SMS_WEBHOOK_URL", None)
        enviado, motivo = S.envia_mensaje_al_propietario("+34600111222", "hola")
        self.assertFalse(enviado)
        self.assertEqual(motivo, "webhook_no_configurado")

    def test_sin_telefono_tampoco_revienta(self):
        enviado, motivo = S.envia_mensaje_al_propietario("", "hola")
        self.assertFalse(enviado)
        self.assertEqual(motivo, "sin_telefono")

    def test_whatsapp_gana_al_sms_si_estan_los_dos(self):
        os.environ["SIGNATURE_WHATSAPP_WEBHOOK_URL"] = "https://x.invalido/w"
        os.environ["SIGNATURE_SMS_WEBHOOK_URL"] = "https://x.invalido/s"
        try:
            self.assertEqual(S.canal_para_avisar(), "whatsapp")
        finally:
            os.environ.pop("SIGNATURE_WHATSAPP_WEBHOOK_URL", None)
            os.environ.pop("SIGNATURE_SMS_WEBHOOK_URL", None)


class DondeEstaElContactoDelPropietarioTests(BasePortal):
    """El teléfono y el correo no viven en un solo sitio.

    Se escriben unas veces en la ficha del cliente y otras sueltos en la del
    inmueble o en la captación, según por dónde entrara el dato. Mirando sólo
    `clientes` llegué a afirmar que ninguno de los 13 propietarios de producción
    tenía correo: había 6, en `inmuebles.propietario_email`. La comprobación estaba
    mal, no el dato.
    """

    def test_lo_coge_de_la_ficha_del_cliente(self):
        c = S.contacto_del_propietario(self.conn, "inm1", {"telefono": "+34600111222", "email": "a@b.test"})
        self.assertEqual(c["telefono"], "+34600111222")
        self.assertEqual(c["email"], "a@b.test")

    def test_si_no_esta_ahi_lo_busca_en_la_ficha_del_inmueble(self):
        self.conn.execute("UPDATE inmuebles SET propietario_email = 'duena@ejemplo.test' WHERE id='inm1'")
        self.conn.commit()
        c = S.contacto_del_propietario(self.conn, "inm1", {"telefono": "", "email": ""})
        self.assertEqual(c["email"], "duena@ejemplo.test")

    def test_y_si_no_en_la_captacion(self):
        self.conn.execute("UPDATE captaciones SET propietario_telefono = '+34611222333' WHERE id='cap1'")
        self.conn.commit()
        c = S.contacto_del_propietario(self.conn, "inm1", {"telefono": "", "email": ""})
        self.assertEqual(c["telefono"], "+34611222333")

    def test_la_ficha_del_cliente_manda_sobre_las_demas(self):
        self.conn.execute("UPDATE inmuebles SET propietario_email = 'vieja@ejemplo.test' WHERE id='inm1'")
        self.conn.commit()
        c = S.contacto_del_propietario(self.conn, "inm1", {"telefono": "", "email": "nueva@ejemplo.test"})
        self.assertEqual(c["email"], "nueva@ejemplo.test")

    def test_sin_nada_lo_dice(self):
        c = S.contacto_del_propietario(self.conn, "inm1", {"telefono": "", "email": ""})
        self.assertFalse(c["hay"])

    def test_el_correo_encontrado_se_guarda_con_el_acceso(self):
        self.conn.execute("UPDATE inmuebles SET propietario_email = 'duena@ejemplo.test' WHERE id='inm1'")
        self.conn.commit()
        self._abre_portal()
        fila = self.conn.execute(
            "SELECT email FROM inmueble_portal_accesos WHERE revocado=0").fetchone()
        self.assertEqual(fila["email"], "duena@ejemplo.test")


class AvisarCuandoNoHayPorDondeMandarloTests(BasePortal):
    """Abrir un acceso que no se le puede hacer llegar es peor que no abrirlo: se
    da por hecho que el propietario ya lo tiene y nadie vuelve a mirarlo."""

    def _sin_contacto(self):
        self.conn.execute("UPDATE clientes SET telefono = '', email = '' WHERE id='prop1'")
        self.conn.execute("UPDATE inmuebles SET propietario_telefono = '', propietario_email = '' WHERE id='inm1'")
        self.conn.execute("UPDATE captaciones SET propietario_telefono = '', propietario_email = '' WHERE id='cap1'")
        self.conn.commit()

    def test_lo_avisa_en_la_respuesta(self):
        self._sin_contacto()
        estado, d = self._post("/api/inmueble_portal_acceso", {"inmueble_id": "inm1", "avisar": False})
        self.assertEqual(estado, 200, d)
        self.assertTrue(d["sin_contacto"])

    def test_pero_el_acceso_se_crea_igual(self):
        """El asesor puede tener el número en su móvil: no se le bloquea el trabajo."""
        self._sin_contacto()
        d = self._post("/api/inmueble_portal_acceso", {"inmueble_id": "inm1", "avisar": False})[1]
        self.assertIn("/portal-venta?token=", d["enlace"])

    def test_con_contacto_no_avisa_de_nada(self):
        estado, d = self._post("/api/inmueble_portal_acceso", {"inmueble_id": "inm1", "avisar": False})
        self.assertEqual(estado, 200, d)
        self.assertFalse(d["sin_contacto"])

    def test_la_pantalla_lo_dice_con_palabras(self):
        fuente = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("sin_contacto", fuente)
        self.assertIn("no tiene teléfono ni correo", fuente)


class ElEnlacePorCorreoTests(BasePortal):
    def tearDown(self):
        os.environ.pop("SMTP_HOST", None)
        super().tearDown()

    def test_sin_smtp_no_se_intenta(self):
        self.conn.execute("UPDATE clientes SET telefono='', email='duena@ejemplo.test' WHERE id='prop1'")
        self.conn.commit()
        d = self._post("/api/inmueble_portal_acceso", {"inmueble_id": "inm1"})[1]
        self.assertFalse(d["aviso"]["enviado"])

    def test_el_correo_vuelve_enmascarado(self):
        self.conn.execute("UPDATE clientes SET email='duenamuylarga@ejemplo.test' WHERE id='prop1'")
        self.conn.commit()
        d = self._post("/api/inmueble_portal_acceso", {"inmueble_id": "inm1", "avisar": False})[1]
        self.assertNotIn("duenamuylarga", json.dumps(d))
        self.assertIn("ejemplo.test", d["email"])

    def test_el_mensaje_avisa_de_que_el_enlace_es_personal(self):
        cuerpo = S.correo_con_el_enlace_del_portal(
            agencia="Agencia Propia", direccion="Calle Portal 1", enlace="https://x.test/portal-venta?token=abc")
        self.assertIn("No lo compartas", cuerpo)
        self.assertIn("Calle Portal 1", cuerpo)

    def test_y_escapa_lo_que_venga_de_la_base(self):
        """Una dirección con un `<script>` dentro no puede acabar ejecutándose."""
        cuerpo = S.correo_con_el_enlace_del_portal(
            agencia="A", direccion="<script>alert(1)</script>", enlace="https://x.test/p")
        self.assertNotIn("<script>", cuerpo)


class LaVistaPreviaDelAsesorTests(BasePortal):
    """«¿Cómo sé lo que ve el propietario?»

    La alternativa era abrir su enlace y mirarlo. Pero eso le cuenta una visita y
    falsea el «última vez que entró», que es justo el dato por el que se mira. Así
    que la vista previa va con la sesión del CRM, sobre la misma página y la misma
    consulta: si algún día dejaran de parecerse, la imitación mentiría justo cuando
    hace falta que no.
    """

    def _previa(self, inmueble_id="inm1", con_sesion=True):
        return self._get(f"/api/portal_venta?preview={inmueble_id}", con_sesion=con_sesion)

    def test_el_asesor_ve_lo_mismo_que_el_propietario(self):
        propietario = self._vista(self._token(self._abre_portal()["enlace"]))
        estado, cuerpo = self._previa()
        self.assertEqual(estado, 200, cuerpo)
        previa = json.loads(cuerpo)
        for clave in ("inmueble", "etapa", "resumen", "cronologia", "pendiente_de_ti", "documentos"):
            with self.subTest(clave):
                self.assertEqual(previa[clave], propietario[clave])

    def test_y_se_ve_que_es_una_vista_previa(self):
        self.assertTrue(json.loads(self._previa()[1])["vista_previa"])

    def test_no_le_cuenta_una_visita_al_propietario(self):
        self._abre_portal()
        for _ in range(3):
            self._previa()
        fila = self.conn.execute(
            "SELECT accesos, last_access_at FROM inmueble_portal_accesos WHERE revocado=0").fetchone()
        self.assertEqual(fila["accesos"], 0)
        self.assertIsNone(fila["last_access_at"])

    def test_funciona_aunque_no_haya_acceso_abierto(self):
        """Sirve para mirar antes de decidir si se lo mandas."""
        estado, cuerpo = self._previa()
        self.assertEqual(estado, 200, cuerpo)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) c FROM inmueble_portal_accesos").fetchone()["c"], 0)

    def test_sin_sesion_no_hay_vista_previa(self):
        """Si no, sería una puerta abierta a cualquier ficha con sólo saber su id."""
        estado, _ = self._previa(con_sesion=False)
        self.assertIn(estado, (401, 403))

    def test_ni_de_una_ficha_de_otra_agencia(self):
        self._ins("usuarios", {"id": "u3", "nombre": "Comercial", "usuario": "comercial2",
                               "email": "c2@x.test", "rol": "Comercial", "servicio": "Inmobiliaria",
                               "activo": 1, "password_hash": S.hash_password(CLAVE),
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_miembros", {"id": "wm3", "workspace_id": self.ws, "usuario_id": "u3",
                                         "rol": "Miembro", "created_at": AHORA, "updated_at": AHORA})
        req = urllib.request.Request(
            self.base + "/api/login",
            data=json.dumps({"usuario": "comercial2", "password": CLAVE}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            cookie = r.headers.get("Set-Cookie").split(";")[0]
        req = urllib.request.Request(self.base + "/api/portal_venta?preview=inmX", headers={"Cookie": cookie})
        try:
            with urllib.request.urlopen(req) as r:
                self.fail(f"ha dejado ver la ficha de otra agencia: {r.read()[:200]}")
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (403, 404))

    def test_tampoco_enseña_de_mas_por_ser_una_previa(self):
        """Lo que no sale para el propietario tampoco sale aquí: es la misma vista."""
        _, cuerpo = self._previa()
        for secreto in ("Comprador Secreto", "699888777", "7500", "aprieta el precio"):
            with self.subTest(secreto):
                self.assertNotIn(secreto, cuerpo)

    def test_el_boton_esta_en_la_ficha(self):
        fuente = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("inmuebleOwnerPreviewBtn", fuente)
        self.assertIn("/portal-venta?preview=", fuente)


class ElMensajeCuandoNoHaySesionTests(BasePortal):
    """«No autorizado» no le dice a nadie qué hacer.

    Pasó de verdad: el enlace de vista previa se abrió en un navegador sin sesión del
    CRM y el mensaje no daba ninguna pista. El caso es casi siempre el mismo —otro
    perfil, el navegador de dentro de una aplicación, o la sesión caducada— y la
    respuesta debe decir el remedio, no el síntoma.
    """

    def test_sin_sesion_explica_que_hacer(self):
        estado, cuerpo = self._get("/api/portal_venta?preview=inm1", con_sesion=False)
        self.assertEqual(estado, 401, cuerpo)
        self.assertIn("Entra primero en el CRM", cuerpo)

    def test_con_sesion_sigue_funcionando(self):
        estado, cuerpo = self._get("/api/portal_venta?preview=inm1", con_sesion=True)
        self.assertEqual(estado, 200, cuerpo)

    def test_una_ficha_ajena_sigue_denegando_sin_dar_pistas(self):
        """Que no se confunda «no has entrado» con «esto no es tuyo»."""
        self._ins("usuarios", {"id": "u9", "nombre": "Comercial", "usuario": "comercial9",
                               "email": "c9@x.test", "rol": "Comercial", "servicio": "Inmobiliaria",
                               "activo": 1, "password_hash": S.hash_password(CLAVE),
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_miembros", {"id": "wm9", "workspace_id": self.ws, "usuario_id": "u9",
                                         "rol": "Miembro", "created_at": AHORA, "updated_at": AHORA})
        req = urllib.request.Request(
            self.base + "/api/login",
            data=json.dumps({"usuario": "comercial9", "password": CLAVE}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            cookie = r.headers.get("Set-Cookie").split(";")[0]
        req = urllib.request.Request(self.base + "/api/portal_venta?preview=inmX", headers={"Cookie": cookie})
        try:
            with urllib.request.urlopen(req) as r:
                self.fail("ha dejado ver una ficha ajena")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 403)
            self.assertNotIn("Entra primero", e.read().decode())


class ElHiloConElComercialTests(BasePortal):
    """Un portal donde sólo se lee deja al vendedor con la duda en la mano y le
    empuja al teléfono, que es lo que se quería evitar. Y hacerlo aquí en vez de por
    WhatsApp tiene una ventaja para la agencia: lo hablado queda en el expediente del
    inmueble, no en el móvil de quien lo llevaba."""

    def setUp(self):
        super().setUp()
        self.token = self._token(self._abre_portal()["enlace"])

    def _escribe(self, texto):
        return self._post("/api/portal_venta_mensaje",
                          {"token": self.token, "texto": texto}, con_sesion=False)

    def test_el_propietario_escribe(self):
        estado, d = self._escribe("¿Hay novedades de la visita del jueves?")
        self.assertEqual(estado, 200, d)
        fila = self.conn.execute("SELECT autor, texto FROM inmueble_portal_mensajes").fetchone()
        self.assertEqual(fila["autor"], "propietario")

    def test_y_le_deja_tarea_al_comercial(self):
        """Un mensaje que nadie ve es peor que no tener mensajería: el propietario
        da por hecho que llegó."""
        self._escribe("Quiero bajar el precio")
        fila = self.conn.execute(
            "SELECT asunto, estado FROM acciones WHERE asunto LIKE '%escrito%'").fetchone()
        self.assertIsNotNone(fila)
        self.assertEqual(fila["estado"], "Pendiente")

    def test_el_comercial_contesta_y_el_propietario_lo_ve(self):
        self._escribe("¿Cómo va?")
        estado, d = self._post("/api/inmueble_portal_mensaje",
                               {"inmueble_id": "inm1", "texto": "Vamos bien, el jueves hay visita."})
        self.assertEqual(estado, 200, d)
        vista = self._vista(self.token)
        self.assertEqual([m["autor"] for m in vista["mensajes"]], ["propietario", "agencia"])
        self.assertIn("el jueves hay visita", vista["mensajes"][1]["texto"])

    def test_un_mensaje_vacio_se_rechaza(self):
        self.assertEqual(self._escribe("   ")[0], 400)

    def test_sin_enlace_valido_no_se_puede_escribir(self):
        self._post("/api/inmueble_portal_acceso_revoke", {"inmueble_id": "inm1"})
        self.assertEqual(self._escribe("hola")[0], 403)

    def test_el_hilo_del_crm_pide_permiso(self):
        self.assertIn(self._get("/api/inmueble_portal_mensajes?inmueble_id=inm1")[0], (401, 403))

    def test_un_comercial_no_puede_escribir_en_una_ficha_ajena(self):
        """Con Administrador no prueba nada: cruza workspaces a propósito."""
        self._ins("usuarios", {"id": "u7", "nombre": "Comercial", "usuario": "comercial7",
                               "email": "c7@x.test", "rol": "Comercial", "servicio": "Inmobiliaria",
                               "activo": 1, "password_hash": S.hash_password(CLAVE),
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_miembros", {"id": "wm7", "workspace_id": self.ws, "usuario_id": "u7",
                                         "rol": "Miembro", "created_at": AHORA, "updated_at": AHORA})
        req = urllib.request.Request(
            self.base + "/api/login",
            data=json.dumps({"usuario": "comercial7", "password": CLAVE}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            cookie = r.headers.get("Set-Cookie").split(";")[0]
        req = urllib.request.Request(
            self.base + "/api/inmueble_portal_mensaje",
            data=json.dumps({"inmueble_id": "inmX", "texto": "hola"}).encode(),
            headers={"Content-Type": "application/json", "Cookie": cookie}, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                self.fail("ha dejado escribir en la ficha de otra agencia")
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (403, 404))


class LaAgendaDeCitasTests(BasePortal):
    """Lo que tiene por delante es otra cosa que lo que ya pasó."""

    def setUp(self):
        super().setUp()
        hoy = S.datetime.now(S.timezone.utc).date()
        self.manana = (hoy + S.timedelta(days=1)).isoformat()
        self.ayer = (hoy - S.timedelta(days=1)).isoformat()
        self._ins("visitas", {"id": "vFut", "workspace_id": self.ws, "empresa_id": "emp1",
                              "inmueble_id": "inm1", "fecha": self.manana, "hora": "18:00",
                              "estado": "Prevista", "created_at": AHORA, "updated_at": AHORA})
        self._ins("visitas", {"id": "vPas", "workspace_id": self.ws, "empresa_id": "emp1",
                              "inmueble_id": "inm1", "fecha": self.ayer, "hora": "10:00",
                              "estado": "Realizada", "created_at": AHORA, "updated_at": AHORA})
        self.conn.commit()
        self.d = self._vista(self._token(self._abre_portal()["enlace"]))

    def test_lo_que_viene_sale_en_la_agenda(self):
        self.assertIn(self.manana, [c["fecha"] for c in self.d["agenda"]])

    def test_lo_que_ya_pasó_no(self):
        self.assertNotIn(self.ayer, [c["fecha"] for c in self.d["agenda"]])

    def test_la_agenda_va_de_la_más_próxima_en_adelante(self):
        fechas = [c["fecha"] for c in self.d["agenda"]]
        self.assertEqual(fechas, sorted(fechas))

    def test_y_la_cronología_sigue_teniendo_lo_pasado(self):
        self.assertIn(self.ayer, [x["fecha"] for x in self.d["cronologia"]])


class LasFotosYLaMarcaTests(BasePortal):
    def setUp(self):
        super().setUp()
        carpeta = S.UPLOADS / "inmuebles" / "inm1" / "fotos"
        carpeta.mkdir(parents=True, exist_ok=True)
        self.foto = carpeta / "portada.jpg"
        self.foto.write_bytes(b"\xff\xd8\xff\xe0 falsa pero suficiente")
        self._ins("inmueble_docs", {"id": "foto1", "inmueble_id": "inm1", "empresa_id": "emp1",
                                    "nombre": "Salón", "url": "/uploads/inmuebles/inm1/fotos/portada.jpg",
                                    "created_at": AHORA, "updated_at": AHORA})
        self.token = self._token(self._abre_portal()["enlace"])

    def tearDown(self):
        try:
            self.foto.unlink()
        except Exception:
            pass
        super().tearDown()

    def test_la_ficha_dice_cuántas_fotos_hay(self):
        self.assertEqual(self._vista(self.token)["inmueble"]["fotos"], 1)

    def test_la_foto_se_sirve_con_el_token(self):
        """`/uploads` pide sesión y en el portal no hay ninguna."""
        req = urllib.request.Request(self.base + f"/api/portal_venta_foto?token={self.token}&n=0")
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.status, 200)
            self.assertTrue(r.read())
            self.assertTrue(r.headers.get("Content-Type", "").startswith("image/"))

    def test_sin_token_no_se_sirve(self):
        self.assertEqual(self._get("/api/portal_venta_foto?token=inventado&n=0")[0], 404)

    def test_con_un_enlace_revocado_tampoco(self):
        self._post("/api/inmueble_portal_acceso_revoke", {"inmueble_id": "inm1"})
        self.assertEqual(self._get(f"/api/portal_venta_foto?token={self.token}&n=0")[0], 404)

    def test_no_se_puede_pedir_una_foto_que_no_es_de_su_inmueble(self):
        """El índice se acota contra la lista: no hay forma de pedir otra ruta."""
        self.assertEqual(self._get(f"/api/portal_venta_foto?token={self.token}&n=99")[0], 404)

    def test_un_logo_de_s3_no_se_intenta_pintar(self):
        """Lleva enlace firmado y desde el portal no hay quien lo firme: mejor sin
        logo que con un roto."""
        self.conn.execute("UPDATE empresas SET logo_url='s3://logos/x.jpg' WHERE id='emp1'")
        self.conn.commit()
        self.assertEqual(self._vista(self.token)["agencia"]["logo"], "")

    def test_un_logo_publico_si(self):
        self.conn.execute("UPDATE empresas SET logo_url='/assets/logo.png' WHERE id='emp1'")
        self.conn.commit()
        self.assertEqual(self._vista(self.token)["agencia"]["logo"], "/assets/logo.png")


class LaDocumentacionSeSubeSinTareaTests(BasePortal):
    """Tiene que poder aportar documentación cuando quiera, no sólo contra una
    tarea que alguien le haya puesto."""

    def test_se_admite_una_subida_suelta(self):
        import base64
        token = self._token(self._abre_portal()["enlace"])
        estado, d = self._post("/api/portal_venta_doc", {
            "token": token, "nombre": "escritura.pdf",
            "file_base64": "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4").decode(),
        }, con_sesion=False)
        self.assertEqual(estado, 200, d)
        self.assertEqual(
            self.conn.execute("SELECT nombre FROM inmueble_docs WHERE origen_tipo='propietario'").fetchone()["nombre"],
            "escritura.pdf")

    def test_la_pagina_ofrece_añadir_documento(self):
        _, html = self._get("/portal-venta")
        self.assertIn("Añadir documento", html)
        self.assertIn("Documentación del inmueble", html)


class ElBotonDeRechazarSeVeTests(BasePortal):
    """Salió blanco sobre blanco: invisible.

    `.oferta button` ganaba el fondo y `.oferta .fantasma` ganaba el color, así que
    el botón de rechazar quedaba en blanco sobre blanco. Al propietario le aparecía
    un rectángulo vacío al lado de «Acepto», que en una pantalla donde se decide
    sobre una oferta de 238.000 € no es un detalle estético.
    """

    def test_el_fantasma_declara_su_propio_fondo(self):
        _, html = self._get("/portal-venta")
        i = html.index(".oferta .fantasma")
        regla = html[i:html.index("}", i)]
        self.assertIn("background: transparent", regla)
        self.assertIn("border", regla)

    def test_la_tarjeta_de_la_oferta_no_usa_el_verde_de_acento_de_fondo(self):
        """En oscuro ese verde es claro: con texto blanco encima daba 1,8:1, en la
        pantalla donde el propietario decide sobre el precio de su casa."""
        _, html = self._get("/portal-venta")
        i = html.index(".oferta {")
        self.assertIn("var(--oferta-fondo)", html[i:html.index("}", i)])
        j = html.index('--oferta-fondo: #06301f')
        self.assertGreater(j, html.index("prefers-color-scheme: dark"))

    def test_nada_escribe_blanco_fijo_sobre_el_verde_de_acento(self):
        """El verde de acento cambia con el modo; el texto encima también tiene que
        cambiar. Con `#fff` fijo, en oscuro quedaba a 1,7:1."""
        _, html = self._get("/portal-venta")
        css = html[html.index("<style>"):html.index("</style>")]
        for regla in (".globo.suyo {", "button { padding"):
            i = css.index(regla)
            bloque = css[i:css.index("}", i)]
            with self.subTest(regla):
                self.assertIn("var(--sobre-verde)", bloque)
                self.assertNotIn("color: #fff", bloque)


class ElAnchoYLaAgendaTests(BasePortal):
    """En pantalla grande el portal era una tira de 640 px con 1.800 de scroll y
    media pantalla vacía a los lados. Y la agenda no se veía nunca: se escondía
    entera cuando no había citas, que con los datos de hoy es siempre. Una sección
    que desaparece no es una sección discreta, es una sección que nadie sabe que
    existe."""

    def test_hay_dos_columnas_en_pantalla_grande(self):
        """Sin fijar el punto de corte exacto: lo que importa es que exista uno y
        que a partir de ahí el contenido se reparta en columnas."""
        _, html = self._get("/portal-venta")
        m = re.search(r"@media \(min-width: (\d+)px\)\s*\{(.{0,600})", html, re.S)
        self.assertIsNotNone(m, "no hay ningún punto de corte para pantalla grande")
        self.assertGreaterEqual(int(m.group(1)), 700)
        self.assertIn("grid-template-columns", m.group(2))

    def test_la_pagina_puede_ensancharse(self):
        _, html = self._get("/portal-venta")
        i = html.index("main { max-width:")
        self.assertNotIn("640px", html[i:i + 60])

    def test_la_agenda_sale_aunque_no_haya_citas(self):
        _, html = self._get("/portal-venta")
        self.assertIn("Próximas citas", html)
        self.assertIn("No hay ninguna cita prevista", html)

    def test_y_con_citas_sale_la_lista(self):
        manana = (S.datetime.now(S.timezone.utc).date() + S.timedelta(days=3)).isoformat()
        self._ins("visitas", {"id": "vX", "workspace_id": self.ws, "empresa_id": "emp1",
                              "inmueble_id": "inm1", "fecha": manana, "hora": "17:00",
                              "estado": "Prevista", "created_at": AHORA, "updated_at": AHORA})
        self.conn.commit()
        d = self._vista(self._token(self._abre_portal()["enlace"]))
        self.assertIn(manana, [c["fecha"] for c in d["agenda"]])

    def test_la_barra_de_movil_se_esconde_en_escritorio(self):
        """La regla estaba ANTES de definir `.barra`: con la misma especificidad
        gana la última, así que no se aplicaba nunca y la barra fija salía también
        en el monitor, tapando contenido."""
        _, html = self._get("/portal-venta")
        css = html[html.index("<style>"):html.index("</style>")]
        i = css.index(".barra { position: fixed")
        self.assertIn(".barra { display: none; }", css[i:], "la regla que la esconde tiene que ir después")
