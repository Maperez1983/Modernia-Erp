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

    def test_ficha_devuelve_checklist_pendiente(self):
        pericial_id = self._crear_pericial()
        r = self._get(f"/api/workspace_pericial?id={pericial_id}&workspace_id={self.ws}")
        data = json.loads(r["cuerpo"].decode("utf-8"))
        self.assertIn("checklist_pendiente", data)
        self.assertTrue(data["checklist_pendiente"])  # sin testigos, no puede firmarse todavía


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


if __name__ == "__main__":
    unittest.main()
