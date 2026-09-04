"""Informes periciales de valoración de inmuebles.

Módulo nuevo: expediente pericial (workspace_periciales) con testigos de
comparación, cadena de integridad de evidencia (fotos de visita, comparables
congelados) y firma electrónica propia, todo con el formato de la UNE 197001
y la metodología de la Orden ECO/805/2003.

Tres decisiones de diseño que estos tests fijan, porque son las que de verdad
importan si este informe acaba en un juzgado:

- **Un expediente firmado no se puede editar.** A diferencia de
  `workspace_presupuestos` (que no bloquea nada tras "Aceptado", es pura
  convención), aquí el guard es real: el endpoint rechaza con 409 cualquier
  escritura una vez `estado == "Firmado"`, y ese estado solo se alcanza desde
  dentro del propio flujo de firma — el POST público nunca lo acepta como
  valor de entrada.
- **La cadena de evidencia está aislada por expediente.** Se comprobó al
  diseñar esto que el patrón que se iba a copiar (`apunta_evento_de_oferta`)
  tiene la cadena de hash SIN acotar por entidad — un fallo real, ajeno a este
  módulo, que se dejó tal cual y se señaló aparte. Aquí se replicó el patrón
  correcto (`inmueble_portal_decisiones`), y un test lo demuestra: dos
  expedientes en paralelo no contaminan sus cadenas entre sí.
- **Una edición parcial no vacía el resto del expediente.** Mandar solo un
  campo (p. ej. la dirección) no debe borrar el resto — mismo criterio que
  ya usa `workspace_presupuestos`.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from web import server as S  # noqa: E402

CLAVE = "Pericial1234!"
AHORA = "2026-08-25 09:00:00"

TESTIGOS_SEIS = [
    ("Idealista", "2026-07-20", 190000, 90),
    ("Fotocasa", "2026-07-21", 185000, 88),
    ("Idealista", "2026-07-18", 200000, 92),
    ("Notaría", "2026-07-15", 178000, 85),
    ("Idealista", "2026-07-22", 192000, 91),
    ("Registro", "2026-07-10", 188000, 89),
]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "periciales.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("empresas", dict(id="emp1", nombre="Perito Test SL", activo=1, **base))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=self.ws, empresa_id="emp1", **base))
        self._ins("usuarios", dict(id="u1", nombre="Ana Perito", usuario="administradora",
                                    email="ana@perito.test", rol="Administrador", servicio="Inmobiliaria",
                                    activo=1, password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=self.ws, usuario_id="u1",
                                              rol="Owner", **base))
        self._prev = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.cookie = self._post("/api/login", {"usuario": "administradora", "password": CLAVE},
                                  cookie=False)["cookie"]

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
            f"INSERT INTO {tabla} ({','.join(d)}) VALUES ({','.join('?' * len(d))})",
            tuple(d.values()))
        self.conn.commit()

    def _post(self, ruta, cuerpo, cookie=True):
        req = urllib.request.Request(self.base + ruta, data=json.dumps(cuerpo).encode(),
                                      headers={"Content-Type": "application/json"}, method="POST")
        if cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                cuerpo_resp, galleta = r.read(), r.headers.get("Set-Cookie")
                return {"estado": r.status, "cookie": galleta.split(";")[0] if galleta else None,
                        "json": json.loads(cuerpo_resp.decode("utf-8"))}
        except urllib.error.HTTPError as e:
            cuerpo_resp = e.read()
            return {"estado": e.code, "cookie": None,
                    "json": json.loads(cuerpo_resp.decode("utf-8")) if cuerpo_resp else {}}

    def _get(self, ruta, cookie=True):
        req = urllib.request.Request(self.base + ruta, method="GET")
        if cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return {"estado": r.status, "cuerpo": r.read()}
        except urllib.error.HTTPError as e:
            return {"estado": e.code, "cuerpo": e.read()}

    def _crear_pericial(self, **overrides):
        payload = dict(
            workspace_id=self.ws, empresa_id="emp1", perito_usuario_id="u1",
            colegiado_numero="3079", finalidad="Judicial - Divorcio",
            denominacion_manual="Vivienda de prueba", direccion_manual="Calle Falsa 1, Málaga",
            fecha_valoracion="2026-08-10", superficie_calculo_usada="90",
        )
        payload.update(overrides)
        r = self._post("/api/workspace_pericial", payload)
        self.assertEqual(r["estado"], 200, r["json"])
        return r["json"]["id"]

    def _anade_testigos(self, pericial_id, testigos=TESTIGOS_SEIS):
        ultimo = None
        for fuente, fecha, precio, superficie in testigos:
            ultimo = self._post("/api/workspace_pericial_testigo", {
                "workspace_id": self.ws, "pericial_id": pericial_id, "fuente": fuente,
                "fecha_captura": fecha, "precio": precio, "superficie": superficie,
            })
            self.assertEqual(ultimo["estado"], 200, ultimo["json"])
        return ultimo["json"]


class ElExpedienteSeCreaYSeEditaTests(Base):
    def test_se_crea_sin_inmueble_gestionado(self):
        pericial_id = self._crear_pericial()
        fila = self.conn.execute(
            "SELECT estado, denominacion_manual FROM workspace_periciales WHERE id = ?", (pericial_id,)
        ).fetchone()
        self.assertEqual(fila["estado"], "Encargado")
        self.assertEqual(fila["denominacion_manual"], "Vivienda de prueba")

    def test_editar_parcial_no_vacia_el_resto(self):
        """Mandar solo `direccion_manual` no puede borrar la finalidad ni la
        denominación ya guardadas."""
        pericial_id = self._crear_pericial()
        r = self._post("/api/workspace_pericial", {
            "id": pericial_id, "workspace_id": self.ws, "empresa_id": "emp1",
            "direccion_manual": "Calle Falsa 1, planta 3, Málaga",
        })
        self.assertEqual(r["estado"], 200, r["json"])
        fila = self.conn.execute(
            "SELECT direccion_manual, denominacion_manual, finalidad FROM workspace_periciales WHERE id = ?",
            (pericial_id,),
        ).fetchone()
        self.assertEqual(fila["direccion_manual"], "Calle Falsa 1, planta 3, Málaga")
        self.assertEqual(fila["denominacion_manual"], "Vivienda de prueba")
        self.assertEqual(fila["finalidad"], "Judicial - Divorcio")

    def test_no_pertenecer_al_workspace_lo_rechaza(self):
        r = self._post("/api/workspace_pericial", {
            "workspace_id": self.ws, "empresa_id": "empresa-que-no-existe",
            "finalidad": "Judicial", "fecha_valoracion": "2026-08-10",
        })
        self.assertEqual(r["estado"], 403)


class LosTestigosSeHomogeneizanTests(Base):
    def test_alta_de_testigo_devuelve_homogeneizacion(self):
        pericial_id = self._crear_pericial()
        r = self._post("/api/workspace_pericial_testigo", {
            "workspace_id": self.ws, "pericial_id": pericial_id, "fuente": "Idealista",
            "fecha_captura": "2026-07-20", "precio": "180000", "superficie": "90",
        })
        self.assertEqual(r["estado"], 200)
        self.assertAlmostEqual(r["json"]["homogeneizacion"]["valor_unitario"], 2000.0)

    def test_coeficientes_ajustan_el_valor_homogeneizado(self):
        pericial_id = self._crear_pericial()
        r = self._post("/api/workspace_pericial_testigo", {
            "workspace_id": self.ws, "pericial_id": pericial_id, "fuente": "Idealista",
            "fecha_captura": "2026-07-20", "precio": "180000", "superficie": "90",
            "coeficientes": json.dumps({"planta": {"factor": 1.1, "motivo": "testigo en bajo"}}),
        })
        self.assertEqual(r["estado"], 200)
        # 180000/90 = 2000 €/m², homogeneizado x1.1 = 2200 €/m²
        self.assertAlmostEqual(r["json"]["homogeneizacion"]["valor_homogeneizado_unitario"], 2200.0)

    def test_el_valor_final_del_expediente_se_recalcula(self):
        pericial_id = self._crear_pericial()
        self._anade_testigos(pericial_id, TESTIGOS_SEIS[:2])
        fila = self.conn.execute("SELECT valor_final FROM workspace_periciales WHERE id = ?",
                                  (pericial_id,)).fetchone()
        self.assertGreater(float(fila["valor_final"] or 0), 0)

    def test_descartar_un_testigo_no_lo_borra(self):
        pericial_id = self._crear_pericial()
        resultado = self._anade_testigos(pericial_id, TESTIGOS_SEIS[:1])
        testigo_id = self.conn.execute(
            "SELECT id FROM workspace_pericial_testigos WHERE pericial_id = ?", (pericial_id,)
        ).fetchone()["id"]
        r = self._post("/api/workspace_pericial_testigo", {
            "workspace_id": self.ws, "pericial_id": pericial_id, "id": testigo_id,
            "fuente": "Idealista", "precio": "190000", "superficie": "90",
            "estado": "descartado", "motivo_descarte": "No homogéneo con el sujeto",
        })
        self.assertEqual(r["estado"], 200)
        fila = self.conn.execute("SELECT estado, motivo_descarte FROM workspace_pericial_testigos WHERE id = ?",
                                  (testigo_id,)).fetchone()
        self.assertEqual(fila["estado"], "descartado")
        self.assertTrue(fila["motivo_descarte"])
        # Sigue existiendo la fila: no es un DELETE.
        total = self.conn.execute("SELECT COUNT(*) AS n FROM workspace_pericial_testigos WHERE pericial_id = ?",
                                   (pericial_id,)).fetchone()["n"]
        self.assertEqual(total, 1)


class LaFirmaCierraElExpedienteTests(Base):
    def test_no_se_puede_firmar_sin_generar_el_pdf(self):
        pericial_id = self._crear_pericial()
        self._anade_testigos(pericial_id)
        r = self._post("/api/workspace_pericial_firmar", {"workspace_id": self.ws, "pericial_id": pericial_id})
        self.assertEqual(r["estado"], 422)
        self.assertIn("Genera primero el PDF", r["json"]["error"])

    def test_el_checklist_exige_seis_testigos_o_justificacion(self):
        pericial_id = self._crear_pericial()
        self._anade_testigos(pericial_id, TESTIGOS_SEIS[:2])
        self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        r = self._post("/api/workspace_pericial_firmar", {"workspace_id": self.ws, "pericial_id": pericial_id})
        self.assertEqual(r["estado"], 422)
        self.assertTrue(any("testigos" in f for f in r["json"]["faltan"]))

    def test_firma_completa_pasa_el_expediente_a_firmado(self):
        pericial_id = self._crear_pericial()
        self._anade_testigos(pericial_id)
        self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        r = self._post("/api/workspace_pericial_firmar", {
            "workspace_id": self.ws, "pericial_id": pericial_id,
            "signer_nombre": "Ana Perito", "signer_nif": "12345678Z",
        })
        self.assertEqual(r["estado"], 200, r["json"])
        token = r["json"]["solicitud"]["token"]
        # El envío de la solicitud no cierra el expediente por sí solo: solo
        # firmarla de verdad lo hace.
        antes = self.conn.execute("SELECT estado FROM workspace_periciales WHERE id = ?",
                                   (pericial_id,)).fetchone()
        self.assertEqual(antes["estado"], "Encargado")
        resultado, status = S.sign_pericial_signature_request(
            self.conn, token,
            {"signed_name": "Ana Perito", "signed_nif": "12345678Z", "acceptance_text": "Acepto y firmo"},
            now="2026-08-25 10:00:00",
        )
        self.conn.commit()
        self.assertEqual(status, 200, resultado)
        despues = self.conn.execute("SELECT estado, fecha_emision FROM workspace_periciales WHERE id = ?",
                                     (pericial_id,)).fetchone()
        self.assertEqual(despues["estado"], "Firmado")
        self.assertTrue(despues["fecha_emision"])

    def test_un_expediente_firmado_no_se_puede_editar(self):
        pericial_id = self._crear_pericial()
        self._anade_testigos(pericial_id)
        self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        r = self._post("/api/workspace_pericial_firmar", {
            "workspace_id": self.ws, "pericial_id": pericial_id,
            "signer_nombre": "Ana Perito", "signer_nif": "12345678Z",
        })
        token = r["json"]["solicitud"]["token"]
        S.sign_pericial_signature_request(
            self.conn, token,
            {"signed_name": "Ana Perito", "signed_nif": "12345678Z", "acceptance_text": "Acepto y firmo"},
            now="2026-08-25 10:00:00",
        )
        self.conn.commit()
        r2 = self._post("/api/workspace_pericial", {
            "id": pericial_id, "workspace_id": self.ws, "empresa_id": "emp1",
            "direccion_manual": "Otra dirección cualquiera",
        })
        self.assertEqual(r2["estado"], 409)
        r3 = self._post("/api/workspace_pericial_delete", {"workspace_id": self.ws, "id": pericial_id})
        self.assertEqual(r3["estado"], 409)
        r4 = self._post("/api/workspace_pericial_testigo", {
            "workspace_id": self.ws, "pericial_id": pericial_id, "fuente": "Idealista",
            "precio": "100000", "superficie": "50",
        })
        self.assertEqual(r4["estado"], 409)

    def test_no_se_puede_firmar_dos_veces_la_misma_solicitud(self):
        pericial_id = self._crear_pericial()
        self._anade_testigos(pericial_id)
        self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        r = self._post("/api/workspace_pericial_firmar", {
            "workspace_id": self.ws, "pericial_id": pericial_id,
            "signer_nombre": "Ana Perito", "signer_nif": "12345678Z",
        })
        token = r["json"]["solicitud"]["token"]
        _, status1 = S.sign_pericial_signature_request(
            self.conn, token,
            {"signed_name": "Ana Perito", "signed_nif": "12345678Z", "acceptance_text": "Acepto y firmo"},
            now="2026-08-25 10:00:00",
        )
        self.conn.commit()
        self.assertEqual(status1, 200)
        _, status2 = S.sign_pericial_signature_request(
            self.conn, token, {"signed_name": "x", "signed_nif": "y", "acceptance_text": "acepto"},
            now="2026-08-25 10:05:00",
        )
        self.assertEqual(status2, 409)

    def test_el_pdf_firmado_se_sirve_congelado_no_regenerado(self):
        """Tras firmar, el PDF que se descarga es el mismo fichero que se firmó
        (mismo hash) — no uno recalculado al vuelo con los datos de hoy."""
        pericial_id = self._crear_pericial()
        self._anade_testigos(pericial_id)
        gen1 = self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        doc_key_firmado = gen1["json"]["doc"]["url"]
        r = self._post("/api/workspace_pericial_firmar", {
            "workspace_id": self.ws, "pericial_id": pericial_id,
            "signer_nombre": "Ana Perito", "signer_nif": "12345678Z",
        })
        token = r["json"]["solicitud"]["token"]
        S.sign_pericial_signature_request(
            self.conn, token,
            {"signed_name": "Ana Perito", "signed_nif": "12345678Z", "acceptance_text": "Acepto y firmo"},
            now="2026-08-25 10:00:00",
        )
        self.conn.commit()
        servido = self._get(f"/api/workspace_pericial_pdf?id={pericial_id}&workspace_id={self.ws}")
        self.assertEqual(servido["estado"], 200)
        esperado = Path(S._signature_url_to_local_path(doc_key_firmado)).read_bytes()
        self.assertEqual(servido["cuerpo"], esperado)


class LaCadenaDeEvidenciaEstaAisladaPorExpedienteTests(Base):
    def test_dos_expedientes_no_contaminan_su_cadena(self):
        """El fallo que se encontró (y no se tocó) en `apunta_evento_de_oferta`
        es justo este: una cadena global mezcla eventos de entidades distintas.
        Aquí se comprueba que el patrón replicado sí aísla por `pericial_id`."""
        p1 = self._crear_pericial(denominacion_manual="Piso A")
        p2 = self._crear_pericial(denominacion_manual="Piso B")
        S.apunta_evidencia_de_peritaje(self.conn, p1, None, "foto_visita", "k1", "hashA1", "perito", now="2026-08-25 09:01:00")
        S.apunta_evidencia_de_peritaje(self.conn, p2, None, "foto_visita", "k2", "hashB1", "perito", now="2026-08-25 09:02:00")
        S.apunta_evidencia_de_peritaje(self.conn, p1, None, "foto_visita", "k3", "hashA2", "perito", now="2026-08-25 09:03:00")
        self.conn.commit()
        filas_p1 = self.conn.execute(
            "SELECT prev_hash, integrity_hash FROM workspace_pericial_evidencias WHERE pericial_id = ? ORDER BY created_at",
            (p1,),
        ).fetchall()
        filas_p2 = self.conn.execute(
            "SELECT prev_hash FROM workspace_pericial_evidencias WHERE pericial_id = ?", (p2,),
        ).fetchall()
        # La segunda evidencia de p1 encadena con la primera DE P1, no con la de p2.
        self.assertEqual(filas_p1[1]["prev_hash"], filas_p1[0]["integrity_hash"])
        self.assertNotEqual(filas_p1[1]["prev_hash"], "")
        # p2 solo tiene una evidencia: su prev_hash está vacío (es la primera de su cadena).
        self.assertFalse(filas_p2[0]["prev_hash"])
        v1 = S.verifica_evidencias_del_peritaje(self.conn, p1)
        v2 = S.verifica_evidencias_del_peritaje(self.conn, p2)
        self.assertTrue(v1["ok"])
        self.assertTrue(v2["ok"])
        self.assertEqual(v1["checked"], 2)
        self.assertEqual(v2["checked"], 1)

    def test_manipular_una_fila_se_detecta(self):
        pericial_id = self._crear_pericial()
        S.apunta_evidencia_de_peritaje(self.conn, pericial_id, None, "foto_visita", "k1", "hash1", "perito", now="2026-08-25 09:01:00")
        S.apunta_evidencia_de_peritaje(self.conn, pericial_id, None, "foto_visita", "k2", "hash2", "perito", now="2026-08-25 09:02:00")
        self.conn.commit()
        self.conn.execute(
            "UPDATE workspace_pericial_evidencias SET doc_key = 'k1-manipulado' "
            "WHERE pericial_id = ? AND doc_key = 'k1'", (pericial_id,),
        )
        self.conn.commit()
        verificacion = S.verifica_evidencias_del_peritaje(self.conn, pericial_id)
        self.assertFalse(verificacion["ok"])
        self.assertTrue(verificacion["manipuladas"])


class ElListadoYLaFichaFuncionanTests(Base):
    def test_listado_incluye_denominacion_manual(self):
        self._crear_pericial(denominacion_manual="Piso sin gestionar")
        r = self._get(f"/api/workspace_periciales?workspace_id={self.ws}")
        data = json.loads(r["cuerpo"].decode("utf-8"))
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["inmueble_denominacion"], "Piso sin gestionar")

    def test_ficha_resuelve_la_direccion_de_un_inmueble_enlazado(self):
        # Un expediente enlazado a un inmueble ya gestionado no lleva
        # `direccion_manual` propia — la ficha (no solo el listado) tiene que
        # poder resolver esa dirección para que "Buscar entorno" y "Buscar
        # en nuestro inventario" tengan algo por donde tirar.
        self._ins("inmuebles", dict(
            id="inm-ficha-1", empresa_id="emp1", direccion="Guillermo Carrera Rubio 4",
            m2=106, created_at="2026-01-01", updated_at="2026-01-01",
        ))
        pericial_id = self._crear_pericial(inmueble_id="inm-ficha-1", direccion_manual="", denominacion_manual="")
        r = self._get(f"/api/workspace_pericial?id={pericial_id}&workspace_id={self.ws}")
        data = json.loads(r["cuerpo"].decode("utf-8"))
        self.assertEqual(data["pericial"]["inmueble_denominacion"], "Guillermo Carrera Rubio 4")

    def test_el_listado_trae_lo_que_hace_falta_para_editar_sin_vaciar_nada(self):
        # El botón "Editar" del listado rellena el formulario con esta misma
        # fila (no con la ficha completa) y, al guardar, cualquier campo
        # ausente del payload se manda como cadena vacía y se pisa a NULL. Si
        # el listado no trae dirección/superficies, "editar y guardar" sin
        # tocar nada real vacía el expediente.
        self._crear_pericial(
            direccion_manual="Calle Real 5", referencia_catastral_manual="1234567AB1234A0001XY",
            superficie_calculo_usada="90", motivo_superficie_usada="Medida en visita",
        )
        r = self._get(f"/api/workspace_periciales?workspace_id={self.ws}")
        fila = json.loads(r["cuerpo"].decode("utf-8"))["rows"][0]
        for campo in ("direccion_manual", "referencia_catastral_manual",
                      "superficie_calculo_usada", "motivo_superficie_usada"):
            self.assertTrue(fila.get(campo), f"falta {campo} en el listado")

    def test_ficha_devuelve_checklist_pendiente(self):
        pericial_id = self._crear_pericial()
        r = self._get(f"/api/workspace_pericial?id={pericial_id}&workspace_id={self.ws}")
        data = json.loads(r["cuerpo"].decode("utf-8"))
        self.assertIn("checklist_pendiente", data)
        self.assertTrue(data["checklist_pendiente"])  # sin testigos, no puede firmarse todavía

    def test_ficha_devuelve_el_calculo_ya_parseado(self):
        # La ficha del expediente (que ahora vive en su propia pestaña, no
        # repartida entre un formulario y un modal) necesita leer
        # `justificacion_metodo` sin tener que parsear ella misma el
        # `calculo_json` crudo — eso ya se hacía por duplicado en dos sitios
        # del frontend antes de esta ficha.
        pericial_id = self._crear_pericial(justificacion_metodo="Motivo de prueba")
        r = self._get(f"/api/workspace_pericial?id={pericial_id}&workspace_id={self.ws}")
        data = json.loads(r["cuerpo"].decode("utf-8"))
        self.assertIn("calculo", data)
        self.assertIsInstance(data["calculo"], dict)
        self.assertEqual(data["calculo"].get("conclusion", {}).get("justificacion_metodo"), "Motivo de prueba")


class LasFotosYLaDocumentacionAparecenEnElInformeTests(Base):
    """Ambas cuelgan de `/api/workspace_pericial_evidencia` (el mismo endpoint
    con hash-chain), pero se tratan distinto en el PDF: la foto se embebe,
    la documentación (ficha catastral, nota simple...) solo se lista por
    nombre — es texto de varias páginas, no una imagen."""

    @staticmethod
    def _png_1x1():
        from PIL import Image
        buf = BytesIO()
        Image.new("RGB", (2, 2), color=(10, 20, 30)).save(buf, format="PNG")
        return buf.getvalue()

    def test_subir_foto_y_documento_devuelve_id_y_hash(self):
        pericial_id = self._crear_pericial()
        with patch.object(S, "s3_get_object_bytes", return_value=(self._png_1x1(), None)):
            r = self._post("/api/workspace_pericial_evidencia", {
                "workspace_id": self.ws, "pericial_id": pericial_id,
                "doc_key": "periciales/foto1.png", "tipo": "foto_visita",
            })
        self.assertEqual(r["estado"], 200, r["json"])
        self.assertTrue(r["json"]["hash_archivo"])
        with patch.object(S, "s3_get_object_bytes", return_value=(b"%PDF-1.4 contenido falso", None)):
            r = self._post("/api/workspace_pericial_evidencia", {
                "workspace_id": self.ws, "pericial_id": pericial_id,
                "doc_key": "periciales/nota_simple.pdf", "tipo": "documento_aportado",
                "nombre": "Nota simple registral",
            })
        self.assertEqual(r["estado"], 200, r["json"])

    def test_la_ficha_devuelve_nombre_y_doc_url_de_cada_evidencia(self):
        pericial_id = self._crear_pericial()
        with patch.object(S, "s3_get_object_bytes", return_value=(self._png_1x1(), None)):
            self._post("/api/workspace_pericial_evidencia", {
                "workspace_id": self.ws, "pericial_id": pericial_id,
                "doc_key": "periciales/foto1.png", "tipo": "documento_aportado",
                "nombre": "Ficha catastral",
            })
        with patch.object(S, "s3_config", return_value=("bucket-test", "eu-west-1")):
            r = self._get(f"/api/workspace_pericial?id={pericial_id}&workspace_id={self.ws}")
        data = json.loads(r["cuerpo"].decode("utf-8"))
        ev = data["evidencias"][0]
        self.assertEqual(ev["nombre"], "Ficha catastral")
        self.assertIn("foto1.png", ev["doc_url"])

    def test_un_expediente_firmado_no_admite_nueva_evidencia(self):
        pericial_id = self._crear_pericial()
        self._anade_testigos(pericial_id)
        self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        r = self._post("/api/workspace_pericial_firmar", {
            "workspace_id": self.ws, "pericial_id": pericial_id,
            "signer_nombre": "Ana Perito", "signer_nif": "12345678Z",
        })
        token = r["json"]["solicitud"]["token"]
        _resultado, status = S.sign_pericial_signature_request(
            self.conn, token,
            {"signed_name": "Ana Perito", "signed_nif": "12345678Z", "acceptance_text": "Acepto y firmo"},
            now="2026-08-25 10:00:00",
        )
        self.conn.commit()
        self.assertEqual(status, 200)
        with patch.object(S, "s3_get_object_bytes", return_value=(self._png_1x1(), None)):
            r = self._post("/api/workspace_pericial_evidencia", {
                "workspace_id": self.ws, "pericial_id": pericial_id,
                "doc_key": "periciales/tarde.png", "tipo": "foto_visita",
            })
        self.assertEqual(r["estado"], 409, r["json"])

    def test_la_foto_aparece_en_el_anexo_y_el_documento_se_lista_por_nombre(self):
        pericial_id = self._crear_pericial()
        self._anade_testigos(pericial_id)
        with patch.object(S, "s3_get_object_bytes", return_value=(self._png_1x1(), None)):
            self._post("/api/workspace_pericial_evidencia", {
                "workspace_id": self.ws, "pericial_id": pericial_id,
                "doc_key": "periciales/salon.png", "tipo": "foto_visita",
                "nombre": "Salón, orientación sur",
            })
            self._post("/api/workspace_pericial_evidencia", {
                "workspace_id": self.ws, "pericial_id": pericial_id,
                "doc_key": "periciales/catastro.pdf", "tipo": "documento_aportado",
                "nombre": "Ficha catastral",
            })
            r = self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        self.assertEqual(r["estado"], 200, r["json"])
        with patch.object(S, "s3_get_object_bytes", return_value=(self._png_1x1(), None)):
            servido = self._get(f"/api/workspace_pericial_pdf?id={pericial_id}&workspace_id={self.ws}")
        from pypdf import PdfReader
        texto = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(servido["cuerpo"])).pages)
        self.assertIn("Documentación aportada", texto)
        self.assertIn("Ficha catastral", texto)
        self.assertIn("Anexo fotográfico", texto)
        self.assertIn("Salón, orientación sur", texto)
        # La cascada de conclusión usaba la clave "items" en vez de "steps"
        # (la que de verdad lee `_cascada` en branded_pdf_vector.py) y la
        # sección se quedaba muda: sin valor de tasación, lo más importante
        # del informe. Este assert es justo el que lo habría detectado.
        self.assertIn("Valor de tasación", texto)
        self.assertIn("Valor unitario homogeneizado", texto)


class _RespuestaHttpFalsa:
    def __init__(self, datos):
        self._datos = json.dumps(datos).encode("utf-8")

    def read(self):
        return self._datos

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


_urlopen_real = urllib.request.urlopen


def _urlopen_falso_para_entorno(req, timeout=None):
    # `S.urllib.request` es el mismo módulo que este test usa para hablar con
    # su propio servidor local: lo que no sea Nominatim/Overpass pasa tal
    # cual al urlopen real, o el _post/_get del propio harness se rompería.
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if "nominatim.openstreetmap.org/reverse" in url:
        return _RespuestaHttpFalsa({
            "address": {"suburb": "El Palo", "city_district": "Distrito Este", "city": "Málaga"},
        })
    if "nominatim.openstreetmap.org/search" in url:
        return _RespuestaHttpFalsa([
            {"lat": "36.7213", "lon": "-4.4214", "display_name": "Calle Ejemplo 1, Málaga"},
        ])
    if "photon.komoot.io" in url:
        return _RespuestaHttpFalsa({"features": []})
    if "geocode.arcgis.com" in url:
        return _RespuestaHttpFalsa({"candidates": []})
    if "overpass-api.de" in url:
        return _RespuestaHttpFalsa({
            "elements": [
                {"tags": {"amenity": "school"}}, {"tags": {"amenity": "school"}},
                {"tags": {"amenity": "pharmacy"}},
                {"tags": {"public_transport": "stop_position"}},
                {"tags": {"public_transport": "stop_position"}}, {"tags": {"public_transport": "stop_position"}},
            ],
        })
    return _urlopen_real(req, timeout=timeout)


class LaDescripcionDelEntornoSeBuscaPorDireccionTests(Base):
    """Barrio/distrito por reverse-geocoding + equipamientos cercanos por
    Overpass, con la fuente citada en el propio texto. Un fallo de red en
    cualquiera de las dos partes no debe tirar la petición entera si al
    menos se pudo geocodificar — media respuesta es mejor que un 502."""

    def test_arma_el_parrafo_con_barrio_distrito_y_equipamientos(self):
        with patch.object(S.urllib.request, "urlopen", _urlopen_falso_para_entorno):
            r = self._post("/api/workspace_pericial_entorno", {
                "workspace_id": self.ws, "direccion": "Calle Ejemplo 1, Málaga",
            })
        self.assertEqual(r["estado"], 200, r["json"])
        texto = r["json"]["texto"]
        self.assertIn("El Palo", texto)
        self.assertIn("Distrito Este", texto)
        self.assertIn("Málaga", texto)
        self.assertIn("2 colegios", texto)
        self.assertIn("1 farmacia", texto)
        self.assertIn("3 paradas de transporte público", texto)
        self.assertIn("OpenStreetMap", texto)

    def test_si_overpass_falla_sigue_dando_la_ubicacion(self):
        def urlopen_sin_overpass(req, timeout=None):
            if "overpass-api.de" in req.full_url:
                raise OSError("sin red")
            return _urlopen_falso_para_entorno(req, timeout=timeout)

        with patch.object(S.urllib.request, "urlopen", urlopen_sin_overpass):
            r = self._post("/api/workspace_pericial_entorno", {
                "workspace_id": self.ws, "direccion": "Calle Ejemplo 1, Málaga",
            })
        self.assertEqual(r["estado"], 200, r["json"])
        self.assertIn("El Palo", r["json"]["texto"])

    def test_no_geocodificable_da_error_claro_no_500(self):
        def urlopen_sin_resultados(req, timeout=None):
            if "nominatim.openstreetmap.org/search" in req.full_url:
                return _RespuestaHttpFalsa([])
            return _urlopen_falso_para_entorno(req, timeout=timeout)

        with patch.object(S.urllib.request, "urlopen", urlopen_sin_resultados):
            r = self._post("/api/workspace_pericial_entorno", {
                "workspace_id": self.ws, "direccion": "Dirección que no existe en ningún sitio",
            })
        self.assertEqual(r["estado"], 400, r["json"])

    def test_el_texto_se_guarda_editable_en_el_expediente_y_sale_en_el_pdf(self):
        pericial_id = self._crear_pericial(
            descripcion_entorno="Zona residencial tranquila, a pie de playa. [Texto editado a mano.]"
        )
        self._anade_testigos(pericial_id)
        r = self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        self.assertEqual(r["estado"], 200, r["json"])
        servido = self._get(f"/api/workspace_pericial_pdf?id={pericial_id}&workspace_id={self.ws}")
        from pypdf import PdfReader
        texto = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(servido["cuerpo"])).pages)
        self.assertIn("Descripción del entorno", texto)
        self.assertIn("Texto editado a mano", texto)


class LaConclusionSiempreExplicaElValorTests(Base):
    """Un informe pericial no debería salir nunca con la cifra final sin
    explicar de dónde sale. Si el perito no ha escrito su propia
    justificación, el PDF lleva un borrador automático — no una conclusión
    muda."""

    def test_sin_justificacion_escrita_el_pdf_trae_una_automatica(self):
        pericial_id = self._crear_pericial()
        self._anade_testigos(pericial_id)  # TESTIGOS_SEIS: 6 testigos
        r = self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        self.assertEqual(r["estado"], 200, r["json"])
        servido = self._get(f"/api/workspace_pericial_pdf?id={pericial_id}&workspace_id={self.ws}")
        from pypdf import PdfReader
        texto = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(servido["cuerpo"])).pages)
        self.assertIn("comparación con 6 testigos de mercado", texto)

    def test_la_justificacion_escrita_a_mano_pisa_a_la_automatica(self):
        pericial_id = self._crear_pericial()
        self._anade_testigos(pericial_id)
        self._post("/api/workspace_pericial", {
            "workspace_id": self.ws, "id": pericial_id, "empresa_id": "emp1",
            "justificacion_metodo": "Texto propio del perito, no el redactado por el sistema.",
        })
        r = self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        self.assertEqual(r["estado"], 200, r["json"])
        servido = self._get(f"/api/workspace_pericial_pdf?id={pericial_id}&workspace_id={self.ws}")
        from pypdf import PdfReader
        texto = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(servido["cuerpo"])).pages)
        self.assertIn("Texto propio del perito", texto)
        self.assertNotIn("comparación con 6 testigos de mercado", texto)


class LosTestigosPropiosSeBuscanEnElInventarioTests(Base):
    """Fase 2: comparables del propio inventario en vez de pegar enlaces de
    portales a mano. El geocode mock (`_urlopen_falso_para_entorno`) sitúa
    la dirección buscada en (36.7213, -4.4214) — Málaga capital."""

    def _seed_operacion(self, oid, *, direccion, precio_escritura, lat=None, lon=None,
                         codigo_postal=None, tipo_operacion="venta", m2=90):
        base = dict(created_at="2026-01-01", updated_at="2026-01-01")
        self._ins("inmuebles", dict(
            id=f"inm-{oid}", empresa_id="emp1", direccion=direccion, m2=m2,
            lat=lat, lon=lon, codigo_postal=codigo_postal, **base,
        ))
        self._ins("operaciones_inmobiliarias", dict(
            id=oid, empresa_id="emp1", tipo_operacion=tipo_operacion, inmueble_id=f"inm-{oid}",
            direccion=direccion, precio_escritura=precio_escritura, fecha_escritura="2026-06-01", **base,
        ))

    def test_encuentra_ventas_cercanas_y_descarta_las_lejanas(self):
        self._seed_operacion("op-cerca", direccion="Calle Vecina 3, Málaga",
                              precio_escritura=180000, lat=36.7220, lon=-4.4205)
        self._seed_operacion("op-lejos", direccion="Calle Otra Ciudad 1, Madrid",
                              precio_escritura=300000, lat=40.4168, lon=-3.7038)
        with patch.object(S.urllib.request, "urlopen", _urlopen_falso_para_entorno):
            r = self._post("/api/workspace_pericial_testigos_sugeridos", {
                "workspace_id": self.ws, "direccion": "Calle Ejemplo 1, Málaga",
            })
        self.assertEqual(r["estado"], 200, r["json"])
        direcciones = [t["direccion"] for t in r["json"]["testigos"]]
        self.assertIn("Calle Vecina 3, Málaga", direcciones)
        self.assertNotIn("Calle Otra Ciudad 1, Madrid", direcciones)

    def test_sin_coordenadas_cae_a_mismo_codigo_postal(self):
        self._seed_operacion("op-cp", direccion="Calle Sin Coordenadas 9, 29010 Málaga",
                              precio_escritura=175000, codigo_postal="29010")
        with patch.object(S.urllib.request, "urlopen", _urlopen_falso_para_entorno):
            r = self._post("/api/workspace_pericial_testigos_sugeridos", {
                "workspace_id": self.ws, "direccion": "Calle Ejemplo 1, 29010 Málaga",
            })
        self.assertEqual(r["estado"], 200, r["json"])
        self.assertEqual(len(r["json"]["testigos"]), 1)
        self.assertTrue(r["json"]["testigos"][0]["mismo_codigo_postal"])

    def test_sin_coordenadas_y_sin_codigo_postal_coincidente_no_devuelve_nada(self):
        # El bug real: cuando ni el candidato ni el objetivo tienen coordenadas,
        # "caer al código postal" significaba en el código "no filtrar nada" —
        # se colaba toda la cartera cerrada del workspace, viniera de donde
        # viniera. Probado en vivo el 2026-08-26 con un inmueble real: una
        # búsqueda en Torremolinos devolvía ventas de Málaga capital.
        self._seed_operacion("op-otra-ciudad", direccion="Calle Lejana 1, Madrid",
                              precio_escritura=300000, codigo_postal="28001")
        with patch.object(S.urllib.request, "urlopen", _urlopen_falso_para_entorno):
            r = self._post("/api/workspace_pericial_testigos_sugeridos", {
                "workspace_id": self.ws, "direccion": "Calle Ejemplo 1, 29010 Málaga",
            })
        self.assertEqual(r["estado"], 200, r["json"])
        self.assertEqual(r["json"]["testigos"], [])

    def test_ignora_alquileres_y_operaciones_sin_escriturar(self):
        self._seed_operacion("op-alquiler", direccion="Calle Vecina 5, Málaga",
                              precio_escritura=900, lat=36.7214, lon=-4.4213, tipo_operacion="alquiler")
        self._seed_operacion("op-sin-cerrar", direccion="Calle Vecina 7, Málaga",
                              precio_escritura=0, lat=36.7216, lon=-4.4211)
        with patch.object(S.urllib.request, "urlopen", _urlopen_falso_para_entorno):
            r = self._post("/api/workspace_pericial_testigos_sugeridos", {
                "workspace_id": self.ws, "direccion": "Calle Ejemplo 1, Málaga",
            })
        self.assertEqual(r["estado"], 200, r["json"])
        self.assertEqual(r["json"]["testigos"], [])

    def test_un_candidato_se_puede_anadir_como_testigo_real(self):
        self._seed_operacion("op-real", direccion="Calle Vecina 3, Málaga",
                              precio_escritura=180000, lat=36.7220, lon=-4.4205, m2=88)
        with patch.object(S.urllib.request, "urlopen", _urlopen_falso_para_entorno):
            r = self._post("/api/workspace_pericial_testigos_sugeridos", {
                "workspace_id": self.ws, "direccion": "Calle Ejemplo 1, Málaga",
            })
        candidato = r["json"]["testigos"][0]
        pericial_id = self._crear_pericial()
        alta = self._post("/api/workspace_pericial_testigo", {
            "workspace_id": self.ws, "pericial_id": pericial_id,
            "fuente": f"CRM propio — {candidato['direccion']}",
            "fecha_captura": candidato["fecha"], "precio": candidato["precio"],
            "superficie": candidato["superficie"],
        })
        self.assertEqual(alta["estado"], 200, alta["json"])
        detalle = self._get(f"/api/workspace_pericial?id={pericial_id}&workspace_id={self.ws}")
        testigo_guardado = json.loads(detalle["cuerpo"].decode("utf-8"))["testigos"][0]
        self.assertEqual(testigo_guardado["precio"], 180000)
        self.assertTrue(testigo_guardado["valor_homogeneizado"])


class ElCalculoEsPuroYNoNecesitaServidorTests(unittest.TestCase):
    def test_homogenizacion_sin_coeficientes_es_precio_entre_superficie(self):
        r = S.compute_homogenizacion_testigo({"precio": 200000, "superficie": 100}, {})
        self.assertEqual(r["valor_unitario"], 2000.0)
        self.assertEqual(r["valor_homogeneizado_unitario"], 2000.0)

    def test_factor_invalido_se_ignora_no_invierte_el_valor(self):
        r = S.compute_homogenizacion_testigo({"precio": 200000, "superficie": 100},
                                              {"x": {"factor": -1, "motivo": "dato erróneo"}})
        self.assertGreater(r["valor_homogeneizado_unitario"], 0)

    def test_comparacion_calcula_media_mediana_y_valor_total(self):
        testigos = [{"valor_homogeneizado_unitario": v} for v in (2000, 2100, 1900, 2050)]
        r = S.compute_comparacion_valoracion(testigos, 90)
        self.assertEqual(r["n_muestra"], 4)
        self.assertAlmostEqual(r["media"], 2012.5)
        self.assertAlmostEqual(r["valor_total"], 2012.5 * 90, places=1)

    def test_sin_testigos_no_revienta(self):
        r = S.compute_comparacion_valoracion([], 90)
        self.assertEqual(r["valor_total"], 0.0)

    def test_checklist_completo_no_deja_nada_pendiente(self):
        pericial = {
            "perito_usuario_id": "u1", "colegiado_numero": "3079", "finalidad": "Judicial",
            "fecha_valoracion": "2026-08-10", "metodo": "comparacion", "valor_final": 190000,
        }
        testigos = [{"estado": "activo"} for _ in range(6)]
        faltan = S.checklist_une197001_pericial(pericial, testigos, {"ok": True})
        self.assertEqual(faltan, [])

    def test_checklist_exige_declaracion_de_imparcialidad_fija(self):
        self.assertIn("335.2", S.PERICIAL_DECLARACION_IMPARCIALIDAD)
        self.assertIn("juramento", S.PERICIAL_DECLARACION_IMPARCIALIDAD.lower())

    def test_justificacion_automatica_sin_testigos_lo_dice_claro(self):
        texto = S.build_justificacion_metodo_automatica(0, {})
        self.assertIn("pendiente de determinar", texto)

    def test_justificacion_automatica_con_un_testigo_no_promedia(self):
        texto = S.build_justificacion_metodo_automatica(1, {"media": 2000, "mediana": 2000, "desviacion": 0})
        self.assertIn("único testigo", texto)
        self.assertIn("sin promediar", texto)

    def test_justificacion_automatica_avisa_de_dispersion_alta(self):
        texto = S.build_justificacion_metodo_automatica(5, {"media": 2000, "mediana": 1950, "desviacion": 500})
        self.assertIn("dispersión", texto.lower())
        self.assertIn("relativamente alta", texto)

    def test_justificacion_automatica_con_pocos_testigos_avisa_del_minimo(self):
        texto = S.build_justificacion_metodo_automatica(2, {"media": 2000, "mediana": 2000, "desviacion": 50})
        self.assertIn("ECO/805/2003", texto)

    def test_justificacion_automatica_con_muestra_suficiente_no_avisa_del_minimo(self):
        texto = S.build_justificacion_metodo_automatica(6, {"media": 2000, "mediana": 2000, "desviacion": 50})
        self.assertNotIn("ECO/805/2003", texto)


class LaConsultaOverpassPideEtiquetasTests(Base):
    """Bug real encontrado auditando por qué la descripción del entorno salía
    pobre: la consulta usaba `out ids;`, que NO incluye las etiquetas de cada
    elemento — así que el conteo de equipamientos daba siempre cero contra el
    Overpass real (el mock de otros tests no lo detectaba porque devuelve
    tags directamente, sin mirar qué se pidió)."""

    def test_la_consulta_pide_tags_no_solo_ids(self):
        capturado = {}

        def urlopen_que_inspecciona(req, timeout=None):
            # El cuerpo va como `data=<consulta urlencoded>` (POST form).
            cuerpo = S.urllib.parse.parse_qs(req.data.decode("utf-8"))
            capturado["consulta"] = cuerpo["data"][0]
            return _RespuestaHttpFalsa({"elements": []})

        with patch.object(S.urllib.request, "urlopen", urlopen_que_inspecciona):
            S._fetch_overpass_pois(36.7213, -4.4214, radio_m=400)
        self.assertIn("out tags;", capturado["consulta"])
        self.assertNotIn("out ids;", capturado["consulta"])


class LaFichaCatastralSeBuscaYSeAdjuntaTests(Base):
    """Un solo botón hace las dos cosas que pedía el usuario: busca la
    referencia catastral real (reutilizando la infraestructura de inmuebles,
    no una copia) y adjunta la ficha generada al expediente pericial."""

    RESUMEN_FALSO = {
        "referencia_catastral": "1234567AB1234A0001XY",
        "localizacion": "CL EJEMPLO 1",
        "uso": "Residencial",
        "superficie_construida_m2": 90,
        "anio_construccion": 1995,
        "source_url": "https://sede.catastro.gob.es/ejemplo",
    }

    def _crear_inmueble_y_pericial(self, *, con_referencia=False):
        self._ins("inmuebles", dict(
            id="inm1", empresa_id="emp1", direccion="Calle Ejemplo 1", m2=90,
            poblacion="Málaga", provincia="Málaga", codigo_postal="29003",
            referencia_catastral="1234567AB1234A0001XY" if con_referencia else "",
            created_at=AHORA, updated_at=AHORA,
        ))
        return self._crear_pericial(inmueble_id="inm1", direccion_manual="", denominacion_manual="")

    def test_sin_inmueble_enlazado_da_error_claro(self):
        pericial_id = self._crear_pericial()
        r = self._post("/api/workspace_pericial_catastro_sync", {"workspace_id": self.ws, "pericial_id": pericial_id})
        self.assertEqual(r["estado"], 400, r["json"])
        self.assertIn("inmueble", r["json"]["error"].lower())

    def test_busca_la_referencia_y_la_deja_en_el_inmueble(self):
        pericial_id = self._crear_inmueble_y_pericial(con_referencia=False)
        with patch.object(S, "lookup_catastro_reference_by_address",
                           return_value={"match_unique": True, "referencia_catastral": "1234567AB1234A0001XY"}), \
             patch.object(S, "fetch_catastro_public_summary", return_value=(self.RESUMEN_FALSO, "<html></html>")):
            r = self._post("/api/workspace_pericial_catastro_sync", {"workspace_id": self.ws, "pericial_id": pericial_id})
        self.assertEqual(r["estado"], 200, r["json"])
        self.assertEqual(r["json"]["referencia_catastral"], "1234567AB1234A0001XY")
        fila = self.conn.execute("SELECT referencia_catastral FROM inmuebles WHERE id = 'inm1'").fetchone()
        self.assertEqual(fila["referencia_catastral"], "1234567AB1234A0001XY")

    def test_la_ficha_catastral_queda_como_documento_del_expediente(self):
        pericial_id = self._crear_inmueble_y_pericial(con_referencia=True)
        with patch.object(S, "fetch_catastro_public_summary", return_value=(self.RESUMEN_FALSO, "<html></html>")):
            r = self._post("/api/workspace_pericial_catastro_sync", {"workspace_id": self.ws, "pericial_id": pericial_id})
        self.assertEqual(r["estado"], 200, r["json"])
        fila = self.conn.execute(
            "SELECT tipo, nombre FROM workspace_pericial_docs WHERE pericial_id = ?", (pericial_id,),
        ).fetchone()
        self.assertIsNotNone(fila)
        self.assertEqual(fila["tipo"], "ficha_catastro")
        # También debe verse en la ficha del expediente (no solo en la tabla).
        detalle = self._get(f"/api/workspace_pericial?id={pericial_id}&workspace_id={self.ws}")
        docs = json.loads(detalle["cuerpo"].decode("utf-8"))["docs"]
        self.assertTrue(any(d["tipo"] == "ficha_catastro" for d in docs))

    def test_la_ficha_catastral_aparece_en_documentos_del_pdf(self):
        pericial_id = self._crear_inmueble_y_pericial(con_referencia=True)
        with patch.object(S, "fetch_catastro_public_summary", return_value=(self.RESUMEN_FALSO, "<html></html>")):
            self._post("/api/workspace_pericial_catastro_sync", {"workspace_id": self.ws, "pericial_id": pericial_id})
        self._anade_testigos(pericial_id)
        r = self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        self.assertEqual(r["estado"], 200, r["json"])
        servido = self._get(f"/api/workspace_pericial_pdf?id={pericial_id}&workspace_id={self.ws}")
        from pypdf import PdfReader
        texto = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(servido["cuerpo"])).pages)
        self.assertIn("Ficha catastral", texto)
        # La referencia real, ya sincronizada en el inmueble, sale en el PDF.
        self.assertIn("1234567AB1234A0001XY", texto)


class ElPlanoDeSituacionApareceEnElPdfTests(Base):
    """Mismo generador de mapas que ya usan los presupuestos de fincas
    (`build_mapa_estatico`) — aquí se comprueba que se llama con las
    coordenadas correctas y que el bloque aparece en el PDF, sin depender de
    la red real de teselas de OpenStreetMap."""

    @staticmethod
    def _mapa_falso():
        from PIL import Image
        return Image.new("RGB", (900, 380), (200, 200, 200))

    def test_con_coordenadas_del_inmueble_se_pinta_el_plano(self):
        self._ins("inmuebles", dict(
            id="inm1", empresa_id="emp1", direccion="Calle Ejemplo 1", m2=90,
            lat=36.7213, lon=-4.4214, created_at=AHORA, updated_at=AHORA,
        ))
        pericial_id = self._crear_pericial(inmueble_id="inm1", direccion_manual="", denominacion_manual="")
        self._anade_testigos(pericial_id)
        with patch.object(S, "build_mapa_estatico", return_value=self._mapa_falso()) as mapa_mock:
            r = self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        self.assertEqual(r["estado"], 200, r["json"])
        mapa_mock.assert_called_once()
        lat_llamado, lon_llamado = mapa_mock.call_args[0][:2]
        self.assertAlmostEqual(lat_llamado, 36.7213, places=3)
        self.assertAlmostEqual(lon_llamado, -4.4214, places=3)
        servido = self._get(f"/api/workspace_pericial_pdf?id={pericial_id}&workspace_id={self.ws}")
        from pypdf import PdfReader
        texto = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(servido["cuerpo"])).pages)
        self.assertIn("Plano de situación", texto)

    def test_sin_coordenadas_ni_geocodificable_no_rompe_el_pdf(self):
        # Hay dirección (para forzar el intento de geocodificar) pero la
        # geocodificación falla: el informe se sigue generando sin el plano.
        pericial_id = self._crear_pericial(direccion_manual="Dirección que no existe en ningún sitio")
        self._anade_testigos(pericial_id)
        with patch.object(S, "fetch_geocode_coordinates", return_value={"ok": False}), \
             patch.object(S, "build_mapa_estatico") as mapa_mock:
            r = self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        self.assertEqual(r["estado"], 200, r["json"])
        mapa_mock.assert_not_called()


class ElTestigoSeEditaSeDescartaYSeHomogeneizaTests(Base):
    """Un testigo nunca se borra de verdad — solo cambia de estado — y la
    homogeneización ahora puede llevar coeficientes reales, no solo
    precio÷m². El backend ya lo soportaba todo; esto prueba que el POST que
    usa la ficha (id para editar, estado/motivo_descarte para descartar,
    coeficientes) se comporta como se espera."""

    def _crea_testigo(self, pericial_id, **overrides):
        payload = dict(
            workspace_id=self.ws, pericial_id=pericial_id, fuente="Idealista",
            fecha_captura="2026-07-01", precio=200000, superficie=100,
        )
        payload.update(overrides)
        r = self._post("/api/workspace_pericial_testigo", payload)
        self.assertEqual(r["estado"], 200, r["json"])
        return r["json"]["id"]

    def test_editar_con_id_actualiza_no_duplica(self):
        pericial_id = self._crear_pericial()
        testigo_id = self._crea_testigo(pericial_id, precio=200000, superficie=100)
        self._post("/api/workspace_pericial_testigo", {
            "id": testigo_id, "workspace_id": self.ws, "pericial_id": pericial_id,
            "fuente": "Idealista (corregido)", "fecha_captura": "2026-07-01",
            "precio": 210000, "superficie": 100,
        })
        filas = self.conn.execute(
            "SELECT COUNT(*) AS n FROM workspace_pericial_testigos WHERE pericial_id = ?", (pericial_id,),
        ).fetchone()
        self.assertEqual(filas["n"], 1)
        fila = self.conn.execute(
            "SELECT fuente, precio FROM workspace_pericial_testigos WHERE id = ?", (testigo_id,),
        ).fetchone()
        self.assertEqual(fila["fuente"], "Idealista (corregido)")
        self.assertEqual(fila["precio"], 210000)

    def test_descartar_guarda_motivo_y_sale_del_calculo(self):
        pericial_id = self._crear_pericial()
        testigo_id = self._crea_testigo(pericial_id)
        self._post("/api/workspace_pericial_testigo", {
            "id": testigo_id, "workspace_id": self.ws, "pericial_id": pericial_id,
            "estado": "descartado", "motivo_descarte": "Superficie no comparable",
            "fuente": "Idealista", "fecha_captura": "2026-07-01", "precio": 200000, "superficie": 100,
        })
        fila = self.conn.execute(
            "SELECT estado, motivo_descarte FROM workspace_pericial_testigos WHERE id = ?", (testigo_id,),
        ).fetchone()
        self.assertEqual(fila["estado"], "descartado")
        self.assertEqual(fila["motivo_descarte"], "Superficie no comparable")
        detalle = self._get(f"/api/workspace_pericial?id={pericial_id}&workspace_id={self.ws}")
        cuerpo = json.loads(detalle["cuerpo"].decode("utf-8"))
        # Sin testigos activos, la muestra recalculada queda vacía (el
        # `valor_final` ya fijado no se pisa a la baja — es deliberado, para
        # que un valor manual no desaparezca solo por tocar un testigo).
        estadisticos = cuerpo["calculo"].get("comparacion", {}).get("estadisticos", {})
        self.assertEqual(estadisticos.get("n_muestra"), 0)
        self.assertIn("El método de comparación exige al menos", " ".join(cuerpo["checklist_pendiente"]))

    def test_descartado_aparece_en_el_pdf_como_descartado(self):
        pericial_id = self._crear_pericial()
        self._anade_testigos(pericial_id)
        testigo_a_descartar_id = self._crea_testigo(pericial_id, fuente="Notaría dudosa", precio=500000, superficie=100)
        self._post("/api/workspace_pericial_testigo", {
            "id": testigo_a_descartar_id, "workspace_id": self.ws, "pericial_id": pericial_id,
            "estado": "descartado", "motivo_descarte": "Precio muy alejado del resto de la muestra",
            "fuente": "Notaría dudosa", "fecha_captura": "2026-07-01", "precio": 500000, "superficie": 100,
        })
        r = self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        self.assertEqual(r["estado"], 200, r["json"])
        servido = self._get(f"/api/workspace_pericial_pdf?id={pericial_id}&workspace_id={self.ws}")
        from pypdf import PdfReader
        texto = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(servido["cuerpo"])).pages)
        self.assertIn("Testigos descartados", texto)
        self.assertIn("Notaría dudosa", texto)
        self.assertIn("Precio muy alejado del resto de la muestra", texto)

    def test_coeficiente_no_neutro_se_ve_en_el_pdf(self):
        pericial_id = self._crear_pericial()
        self._anade_testigos(pericial_id)
        self._post("/api/workspace_pericial_testigo", {
            "workspace_id": self.ws, "pericial_id": pericial_id,
            "fuente": "Idealista (planta baja)", "fecha_captura": "2026-07-01",
            "precio": 200000, "superficie": 100,
            "coeficientes": json.dumps({
                "planta": {"factor": 1.08, "motivo": "testigo en planta baja, sujeto en 2ª"},
            }),
        })
        r = self._post("/api/workspace_pericial_pdf", {"workspace_id": self.ws, "id": pericial_id})
        self.assertEqual(r["estado"], 200, r["json"])
        servido = self._get(f"/api/workspace_pericial_pdf?id={pericial_id}&workspace_id={self.ws}")
        from pypdf import PdfReader
        texto = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(servido["cuerpo"])).pages)
        self.assertIn("Ajustes de homogeneización aplicados", texto)
        self.assertIn("testigo en planta baja, sujeto en 2ª", texto)


if __name__ == "__main__":
    unittest.main()
