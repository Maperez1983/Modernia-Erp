"""Regresión: aislamiento multi-tenant POR FILA en el CRM de seguros.

Hallazgo verificado en vivo (2026-07-29): el gate central de POST solo valida el
`empresa_id` que viaja en el payload, no que la fila objetivo pertenezca a esa
empresa. Un usuario legítimo y NO privilegiado de la empresa A podía modificar,
borrar y anular pólizas de la empresa B, crear movimientos/snapshots sobre ellas
y borrar sus recibos, siniestros y reclamaciones pasando el id ajeno.

Estos tests levantan un servidor real, hacen login como usuario de la empresa A
y comprueban que cada operación contra datos de la empresa B responde 403 y NO
modifica la base de datos, mientras la misma operación sobre datos propios sigue
funcionando.
"""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from web import server as S

NOW = "2026-07-29 10:00:00"
PASSWORD = "Secreto123!"


class SegurosTenantIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmp.name) / "seguros_tenant.sqlite"
        S.ensure_tables(cls.db_path)
        cls.conn = S.open_sqlite_conn(str(cls.db_path), with_row_factory=True)
        cls._seed()

        S.Handler.db_path = str(cls.db_path)
        S.Handler.ocr_db_path = str(Path(cls.tmp.name) / "ocr.sqlite")
        cls.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

        status, _, set_cookie = cls._post("/api/login", {"usuario": "ana", "password": PASSWORD})
        assert status == 200, f"login falló: {status}"
        cls.cookie = (set_cookie or "").split(";")[0]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.conn.close()
        cls.tmp.cleanup()

    # ---------- utilidades ----------

    @classmethod
    def _cols(cls, table):
        return [row[1] for row in cls.conn.execute(f"pragma table_info({table})")]

    @classmethod
    def _insert(cls, table, data):
        usable = {k: v for k, v in data.items() if k in cls._cols(table)}
        cls.conn.execute(
            f"INSERT INTO {table} ({','.join(usable)}) VALUES ({','.join('?' * len(usable))})",
            list(usable.values()),
        )

    @classmethod
    def _seed(cls):
        for empresa_id, nombre in (("empA", "Empresa A SL"), ("empB", "Empresa B SL")):
            cls._insert("empresas", {"id": empresa_id, "nombre": nombre, "activo": 1,
                                     "created_at": NOW, "updated_at": NOW})
        for ws_id, nombre in (("wsA", "WS A"), ("wsB", "WS B")):
            cls._insert("workspaces", {"id": ws_id, "nombre": nombre, "slug": ws_id.lower(),
                                       "estado": "Activo", "plan": "Enterprise",
                                       "created_at": NOW, "updated_at": NOW})
        for ws_id, empresa_id in (("wsA", "empA"), ("wsB", "empB")):
            cls._insert("workspace_empresas", {"id": f"we-{ws_id}", "workspace_id": ws_id,
                                               "empresa_id": empresa_id,
                                               "created_at": NOW, "updated_at": NOW})
        # Ana: miembro NO privilegiado del workspace A únicamente.
        cls._insert("usuarios", {"id": "userA", "nombre": "Ana", "usuario": "ana",
                                 "email": "ana@a.test", "rol": "Miembro", "servicio": "Seguros",
                                 "activo": 1, "password_hash": S.hash_password(PASSWORD),
                                 "created_at": NOW, "updated_at": NOW})
        cls._insert("workspace_miembros", {"id": "wm-A", "workspace_id": "wsA",
                                           "usuario_id": "userA", "rol": "Miembro",
                                           "created_at": NOW, "updated_at": NOW})

        # Una póliza propia y varias ajenas (una por operación destructiva).
        for poliza_id, empresa_id in (
            ("polA", "empA"), ("polB", "empB"), ("polB2", "empB"),
            ("polB3", "empB"), ("polB4", "empB"),
        ):
            cls._insert("seguros", {"id": poliza_id, "empresa_id": empresa_id,
                                    "tomador": f"Tomador {empresa_id}", "compania": "ALLIANZ",
                                    "ramo": "Hogar", "poliza_numero": f"NUM-{poliza_id}",
                                    "prima_neta": 100.0, "prima_total": 121.0, "comision": 20.0,
                                    "estado": "Presupuesto", "estado_poliza": "activa",
                                    "created_at": NOW, "updated_at": NOW})
        cls._insert("seguros_recibos", {"id": "recB", "seguro_id": "polB", "empresa_id": "empB",
                                        "prima_total": 121.0, "estado": "Pendiente",
                                        "created_at": NOW, "updated_at": NOW})
        cls._insert("seguros_siniestros", {"id": "sinB", "seguro_id": "polB", "empresa_id": "empB",
                                           "descripcion": "Siniestro B", "estado": "Abierto",
                                           "created_at": NOW, "updated_at": NOW})
        cls._insert("seguros_reclamaciones", {"id": "reclB", "seguro_id": "polB",
                                              "empresa_id": "empB", "estado": "Abierta",
                                              "created_at": NOW, "updated_at": NOW})
        cls._insert("seguros_checklist", {"id": "chkB", "poliza_id": "polB", "tarea": "Tarea B",
                                          "estado": "Pendiente", "created_at": NOW,
                                          "updated_at": NOW})

        # seguros_ofertas no tiene empresa_id: el tenant sale del cliente.
        cls._insert("clientes", {"id": "cliA", "empresa_id": "empA", "nombre": "Cliente de A",
                                 "created_at": NOW, "updated_at": NOW})
        cls._insert("clientes", {"id": "cliB", "empresa_id": "empB", "nombre": "Cliente de B",
                                 "created_at": NOW, "updated_at": NOW})
        for oferta_id, cliente_id in (("ofA", "cliA"), ("ofB", "cliB"), ("ofB2", "cliB")):
            cls._insert("seguros_ofertas", {"id": oferta_id, "cliente_id": cliente_id,
                                            "ramo": "Hogar", "compania": "AXA",
                                            "propuesta": f"Propuesta {oferta_id}",
                                            "estado": "Abierta", "created_at": NOW,
                                            "updated_at": NOW})
        cls.conn.commit()

    @classmethod
    def _post(cls, path, payload, cookie=None):
        request = urllib.request.Request(
            cls.base + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Origin": cls.base,
                     **({"Cookie": cookie} if cookie else {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read().decode() or "{}"), response.headers.get("Set-Cookie")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode() or "{}"), None

    def _as_ana(self, path, payload):
        """POST autenticado como Ana (empresa A) declarando su propio ámbito."""
        return self._post(path, {"empresa_id": "empA", "workspace_id": "wsA", **payload}, self.cookie)

    def _scalar(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()[0]

    # ---------- cross-tenant: debe responder 403 y no tocar la BD ----------

    def test_no_puede_modificar_poliza_de_otra_empresa(self):
        status, _, _ = self._as_ana("/api/seguros_update", {"id": "polB", "tomador": "HACKEADO"})
        self.assertEqual(status, 403)
        self.assertEqual(self._scalar("SELECT tomador FROM seguros WHERE id='polB'"), "Tomador empB")

    def test_no_puede_borrar_poliza_de_otra_empresa(self):
        status, _, _ = self._as_ana("/api/seguros_delete", {"id": "polB2"})
        self.assertEqual(status, 403)
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM seguros WHERE id='polB2'"), 1)

    def test_no_puede_anular_poliza_de_otra_empresa(self):
        status, _, _ = self._as_ana("/api/seguros_poliza_accion",
                                    {"id": "polB3", "accion": "anular", "motivo": "x"})
        self.assertEqual(status, 403)
        self.assertEqual(self._scalar("SELECT estado FROM seguros WHERE id='polB3'"), "Presupuesto")

    def test_no_puede_cambiar_compania_de_poliza_ajena(self):
        status, _, _ = self._as_ana("/api/seguros_cambio_compania",
                                    {"id": "polB4", "nueva_compania": "AXA"})
        self.assertEqual(status, 403)

    def test_no_puede_crear_movimiento_en_poliza_ajena(self):
        status, _, _ = self._as_ana("/api/seguros_movimientos",
                                    {"seguro_id": "polB", "tipo": "emision", "prima_total": 999})
        self.assertEqual(status, 403)
        self.assertEqual(
            self._scalar("SELECT COUNT(*) FROM seguros_movimientos WHERE seguro_id='polB'"), 0
        )

    def test_no_puede_versionar_poliza_ajena(self):
        status, _, _ = self._as_ana("/api/seguros_version_snapshot",
                                    {"seguro_id": "polB", "motivo": "x"})
        self.assertEqual(status, 403)
        self.assertEqual(
            self._scalar("SELECT COUNT(*) FROM seguros_versiones WHERE seguro_id='polB'"), 0
        )

    def test_no_puede_borrar_recibo_ajeno(self):
        status, _, _ = self._as_ana("/api/seguros_recibos_delete", {"id": "recB"})
        self.assertEqual(status, 403)
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM seguros_recibos WHERE id='recB'"), 1)

    def test_no_puede_borrar_siniestro_ajeno(self):
        status, _, _ = self._as_ana("/api/seguros_siniestros_delete", {"id": "sinB"})
        self.assertEqual(status, 403)
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM seguros_siniestros WHERE id='sinB'"), 1)

    def test_no_puede_borrar_reclamacion_ajena(self):
        status, _, _ = self._as_ana("/api/seguros_reclamacion_delete", {"id": "reclB"})
        self.assertEqual(status, 403)
        self.assertEqual(
            self._scalar("SELECT COUNT(*) FROM seguros_reclamaciones WHERE id='reclB'"), 1
        )

    def test_no_puede_editar_checklist_de_poliza_ajena(self):
        status, _, _ = self._as_ana("/api/seguros_checklist_update",
                                    {"id": "chkB", "estado": "Hecho"})
        self.assertEqual(status, 403)
        self.assertEqual(self._scalar("SELECT estado FROM seguros_checklist WHERE id='chkB'"),
                         "Pendiente")

    def test_no_puede_modificar_oferta_de_cliente_ajeno(self):
        """seguros_ofertas no tiene empresa_id; el ámbito se deriva de clientes.empresa_id."""
        status, _, _ = self._as_ana("/api/seguros_ofertas_update",
                                    {"id": "ofB", "estado": "Manipulada"})
        self.assertEqual(status, 403)
        self.assertEqual(self._scalar("SELECT estado FROM seguros_ofertas WHERE id='ofB'"),
                         "Abierta")

    def test_no_puede_borrar_oferta_de_cliente_ajeno(self):
        status, _, _ = self._as_ana("/api/seguros_ofertas_delete", {"id": "ofB2"})
        self.assertEqual(status, 403)
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM seguros_ofertas WHERE id='ofB2'"), 1)

    # ---------- mismo tenant: debe seguir funcionando ----------

    def test_si_puede_gestionar_oferta_de_su_cliente(self):
        status, _, _ = self._as_ana("/api/seguros_ofertas_update",
                                    {"id": "ofA", "estado": "Aceptada"})
        self.assertEqual(status, 200)
        self.assertEqual(self._scalar("SELECT estado FROM seguros_ofertas WHERE id='ofA'"),
                         "Aceptada")

    def test_si_puede_modificar_su_propia_poliza(self):
        status, _, _ = self._as_ana("/api/seguros_update", {"id": "polA", "tomador": "Legitimo"})
        self.assertEqual(status, 200)
        self.assertEqual(self._scalar("SELECT tomador FROM seguros WHERE id='polA'"), "Legitimo")

    def test_checklist_propio_responde_y_persiste(self):
        """checklist_update hacía `return` sin respuesta ni commit (error de red + no persistía)."""
        status, body, _ = self._as_ana("/api/seguros_checklist_generate", {"poliza_id": "polA"})
        self.assertEqual(status, 200)
        self.assertEqual(
            self._scalar("SELECT COUNT(*) FROM seguros_checklist WHERE poliza_id='polA'"), 5
        )

        tarea_id = self._scalar("SELECT id FROM seguros_checklist WHERE poliza_id='polA' LIMIT 1")
        status, body, _ = self._as_ana("/api/seguros_checklist_update",
                                       {"id": tarea_id, "estado": "Hecho"})
        self.assertEqual(status, 200)
        self.assertTrue(body.get("ok"))
        self.assertEqual(self._scalar("SELECT estado FROM seguros_checklist WHERE id=?",
                                      (tarea_id,)), "Hecho")


if __name__ == "__main__":
    unittest.main()
