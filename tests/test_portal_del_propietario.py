"""El portal del propietario: un enlace, y solo lo suyo.

Es la única pieza del módulo de fincas que abre superficie pública. Entra un vecino
sin sesión del CRM, con un enlace que le ha pasado el administrador, así que todo el
control está en el token y en lo que el endpoint decide devolver. Por eso la mayoría
de estos tests no comprueban que algo salga, sino que algo **no** salga.

Lo que se ha decidido y este fichero fija:

- **El token no se guarda.** En la base queda solo su sha256. Si alguien lee la
  tabla no puede entrar en el portal de nadie, y por eso el enlace se enseña una vez
  y no se puede volver a ver.
- **Cada alta revoca la anterior.** Renovar un enlace tiene que servir para cortar
  el viejo, que es la razón por la que se renueva.
- **Caduca.** Un enlace sin fecha de fin es un enlace eterno circulando por WhatsApp.
- **Los documentos son invisibles por defecto.** En esa carpeta hay contratos y
  facturas de proveedores; que un vecino los vea por descuido es peor que tener que
  marcar uno a uno los que sí.
- **No salen ids internos.** Con el enlace basta; el workspace o el id del vecino
  solo servirían para probar suerte en otros endpoints.
"""

import datetime
import json
import os
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
os.environ.pop("DATABASE_URL", None)
from web import server  # noqa: E402

IBAN = "ES9121000418450200051332"


class PortalDePrueba(unittest.TestCase):
    def setUp(self):
        self.conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(self.conn)
        self.ahora = datetime.datetime.now().isoformat(timespec="seconds")
        self.ws, self.com = "ws1", "com1"
        self.conn.execute(
            "INSERT INTO workspace_fincas_comunidades (id, workspace_id, nombre, direccion, estado, "
            "created_at, updated_at) VALUES (?,?,?,?,'Activa',datetime(?),datetime(?))",
            (self.com, self.ws, "C.P. Velázquez 11", "Avenida Velázquez 11", self.ahora, self.ahora),
        )
        for vid, nombre, piso in (("v1", "Juan Pérez", "1A"), ("v2", "Ana Ruiz", "1B")):
            self.conn.execute(
                "INSERT INTO workspace_fincas_vecinos (id, workspace_id, comunidad_id, nombre, piso, nif, "
                "coeficiente, iban, created_at, updated_at) "
                "VALUES (?,?,?,?,?, '12345678Z', 50, ?, datetime(?), datetime(?))",
                (vid, self.ws, self.com, nombre, piso, IBAN, self.ahora, self.ahora),
            )
        for i, (vid, periodo, estado, importe) in enumerate((
            ("v1", "2026-06", "Cobrado", 50), ("v1", "2026-07", "Pendiente", 50), ("v2", "2026-07", "Pendiente", 999),
        )):
            self.conn.execute(
                "INSERT INTO workspace_fincas_recibos (id, workspace_id, comunidad_id, vecino_id, periodo, "
                "concepto, importe, estado, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,datetime(?),datetime(?))",
                (f"r{i}", self.ws, self.com, vid, periodo, f"Cuota {periodo}", importe, estado, self.ahora, self.ahora),
            )
        self.conn.execute(
            "INSERT INTO workspace_fincas_documentos (id, workspace_id, comunidad_id, titulo, tipo, fecha, "
            "visible_portal, created_at, updated_at) "
            "VALUES ('d1',?,?,'Acta junta ordinaria','Acta','2026-06-20',1,datetime(?),datetime(?))",
            (self.ws, self.com, self.ahora, self.ahora),
        )
        self.conn.execute(
            "INSERT INTO workspace_fincas_documentos (id, workspace_id, comunidad_id, titulo, tipo, fecha, "
            "visible_portal, created_at, updated_at) "
            "VALUES ('d2',?,?,'Contrato con la empresa de limpieza','Contrato','2026-01-10',0,datetime(?),datetime(?))",
            (self.ws, self.com, self.ahora, self.ahora),
        )
        self.token = self.alta("v1")
        self.conn.commit()

    def alta(self, vecino_id, caduca="2027-01-01", revocado=0):
        crudo = server.make_portal_token()
        self.conn.execute(
            "INSERT INTO workspace_fincas_portal_accesos (id, workspace_id, comunidad_id, vecino_id, "
            "token_hash, expires_at, revocado, accesos, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,0,datetime(?),datetime(?))",
            (os.urandom(8).hex(), self.ws, self.com, vecino_id, server.hash_portal_token(crudo),
             caduca, revocado, self.ahora, self.ahora),
        )
        self.conn.commit()
        return crudo

    def portal(self, token=None):
        return server.fetch_fincas_portal_public(self.conn, token or self.token)


class SoloVeLoSuyoTests(PortalDePrueba):
    def test_ve_sus_recibos(self):
        datos = self.portal()
        self.assertEqual(len(datos["recibos"]), 2)
        self.assertEqual(datos["deuda"], 50.0)

    def test_no_ve_a_los_demas_propietarios(self):
        """Un vecino no tiene por qué saber quién está al corriente."""
        crudo = json.dumps(self.portal(), ensure_ascii=False)
        self.assertNotIn("Ana Ruiz", crudo)
        self.assertNotIn("999", crudo)

    def test_no_ve_documentos_sin_marcar(self):
        crudo = json.dumps(self.portal(), ensure_ascii=False)
        self.assertIn("Acta junta ordinaria", crudo)
        self.assertNotIn("Contrato con la empresa", crudo)

    def test_no_sale_el_iban_entero(self):
        datos = self.portal()
        self.assertNotIn(IBAN, json.dumps(datos))
        self.assertEqual(datos["propietario"]["cuenta"], "····1332")

    def test_no_salen_identificadores_internos(self):
        """Con el enlace basta; los ids solo servirían para probar en otros sitios."""
        crudo = json.dumps(self.portal(), ensure_ascii=False)
        for identificador in (self.ws, self.com, "v1", "d1"):
            with self.subTest(identificador=identificador):
                self.assertNotIn(f'"{identificador}"', crudo)

    def test_dos_propietarios_ven_cosas_distintas(self):
        otro = self.alta("v2")
        self.assertEqual(self.portal()["propietario"]["nombre"], "Juan Pérez")
        self.assertEqual(self.portal(otro)["propietario"]["nombre"], "Ana Ruiz")
        self.assertEqual(self.portal(otro)["deuda"], 999.0)


class ElTokenTests(PortalDePrueba):
    def test_es_largo_y_aleatorio(self):
        tokens = {server.make_portal_token() for _ in range(50)}
        self.assertEqual(len(tokens), 50)
        self.assertGreaterEqual(len(server.make_portal_token()), 40)

    def test_en_la_base_solo_esta_el_hash(self):
        guardado = self.conn.execute(
            "SELECT token_hash FROM workspace_fincas_portal_accesos LIMIT 1"
        ).fetchone()
        valor = server.row_value(guardado, "token_hash", "")
        self.assertNotEqual(valor, self.token)
        self.assertEqual(valor, server.hash_portal_token(self.token))
        self.assertEqual(len(valor), 64)

    def test_un_token_inventado_no_abre_nada(self):
        for intento in ("", None, "loquesea", "a" * 43):
            with self.subTest(intento=intento):
                self.assertIsNone(server.fetch_fincas_portal_public(self.conn, intento))

    def test_revocado_no_entra(self):
        self.conn.execute("UPDATE workspace_fincas_portal_accesos SET revocado = 1")
        self.conn.commit()
        self.assertEqual(self.portal(), {"error": "revocado"})

    def test_caducado_no_entra(self):
        self.conn.execute("UPDATE workspace_fincas_portal_accesos SET expires_at = '2020-01-01'")
        self.conn.commit()
        self.assertEqual(self.portal(), {"error": "caducado"})

    def test_se_apunta_cada_visita(self):
        """Sirve para saber si el vecino ha entrado, y para detectar un enlace filtrado."""
        self.portal()
        self.portal()
        fila = self.conn.execute("SELECT accesos FROM workspace_fincas_portal_accesos LIMIT 1").fetchone()
        self.assertEqual(int(server.row_value(fila, "accesos", 0) or 0), 2)


class ElAltaYLaRevocacionTests(unittest.TestCase):
    def _manejador(self, ruta):
        i = SERVER.index(f'elif parsed.path == "{ruta}"')
        return SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]

    def test_las_dos_exigen_pertenencia_con_escritura(self):
        for ruta in ("/api/workspace_fincas_portal_alta", "/api/workspace_fincas_portal_revocar"):
            with self.subTest(ruta=ruta):
                self.assertIn(
                    "enforce_workspace_membership(conn, session, workspace_id, write=True)",
                    self._manejador(ruta),
                )

    def test_no_se_puede_dar_alta_a_un_vecino_de_otro_workspace(self):
        cuerpo = self._manejador("/api/workspace_fincas_portal_alta")
        self.assertIn("WHERE id = ? AND workspace_id = ?", cuerpo)

    def test_cada_alta_revoca_la_anterior(self):
        """Renovar tiene que cortar el viejo: si no, quedan dos enlaces válidos."""
        cuerpo = self._manejador("/api/workspace_fincas_portal_alta")
        i = cuerpo.index("UPDATE workspace_fincas_portal_accesos SET revocado = 1")
        self.assertLess(i, cuerpo.index("INSERT INTO workspace_fincas_portal_accesos"))

    def test_el_enlace_caduca(self):
        cuerpo = self._manejador("/api/workspace_fincas_portal_alta")
        self.assertIn("timedelta(days=int(dias))", cuerpo)
        self.assertIn("FINCAS_PORTAL_DIAS_VALIDEZ", cuerpo)

    def test_avisa_de_que_el_enlace_solo_se_ve_una_vez(self):
        self.assertIn("solo se enseña ahora", self._manejador("/api/workspace_fincas_portal_alta"))
        self.assertIn("no se puede volver a ver", APP)

    def test_el_enlace_no_se_construye_con_el_host_de_la_peticion(self):
        """Si no, un Host manipulado generaría enlaces con el token hacia otro dominio."""
        cuerpo = self._manejador("/api/workspace_fincas_portal_alta")
        self.assertIn("self._external_base_url()", cuerpo)
        self.assertNotIn("self.headers.get(\"Host\")", cuerpo)


class LaSuperficiePublicaTests(unittest.TestCase):
    def test_solo_el_endpoint_de_lectura_es_publico(self):
        i = SERVER.index("AUTH_PUBLIC_GET_ENDPOINTS = {")
        publicos = SERVER[i: SERVER.index("}", i)]
        self.assertIn('"/api/workspace_fincas_portal_public",', publicos)
        self.assertIn('"/portal-comunidad",', publicos)
        j = SERVER.index("AUTH_PUBLIC_POST_ENDPOINTS = {")
        publicos_post = SERVER[j: SERVER.index("}", j)]
        self.assertNotIn("workspace_fincas_portal_alta", publicos_post)
        self.assertNotIn("workspace_fincas_portal_revocar", publicos_post)

    def test_la_pagina_no_se_indexa_ni_se_cachea(self):
        i = SERVER.index('if parsed.path == "/portal-comunidad"')
        cuerpo = SERVER[i: i + 8000]
        self.assertIn('"Cache-Control", "no-store"', cuerpo)
        self.assertIn("noindex", cuerpo)
        self.assertIn('"Referrer-Policy", "no-referrer"', cuerpo)

    def test_la_pagina_quita_el_token_de_la_barra(self):
        """El enlace lleva la llave dentro: no debe quedarse en el historial."""
        i = SERVER.index('if parsed.path == "/portal-comunidad"')
        cuerpo = SERVER[i: i + 8000]
        self.assertIn("history.replaceState(null, \"\", location.pathname)", cuerpo)

    def test_el_portal_no_carga_el_crm_entero(self):
        """Quien entra es un vecino, no un usuario de la aplicación."""
        i = SERVER.index('if parsed.path == "/portal-comunidad"')
        cuerpo = SERVER[i: i + 8000]
        self.assertNotIn("app.js", cuerpo)


if __name__ == "__main__":
    unittest.main()
