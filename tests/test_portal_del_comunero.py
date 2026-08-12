"""El portal del comunero: lo que ve el vecino y lo que no puede alcanzar.

El portal ya existía y estaba bien planteado —token con hash en base, cada alta revoca
la anterior, caducidad, y una minimización de datos razonada—. Le faltaban dos cosas:

**Los documentos se listaban pero no se podían abrir.** La respuesta llevaba título,
tipo y fecha, y nada más. Enseñar un documento que no se puede descargar es peor que no
enseñarlo.

**Las juntas no estaban.** Ni la convocatoria ni el acta, que son justo los dos
documentos que la ley manda entregar a todos los propietarios (arts. 16.2 y 19.4 LPH) y
que hoy iban por correo aparte.

Lo delicado es cómo se pide un documento sin mandar identificadores internos, que es un
principio que el portal ya tenía escrito: «con un id se puede probar suerte en otros
endpoints». La respuesta es una referencia opaca que solo significa algo junto al token
de quien la recibió. Estos tests comprueban justo eso: que la referencia de un vecino no
le sirve a otro, y que la de un documento no publicado no existe.
"""

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
from web import server  # noqa: E402

WS = "ws1"


class BaseDePruebaTests(unittest.TestCase):
    def setUp(self):
        self.conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(self.conn)
        ahora = "2026-08-12T10:00:00"
        # Dos comunidades, para poder comprobar que un vecino no alcanza la otra.
        for cid, nombre in (("c1", "C.P Una"), ("c2", "C.P Otra")):
            self.conn.execute(
                "INSERT INTO workspace_fincas_comunidades (id, workspace_id, nombre, estado, created_at, updated_at) "
                "VALUES (?, ?, ?, 'Activa', ?, ?)", (cid, WS, nombre, ahora, ahora))
        for vid, cid, nombre in (("v1", "c1", "ANA PEREZ"), ("v2", "c2", "JOSE BENITEZ")):
            self.conn.execute(
                "INSERT INTO workspace_fincas_vecinos (id, workspace_id, comunidad_id, nombre, piso, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, '1 A', ?, ?)", (vid, WS, cid, nombre, ahora, ahora))
        # Un documento visible con fichero, uno visible sin fichero, y uno no visible.
        for did, cid, titulo, key, visible in (
            ("d1", "c1", "Acta 2025", "docs/acta.pdf", 1),
            ("d2", "c1", "Presupuesto sin adjuntar", "", 1),
            ("d3", "c1", "Contrato del ascensor", "docs/ascensor.pdf", 0),
            ("d4", "c2", "Documento de la otra", "docs/otra.pdf", 1),
        ):
            self.conn.execute(
                "INSERT INTO workspace_fincas_documentos (id, workspace_id, comunidad_id, titulo, doc_key, "
                "visible_portal, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (did, WS, cid, titulo, key, visible, ahora, ahora))
        # Una junta publicada y otra sin publicar.
        for jid, cid, fecha, publicada in (
            ("j1", "c1", "2026-06-10", 1), ("j2", "c1", "2026-11-20", 0),
        ):
            self.conn.execute(
                "INSERT INTO workspace_fincas_juntas (id, workspace_id, comunidad_id, fecha, tipo, estado, "
                "publicado_portal, created_at, updated_at) VALUES (?, ?, ?, ?, 'ordinaria', 'Celebrada', ?, ?, ?)",
                (jid, WS, cid, fecha, publicada, ahora, ahora))
        self.conn.commit()

    def alta(self, vecino_id, comunidad_id):
        crudo = server.make_portal_token()
        self.conn.execute(
            "INSERT INTO workspace_fincas_portal_accesos (id, workspace_id, comunidad_id, vecino_id, "
            "token_hash, expires_at, revocado, accesos, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, '2030-01-01', 0, 0, ?, ?)",
            (server.os.urandom(8).hex(), WS, comunidad_id, vecino_id,
             server.hash_portal_token(crudo), "2026-08-12", "2026-08-12"))
        self.conn.commit()
        return crudo


class ElVecinoVeLoSuyoTests(BaseDePruebaTests):
    def test_ve_sus_documentos_visibles_y_no_los_demas(self):
        datos = server.fetch_fincas_portal_public(self.conn, self.alta("v1", "c1"))
        titulos = [d["titulo"] for d in datos["documentos"]]
        self.assertIn("Acta 2025", titulos)
        self.assertIn("Presupuesto sin adjuntar", titulos)
        self.assertNotIn("Contrato del ascensor", titulos)   # no marcado visible
        self.assertNotIn("Documento de la otra", titulos)    # de otra comunidad

    def test_el_que_tiene_fichero_lleva_referencia_y_el_que_no_va_sin_ella(self):
        """Sin referencia la página no pinta enlace: no se ofrece lo que no se puede abrir."""
        datos = server.fetch_fincas_portal_public(self.conn, self.alta("v1", "c1"))
        por_titulo = {d["titulo"]: d for d in datos["documentos"]}
        self.assertTrue(por_titulo["Acta 2025"]["ref"])
        self.assertEqual(por_titulo["Presupuesto sin adjuntar"]["ref"], "")

    def test_solo_ve_las_juntas_publicadas(self):
        datos = server.fetch_fincas_portal_public(self.conn, self.alta("v1", "c1"))
        self.assertEqual([j["fecha"] for j in datos["juntas"]], ["2026-06-10"])

    def test_no_sale_ningun_identificador_interno(self):
        """El principio que ya tenía el portal, y que la descarga no podía romper."""
        import json
        crudo = json.dumps(server.fetch_fincas_portal_public(self.conn, self.alta("v1", "c1")))
        for interno in ("ws1", "c1", "v1", "d1", "j1", "docs/acta.pdf"):
            with self.subTest(interno=interno):
                self.assertNotIn(f'"{interno}"', crudo)


class UnaReferenciaSoloValeConSuTokenTests(BaseDePruebaTests):
    def test_la_del_vecino_de_al_lado_no_sirve(self):
        token_ana = self.alta("v1", "c1")
        token_jose = self.alta("v2", "c2")
        ref_de_ana = server.fetch_fincas_portal_public(self.conn, token_ana)["documentos"][0]["ref"]
        # La misma referencia, presentada con el otro token, no encaja con nada suyo.
        suyas = {server.referencia_portal(token_jose, d)
                 for d in ("d1", "d2", "d3", "d4")}
        self.assertNotIn(ref_de_ana, suyas)

    def test_cambia_con_el_token_aunque_el_documento_sea_el_mismo(self):
        a, b = self.alta("v1", "c1"), self.alta("v1", "c1")
        self.assertNotEqual(server.referencia_portal(a, "d1"), server.referencia_portal(b, "d1"))

    def test_no_se_puede_construir_sin_el_token(self):
        """Sin el token no hay forma de llegar a la referencia.

        Antes esto comprobaba que el id no apareciera como subcadena del hash, y eso
        falla por azar: «d1» sale en un hexadecimal de dieciséis dígitos una vez de cada
        pocas. Lo que importa no es la forma, es que dependa del token."""
        ref = server.referencia_portal(self.alta("v1", "c1"), "d1")
        self.assertRegex(ref, r"^[0-9a-f]{16}$")
        self.assertNotEqual(ref, server.referencia_portal("token-inventado", "d1"))
        self.assertNotEqual(ref, server.referencia_portal("", "d1"))


class LasDescargasSeComprubanContraLoPublicadoTests(unittest.TestCase):
    """El endpoint recalcula las referencias de lo que ese vecino puede ver y busca la
    que encaja; no acepta un id ni consulta por él."""

    def _cuerpo(self):
        i = SERVER.index('if path in ("/api/workspace_fincas_portal_doc"')
        return SERVER[i: SERVER.index("\n        if path ==", i + 10)]

    def test_filtra_por_visible_y_por_comunidad(self):
        cuerpo = self._cuerpo()
        self.assertIn("COALESCE(visible_portal, 0) = 1", cuerpo)
        self.assertIn("comunidad_id = ?", cuerpo)

    def test_la_junta_tiene_que_estar_publicada(self):
        self.assertIn("COALESCE(publicado_portal, 0) = 1", self._cuerpo())

    def test_compara_en_tiempo_constante(self):
        """Comparar referencias con `==` filtra información por el tiempo de respuesta."""
        self.assertIn("secrets.compare_digest", self._cuerpo())

    def test_respeta_la_revocacion_y_la_caducidad(self):
        cuerpo = self._cuerpo()
        self.assertIn('row_value(acceso, "revocado", 0)', cuerpo)
        self.assertIn("expires_at", cuerpo)

    def test_son_rutas_publicas_declaradas(self):
        """Si no están en la lista, el portal pide sesión y el vecino no la tiene."""
        for ruta in ("/api/workspace_fincas_portal_doc", "/api/workspace_fincas_portal_junta"):
            with self.subTest(ruta=ruta):
                self.assertIn(f'"{ruta}",', SERVER)

    def test_la_pagina_enlaza_las_dos_cosas(self):
        i = SERVER.index("Documentos de la comunidad")
        pagina = SERVER[i - 2500: i + 1500]
        self.assertIn("workspace_fincas_portal_doc?ref=", pagina)
        self.assertIn("tipo=convocatoria", pagina)
        self.assertIn("tipo=acta", pagina)


if __name__ == "__main__":
    unittest.main()
