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


class ComunicarUnaIncidenciaTests(BaseDePruebaTests):
    """El único sitio del portal donde el vecino escribe, así que es donde más cuidado
    hace falta: la llave es el token, hay tope de envíos y la validación va en el
    servidor —el formulario se puede saltar—."""

    def _crea(self, workspace_id, comunidad_id, vecino_id, titulo, cuando=None):
        """Lo que hace el endpoint al insertar, para poder probar el tope sin HTTP."""
        self.conn.execute(
            "INSERT INTO workspace_fincas_incidencias (id, workspace_id, comunidad_id, titulo, "
            "estado, fecha_apertura, vecino_id, origen, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'Abierta', '2026-08-12', ?, 'portal', ?, ?)",
            (server.os.urandom(8).hex(), workspace_id, comunidad_id, titulo, vecino_id,
             cuando or "2026-08-12T10:00:00", "2026-08-12T10:00:00"))
        self.conn.commit()

    def test_solo_ve_las_suyas(self):
        self._crea(WS, "c1", "v1", "Gotera en mi trastero")
        self._crea(WS, "c1", "otro", "La del vecino de arriba")
        datos = server.fetch_fincas_portal_public(self.conn, self.alta("v1", "c1"))
        self.assertEqual([i["titulo"] for i in datos["incidencias"]], ["Gotera en mi trastero"])

    def test_el_tope_esta_puesto_y_es_por_vecino_y_dia(self):
        self.assertEqual(server.FINCAS_PORTAL_INCIDENCIAS_DIA, 5)
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_portal_incidencia":')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn("FINCAS_PORTAL_INCIDENCIAS_DIA", cuerpo)
        self.assertIn("vecino_id = ?", cuerpo)
        self.assertIn("status=429", cuerpo)

    def test_la_comunidad_sale_del_token_y_no_del_envio(self):
        """Si viniera en el cuerpo, cualquiera con un enlace escribiría en otra finca."""
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_portal_incidencia":')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn('comunidad_id = row_value(acceso, "comunidad_id", "")', cuerpo)
        self.assertNotIn('payload.get("comunidad_id")', cuerpo)
        self.assertNotIn('payload.get("vecino_id")', cuerpo)

    def test_recorta_en_el_servidor(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_portal_incidencia":')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn("FINCAS_PORTAL_TITULO_MAX", cuerpo)
        self.assertIn("FINCAS_PORTAL_DESCRIPCION_MAX", cuerpo)
        self.assertEqual(server.FINCAS_PORTAL_TITULO_MAX, 120)
        self.assertEqual(server.FINCAS_PORTAL_DESCRIPCION_MAX, 2000)

    def test_no_deja_mandar_un_titulo_vacio(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_portal_incidencia":')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn("len(titulo) < 4", cuerpo)

    def test_entra_abierta_sin_prioridad_y_marcada_como_del_portal(self):
        """Describir es del vecino; triar, del administrador. Y hay que poder
        distinguir lo que nadie ha mirado todavía."""
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_portal_incidencia":')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        insert = cuerpo[cuerpo.index("INSERT INTO workspace_fincas_incidencias"):
                        cuerpo.index("conn.commit()")]
        self.assertIn("'Abierta'", insert)
        self.assertIn("'portal'", insert)
        # En la sentencia, no en el comentario que explica por qué: la primera versión
        # de este test buscaba la palabra en todo el bloque y la encontraba ahí.
        self.assertNotIn("prioridad", insert)

    def test_respeta_revocacion_y_caducidad(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_portal_incidencia":')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn('row_value(acceso, "revocado", 0)', cuerpo)
        self.assertIn("expires_at", cuerpo)

    def test_es_ruta_publica_de_escritura(self):
        i = SERVER.index("AUTH_PUBLIC_POST_ENDPOINTS = {")
        self.assertIn('"/api/workspace_fincas_portal_incidencia",', SERVER[i: SERVER.index("}", i)])


class ElCertificadoSeCobraAntesDeDescargarseTests(BaseDePruebaTests):
    """El certificado del art. 9.1.e se factura siempre, así que no se emite a crédito.

    El vecino lo pide, ve el precio, y solo cuando la administración confirma el cobro
    aparece el enlace. Marcar el pago es del CRM, con sesión: el vecino no puede
    marcárselo a sí mismo.
    """

    def solicita(self, vecino_id="v1", comunidad_id="c1", estado="Solicitado", importe=25.0):
        cid = server.os.urandom(8).hex()
        self.conn.execute(
            "INSERT INTO workspace_fincas_certificados (id, workspace_id, comunidad_id, vecino_id, "
            "estado, importe, fecha_solicitud, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, '2026-08-12', '2026-08-12T10:00:00', '2026-08-12T10:00:00')",
            (cid, WS, comunidad_id, vecino_id, estado, importe))
        self.conn.commit()
        return cid

    def test_sin_solicitar_no_hay_estado_ni_enlace(self):
        cert = server.fetch_fincas_portal_public(self.conn, self.alta("v1", "c1"))["certificado"]
        self.assertEqual(cert["estado"], "")
        self.assertEqual(cert["ref"], "")

    def test_solicitado_pero_sin_pagar_no_da_enlace(self):
        """Lo importante: pedirlo no es tenerlo."""
        self.solicita(estado="Solicitado")
        cert = server.fetch_fincas_portal_public(self.conn, self.alta("v1", "c1"))["certificado"]
        self.assertEqual(cert["estado"], "Solicitado")
        self.assertEqual(cert["ref"], "")

    def test_pagado_si_da_enlace(self):
        self.solicita(estado="Pagado")
        cert = server.fetch_fincas_portal_public(self.conn, self.alta("v1", "c1"))["certificado"]
        self.assertEqual(cert["estado"], "Pagado")
        self.assertTrue(cert["ref"])

    def test_la_descarga_vuelve_a_comprobar_el_pago(self):
        """La referencia solo se calcula si está pagado, pero el endpoint lo comprueba
        otra vez: quien guardó el enlace de una solicitud anterior no puede usarlo para
        una nueva sin pagar."""
        i = SERVER.index('if path == "/api/workspace_fincas_portal_certificado_pdf":')
        cuerpo = SERVER[i: SERVER.index("# La junta: convocatoria o acta", i)]
        self.assertIn("estado = 'Pagado'", cuerpo)
        self.assertIn("secrets.compare_digest", cuerpo)

    def test_el_pago_lo_confirma_el_crm_con_sesion(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_certificado_pagado":')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn("enforce_workspace_membership", cuerpo)
        self.assertIn("write=True", cuerpo)
        # Y no está entre las rutas que se pueden llamar sin sesión.
        j = SERVER.index("AUTH_PUBLIC_POST_ENDPOINTS = {")
        self.assertNotIn("workspace_fincas_certificado_pagado", SERVER[j: SERVER.index("}", j)])

    def test_no_deja_pedir_dos_a_la_vez(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_portal_certificado":')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn("estado IN ('Solicitado', 'Pagado')", cuerpo)
        self.assertIn("status=409", cuerpo)

    def test_el_precio_sale_de_la_tarifa_del_workspace(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_portal_certificado":')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn('"certificado_corriente"', cuerpo)
        self.assertNotIn('payload.get("importe")', cuerpo)   # no lo pone el vecino

    def test_el_concepto_viene_en_la_tarifa_de_partida_y_a_cero(self):
        """A cero para que cada despacho ponga el suyo; inventarle un precio sería peor."""
        cert = next(t for t in server.FINCAS_TARIFAS_DEFECTO if t["clave"] == "certificado_corriente")
        self.assertEqual(cert["tipo"], "fija")
        self.assertEqual(cert["precio"], 0.0)


class ElCertificadoDiceLoQueCertificaTests(unittest.TestCase):
    """Se titulaba «certificado de deuda» también sin deuda, que es justo el caso de
    quien va a vender y tiene que enseñarlo en una notaría."""

    def _texto(self, recibos):
        from io import BytesIO
        from pypdf import PdfReader
        pdf = server.build_certificado_deuda_pdf(
            {"nombre": "C.P Una", "direccion": "Calle X 1"},
            {"nombre": "ANA PEREZ", "piso": "6 C", "nif": "25123456X"},
            recibos, company={"nombre": "Fincas Velazquez"})
        return "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)

    def test_sin_deuda_es_certificado_de_estar_al_corriente(self):
        texto = self._texto([])
        self.assertIn("CERTIFICADO DE ESTAR AL CORRIENTE DE PAGO", texto)
        self.assertIn("SÍ está al corriente", texto)
        # El artículo NO se cita en el documento: lo prohíbe
        # `test_no_se_inventa_plazos_ni_intereses`, y con razón. Un certificado que
        # emite un programa sin firma no invoca efectos legales.
        self.assertNotIn("9.1.e", texto)

    def test_con_deuda_sigue_siendo_certificado_de_deuda(self):
        texto = self._texto([{"periodo": "2026-07", "concepto": "Cuota", "estado": "Pendiente", "importe": 60}])
        self.assertIn("CERTIFICADO DE DEUDA", texto)
        self.assertIn("NO está al corriente", texto)

    def test_sigue_sin_firmar_solo(self):
        """Lo emite el secretario con el visto bueno del presidente; el programa no
        pone ni la firma ni la responsabilidad."""
        self.assertIn("Fdo.: El secretario administrador", self._texto([]))


if __name__ == "__main__":
    unittest.main()