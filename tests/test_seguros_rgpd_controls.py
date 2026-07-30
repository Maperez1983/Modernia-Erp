"""Regresión de los controles RGPD del módulo de seguros.

Cubre los puntos que la auditoría (2026-07-29/30) dejó abiertos y luego se
arreglaron:

- El OCR enviaba la póliza completa a OpenAI y Google Document AI con la sola
  condición de que existiera una API key, sin control ni registro.
- `ocr_jobs` conservaba el PDF en base64 y la transcripción íntegra para siempre.
- La evidencia de entrega del IPID era retrodatable y con autor suplantable.
- El consentimiento se sobrescribía sin dejar el valor anterior.
- Los catálogos compartidos entre empresas los podía borrar cualquiera.
- Cualquier binario no reconocido se etiquetaba como PDF y se enviaba fuera.
"""

import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from web import server as S

NOW = "2026-07-29 10:00:00"
PASSWORD = "Secreto123!"


def _cols(conn, table):
    return [row[1] for row in conn.execute(f"pragma table_info({table})")]


def _insert(conn, table, data):
    usable = {k: v for k, v in data.items() if k in _cols(conn, table)}
    conn.execute(
        f"INSERT INTO {table} ({','.join(usable)}) VALUES ({','.join('?' * len(usable))})",
        list(usable.values()),
    )


class SegurosOcrExternalGateTests(unittest.TestCase):
    """El envío a terceros tiene tres niveles de control y queda auditado."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "gate.sqlite"
        S.ensure_tables(db_path)
        self.conn = S.open_sqlite_conn(str(db_path), with_row_factory=True)
        _insert(self.conn, "empresas", {"id": "e1", "nombre": "Con IA", "activo": 1,
                                        "created_at": NOW, "updated_at": NOW})
        _insert(self.conn, "empresas", {"id": "e2", "nombre": "Sin IA", "activo": 1,
                                        "seguros_ocr_externo": 0,
                                        "created_at": NOW, "updated_at": NOW})
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_por_defecto_se_permite_para_no_degradar_la_extraccion(self):
        allowed, motivo = S.seguros_ocr_external_allowed({}, self.conn, "e1")
        self.assertTrue(allowed)
        self.assertEqual(motivo, "")

    def test_la_empresa_puede_quedar_excluida(self):
        allowed, motivo = S.seguros_ocr_external_allowed({}, self.conn, "e2")
        self.assertFalse(allowed)
        self.assertEqual(motivo, "envio_externo_desactivado_para_la_empresa")

    def test_la_peticion_puede_rechazar_el_envio(self):
        allowed, motivo = S.seguros_ocr_external_allowed({"allow_external": False}, self.conn, "e1")
        self.assertFalse(allowed)
        self.assertEqual(motivo, "envio_externo_rechazado_en_peticion")

    def test_el_flag_de_instalacion_lo_corta_todo(self):
        original = S.SEGUROS_OCR_EXTERNAL_ENABLED
        S.SEGUROS_OCR_EXTERNAL_ENABLED = False
        try:
            allowed, motivo = S.seguros_ocr_external_allowed({}, self.conn, "e1")
        finally:
            S.SEGUROS_OCR_EXTERNAL_ENABLED = original
        self.assertFalse(allowed)
        self.assertEqual(motivo, "envio_externo_desactivado_instalacion")

    def test_cada_transferencia_queda_registrada_con_hash_y_no_con_el_documento(self):
        contenido = b"%PDF-1.4 poliza con NIF y direccion"
        S.log_seguros_ocr_external_transfer(
            self.conn, "e1", "openai", contenido, session={"user_id": "u1", "nombre": "Ana"}
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT usuario, detalles FROM auditoria WHERE entidad = 'seguros_ocr' AND accion = 'transferencia_a_proveedor_ia'"
        ).fetchone()
        self.assertIsNotNone(row, "la transferencia no se auditó")
        detalles = json.loads(row["detalles"])
        self.assertEqual(detalles["proveedor"], "openai")
        self.assertEqual(detalles["bytes"], len(contenido))
        self.assertEqual(len(detalles["sha256"]), 64)
        # El documento no debe quedar guardado en la auditoría, solo su huella.
        self.assertNotIn("NIF", row["detalles"])


class SegurosOcrDocumentTypeTests(unittest.TestCase):
    """El tipo se decide por magic bytes y hay tope de tamaño."""

    @staticmethod
    def _payload(data):
        return {"file_base64": "data:application/octet-stream;base64," + base64.b64encode(data).decode()}

    def test_acepta_pdf_jpeg_y_png(self):
        for data, esperado in (
            (b"%PDF-1.4 x", "application/pdf"),
            (b"\xff\xd8\xff\xe0 x", "image/jpeg"),
            (b"\x89PNG\r\n\x1a\n x", "image/png"),
        ):
            _raw, mime, _hint = S.decode_seguros_payload(self._payload(data))
            self.assertEqual(mime, esperado)

    def test_rechaza_lo_que_no_es_un_documento(self):
        # Antes el `else` final etiquetaba cualquier binario como application/pdf
        # y se enviaba igualmente al proveedor externo.
        for data in (b"PK\x03\x04 soy un zip", b"texto plano cualquiera"):
            with self.assertRaises(ValueError):
                S.decode_seguros_payload(self._payload(data))

    def test_rechaza_documentos_por_encima_del_tope(self):
        grande = b"%PDF-1.4" + b"A" * (S.SEGUROS_OCR_MAX_BYTES + 1)
        with self.assertRaises(ValueError):
            S.decode_seguros_payload(self._payload(grande))


class OcrJobRetentionTests(unittest.TestCase):
    """El PDF y la transcripción no se conservan indefinidamente."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.jobs_path = Path(self.tmp.name) / "jobs.sqlite"
        S.ensure_ocr_tables(self.jobs_path)
        self.conn = S.open_sqlite_conn(str(self.jobs_path), with_row_factory=True)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_al_terminar_se_suelta_el_documento_pero_queda_el_resultado(self):
        job_id = S.enqueue_ocr_job(
            str(self.jobs_path), "seguros",
            {"file_base64": "data:application/pdf;base64," + "A" * 4000},
            user_id="u1",
        )
        guardado = self.conn.execute("SELECT payload_json FROM ocr_jobs WHERE id = ?", (job_id,)).fetchone()
        self.assertGreater(len(guardado["payload_json"]), 1000, "el PDF debería estar en la cola")

        S.update_ocr_job(self.conn, job_id, "done", result={"text": "transcripcion"})
        self.conn.commit()
        row = self.conn.execute(
            "SELECT payload_json, result_json FROM ocr_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        self.assertEqual(row["payload_json"], "{}", "el documento sigue almacenado tras terminar")
        self.assertTrue(row["result_json"], "el cliente todavía debe poder leer el resultado")

    def test_purga_los_jobs_terminados_antiguos_y_respeta_los_recientes(self):
        viejo = S.enqueue_ocr_job(str(self.jobs_path), "seguros", {"file_base64": "x"}, user_id="u1")
        reciente = S.enqueue_ocr_job(str(self.jobs_path), "seguros", {"file_base64": "y"}, user_id="u1")
        S.update_ocr_job(self.conn, viejo, "done", result={"text": "a"})
        S.update_ocr_job(self.conn, reciente, "done", result={"text": "b"})
        pasado = (datetime.now(timezone.utc) - timedelta(hours=S.OCR_JOBS_RETENTION_HOURS + 24)).isoformat()
        self.conn.execute("UPDATE ocr_jobs SET finished_at = ? WHERE id = ?", (pasado, viejo))
        self.conn.commit()

        S.purge_ocr_jobs(self.conn)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM ocr_jobs WHERE id = ?", (viejo,)).fetchone()[0], 0
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM ocr_jobs WHERE id = ?", (reciente,)).fetchone()[0], 1
        )


class SegurosComplianceEndpointTests(unittest.TestCase):
    """IPID, consentimientos, catálogos compartidos y log de lectura, por HTTP."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "compliance.sqlite"
        cls.ocr_db_path = Path(cls.tmp.name) / "ocr.sqlite"
        S.ensure_tables(cls.db_path)
        cls.conn = S.open_sqlite_conn(str(cls.db_path), with_row_factory=True)
        cls._seed()

        cls._prev_db_path = getattr(S.Handler, "db_path", None)
        cls._prev_ocr_db_path = getattr(S.Handler, "ocr_db_path", None)
        S.Handler.db_path = str(cls.db_path)
        S.Handler.ocr_db_path = str(cls.ocr_db_path)
        cls.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.cookie = cls._login()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.conn.close()
        if cls._prev_db_path is not None:
            S.Handler.db_path = cls._prev_db_path
        if cls._prev_ocr_db_path is not None:
            S.Handler.ocr_db_path = cls._prev_ocr_db_path
        cls.tmp.cleanup()

    def setUp(self):
        S.Handler.db_path = str(self.db_path)
        S.Handler.ocr_db_path = str(self.ocr_db_path)

    @classmethod
    def _seed(cls):
        _insert(cls.conn, "empresas", {"id": "empA", "nombre": "Empresa A", "activo": 1,
                                       "created_at": NOW, "updated_at": NOW})
        _insert(cls.conn, "workspaces", {"id": "wsA", "nombre": "WS A", "slug": "wsa",
                                         "estado": "Activo", "plan": "Enterprise",
                                         "created_at": NOW, "updated_at": NOW})
        _insert(cls.conn, "workspace_empresas", {"id": "weA", "workspace_id": "wsA",
                                                 "empresa_id": "empA",
                                                 "created_at": NOW, "updated_at": NOW})
        _insert(cls.conn, "usuarios", {"id": "ua", "nombre": "Ana", "usuario": "ana",
                                       "email": "ana@a.test", "rol": "Miembro",
                                       "servicio": "Seguros", "activo": 1,
                                       "password_hash": S.hash_password(PASSWORD),
                                       "created_at": NOW, "updated_at": NOW})
        _insert(cls.conn, "workspace_miembros", {"id": "wmA", "workspace_id": "wsA",
                                                 "usuario_id": "ua", "rol": "Miembro",
                                                 "created_at": NOW, "updated_at": NOW})
        _insert(cls.conn, "clientes", {"id": "cli", "empresa_id": "empA", "nombre": "Cliente",
                                       "created_at": NOW, "updated_at": NOW})
        _insert(cls.conn, "seguros", {"id": "pol", "empresa_id": "empA", "cliente_id": "cli",
                                      "tomador": "Tomador", "compania": "AXA", "ramo": "Salud",
                                      "poliza_numero": "P1", "poliza_key": "k.pdf",
                                      "estado": "En vigor", "estado_poliza": "activa",
                                      "created_at": NOW, "updated_at": NOW})
        _insert(cls.conn, "seguros_comisiones", {"id": "rule1", "compania": "AXA", "ramo": "Salud",
                                                 "porcentaje": 15.0,
                                                 "created_at": NOW, "updated_at": NOW})
        _insert(cls.conn, "seguros_campanas", {"id": "camp1", "compania": "AXA", "nombre": "Camp",
                                               "ramo": "Salud",
                                               "created_at": NOW, "updated_at": NOW})
        _insert(cls.conn, "seguros_consentimientos", {"id": "con1", "empresa_id": "empA",
                                                      "cliente_id": "cli",
                                                      "consent_json": json.dumps({"marketing": True,
                                                                                  "origen": "ORIGINAL"}),
                                                      "created_at": NOW, "updated_at": NOW})
        _insert(cls.conn, "seguros_siniestros", {"id": "sin1", "seguro_id": "pol",
                                                 "empresa_id": "empA", "cliente_id": "cli",
                                                 "descripcion": "Parte", "estado": "Abierto",
                                                 "created_at": NOW, "updated_at": NOW})
        cls.conn.commit()

    @classmethod
    def _login(cls):
        request = urllib.request.Request(
            cls.base + "/api/login",
            data=json.dumps({"usuario": "ana", "password": PASSWORD}).encode(),
            headers={"Content-Type": "application/json", "Origin": cls.base},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return (response.headers.get("Set-Cookie") or "").split(";")[0]

    def _post(self, path, payload):
        body = {"empresa_id": "empA", "workspace_id": "wsA", **payload}
        request = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Origin": self.base,
                     "Cookie": self.cookie}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode() or "{}")

    def _get(self, path, params):
        import urllib.parse
        url = self.base + path + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"Cookie": self.cookie})
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode()

    # ---------- IPID ----------

    def test_el_ipid_no_admite_fecha_futura(self):
        status, body = self._post("/api/seguros_ipid_register",
                                  {"seguro_id": "pol", "fecha_entrega": "2099-01-01"})
        self.assertEqual(status, 400, f"aceptó una entrega futura: {body}")

    def test_el_ipid_registra_al_usuario_de_la_sesion_no_al_del_payload(self):
        status, _ = self._post("/api/seguros_ipid_register",
                               {"seguro_id": "pol", "usuario": "Asesor Inventado"})
        self.assertEqual(status, 200)
        row = self.conn.execute(
            "SELECT usuario, fecha_entrega FROM seguros_ipid_log ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        self.assertNotEqual(row["usuario"], "Asesor Inventado")
        # `now` es la cadena literal "now" en este handler: la fecha debe ser real.
        self.assertNotEqual(row["fecha_entrega"], "now")
        self.assertIn("-", str(row["fecha_entrega"]))

    # ---------- consentimientos ----------

    def test_al_cambiar_el_consentimiento_se_guarda_el_valor_anterior(self):
        status, _ = self._post("/api/seguros_consentimientos_update",
                               {"seguro_id": "pol", "cliente_id": "cli",
                                "marketing": False, "metodo": "web"})
        self.assertEqual(status, 200)
        row = self.conn.execute(
            """
            SELECT detalles FROM auditoria
            WHERE entidad = 'seguros_consentimientos'
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
        detalles = json.loads(row["detalles"])
        self.assertIn("ORIGINAL", detalles.get("consent_anterior", ""))
        self.assertTrue(detalles.get("consent_nuevo"))

    # ---------- catálogos compartidos ----------

    def test_un_miembro_no_puede_tocar_los_catalogos_compartidos(self):
        casos = (
            ("/api/seguros_comisiones_delete", {"id": "rule1"}, "seguros_comisiones", "rule1"),
            ("/api/seguros_comisiones_update", {"id": "rule1", "porcentaje": 99}, "seguros_comisiones", "rule1"),
            ("/api/seguros_campanas_delete", {"id": "camp1"}, "seguros_campanas", "camp1"),
            ("/api/seguros_campanas_update", {"id": "camp1", "nombre": "Otra"}, "seguros_campanas", "camp1"),
        )
        for path, payload, tabla, rid in casos:
            with self.subTest(path=path):
                status, _ = self._post(path, payload)
                self.assertEqual(status, 403)
                self.assertEqual(
                    self.conn.execute(f"SELECT COUNT(*) FROM {tabla} WHERE id = ?", (rid,)).fetchone()[0], 1
                )
        # La regla de comisión no cambió de porcentaje.
        self.assertEqual(
            self.conn.execute("SELECT porcentaje FROM seguros_comisiones WHERE id = 'rule1'").fetchone()[0],
            15.0,
        )

    # ---------- log de lectura ----------

    def test_consultar_siniestros_deja_traza(self):
        antes = self.conn.execute(
            "SELECT COUNT(*) FROM auditoria WHERE entidad = 'seguros_siniestros' AND accion = 'lectura'"
        ).fetchone()[0]
        status, _ = self._get("/api/seguros_siniestros", {"empresa_id": "empA"})
        self.assertEqual(status, 200)
        despues = self.conn.execute(
            "SELECT COUNT(*) FROM auditoria WHERE entidad = 'seguros_siniestros' AND accion = 'lectura'"
        ).fetchone()[0]
        self.assertEqual(despues, antes + 1, "la consulta de siniestros no dejó traza")


if __name__ == "__main__":
    unittest.main()
