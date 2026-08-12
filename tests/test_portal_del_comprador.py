"""El comprador ve lo que le han buscado, y dice qué le parece.

El portal del propietario contesta «cómo va mi venta». Éste contesta otra cosa:
«qué me habéis buscado». Son dos personas con dos preguntas distintas, así que no
es la misma pantalla con otro filtro.

La mitad de este fichero, otra vez, es lo que **no** puede salir por esa puerta.
Un enlace acaba reenviado por WhatsApp, así que detrás no puede haber nada que
duela que lea un desconocido:

- **Quién es el propietario.** El comprador negocia con la agencia. Que le enseñen
  una casa no le da derecho al teléfono de quien la vende.
- **Los honorarios y el precio de encargo.** Ni el margen, ni lo que la agencia
  cobra por la operación.
- **Los demás interesados.** Ni cuántos son: eso es una palanca de venta dicha de
  palabra, y por escrito es una promesa que luego hay que sostener.
- **Los identificadores internos.** Los inmuebles viajan por su posición en la
  selección, no por su id, así que con el enlace no se puede pedir la foto de algo
  que no te han enseñado. Eso es lo que comprueba `NoSePuedeSalirDeLaSeleccion`.
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

AHORA = "2026-08-12 09:00:00"
CLAVE = "Comprador1234!"


class BaseComprador(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "comprador.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        S.ensure_demanda_portal_schema(self.conn)
        S.ensure_portal_consentimientos_schema(self.conn)
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        self._seed()
        self._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        req = urllib.request.Request(
            self.base + "/api/login",
            data=json.dumps({"usuario": "asesora", "password": CLAVE}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            self.cookie = r.headers.get("Set-Cookie").split(";")[0]

    def tearDown(self):
        self.httpd.shutdown()
        self.conn.close()
        if self._prev is not None:
            S.Handler.db_path = self._prev
        self.tmp.cleanup()

    def _ins(self, tabla, datos):
        validas = {r[1] for r in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in validas}
        self.conn.execute(
            f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        self.conn.commit()

    def _seed(self):
        self._ins("empresas", {"id": "emp1", "nombre": "Agencia Propia", "nif": "B00000000",
                               "direccion": "Calle Mayor 1", "email_rgpd": "rgpd@agencia.test",
                               "activo": 1, "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_empresas", {"id": "we1", "workspace_id": self.ws, "empresa_id": "emp1",
                                         "created_at": AHORA, "updated_at": AHORA})
        self._ins("usuarios", {"id": "u1", "nombre": "Ana Asesora", "usuario": "asesora",
                               "email": "a@x.test", "rol": "Administrador", "servicio": "Inmobiliaria",
                               "activo": 1, "password_hash": S.hash_password(CLAVE),
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_miembros", {"id": "wm1", "workspace_id": self.ws, "usuario_id": "u1",
                                         "rol": "Owner", "created_at": AHORA, "updated_at": AHORA})
        self._ins("clientes", {"id": "cli1", "nombre": "Carlos Comprador", "telefono": "600111222",
                               "email": "carlos@x.test", "empresa_id": "emp1", "workspace_id": self.ws,
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("clientes", {"id": "cli2", "nombre": "Pilar Propietaria", "telefono": "600999888",
                               "empresa_id": "emp1", "workspace_id": self.ws,
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("demandas", {"id": "dem1", "empresa_id": "emp1", "workspace_id": self.ws,
                               "cliente_id": "cli1", "tipo": "Piso", "zona": "Centro",
                               "precio_max": 250000, "habitaciones_min": 3, "estado": "Activa",
                               "responsable": "Ana Asesora", "created_at": AHORA, "updated_at": AHORA})
        for i, (id_, calle, precio) in enumerate((
                ("inm1", "Calle Uno 1", 240000), ("inm2", "Calle Dos 2", 210000))):
            self._ins("inmuebles", {"id": id_, "workspace_id": self.ws, "empresa_id": "emp1",
                                    "direccion": calle, "poblacion": "Málaga", "estado": "Encargo",
                                    "tipo_inmueble": "Piso", "m2": 90 + i, "habitaciones": 3,
                                    "banos": 2, "precio_objetivo": precio,
                                    "descripcion": f"Bonito piso en {calle}",
                                    "propietario_telefono": "600999888",
                                    "created_at": AHORA, "updated_at": AHORA})
            self._ins("inmueble_compradores", {"id": f"ic{i}", "empresa_id": "emp1",
                                               "inmueble_id": id_, "demanda_id": "dem1",
                                               "cliente_id": "cli1", "estado": "Interesado",
                                               "notas": "NOTA INTERNA: regatea mucho",
                                               "created_at": f"2026-08-0{i + 1} 09:00:00",
                                               "updated_at": AHORA})
        # Un inmueble que NO está en su selección: nunca puede verlo.
        self._ins("inmuebles", {"id": "ajeno", "workspace_id": self.ws, "empresa_id": "emp1",
                                "direccion": "Calle Ajena 99", "estado": "Encargo",
                                "tipo_inmueble": "Piso", "precio_objetivo": 300000,
                                "created_at": AHORA, "updated_at": AHORA})

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

    def _abre(self, demanda_id="dem1", firmar=True):
        estado, d = self._post("/api/demanda_portal_acceso", {"demanda_id": demanda_id, "avisar": False})
        self.assertEqual(estado, 200, d)
        token = d["enlace"].split("token=", 1)[1]
        if firmar:
            self._post("/api/portal_busqueda_consentimiento",
                       {"token": token, "nombre": "Carlos Comprador", "acepta_informacion": True},
                       con_sesion=False)
        return token

    def _posicion(self, token, direccion):
        """La posición del inmueble en SU selección. No coincide con el orden en
        que se dieron de alta y darlo por hecho me costó dos tests en rojo."""
        for x in self._vista(token)["inmuebles"]:
            if x["direccion"] == direccion:
                return x["i"]
        self.fail(f"{direccion} no está en la selección")

    def _vista(self, token):
        estado, cuerpo = self._get(f"/api/portal_busqueda?token={token}")
        self.assertEqual(estado, 200, cuerpo)
        return json.loads(cuerpo)


class AbrirYCerrarElAccesoTests(BaseComprador):
    def test_el_asesor_genera_el_enlace(self):
        estado, d = self._post("/api/demanda_portal_acceso", {"demanda_id": "dem1", "avisar": False})
        self.assertEqual(estado, 200, d)
        self.assertIn("/portal-busqueda?token=", d["enlace"])
        self.assertTrue(d["caduca"])

    def test_el_token_no_se_guarda_en_claro(self):
        """Si la base se filtra, los enlaces no se pueden reconstruir."""
        token = self._abre(firmar=False)
        fila = self.conn.execute("SELECT * FROM demanda_portal_accesos LIMIT 1").fetchone()
        self.assertNotIn(token, json.dumps(dict(fila)))
        self.assertEqual(fila["token_hash"], S.hash_portal_token(token))

    def test_generar_uno_nuevo_anula_el_anterior(self):
        """Dos enlaces vivos para la misma persona es una llave de más rodando."""
        viejo = self._abre()
        self._abre(firmar=False)
        self.assertEqual(self._get(f"/api/portal_busqueda?token={viejo}")[0], 403)

    def test_se_puede_anular_a_mano(self):
        token = self._abre()
        self.assertEqual(self._vista(token)["estado"], "ok")
        estado, d = self._post("/api/demanda_portal_acceso_revoke", {"demanda_id": "dem1"})
        self.assertEqual(estado, 200, d)
        self.assertEqual(self._get(f"/api/portal_busqueda?token={token}")[0], 403)

    def test_un_token_inventado_no_abre_nada(self):
        self.assertEqual(self._get("/api/portal_busqueda?token=" + "a" * 43)[0], 404)

    def test_la_ficha_lista_los_accesos_sin_el_token(self):
        token = self._abre()
        self._vista(token)
        estado, cuerpo = self._get("/api/demanda_portal_accesos?demanda_id=dem1", con_sesion=True)
        self.assertEqual(estado, 200, cuerpo)
        d = json.loads(cuerpo)
        self.assertEqual(len(d["accesos"]), 1)
        self.assertNotIn(token, cuerpo)
        self.assertGreaterEqual(d["accesos"][0]["entradas"], 1)
        # El teléfono, enmascarado: la lista se enseña en pantalla compartida.
        self.assertNotIn("600111222", cuerpo)


class NadieEntraSinFirmarTests(BaseComprador):
    def test_sin_consentimiento_no_se_devuelve_ni_un_dato(self):
        token = self._abre(firmar=False)
        d = self._vista(token)
        self.assertEqual(d["estado"], "consentimiento_requerido")
        self.assertNotIn("inmuebles", d)

    def test_el_texto_es_el_del_comprador_no_el_del_propietario(self):
        token = self._abre(firmar=False)
        texto = self._vista(token)["texto"]
        self.assertEqual(texto["ambito"], "comprador")

    def test_el_texto_identifica_al_responsable(self):
        """La ley pide identidad y un canal concreto, no «escribiendo a la agencia»."""
        token = self._abre(firmar=False)
        parrafos = " ".join(self._vista(token)["texto"]["parrafos"])
        self.assertIn("B00000000", parrafos)
        self.assertIn("rgpd@agencia.test", parrafos)

    def test_firmar_deja_el_documento_en_la_base(self):
        token = self._abre()
        fila = self.conn.execute(
            "SELECT ambito, nombre, documento_pdf, integrity_hash, texto_sha256 "
            "FROM portal_consentimientos ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertEqual(fila["ambito"], "comprador")
        self.assertEqual(fila["nombre"], "Carlos Comprador")
        self.assertTrue(fila["documento_pdf"], "el PDF firmado tiene que quedarse en la base")
        self.assertTrue(fila["integrity_hash"])
        with urllib.request.urlopen(
                self.base + f"/api/portal_busqueda_consentimiento_pdf?token={token}") as r:
            self.assertEqual(r.status, 200)
            self.assertTrue(r.read().startswith(b"%PDF"))

    def test_sin_marcar_la_casilla_no_hay_consentimiento(self):
        """Guardar medio consentimiento es guardar algo que no vale para nada."""
        token = self._abre(firmar=False)
        estado, d = self._post("/api/portal_busqueda_consentimiento",
                               {"token": token, "nombre": "Carlos", "acepta_informacion": False},
                               con_sesion=False)
        self.assertEqual(estado, 400, d)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) c FROM portal_consentimientos").fetchone()["c"], 0)

    def test_puede_retirarlo_el_mismo(self):
        """Retirarlo tiene que ser tan fácil como darlo."""
        token = self._abre()
        estado, d = self._post("/api/portal_busqueda_retirar", {"token": token}, con_sesion=False)
        self.assertEqual(estado, 200, d)
        self.assertEqual(self._get(f"/api/portal_busqueda?token={token}")[0], 403)
        # Y lo firmado se conserva: es la prueba de que en su día se dio.
        fila = self.conn.execute(
            "SELECT documento_pdf, revocado_at FROM portal_consentimientos LIMIT 1").fetchone()
        self.assertTrue(fila["documento_pdf"])
        self.assertTrue(fila["revocado_at"])


class LoQueVeTests(BaseComprador):
    def test_ve_los_inmuebles_que_le_han_seleccionado(self):
        d = self._vista(self._abre())
        self.assertEqual(d["estado"], "ok")
        direcciones = [x["direccion"] for x in d["inmuebles"]]
        self.assertCountEqual(direcciones, ["Calle Uno 1", "Calle Dos 2"])

    def test_no_ve_los_que_no_le_han_seleccionado(self):
        direcciones = [x["direccion"] for x in self._vista(self._abre())["inmuebles"]]
        self.assertNotIn("Calle Ajena 99", direcciones)

    def test_ve_el_precio_y_los_rasgos(self):
        x = self._vista(self._abre())["inmuebles"][0]
        self.assertTrue(x["precio"])
        self.assertEqual(x["tipo"], "Piso")
        self.assertEqual(x["habitaciones"], 3)

    def test_ve_su_propio_criterio_de_busqueda(self):
        b = self._vista(self._abre())["busqueda"]
        self.assertEqual(b["zona"], "Centro")
        self.assertEqual(b["precio_max"], 250000)

    def test_el_resumen_cuenta_lo_que_lleva_valorado(self):
        token = self._abre()
        self.assertEqual(self._vista(token)["resumen"]["valorados"], 0)
        self._post("/api/portal_busqueda_opinion", {"token": token, "i": 0, "valoracion": "encaja"},
                   con_sesion=False)
        d = self._vista(token)
        self.assertEqual(d["resumen"]["valorados"], 1)
        self.assertEqual(d["resumen"]["pendientes"], 1)

    def test_el_inmueble_vendido_se_marca_como_no_disponible(self):
        self.conn.execute("UPDATE inmuebles SET estado = 'Vendido' WHERE id = 'inm1'")
        self.conn.commit()
        porDireccion = {x["direccion"]: x for x in self._vista(self._abre())["inmuebles"]}
        self.assertFalse(porDireccion["Calle Uno 1"]["disponible"])
        self.assertTrue(porDireccion["Calle Dos 2"]["disponible"])

    def test_el_estado_del_embudo_no_se_cuela_por_el_de_la_ficha(self):
        """`inmueble_compradores` también tiene `estado` y era el del interesado.
        Si gana esa columna, «Interesado» no está en la lista de cerrados y todo
        sale disponible aunque la casa esté vendida."""
        self.conn.execute("UPDATE inmuebles SET estado = 'Vendido'")
        self.conn.execute("UPDATE inmueble_compradores SET estado = 'Interesado'")
        self.conn.commit()
        for x in self._vista(self._abre())["inmuebles"]:
            with self.subTest(x["direccion"]):
                self.assertFalse(x["disponible"])


class LoQueNoPuedeSalirTests(BaseComprador):
    def _crudo(self):
        token = self._abre()
        return self._get(f"/api/portal_busqueda?token={token}")[1]

    def test_no_sale_el_propietario(self):
        crudo = self._crudo()
        self.assertNotIn("Pilar Propietaria", crudo)
        self.assertNotIn("600999888", crudo)

    def test_no_salen_las_notas_internas(self):
        self.assertNotIn("NOTA INTERNA", self._crudo())

    def test_no_salen_los_identificadores_internos(self):
        crudo = self._crudo()
        for id_ in ("emp1", "inm1", "inm2", "dem1", self.ws):
            with self.subTest(id_):
                self.assertNotIn(id_, crudo)

    def test_no_sale_cuanta_gente_mas_esta_mirando(self):
        """Cuántos interesados hay es una palanca de venta, no un dato suyo."""
        crudo = json.loads(self._crudo())
        self.assertNotIn("interesados", json.dumps(crudo))


class NoSePuedeSalirDeLaSeleccionTests(BaseComprador):
    """El portal manda posiciones, no ids. Aquí se prueba que la posición no da
    para más que lo que le han enseñado."""

    def setUp(self):
        super().setUp()
        self.token = self._abre()
        self.sesion = ""

    def test_una_posicion_fuera_de_rango_no_devuelve_foto(self):
        for i in ("9", "-1", "999999", "abc"):
            with self.subTest(i=i):
                estado, _ = self._get(f"/api/portal_busqueda_foto?token={self.token}&i={i}&n=0")
                self.assertEqual(estado, 404)

    def test_no_se_puede_opinar_sobre_algo_que_no_te_han_ensenado(self):
        estado, d = self._post("/api/portal_busqueda_opinion",
                               {"token": self.token, "i": 7, "valoracion": "encaja"}, con_sesion=False)
        self.assertEqual(estado, 404, d)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) c FROM demanda_portal_opiniones").fetchone()["c"], 0)

    def test_la_valoracion_es_de_una_lista_cerrada(self):
        estado, d = self._post("/api/portal_busqueda_opinion",
                               {"token": self.token, "i": 0, "valoracion": "lo_que_sea"},
                               con_sesion=False)
        self.assertEqual(estado, 400, d)

    def test_la_posicion_apunta_al_mismo_inmueble_en_las_dos_listas(self):
        """El índice se resuelve dos veces —al pintar y al opinar— y con dos
        consultas distintas. Si ordenaran distinto, la opinión acabaría pegada a
        otro inmueble."""
        d = self._vista(self.token)
        for x in d["inmuebles"]:
            esperado = S._inmueble_de_la_seleccion(self.conn, "dem1", x["i"])
            fila = self.conn.execute(
                "SELECT direccion FROM inmuebles WHERE id = ?", (esperado,)).fetchone()
            with self.subTest(x["i"]):
                self.assertEqual(fila["direccion"], x["direccion"])


class OpinarSobreCadaInmuebleTests(BaseComprador):
    def test_la_opinion_se_guarda_y_vuelve(self):
        token = self._abre()
        estado, d = self._post("/api/portal_busqueda_opinion",
                               {"token": token, "i": 0, "valoracion": "verlo",
                                "comentario": "Me encaja, ¿cuándo puedo verlo?"}, con_sesion=False)
        self.assertEqual(estado, 200, d)
        x = self._vista(token)["inmuebles"][0]
        self.assertEqual(x["opinion"], "verlo")
        self.assertIn("cuándo puedo verlo", x["comentario"])

    def test_cambiar_de_opinion_no_crea_una_fila_nueva(self):
        token = self._abre()
        i = self._posicion(token, "Calle Uno 1")
        for v in ("encaja", "dudas", "descarta_precio"):
            self._post("/api/portal_busqueda_opinion", {"token": token, "i": i, "valoracion": v},
                       con_sesion=False)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) c FROM demanda_portal_opiniones WHERE inmueble_id='inm1'").fetchone()["c"], 1)
        self.assertEqual(self._vista(token)["inmuebles"][i]["opinion"], "descarta_precio")

    def test_querer_verlo_le_deja_una_tarea_al_asesor(self):
        """Una petición de visita que nadie ve es peor que no preguntar: él ya
        cuenta con que ha pedido cita."""
        token = self._abre()
        self._post("/api/portal_busqueda_opinion",
                   {"token": token, "i": self._posicion(token, "Calle Uno 1"), "valoracion": "verlo"},
                   con_sesion=False)
        fila = self.conn.execute(
            "SELECT asunto, estado FROM acciones WHERE inmueble_id = 'inm1' "
            "ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertIsNotNone(fila, "no se ha creado ninguna tarea")
        self.assertIn("visitar", fila["asunto"])
        self.assertEqual(fila["estado"], "Pendiente")

    def test_descartar_no_genera_tarea(self):
        """Cada descarte creando una tarea convierte la bandeja en ruido."""
        token = self._abre()
        antes = self.conn.execute("SELECT COUNT(*) c FROM acciones").fetchone()["c"]
        self._post("/api/portal_busqueda_opinion",
                   {"token": token, "i": self._posicion(token, "Calle Uno 1"),
                    "valoracion": "descarta_zona"}, con_sesion=False)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM acciones").fetchone()["c"], antes)


class ElHiloConElAsesorTests(BaseComprador):
    def test_van_los_dos_al_mismo_hilo(self):
        token = self._abre()
        self._post("/api/portal_busqueda_mensaje",
                   {"token": token, "texto": "¿Puedo ver el primero el sábado?"}, con_sesion=False)
        self._post("/api/demanda_portal_mensaje",
                   {"demanda_id": "dem1", "texto": "Claro, a las 11."})
        hilo = self._vista(token)["mensajes"]
        self.assertEqual([m["mio"] for m in hilo], [True, False])
        self.assertIn("sábado", hilo[0]["texto"])
        self.assertIn("a las 11", hilo[1]["texto"])

    def test_el_mensaje_del_comprador_deja_tarea(self):
        token = self._abre()
        self._post("/api/portal_busqueda_mensaje", {"token": token, "texto": "Una pregunta"},
                   con_sesion=False)
        fila = self.conn.execute(
            "SELECT asunto FROM acciones ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertIn("te ha escrito", fila["asunto"])

    def test_un_hilo_no_se_ve_desde_otra_demanda(self):
        self._ins("demandas", {"id": "dem2", "empresa_id": "emp1", "workspace_id": self.ws,
                               "cliente_id": "cli2", "tipo": "Piso", "estado": "Activa",
                               "created_at": AHORA, "updated_at": AHORA})
        token1 = self._abre("dem1")
        self._post("/api/portal_busqueda_mensaje", {"token": token1, "texto": "Secreto de dem1"},
                   con_sesion=False)
        token2 = self._abre("dem2")
        self.assertEqual(self._vista(token2)["mensajes"], [])


class LaAgendaTests(BaseComprador):
    def test_sale_la_cita_concertada(self):
        self._ins("visitas", {"id": "v1", "empresa_id": "emp1", "inmueble_id": "inm1",
                              "demanda_id": "dem1", "fecha": "2099-01-15", "hora": "11:00",
                              "estado": "Prevista", "created_at": AHORA, "updated_at": AHORA})
        d = self._vista(self._abre())
        self.assertEqual(len(d["agenda"]), 1)
        self.assertEqual(d["agenda"][0]["donde"], "Calle Uno 1")
        self.assertEqual(d["resumen"]["citas"], 1)

    def test_la_cita_tambien_sale_en_la_tarjeta_del_inmueble(self):
        self._ins("visitas", {"id": "v1", "empresa_id": "emp1", "inmueble_id": "inm1",
                              "demanda_id": "dem1", "fecha": "2099-01-15", "hora": "11:00",
                              "estado": "Prevista", "created_at": AHORA, "updated_at": AHORA})
        porDireccion = {x["direccion"]: x for x in self._vista(self._abre())["inmuebles"]}
        self.assertEqual(porDireccion["Calle Uno 1"]["cita"]["fecha"], "2099-01-15")
        self.assertIsNone(porDireccion["Calle Dos 2"]["cita"])

    def test_las_visitas_de_otro_no_salen(self):
        self._ins("demandas", {"id": "otra", "empresa_id": "emp1", "workspace_id": self.ws,
                               "cliente_id": "cli2", "tipo": "Piso", "estado": "Activa",
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("visitas", {"id": "v2", "empresa_id": "emp1", "inmueble_id": "inm1",
                              "demanda_id": "otra", "fecha": "2099-02-02", "hora": "10:00",
                              "estado": "Prevista", "created_at": AHORA, "updated_at": AHORA})
        self.assertEqual(self._vista(self._abre())["agenda"], [])


class LosDocumentosCompartidosTests(BaseComprador):
    def _doc(self, visible_comprador=0):
        S.ensure_demanda_portal_schema(self.conn)
        S.ensure_inmueble_portal_schema(self.conn)   # es quien crea `visible_portal`
        carpeta = S.UPLOADS / "inmuebles" / "inm1" / "docs"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "nota.pdf").write_bytes(b"%PDF-1.4 nota simple")
        self._ins("inmueble_docs", {"id": "doc1", "inmueble_id": "inm1", "nombre": "Nota simple",
                                    "url": "/uploads/inmuebles/inm1/docs/nota.pdf",
                                    "tipo": "Nota simple", "visible_comprador": visible_comprador,
                                    "created_at": AHORA, "updated_at": AHORA})

    def test_por_defecto_no_se_comparte_nada(self):
        self._doc(visible_comprador=0)
        self.assertEqual(self._vista(self._abre())["inmuebles"][-1]["documentos"], [])

    def test_compartido_se_ve_y_se_descarga(self):
        self._doc(visible_comprador=0)
        estado, d = self._post("/api/inmueble_doc_compartir_comprador",
                               {"doc_id": "doc1", "inmueble_id": "inm1", "visible": True})
        self.assertEqual(estado, 200, d)
        token = self._abre()
        porDireccion = {x["direccion"]: x for x in self._vista(token)["inmuebles"]}
        docs = porDireccion["Calle Uno 1"]["documentos"]
        self.assertEqual([x["nombre"] for x in docs], ["Nota simple"])
        estado, cuerpo = self._get(
            f"/api/portal_busqueda_documento?token={token}&i={porDireccion['Calle Uno 1']['i']}&n=0")
        self.assertEqual(estado, 200)
        self.assertIn("nota simple", cuerpo)

    def test_el_interruptor_del_propietario_no_abre_el_del_comprador(self):
        """Lo que se comparte con quien vende no es lo que se comparte con quien
        compra: son dos columnas a propósito."""
        self._doc(visible_comprador=0)
        self.conn.execute("UPDATE inmueble_docs SET visible_portal = 1 WHERE id = 'doc1'")
        self.conn.commit()
        for x in self._vista(self._abre())["inmuebles"]:
            self.assertEqual(x["documentos"], [])


class LaVistaPreviaDelAsesorTests(BaseComprador):
    def test_ve_lo_mismo_con_su_sesion(self):
        estado, cuerpo = self._get("/api/portal_busqueda?preview=dem1", con_sesion=True)
        self.assertEqual(estado, 200, cuerpo)
        d = json.loads(cuerpo)
        self.assertTrue(d["vista_previa"])
        self.assertEqual(len(d["inmuebles"]), 2)

    def test_sin_sesion_no_hay_vista_previa(self):
        estado, cuerpo = self._get("/api/portal_busqueda?preview=dem1")
        self.assertEqual(estado, 401, cuerpo)

    def test_no_le_cuenta_una_visita_al_comprador(self):
        """Existe justo para eso: mirar el portal sin falsear el «última vez que
        entró», que es el dato por el que se mira."""
        self._abre()
        self._get("/api/portal_busqueda?preview=dem1", con_sesion=True)
        fila = self.conn.execute("SELECT accesos, last_access_at FROM demanda_portal_accesos "
                                 "ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertEqual(int(fila["accesos"] or 0), 0)
        self.assertFalse(fila["last_access_at"])


class LaPaginaTests(BaseComprador):
    def test_la_pagina_se_sirve_sin_sesion(self):
        estado, html = self._get("/portal-busqueda")
        self.assertEqual(estado, 200)
        self.assertIn("Mi selección", html)

    def test_no_carga_el_javascript_del_crm(self):
        """Quien entra aquí es un comprador. El JS de la aplicación sabe de
        honorarios y de márgenes y no tiene por qué llegar a su navegador."""
        _, html = self._get("/portal-busqueda")
        self.assertNotIn("app.js", html)

    def test_no_la_indexa_un_buscador(self):
        _, html = self._get("/portal-busqueda")
        self.assertIn("noindex", html)

    def test_las_tipografias_se_sirven_desde_aqui(self):
        _, html = self._get("/portal-busqueda")
        self.assertNotIn("fonts.googleapis.com", html)
        for f in ("ibm-plex-sans.woff2", "ibm-plex-serif.woff2"):
            with self.subTest(f):
                self.assertIn(f"/assets/fuentes/{f}", html)
                self.assertTrue((S.ASSETS / "fuentes" / f).exists())

    def test_un_bano_no_son_banos(self):
        """Salía «1 baños» en la mitad de las fichas de la muestra."""
        _, html = self._get("/portal-busqueda")
        self.assertIn('Number(x.banos) === 1 ? " baño"', html)

    def test_el_token_no_se_queda_en_la_barra(self):
        _, html = self._get("/portal-busqueda")
        self.assertIn("history.replaceState", html)


class ElEsquemaSobreviveAUnaLecturaTests(BaseComprador):
    def test_las_tablas_se_quedan_creadas(self):
        """En Postgres el DDL va dentro de la transacción: sin `commit`, una
        petición de sólo lectura crea las tablas, responde 200, y el rollback del
        pool se las lleva. Pasó con las del propietario, en producción."""
        fuente = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        i = fuente.index("def ensure_demanda_portal_schema")
        cuerpo = fuente[i:fuente.index("\ndef ", i + 10)]
        self.assertIn("conn.commit()", cuerpo)


if __name__ == "__main__":
    unittest.main()
