"""Lo que salió de auditar el CRM inmobiliario.

Tres agujeros de permisos y un cabo suelto:

- **El rol «Lectura» no impedía escribir.** El rol de la cuenta y el rol dentro del
  workspace eran cosas distintas y solo se miraba el segundo; como el alta sembraba
  a todo el mundo como «Miembro», los ocho usuarios de solo lectura de producción
  podían crear, modificar y borrar igual que un administrador. El rol era
  decorativo, y la pantalla seguía diciendo «Lectura».
- **La guarda de inmuebles la decidía el cliente.** `enforce_workspace_membership`
  se llamaba solo si el cuerpo de la petición traía `workspace_id`: omitirlo bastaba
  para saltársela. En `inmueble_propietarios_update` era peor, porque el `empresa_id`
  también salía del cuerpo y había una rama que leía el inmueble sin filtro alguno.
- **Listar por `empresa_id` no comprobaba nada.** Cualquier sesión podía pedir los
  inmuebles de cualquier empresa pasando su id.
- **No se podía anular una solicitud de firma enviada.** Solo dejaba de valer al
  caducar o si el firmante la rechazaba.

Un matiz de honestidad sobre el alcance: hoy los 86 inmuebles pertenecen a dos
empresas del mismo grupo, así que esto no era una fuga entre clientes distintos. Era
un agujero latente, y quien podía usarlo sin querer era la propia plantilla.
"""

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
from web import server  # noqa: E402


def handler(ruta, post=True):
    a = f'elif parsed.path == "{ruta}":' if post else f'if path == "{ruta}":'
    i = SERVER.index(a)
    fin = [x for x in (SERVER.find("\n        elif parsed.path ==", i), SERVER.find("\n        if path ==", i)) if x > 0]
    return SERVER[i: min(fin) if fin else i + 8000]


ESCRITURAS = [
    "/api/inmueble_update", "/api/inmueble_delete", "/api/inmueble_propietarios_update",
    "/api/inmueble_compradores", "/api/inmueble_servicios_update", "/api/inmueble_docs",
    "/api/inmueble_checklist_generate", "/api/inmueble_checklist_update",
    "/api/inmueble_archive_pending_actions", "/api/inmueble_encargo_close",
    "/api/inmueble_renovar", "/api/inmueble_guided_prepare", "/api/inmueble_propietario_create",
    "/api/inmueble_catastro_sync", "/api/captacion_update", "/api/captacion_delete",
    "/api/captaciones_update", "/api/captacion_convert",
]


class ElRolDeLecturaMandaTests(unittest.TestCase):
    def test_una_cuenta_de_lectura_no_escribe(self):
        conn = server.get_db(":memory:")
        conn.execute("CREATE TABLE IF NOT EXISTS usuarios (id TEXT PRIMARY KEY, rol TEXT, activo INTEGER)")
        conn.execute("INSERT INTO usuarios (id, rol, activo) VALUES ('u1', 'Lectura', 1)")
        conn.commit()
        self.assertTrue(server.cuenta_es_de_solo_lectura(conn, {"user_id": "u1"}))

    def test_un_administrador_si(self):
        conn = server.get_db(":memory:")
        conn.execute("CREATE TABLE IF NOT EXISTS usuarios (id TEXT PRIMARY KEY, rol TEXT, activo INTEGER)")
        conn.execute("INSERT INTO usuarios (id, rol, activo) VALUES ('u2', 'Administrador', 1)")
        conn.commit()
        self.assertFalse(server.cuenta_es_de_solo_lectura(conn, {"user_id": "u2"}))

    def test_se_lee_de_la_base_y_no_de_la_sesion(self):
        """Una sesión abierta antes de bajarle los permisos a alguien seguiría
        escribiendo hasta que caducara."""
        conn = server.get_db(":memory:")
        conn.execute("CREATE TABLE IF NOT EXISTS usuarios (id TEXT PRIMARY KEY, rol TEXT, activo INTEGER)")
        conn.execute("INSERT INTO usuarios (id, rol, activo) VALUES ('u3', 'Lectura', 1)")
        conn.commit()
        # La sesión dice Administrador; la base manda.
        self.assertTrue(server.cuenta_es_de_solo_lectura(conn, {"user_id": "u3", "rol": "Administrador"}))

    def test_sin_sesion_no_es_de_lectura(self):
        self.assertFalse(server.cuenta_es_de_solo_lectura(None, None))

    def test_se_comprueba_antes_que_nada(self):
        """Va delante de la vía de actor privilegiado: una cuenta de solo lectura no
        escribe por ningún camino."""
        i = SERVER.index("def enforce_workspace_membership")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertLess(cuerpo.index("cuenta_es_de_solo_lectura"),
                        cuerpo.index("workspace_actor_is_privileged"))

    def test_solo_afecta_a_la_escritura(self):
        i = SERVER.index("def enforce_workspace_membership")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("if write and cuenta_es_de_solo_lectura(conn, session):", cuerpo)

    def test_el_alta_ya_no_siembra_a_todos_como_miembro(self):
        """Era el origen: la pantalla decía «Lectura» y el permiso era de escritura."""
        self.assertNotIn('"Lectura", ws_modernia, "Miembro")', SERVER)
        self.assertIn('"Lectura", ws_modernia, "Lectura")', SERVER)


class LaGuardaDeInmueblesNoSePuedeSaltarTests(unittest.TestCase):
    def test_todas_las_escrituras_la_llaman(self):
        for ruta in ESCRITURAS:
            with self.subTest(ruta=ruta):
                c = handler(ruta)
                self.assertTrue(
                    "enforce_inmueble_access" in c or "enforce_registro_de_inmueble" in c,
                    f"{ruta} escribe sin comprobar el acceso",
                )

    def test_ya_no_es_opcional_segun_lo_que_mande_el_cliente(self):
        """El patrón viejo: `workspace_id = payload.get(...)` y luego `if workspace_id:`
        alrededor de la comprobación. Omitirlo la saltaba entera."""
        for ruta in ("/api/inmueble_update", "/api/inmueble_delete", "/api/inmueble_archive_pending_actions"):
            with self.subTest(ruta=ruta):
                c = handler(ruta)
                self.assertNotIn(
                    "if workspace_id:\n                session = getattr(self, \"auth_session\", None)", c)

    def test_el_ambito_sale_del_registro_no_del_cuerpo(self):
        i = SERVER.index("def enforce_inmueble_access")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn('FROM {tabla} WHERE id = ?', cuerpo)
        self.assertIn("row_value(fila, \"workspace_id\"", cuerpo)

    def test_los_registros_antiguos_no_quedan_bloqueados(self):
        """81 de los 86 inmuebles de producción no tienen workspace_id: si el
        respaldo por empresa fallara, se quedarían inaccesibles."""
        i = SERVER.index("def enforce_inmueble_access")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("enforce_empresa_membership(conn, session, empresa_id, write=write)", cuerpo)

    def test_sin_empresa_ni_workspace_se_deniega(self):
        """Preferible un registro inaccesible a uno que toca cualquiera."""
        i = SERVER.index("def enforce_inmueble_access")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("if not empresa_id:", cuerpo)

    def test_lo_que_cuelga_hereda_el_ambito_del_inmueble(self):
        i = SERVER.index("def enforce_registro_de_inmueble")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("enforce_inmueble_access(conn, session, padre, write=write)", cuerpo)

    def test_captacion_delete_ya_no_confia_en_la_empresa_del_cuerpo(self):
        c = handler("/api/captacion_delete")
        self.assertNotIn('WHERE id = ? AND empresa_id = ?', c)
        self.assertIn("enforce_registro_de_inmueble", c)

    def test_no_se_reimplementa_lo_que_ya_existia(self):
        """`enforce_empresa_membership` ya resolvía el caso, incluido el legacy de un
        único workspace. Mi primera versión lo duplicaba peor."""
        self.assertNotIn("def enforce_empresa_access", SERVER)


class ListarPorEmpresaSeComprubebaTests(unittest.TestCase):
    def test_el_listado_de_inmuebles_exige_pertenencia(self):
        c = handler("/api/inmuebles", post=False)
        i = c.index('where.append("i.empresa_id = ?")')
        self.assertIn("enforce_empresa_membership(conn, session, empresa_id)", c[:i])


class AnularUnaFirmaEnviadaTests(unittest.TestCase):
    def test_existe_el_endpoint(self):
        self.assertIn('elif parsed.path == "/api/inmueble_signature_cancel":', SERVER)

    def test_esta_en_las_listas_de_rutas(self):
        """Sin esto responde «Endpoint no valido»."""
        self.assertGreaterEqual(SERVER.count('"/api/inmueble_signature_cancel"'), 3)

    def test_comprueba_pertenencia_con_escritura(self):
        c = handler("/api/inmueble_signature_cancel")
        self.assertIn('enforce_empresa_membership(conn, session, data.get("empresa_id"), write=True)', c)

    def test_quema_el_token(self):
        """Sin esto el enlace ya enviado seguiría abriendo la solicitud aunque
        figurara como anulada."""
        c = handler("/api/inmueble_signature_cancel")
        self.assertIn("token_hash = ?", c)
        self.assertIn('"cancelada:" + os.urandom(16).hex()', c)

    def test_no_anula_una_ya_firmada(self):
        """Revocar algo con valor probatorio no puede ser un botón."""
        c = handler("/api/inmueble_signature_cancel")
        self.assertIn('if estado == "signed":', c)
        self.assertIn("La solicitud ya está firmada", c)

    def test_no_anula_dos_veces(self):
        c = handler("/api/inmueble_signature_cancel")
        self.assertIn('if estado in {"cancelled", "rejected", "expired"}:', c)

    def test_queda_en_el_historico(self):
        c = handler("/api/inmueble_signature_cancel")
        self.assertIn('record_signature_event(', c)
        self.assertIn('"cancelled"', c)

    def test_hay_listado_para_poder_anular_desde_la_pantalla(self):
        c = handler("/api/inmueble_signature_requests", post=False)
        self.assertIn("enforce_inmueble_access", c)

    def test_el_listado_no_devuelve_el_token(self):
        """Devolverlo convertiría un listado en una forma de firmar por otro."""
        c = handler("/api/inmueble_signature_requests", post=False)
        self.assertNotIn("token_hash", c)
        self.assertNotIn("otp_hash", c)

    def test_la_pantalla_tiene_el_boton_y_avisa(self):
        self.assertIn("const cancelDocSignature", APP)
        self.assertIn("Anular firma pendiente", APP)
        self.assertIn("El enlace dejará de funcionar al momento", APP)

    def test_no_ofrece_anular_lo_que_ya_esta_cerrado(self):
        i = APP.index("const cancelDocSignature")
        cuerpo = APP[i: i + 1800]
        self.assertIn('["signed", "cancelled", "rejected", "expired"]', cuerpo)


if __name__ == "__main__":
    unittest.main()


class UnProspectoSinInmuebleSigueSiendoAccesibleTests(unittest.TestCase):
    """Casi introduzco una regresión al cerrar las guardas.

    La auditoría contó «1 captación huérfana» como fleco de datos. Al mirarla de
    cerca no lo era: es un prospecto en fase «Prospecto» con `inmueble_id` a nulo,
    que es exactamente como debe estar una captación antes de convertirse. La
    primera versión de `enforce_registro_de_inmueble` denegaba el acceso a los
    registros sin inmueble, así que habría dejado ese prospecto —y todos los futuros—
    imposibles de tocar. Justo lo contrario de lo que se venía a arreglar.
    """

    def test_sin_inmueble_se_cae_al_ambito_por_empresa(self):
        i = SERVER.index("def enforce_registro_de_inmueble")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("enforce_empresa_membership(conn, session, empresa_id, write=write)", cuerpo)

    def test_ya_no_se_deniega_por_no_tener_inmueble(self):
        i = SERVER.index("def enforce_registro_de_inmueble")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertNotIn("El registro no está asociado a ningún inmueble", cuerpo)

    def test_sin_empresa_ni_inmueble_si_se_deniega(self):
        """Ahí ya no hay nada con lo que decidir."""
        i = SERVER.index("def enforce_registro_de_inmueble")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("if not empresa_id:", cuerpo)
