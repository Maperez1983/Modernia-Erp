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

import base64
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

    def _cabeceras(self, ruta):
        try:
            with urllib.request.urlopen(self.base + ruta) as r:
                return r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers)

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

    def test_a_la_vista_van_cuatro_y_los_motivos_se_abren_al_descartar(self):
        """Seis pastillas por ficha eran veinticuatro en una pantalla de cuatro
        inmuebles y la ficha dejaba de leerse. Los motivos del descarte sólo
        significan algo cuando ya ha dicho que no."""
        v = self._vista(self._abre())["valoraciones"]
        self.assertEqual([x["clave"] for x in v["principales"]],
                         ["encaja", "verlo", "dudas", "descarta"])
        self.assertEqual([x["clave"] for x in v["motivos"]],
                         ["descarta_precio", "descarta_zona"])

    def test_los_seis_valores_se_siguen_admitiendo(self):
        """Repartirlos en dos filas es cosa de la pantalla; lo que se guarda no
        cambia, y una opinión vieja tiene que seguir valiendo."""
        token = self._abre()
        i = self._posicion(token, "Calle Uno 1")
        for clave in S.VALORACIONES_DEL_COMPRADOR:
            with self.subTest(clave):
                estado, d = self._post("/api/portal_busqueda_opinion",
                                       {"token": token, "i": i, "valoracion": clave},
                                       con_sesion=False)
                self.assertEqual(estado, 200, d)
                self.assertEqual(self._vista(token)["inmuebles"][i]["opinion"], clave)

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

    def test_el_verde_de_las_superficies_no_cambia_con_el_tema(self):
        """`--verde` se aclara en modo oscuro para poder leerse sobre negro. Usar
        ese mismo verde de FONDO con letra blanca dejaba la cabecera y las pastillas
        marcadas en 1,74:1: se veían, pero no se leían. Las superficies llevan su
        propio token, igual en los dos temas."""
        _, html = self._get("/portal-busqueda")
        css = html[html.index("<style>"):html.index("</style>")]
        for regla in (".cabecera {", '.opinar button[aria-pressed="true"] {', ".boton {"):
            i = css.index(regla)
            with self.subTest(regla):
                trozo = css[i:css.index("}", i)]
                self.assertIn("var(--verde-solido)", trozo)
                self.assertNotIn("background: var(--verde);", trozo)
        # Y el token no se redefine en el bloque de modo oscuro.
        oscuro = css[css.index("@media (prefers-color-scheme: dark)"):]
        self.assertNotIn("--verde-solido", oscuro[:oscuro.index("}\n    }")])

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


class ElSeguimientoDelEstadoTests(BaseComprador):
    """Un comprador vuelve al portal a preguntar dos cosas: si ha bajado de precio
    y si todavía está libre. Las dos estaban guardadas y nadie se las contaba."""

    def _apunte(self, inmueble_id, campo, antes, despues, cuando):
        self._ins("auditoria", {"id": os.urandom(8).hex(), "empresa_id": "emp1",
                                "entidad": "inmueble", "entidad_id": inmueble_id,
                                "accion": "Cambio", "usuario": "ana",
                                "detalles": json.dumps({"campo": campo, "from": antes, "to": despues}),
                                "created_at": cuando})

    def _etapa(self, inmueble_id, desde, hasta, cuando):
        self._ins("crm_stage_events", {"id": os.urandom(8).hex(), "empresa_id": "emp1",
                                       "inmueble_id": inmueble_id, "from_etapa": desde,
                                       "to_etapa": hasta, "usuario": "ana", "created_at": cuando})

    def test_una_bajada_de_precio_se_le_cuenta(self):
        self._apunte("inm1", "precio_objetivo", 260000, 249000, "2026-08-10 10:00:00")
        x = self._vista(self._abre())["inmuebles"][self._posicion(self._abre(), "Calle Uno 1")]
        textos = [n["texto"] for n in x["novedades"]]
        self.assertTrue(any("bajado" in t for t in textos), textos)
        self.assertTrue(any("249.000 €" in t for t in textos), textos)
        # Sin céntimos: «249.000,00 €» por una casa se lee como un extracto.
        self.assertFalse(any(",00" in t for t in textos), textos)

    def test_una_subida_tambien_se_le_cuenta(self):
        """Enseñar sólo las bajadas convierte el portal en un folleto."""
        self._apunte("inm1", "precio_objetivo", 240000, 255000, "2026-08-10 10:00:00")
        token = self._abre()
        x = self._vista(token)["inmuebles"][self._posicion(token, "Calle Uno 1")]
        self.assertTrue(any("subido" in n["texto"] for n in x["novedades"]))

    def test_poner_el_precio_por_primera_vez_no_es_una_bajada(self):
        """En la bitácora eso es `from: null`, y en producción hay 153 apuntes así.
        Contarlo como bajada sería mentir con buena letra."""
        self._apunte("inm1", "precio_encargo", None, 249000, "2026-08-10 10:00:00")
        token = self._abre()
        x = self._vista(token)["inmuebles"][self._posicion(token, "Calle Uno 1")]
        self.assertEqual(x["novedades"], [])

    def test_reservarse_y_volver_al_mercado(self):
        self._etapa("inm1", "Encargo", "Reservado", "2026-08-09 10:00:00")
        self._etapa("inm1", "Reservado", "Encargo", "2026-08-11 10:00:00")
        token = self._abre()
        textos = [n["texto"] for n in self._vista(token)["inmuebles"][self._posicion(token, "Calle Uno 1")]["novedades"]]
        self.assertIn("Se ha reservado", textos)
        self.assertIn("Vuelve a estar disponible", textos)

    def test_el_encargo_del_principio_no_es_una_novedad(self):
        """Si no venía de estar cerrado, «vuelve a estar disponible» es falso."""
        self._etapa("inm1", "", "Encargo", "2026-08-01 10:00:00")
        token = self._abre()
        self.assertEqual(self._vista(token)["inmuebles"][self._posicion(token, "Calle Uno 1")]["novedades"], [])

    def test_que_hay_una_oferta_no_se_le_cuenta(self):
        """Es una palanca de venta. Por escrito y con fecha es una promesa que luego
        hay que sostener."""
        self._etapa("inm1", "Encargo", "Propuesta", "2026-08-10 10:00:00")
        token = self._abre()
        self.assertEqual(self._vista(token)["inmuebles"][self._posicion(token, "Calle Uno 1")]["novedades"], [])

    def test_lo_posterior_a_su_ultima_entrada_va_marcado(self):
        token = self._abre()
        self._vista(token)          # primera entrada: queda el sello
        self._apunte("inm1", "precio_objetivo", 260000, 249000, "2099-01-01 10:00:00")
        d = self._vista(token)
        x = d["inmuebles"][self._posicion(token, "Calle Uno 1")]
        self.assertTrue(x["novedades"][0]["nuevo"])
        self.assertEqual(d["resumen"]["novedades"], 1)

    def test_lo_que_ya_habia_visto_no_lo_esta(self):
        self._apunte("inm1", "precio_objetivo", 260000, 249000, "2026-08-01 10:00:00")
        token = self._abre()
        self._vista(token)
        d = self._vista(token)
        self.assertFalse(d["inmuebles"][self._posicion(token, "Calle Uno 1")]["novedades"][0]["nuevo"])
        self.assertEqual(d["resumen"]["novedades"], 0)

    def test_las_novedades_de_otro_inmueble_no_se_mezclan(self):
        self._apunte("inm1", "precio_objetivo", 260000, 249000, "2026-08-10 10:00:00")
        token = self._abre()
        self.assertEqual(self._vista(token)["inmuebles"][self._posicion(token, "Calle Dos 2")]["novedades"], [])


class PedirVisitaDesdeElPortalTests(BaseComprador):
    def _pide(self, token, direccion="Calle Uno 1", **extra):
        cuerpo = {"token": token, "i": self._posicion(token, direccion),
                  "fecha": "2099-03-04", "franja": "mañana"}
        cuerpo.update(extra)
        return self._post("/api/portal_busqueda_visita", cuerpo, con_sesion=False)

    def test_entra_como_cita_solicitada_en_la_agenda(self):
        token = self._abre()
        estado, d = self._pide(token)
        self.assertEqual(estado, 200, d)
        fila = self.conn.execute(
            "SELECT inmueble_id, demanda_id, fecha, estado, notas FROM visitas").fetchone()
        self.assertEqual(fila["inmueble_id"], "inm1")
        self.assertEqual(fila["demanda_id"], "dem1")
        self.assertEqual(fila["fecha"], "2099-03-04")
        self.assertEqual(fila["estado"], "Solicitada")
        self.assertIn("mañana", fila["notas"])

    def test_no_se_da_por_confirmada(self):
        """Ponerla como prevista en su agenda sería prometer en nombre del asesor."""
        token = self._abre()
        self._pide(token)
        x = self._vista(token)["inmuebles"][self._posicion(token, "Calle Uno 1")]
        self.assertEqual(x["cita"]["estado"], "Solicitada")

    def test_le_deja_tarea_al_asesor(self):
        token = self._abre()
        self._pide(token)
        fila = self.conn.execute(
            "SELECT asunto, estado FROM acciones ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertIn("Pide visita", fila["asunto"])
        self.assertIn("mañana", fila["asunto"])
        self.assertEqual(fila["estado"], "Pendiente")

    def test_pedirla_cuenta_como_querer_verlo(self):
        token = self._abre()
        self._pide(token)
        self.assertEqual(self._vista(token)["inmuebles"][self._posicion(token, "Calle Uno 1")]["opinion"],
                         "verlo")

    def test_no_pisa_lo_que_ya_habia_dicho(self):
        token = self._abre()
        self._post("/api/portal_busqueda_opinion",
                   {"token": token, "i": self._posicion(token, "Calle Uno 1"), "valoracion": "dudas"},
                   con_sesion=False)
        self._pide(token)
        self.assertEqual(self._vista(token)["inmuebles"][self._posicion(token, "Calle Uno 1")]["opinion"],
                         "dudas")

    def test_pulsar_dos_veces_no_duplica_la_cita(self):
        token = self._abre()
        self._pide(token)
        self._pide(token)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM visitas").fetchone()["c"], 1)

    def test_un_dia_pasado_no_se_admite(self):
        token = self._abre()
        estado, d = self._pide(token, fecha="2020-01-01")
        self.assertEqual(estado, 400, d)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM visitas").fetchone()["c"], 0)

    def test_ni_un_dia_con_cualquier_forma(self):
        token = self._abre()
        for malo in ("mañana", "04/03/2099", "", "2099-13-40x"):
            with self.subTest(malo):
                self.assertEqual(self._pide(token, fecha=malo)[0], 400)

    def test_no_se_pide_visita_de_algo_ya_vendido(self):
        self.conn.execute("UPDATE inmuebles SET estado = 'Vendido' WHERE id = 'inm1'")
        self.conn.commit()
        token = self._abre()
        estado, d = self._pide(token)
        self.assertEqual(estado, 409, d)

    def test_ni_de_algo_que_no_esta_en_su_seleccion(self):
        token = self._abre()
        estado, _ = self._post("/api/portal_busqueda_visita",
                               {"token": token, "i": 9, "fecha": "2099-03-04"}, con_sesion=False)
        self.assertEqual(estado, 404)


class LaHojaDeVisitaSeHaceSolaTests(BaseComprador):
    def _pide(self, token):
        return self._post("/api/portal_busqueda_visita",
                          {"token": token, "i": self._posicion(token, "Calle Uno 1"),
                           "fecha": "2099-03-04", "franja": "tarde"}, con_sesion=False)

    def setUp(self):
        super().setUp()
        # La hoja de visita sólo existe con encargo vivo, igual que la manual.
        self._ins("captaciones", {"id": "cap1", "empresa_id": "emp1", "workspace_id": self.ws,
                                  "inmueble_id": "inm1", "direccion": "Calle Uno 1",
                                  "etapa": "Encargo", "situacion_comercial": "Encargo",
                                  "precio_objetivo": 240000,
                                  "created_at": AHORA, "updated_at": AHORA})

    def test_al_concertar_la_visita_se_genera(self):
        token = self._abre()
        estado, d = self._pide(token)
        self.assertEqual(estado, 200, d)
        self.assertTrue(d["hoja"], "no se ha generado la hoja de visita")
        fila = self.conn.execute(
            "SELECT nombre, tipo, url, origen_tipo, origen_id FROM inmueble_docs "
            "WHERE tipo = 'Hoja de visita'").fetchone()
        self.assertIsNotNone(fila)
        self.assertEqual(fila["origen_tipo"], "portal_hoja_visita")
        self.assertEqual(fila["origen_id"], "dem1")

    def test_le_llega_a_el_en_su_ficha(self):
        token = self._abre()
        self._pide(token)
        x = self._vista(token)["inmuebles"][self._posicion(token, "Calle Uno 1")]
        self.assertTrue(any("Hoja de visita" in doc["nombre"] for doc in x["documentos"]),
                        [doc["nombre"] for doc in x["documentos"]])

    def test_lleva_el_precio_del_inmueble_que_va_a_ver(self):
        """Es el punto del documento: qué precio le hemos dicho, y cuándo."""
        token = self._abre()
        self._pide(token)
        i = self._posicion(token, "Calle Uno 1")
        docs = self._vista(token)["inmuebles"][i]["documentos"]
        n = next(d["n"] for d in docs if "Hoja de visita" in d["nombre"])
        with urllib.request.urlopen(
                self.base + f"/api/portal_busqueda_documento?token={token}&i={i}&n={n}") as r:
            crudo = r.read()
        self.assertTrue(crudo.startswith(b"%PDF"))
        # El texto de un PDF va comprimido: buscarlo en los bytes no prueba nada.
        import io
        from pypdf import PdfReader
        texto = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(crudo)).pages)
        self.assertIn("240.000", texto.replace("\u202f", " "))
        self.assertIn("Calle Uno 1".upper(), texto.upper())

    def test_la_hoja_de_otro_comprador_no_se_ve(self):
        """Lleva su nombre y su teléfono: si fuera por el interruptor general, la
        vería cualquier otro interesado en la misma casa."""
        self._ins("demandas", {"id": "dem2", "empresa_id": "emp1", "workspace_id": self.ws,
                               "cliente_id": "cli2", "tipo": "Piso", "estado": "Activa",
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmueble_compradores", {"id": "ic9", "empresa_id": "emp1", "inmueble_id": "inm1",
                                           "demanda_id": "dem2", "cliente_id": "cli2",
                                           "estado": "Interesado",
                                           "created_at": AHORA, "updated_at": AHORA})
        self._pide(self._abre("dem1"))
        token2 = self._abre("dem2")
        x = self._vista(token2)["inmuebles"][self._posicion(token2, "Calle Uno 1")]
        self.assertEqual([doc["nombre"] for doc in x["documentos"]], [])

    def test_sin_encargo_vivo_no_se_genera_pero_la_visita_se_pide_igual(self):
        """Un documento de visita de un inmueble que ya no llevamos no lo firma
        nadie. Lo que no puede es cargarse la petición de cita."""
        self.conn.execute("UPDATE captaciones SET situacion_comercial = 'Noticia' WHERE id = 'cap1'")
        self.conn.commit()
        token = self._abre()
        estado, d = self._pide(token)
        self.assertEqual(estado, 200, d)
        self.assertFalse(d["hoja"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM visitas").fetchone()["c"], 1)


class LaCabeceraDeLaAgenciaTests(BaseComprador):
    """El color y el logo son de la agencia, no míos. Con una condición: que se
    siga leyendo."""

    def test_sin_color_elegido_va_el_verde_de_la_casa(self):
        d = self._vista(self._abre())
        self.assertEqual(d["agencia"]["color"], S.PORTAL_COLOR_POR_DEFECTO)
        self.assertEqual(d["agencia"]["tinta"], "#ffffff")

    def test_el_color_de_la_agencia_manda(self):
        self.conn.execute("UPDATE empresas SET color_portal = '#7C2D12' WHERE id = 'emp1'")
        self.conn.commit()
        d = self._vista(self._abre())
        self.assertEqual(d["agencia"]["color"], "#7C2D12")
        self.assertEqual(d["agencia"]["tinta"], "#ffffff")

    def test_un_color_claro_cambia_la_letra_a_oscura(self):
        """Una agencia elige su color mirando su logo, no midiendo contrastes. Con
        un amarillo corporativo la letra blanca desaparece."""
        self.conn.execute("UPDATE empresas SET color_portal = '#FACC15' WHERE id = 'emp1'")
        self.conn.commit()
        d = self._vista(self._abre())
        self.assertEqual(d["agencia"]["color"], "#FACC15")
        self.assertEqual(d["agencia"]["tinta"], "#0f172a")

    def test_un_color_que_no_se_lee_con_ninguna_letra_se_descarta(self):
        """Ni blanco ni negro llegan a 4,5:1: se vuelve al verde de la casa antes
        que publicar una cabecera ilegible."""
        self.conn.execute("UPDATE empresas SET color_portal = '#7A7A7A' WHERE id = 'emp1'")
        self.conn.commit()
        self.assertEqual(self._vista(self._abre())["agencia"]["color"], S.PORTAL_COLOR_POR_DEFECTO)

    def test_lo_que_no_es_un_color_se_ignora(self):
        for basura in ("rojo", "#ZZZ", "15803D", "'; DROP TABLE empresas; --", "#15803D  "):
            with self.subTest(basura):
                self.assertEqual(S.color_de_marca(basura)[0], S.PORTAL_COLOR_POR_DEFECTO)

    def test_el_contraste_elegido_es_de_verdad(self):
        for color in ("#15803D", "#7C2D12", "#FACC15", "#0EA5E9", "#831843"):
            fondo, tinta = S.color_de_marca(color)
            with self.subTest(color):
                self.assertGreaterEqual(S._contraste(fondo, tinta), 4.5)

    def test_el_logo_en_s3_ya_no_se_descarta(self):
        """Sólo se enseñaba si estaba en `/assets/`, y la única agencia que usa esto
        tiene el suyo en S3: salía sin logo y no lo sabía nadie."""
        self.conn.execute("UPDATE empresas SET logo_url = 's3://company_logos/x.png' WHERE id = 'emp1'")
        self.conn.commit()
        self.assertTrue(self._vista(self._abre())["agencia"]["logo"])

    def test_el_logo_se_sirve_con_el_token_y_no_de_otra_forma(self):
        origen = S.ASSETS / "verifika2" / "verifika2_wordmark_check_green.png"
        if not origen.exists():
            self.skipTest("no hay logo de ejemplo en assets/")
        self.conn.execute("UPDATE empresas SET logo_url = ? WHERE id = 'emp1'",
                          ("/assets/verifika2/" + origen.name,))
        self.conn.commit()
        token = self._abre()
        with urllib.request.urlopen(
                self.base + f"/api/portal_busqueda_logo?token={token}") as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers.get("Content-Type"), "image/png")
            self.assertTrue(r.read().startswith(b"\x89PNG"))
        self.assertEqual(self._get("/api/portal_busqueda_logo?token=" + "a" * 43)[0], 404)

    def test_sin_logo_no_se_inventa_uno(self):
        self.conn.execute("UPDATE empresas SET logo_url = '' WHERE id = 'emp1'")
        self.conn.commit()
        token = self._abre()
        self.assertFalse(self._vista(token)["agencia"]["logo"])
        estado, _ = self._cabeceras(f"/api/portal_busqueda_logo?token={token}")
        self.assertEqual(estado, 404)

    def test_la_pagina_usa_los_dos_tokens(self):
        _, html = self._get("/portal-busqueda")
        css = html[html.index("<style>"):html.index("</style>")]
        i = css.index(".cabecera {")
        self.assertIn("var(--sobre-solido)", css[i:css.index("}", i)])
        # La marca se aplica con una hoja de estilo y no con `style.setProperty`:
        # el acento tiene que cambiar con el tema del sistema, y eso sólo lo sabe
        # hacer una media query.
        self.assertIn("--verde-solido: ${pal.fondo}", html)
        self.assertIn("prefers-color-scheme: dark", html[html.index('hoja.textContent'):])


class LaPaletaQueSaleDeUnSoloColorTests(unittest.TestCase):
    """Dejar el precio en verde sobre una cabecera granate se ve peor que no dejar
    elegir. Del corporativo salen los cinco colores, y los cinco tienen que leerse
    en los dos temas."""

    COLORES = ("#15803D", "#7C2D12", "#0EA5E9", "#831843", "#FACC15", "#1E3A8A", "#EA580C")

    def test_el_acento_se_lee_sobre_tarjeta_clara_y_oscura(self):
        for color in self.COLORES:
            p = S.paleta_de_marca(color)
            with self.subTest(color=color, tema="claro"):
                self.assertGreaterEqual(S._contraste(p["acento_claro"], "#ffffff"), 4.5)
            with self.subTest(color=color, tema="oscuro"):
                self.assertGreaterEqual(S._contraste(p["acento_oscuro"], "#161a21"), 4.5)

    def test_la_etiqueta_se_lee_sobre_su_propio_fondo_suave(self):
        for color in self.COLORES:
            p = S.paleta_de_marca(color)
            with self.subTest(color=color, tema="claro"):
                self.assertGreaterEqual(S._contraste(p["acento_claro"], p["suave_claro"]), 4.5)
            with self.subTest(color=color, tema="oscuro"):
                self.assertGreaterEqual(S._contraste(p["acento_oscuro"], p["suave_oscuro"]), 4.5)

    def test_la_cabecera_se_lee_con_su_tinta(self):
        for color in self.COLORES:
            p = S.paleta_de_marca(color)
            with self.subTest(color):
                self.assertGreaterEqual(S._contraste(p["fondo"], p["tinta"]), 4.5)

    def test_sin_color_la_cabecera_sigue_siendo_la_de_siempre(self):
        p = S.paleta_de_marca("")
        self.assertEqual(p["fondo"], S.PORTAL_COLOR_POR_DEFECTO)
        # El acento sale del mismo verde, un punto más oscuro para que la etiqueta
        # —tinta sobre fondo teñido— llegue a 4,5:1. Antes se quedaba en 4,31.
        self.assertGreaterEqual(S._contraste(p["acento_claro"], p["suave_claro"]), 4.5)

    def test_el_tono_se_conserva(self):
        """Corrido para que se lea, no cambiado: un naranja tiene que seguir
        pareciendo naranja o la marca deja de reconocerse."""
        def canal_dominante(hexa):
            v = [int(hexa.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
            return v.index(max(v))
        for color in ("#EA580C", "#0EA5E9", "#831843"):
            with self.subTest(color):
                p = S.paleta_de_marca(color)
                self.assertEqual(canal_dominante(p["acento_oscuro"]), canal_dominante(color))


class ElLogoSobreElColorTests(BaseComprador):
    def test_el_logo_va_sobre_pastilla_blanca(self):
        """La mitad de los logos vienen con su propio fondo blanco: encima de un
        color corporativo se ven como un recorte pegado. Puesta a propósito se lee
        como parte del diseño, y con un PNG transparente funciona igual."""
        _, html = self._get("/portal-busqueda")
        css = html[html.index("<style>"):html.index("</style>")]
        i = css.index(".cabecera .marca img {")
        regla = css[i:css.index("}", i)]
        self.assertIn("background: #fff", regla)
        self.assertIn("border-radius", regla)


class DeLaOfertaALaReservaTests(BaseComprador):
    """El camino entero, que es donde se gana o se pierde la operación: ofrece,
    le contestan, acepta, ingresa la señal y sube el justificante."""

    def setUp(self):
        super().setUp()
        S.ensure_ofertas_schema(self.conn)
        self.conn.execute("UPDATE empresas SET iban = 'ES91 2100 0418 4502 0005 1332' WHERE id = 'emp1'")
        self.conn.commit()
        self.token = self._abre()
        self.i = self._posicion(self.token, "Calle Uno 1")

    def _oferta(self, **extra):
        cuerpo = {"token": self.token, "i": self.i, "importe": 230000,
                  "plazo_escritura": 60, "vigencia": "2099-01-01"}
        cuerpo.update(extra)
        return self._post("/api/portal_busqueda_oferta", cuerpo, con_sesion=False)

    def _id_de_la_oferta(self):
        return self.conn.execute(
            "SELECT id FROM inmueble_ofertas ORDER BY created_at DESC LIMIT 1").fetchone()["id"]

    def _ficha(self):
        return self._vista(self.token)["inmuebles"][self.i]

    def test_presentar_una_oferta(self):
        estado, d = self._oferta(financiacion=True, comentario="Sujeto a que me den la hipoteca")
        self.assertEqual(estado, 200, d)
        o = self._ficha()["oferta"]
        self.assertEqual(o["estado"], "presentada")
        self.assertEqual(o["importe"], 230000)
        self.assertTrue(o["financiacion"])
        self.assertEqual(o["plazo_escritura"], 60)
        self.assertTrue(o["puede_retirar"])

    def test_le_deja_tarea_al_asesor(self):
        self._oferta()
        fila = self.conn.execute(
            "SELECT asunto FROM acciones ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertIn("Oferta de", fila["asunto"])
        self.assertIn("230.000", fila["asunto"])

    def test_sin_importe_no_hay_oferta(self):
        self.assertEqual(self._oferta(importe=0)[0], 400)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM inmueble_ofertas").fetchone()["c"], 0)

    def test_una_fecha_de_vigencia_que_no_existe(self):
        self.assertEqual(self._oferta(vigencia="2099-02-31")[0], 400)

    def test_no_se_oferta_dos_veces_a_la_vez(self):
        self._oferta()
        estado, d = self._oferta(importe=235000)
        self.assertEqual(estado, 409, d)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) c FROM inmueble_ofertas").fetchone()["c"], 1)

    def test_no_se_oferta_por_lo_que_ya_esta_vendido(self):
        self.conn.execute("UPDATE inmuebles SET estado = 'Vendido' WHERE id = 'inm1'")
        self.conn.commit()
        self.assertEqual(self._oferta()[0], 409)

    def test_retirarla_mientras_no_han_contestado(self):
        self._oferta()
        estado, d = self._post("/api/portal_busqueda_oferta_decision",
                               {"token": self.token, "i": self.i, "decision": "retirar"},
                               con_sesion=False)
        self.assertEqual(estado, 200, d)
        o = self._ficha()["oferta"]
        self.assertEqual(o["estado"], "retirada")
        self.assertTrue(o["puede_ofertar"], "tras retirarla tiene que poder hacer otra")

    def test_la_contraoferta_y_su_respuesta(self):
        self._oferta()
        estado, d = self._post("/api/inmueble_oferta_responder",
                               {"oferta_id": self._id_de_la_oferta(), "decision": "contraoferta",
                                "importe": 240000, "nota": "Es lo mínimo que acepta la propiedad"})
        self.assertEqual(estado, 200, d)
        o = self._ficha()["oferta"]
        self.assertEqual(o["estado"], "contraoferta")
        self.assertEqual(o["contraoferta"], 240000)
        self.assertTrue(o["puede_decidir"])
        self.assertFalse(o["puede_retirar"], "con una contraoferta encima ya no se retira, se decide")
        estado, d = self._post("/api/portal_busqueda_oferta_decision",
                               {"token": self.token, "i": self.i, "decision": "aceptar"},
                               con_sesion=False)
        self.assertEqual(estado, 200, d)
        self.assertEqual(self._ficha()["oferta"]["estado"], "aceptada")

    def test_aceptar_sin_decir_la_senal_no_vale(self):
        """Aceptar y no decir cuánto ni a qué cuenta deja al comprador esperando un
        correo que no llega."""
        self._oferta()
        estado, d = self._post("/api/inmueble_oferta_responder",
                               {"oferta_id": self._id_de_la_oferta(), "decision": "aceptar"})
        self.assertEqual(estado, 400, d)
        self.assertEqual(self._ficha()["oferta"]["estado"], "presentada")

    def test_al_aceptar_le_llegan_la_cuenta_y_el_plazo(self):
        self._oferta()
        estado, d = self._post("/api/inmueble_oferta_responder",
                               {"oferta_id": self._id_de_la_oferta(), "decision": "aceptar",
                                "senal": 6000, "limite": "2099-02-02"})
        self.assertEqual(estado, 200, d)
        o = self._ficha()["oferta"]
        self.assertEqual(o["estado"], "reserva_pendiente")
        self.assertEqual(o["senal"], 6000)
        # El IBAN sale de la ficha de la empresa si no se manda otro.
        self.assertEqual(o["iban"], "ES91 2100 0418 4502 0005 1332")
        self.assertEqual(o["limite"], "2099-02-02")
        self.assertTrue(o["puede_justificar"])

    def test_sin_cuenta_en_ningun_sitio_se_dice(self):
        self.conn.execute("UPDATE empresas SET iban = '' WHERE id = 'emp1'")
        self.conn.commit()
        self._oferta()
        estado, d = self._post("/api/inmueble_oferta_responder",
                               {"oferta_id": self._id_de_la_oferta(), "decision": "aceptar", "senal": 6000})
        self.assertEqual(estado, 400, d)
        self.assertIn("cuenta", d["error"])

    def _hasta_la_senal(self):
        self._oferta()
        self._post("/api/inmueble_oferta_responder",
                   {"oferta_id": self._id_de_la_oferta(), "decision": "aceptar", "senal": 6000})

    def test_el_justificante_se_sube_y_queda_en_el_expediente(self):
        self._hasta_la_senal()
        estado, d = self._post("/api/portal_busqueda_justificante",
                               {"token": self.token, "i": self.i, "nombre": "transferencia.pdf",
                                "file_base64": base64.b64encode(b"%PDF-1.4 justificante").decode()},
                               con_sesion=False)
        self.assertEqual(estado, 200, d)
        self.assertEqual(self._ficha()["oferta"]["estado"], "reserva_justificada")
        doc = self.conn.execute(
            "SELECT nombre, tipo, origen_tipo FROM inmueble_docs WHERE tipo = 'Justificante de la señal'"
        ).fetchone()
        self.assertEqual(doc["nombre"], "transferencia.pdf")
        self.assertEqual(doc["origen_tipo"], "portal_justificante")

    def test_no_se_sube_el_justificante_antes_de_tiempo(self):
        self._oferta()
        estado, d = self._post("/api/portal_busqueda_justificante",
                               {"token": self.token, "i": self.i, "nombre": "x.pdf",
                                "file_base64": base64.b64encode(b"%PDF").decode()}, con_sesion=False)
        self.assertEqual(estado, 409, d)

    def test_solo_pdf_o_foto(self):
        self._hasta_la_senal()
        estado, d = self._post("/api/portal_busqueda_justificante",
                               {"token": self.token, "i": self.i, "nombre": "recibo.html",
                                "file_base64": base64.b64encode(b"<script>").decode()}, con_sesion=False)
        self.assertEqual(estado, 415, d)

    def test_la_agencia_da_por_buena_la_senal_y_queda_reservado(self):
        self._hasta_la_senal()
        self._post("/api/portal_busqueda_justificante",
                   {"token": self.token, "i": self.i, "nombre": "t.pdf",
                    "file_base64": base64.b64encode(b"%PDF").decode()}, con_sesion=False)
        estado, d = self._post("/api/inmueble_oferta_verificar", {"oferta_id": self._id_de_la_oferta()})
        self.assertEqual(estado, 200, d)
        o = self._ficha()["oferta"]
        self.assertEqual(o["estado"], "reservada")
        self.assertFalse(o["puede_ofertar"])
        self.assertFalse(o["puede_justificar"])

    def test_no_se_verifica_lo_que_no_se_ha_justificado(self):
        self._hasta_la_senal()
        self.assertEqual(self._post("/api/inmueble_oferta_verificar",
                                    {"oferta_id": self._id_de_la_oferta()})[0], 409)

    def test_la_historia_va_encadenada(self):
        """La fila cambia de estado —es el ahora—; lo que pasó, no."""
        self._hasta_la_senal()
        filas = self.conn.execute(
            "SELECT quien, que, prev_hash, integrity_hash FROM inmueble_oferta_eventos "
            "ORDER BY created_at ASC").fetchall()
        self.assertEqual([f["que"] for f in filas],
                         ["presenta la oferta", "acepta la oferta y pide la señal"])
        self.assertEqual(filas[0]["prev_hash"], "")
        self.assertEqual(filas[1]["prev_hash"], filas[0]["integrity_hash"])
        for f in filas:
            self.assertTrue(f["integrity_hash"])

    def test_tocar_un_apunte_despues_se_nota(self):
        self._oferta()
        fila = self.conn.execute("SELECT * FROM inmueble_oferta_eventos LIMIT 1").fetchone()
        self.conn.execute("UPDATE inmueble_oferta_eventos SET importe = '1.00' WHERE id = ?",
                          (fila["id"],))
        self.conn.commit()
        tocada = self.conn.execute("SELECT * FROM inmueble_oferta_eventos WHERE id = ?",
                                   (fila["id"],)).fetchone()
        import hashlib as _h
        recalculado = _h.sha256(
            S._payload_de_evento_de_oferta(tocada, tocada["prev_hash"]).encode("utf-8")).hexdigest()
        self.assertNotEqual(recalculado, tocada["integrity_hash"])

    def test_la_oferta_de_otro_comprador_no_se_ve(self):
        self._ins("demandas", {"id": "dem3", "empresa_id": "emp1", "workspace_id": self.ws,
                               "cliente_id": "cli2", "tipo": "Piso", "estado": "Activa",
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("inmueble_compradores", {"id": "ic8", "empresa_id": "emp1", "inmueble_id": "inm1",
                                           "demanda_id": "dem3", "cliente_id": "cli2",
                                           "estado": "Interesado", "created_at": AHORA,
                                           "updated_at": AHORA})
        self._oferta()
        token2 = self._abre("dem3")
        otra = self._vista(token2)["inmuebles"][self._posicion(token2, "Calle Uno 1")]
        self.assertIsNone(otra["oferta"], "no puede ver la oferta de otro interesado")
        self.assertNotIn("230000", self._get(f"/api/portal_busqueda?token={token2}")[1])

    def test_no_se_responde_a_una_oferta_de_otro_workspace(self):
        """Con un comercial, no con el Administrador sembrado: el Administrador
        cruza workspaces por diseño y con él este test no probaría nada."""
        self._ins("usuarios", {"id": "u2", "nombre": "Comercial Ajeno", "usuario": "ajeno",
                               "email": "aj@x.test", "rol": "Comercial", "servicio": "Inmobiliaria",
                               "activo": 1, "password_hash": S.hash_password(CLAVE),
                               "created_at": AHORA, "updated_at": AHORA})
        self._ins("workspace_miembros", {"id": "wm2", "workspace_id": self.ws, "usuario_id": "u2",
                                         "rol": "Miembro", "created_at": AHORA, "updated_at": AHORA})
        # Y con un segundo workspace de verdad: con uno solo, la autorreparación
        # vincula al usuario al vuelo —es lo previsto para instalaciones legacy— y
        # el test no probaría el aislamiento, sino ese atajo.
        self._ins("workspaces", {"id": "ws-ajeno", "nombre": "Otra agencia", "slug": "otra-agencia",
                                 "created_at": AHORA, "updated_at": AHORA})
        self._oferta()
        oferta_id = self._id_de_la_oferta()
        self.conn.execute("UPDATE inmuebles SET workspace_id = 'ws-ajeno' WHERE id = 'inm1'")
        self.conn.commit()
        req = urllib.request.Request(
            self.base + "/api/login",
            data=json.dumps({"usuario": "ajeno", "password": CLAVE}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            self.cookie = r.headers.get("Set-Cookie").split(";")[0]
        estado, d = self._post("/api/inmueble_oferta_responder",
                               {"oferta_id": oferta_id, "decision": "rechazar"})
        self.assertIn(estado, (403, 404), d)
        self.assertEqual(self.conn.execute(
            "SELECT estado FROM inmueble_ofertas WHERE id = ?", (oferta_id,)).fetchone()["estado"],
            "presentada")

    def test_una_retirada_no_tapa_a_la_nueva(self):
        """El sello de tiempo va al segundo: retirar una y presentar otra seguido
        deja dos filas con la misma fecha, y ordenar sólo por fecha podía devolver
        la retirada y dejarle la pantalla en un paso que ya no existe."""
        self._oferta()
        self._post("/api/portal_busqueda_oferta_decision",
                   {"token": self.token, "i": self.i, "decision": "retirar"}, con_sesion=False)
        ahora = self.conn.execute(
            "SELECT created_at FROM inmueble_ofertas LIMIT 1").fetchone()["created_at"]
        self._oferta(importe=235000)
        # Se fuerza el empate, que es lo que pasa de verdad cuando van seguidas.
        self.conn.execute("UPDATE inmueble_ofertas SET created_at = ?", (ahora,))
        self.conn.commit()
        o = self._ficha()["oferta"]
        self.assertEqual(o["estado"], "presentada")
        self.assertEqual(o["importe"], 235000)
