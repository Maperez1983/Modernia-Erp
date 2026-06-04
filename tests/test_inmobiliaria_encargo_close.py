import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from web import server


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class InmobiliariaEncargoCloseTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "encargo_close.sqlite"
        server.ensure_tables(self.db_path)
        self.conn = server.open_sqlite_conn(str(self.db_path), with_row_factory=True)
        self.empresa_id = "emp-encargo"
        now = _now_iso()
        self.conn.execute(
            """
            INSERT INTO empresas (id, nombre, activo, created_at, updated_at)
            VALUES (?, ?, 1, datetime(?), datetime(?))
            """,
            (self.empresa_id, "EMPRESA ENCARGO", now, now),
        )
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            self.tmpdir.cleanup()
        except Exception:
            pass

    def test_close_encargo_inserts_cierre_updates_estado_and_archives_pending_actions(self):
        now = _now_iso()
        inmueble_id = os.urandom(16).hex()
        old_owner_id = os.urandom(16).hex()
        self.conn.execute(
            """
            INSERT INTO clientes (id, empresa_id, nombre, nif, telefono, email, estado, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'Activo', datetime(?), datetime(?))
            """,
            (old_owner_id, self.empresa_id, "Propietario anterior", "11111111A", "600000001", "old@example.test", now, now),
        )
        self.conn.execute(
            """
            INSERT INTO inmuebles (
              id, empresa_id, referencia, direccion, tipo_operacion, tipo_inmueble, precio_objetivo,
              estado, portal_publicado, portal_publicado_at, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, 1, datetime(?), datetime(?), datetime(?)
            )
            """,
            (
                inmueble_id,
                self.empresa_id,
                "TEST-ENCARGO-1",
                "CALLE TEST ENCARGO 1",
                "venta",
                "Piso",
                100000.0,
                "Encargo",
                now,
                now,
                now,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO inmueble_propietarios (id, inmueble_id, cliente_id, created_at, updated_at)
            VALUES (?, ?, ?, datetime(?), datetime(?))
            """,
            (os.urandom(16).hex(), inmueble_id, old_owner_id, now, now),
        )
        # Crea acciones pendientes (para validar archivado).
        a1 = os.urandom(16).hex()
        a2 = os.urandom(16).hex()
        a3 = os.urandom(16).hex()
        for aid, estado in ((a1, "Pendiente"), (a2, "Pendiente"), (a3, "Completada")):
            self.conn.execute(
                """
                INSERT INTO acciones (
                  id, empresa_id, servicio, inmueble_id, asunto, tipo, estado,
                  created_at, updated_at
                ) VALUES (
                  ?, ?, 'inmobiliaria', ?, 'Acción test', 'Seguimiento', ?,
                  datetime(?), datetime(?)
                )
                """,
                (aid, self.empresa_id, inmueble_id, estado, now, now),
            )
        self.conn.commit()

        res = server.close_inmueble_encargo_positive(
            self.conn,
            self.empresa_id,
            inmueble_id,
            now,
            usuario="tester",
            fecha_cierre="2026-05-12",
            importe_final=123456.78,
            numero_citas=7,
            tipo="Vendido",
            notas="Test cierre",
            archive_pending=True,
            honorarios=5000.0,
            nuevo_propietario={
                "nombre": "Comprador nuevo",
                "nif": "22222222B",
                "telefono": "600000002",
                "email": "buyer@example.test",
            },
        )
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("tipo"), "Vendido")
        # Puede archivar también acciones "auto" creadas al mover etapa (checklist/pending defaults).
        self.assertGreaterEqual(int(res.get("archived") or 0), 2)
        self.assertTrue(res.get("portal_retired"))
        self.assertTrue(res.get("cierre_id"))
        self.assertTrue(res.get("operacion_id"))
        self.assertTrue(res.get("nuevo_propietario_id"))
        self.assertEqual(res.get("estado_final"), "Inmueble")

        cierre = self.conn.execute(
            "SELECT * FROM inmueble_cierres WHERE id = ? LIMIT 1",
            (res["cierre_id"],),
        ).fetchone()
        self.assertIsNotNone(cierre)
        self.assertEqual(cierre["tipo"], "Vendido")
        self.assertEqual(cierre["fecha_cierre"], "2026-05-12")
        self.assertAlmostEqual(float(cierre["importe_final"]), 123456.78, places=2)
        self.assertAlmostEqual(float(cierre["honorarios"]), 5000.0, places=2)
        self.assertEqual(int(cierre["numero_citas"]), 7)
        self.assertEqual(cierre["usuario"], "tester")
        self.assertEqual(cierre["operacion_id"], res["operacion_id"])
        self.assertEqual(cierre["nuevo_propietario_id"], res["nuevo_propietario_id"])

        op = self.conn.execute(
            "SELECT * FROM operaciones_inmobiliarias WHERE id = ? LIMIT 1",
            (res["operacion_id"],),
        ).fetchone()
        self.assertIsNotNone(op)
        self.assertEqual(op["tipo_operacion"], "venta")
        self.assertEqual(op["estado"], "Cerrada")
        self.assertEqual(op["propietario1_id"], old_owner_id)
        self.assertEqual(op["contraparte1_id"], res["nuevo_propietario_id"])
        self.assertAlmostEqual(float(op["precio_escritura"]), 123456.78, places=2)
        self.assertAlmostEqual(float(op["honorarios"]), 5000.0, places=2)

        inm = self.conn.execute(
            "SELECT estado, portal_publicado, portal_retirado_at FROM inmuebles WHERE id = ? LIMIT 1",
            (inmueble_id,),
        ).fetchone()
        self.assertEqual((inm["estado"] if inm else None), "Inmueble")
        self.assertEqual(int(inm["portal_publicado"] or 0), 0)
        self.assertTrue(inm["portal_retirado_at"])

        capt = self.conn.execute(
            "SELECT etapa FROM captaciones WHERE inmueble_id = ? AND empresa_id = ? LIMIT 1",
            (inmueble_id, self.empresa_id),
        ).fetchone()
        self.assertEqual((capt["etapa"] if capt else None), "Inmueble")

        linked_owner = self.conn.execute(
            "SELECT cliente_id FROM inmueble_propietarios WHERE inmueble_id = ? LIMIT 1",
            (inmueble_id,),
        ).fetchone()
        self.assertEqual(linked_owner["cliente_id"], res["nuevo_propietario_id"])

        rows = self.conn.execute(
            "SELECT id, estado FROM acciones WHERE empresa_id = ? AND inmueble_id = ? ORDER BY id",
            (self.empresa_id, inmueble_id),
        ).fetchall()
        by_id = {row["id"]: dict(row) for row in rows}
        self.assertEqual(by_id[a1]["estado"], "Cancelada")
        self.assertEqual(by_id[a2]["estado"], "Cancelada")
        self.assertEqual(by_id[a3]["estado"], "Completada")

    def test_close_encargo_negative_keeps_history_without_operation_and_returns_to_inmueble(self):
        now = _now_iso()
        inmueble_id = os.urandom(16).hex()
        self.conn.execute(
            """
            INSERT INTO inmuebles (
              id, empresa_id, referencia, direccion, tipo_operacion, tipo_inmueble, precio_objetivo,
              estado, portal_publicado, portal_publicado_at, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, 1, datetime(?), datetime(?), datetime(?)
            )
            """,
            (
                inmueble_id,
                self.empresa_id,
                "TEST-ENCARGO-NEG",
                "CALLE TEST NEGATIVO 1",
                "venta",
                "Piso",
                150000.0,
                "Encargo",
                now,
                now,
                now,
            ),
        )
        self.conn.commit()

        res = server.close_inmueble_encargo_positive(
            self.conn,
            self.empresa_id,
            inmueble_id,
            now,
            usuario="tester",
            fecha_cierre="2026-05-13",
            tipo="Cerrado negativamente",
            motivo_cierre="Propietario retira el encargo",
            notas="Sin operación",
            archive_pending=True,
        )
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("tipo"), "Cerrado negativamente")
        self.assertIsNone(res.get("operacion_id"))

        cierre = self.conn.execute(
            "SELECT * FROM inmueble_cierres WHERE id = ? LIMIT 1",
            (res["cierre_id"],),
        ).fetchone()
        self.assertEqual(cierre["motivo_cierre"], "Propietario retira el encargo")
        self.assertIsNone(cierre["operacion_id"])

        op_count = self.conn.execute(
            "SELECT COUNT(*) AS total FROM operaciones_inmobiliarias WHERE inmueble_id = ?",
            (inmueble_id,),
        ).fetchone()
        self.assertEqual(int(op_count["total"]), 0)

        inm = self.conn.execute(
            "SELECT estado, portal_publicado FROM inmuebles WHERE id = ? LIMIT 1",
            (inmueble_id,),
        ).fetchone()
        self.assertEqual(inm["estado"], "Inmueble")
        self.assertEqual(int(inm["portal_publicado"] or 0), 0)

    def test_create_inmueble_convert_to_encargo_contract_appointment_and_close_rental(self):
        now = _now_iso()
        owner_id = server.ensure_cliente_for_inmobiliaria(
            self.conn,
            self.empresa_id,
            "ARRENDADOR PRUEBA CIERRE",
            "33333333C",
            now,
            {"telefono": "600333333", "email": "seller-close@example.test"},
        )
        tenant_id = server.ensure_cliente_for_inmobiliaria(
            self.conn,
            self.empresa_id,
            "INQUILINO PRUEBA CIERRE",
            "44444444D",
            now,
            {"telefono": "600444444", "email": "buyer-close@example.test"},
        )
        inmueble_id = server.ensure_inmueble_for_compraventa(
            self.conn,
            self.empresa_id,
            payload={
                "tipo_inmueble": "Piso",
                "direccion": "CALLE PRUEBA CIERRE 10",
                "referencia_catastral": "9999999UF7699S0001ZZ",
                "precio_encargo": "1200",
            },
            now=now,
        )
        self.conn.execute(
            "UPDATE inmuebles SET tipo_operacion = 'alquiler', updated_at = datetime(?) WHERE id = ?",
            (now, inmueble_id),
        )
        server.ensure_inmueble_propietario_link(self.conn, inmueble_id, owner_id, now)
        server.sync_inmueble_stage_for_action(self.conn, inmueble_id, "noticia", now)
        server.sync_inmueble_stage_for_action(self.conn, inmueble_id, "encargo", now)
        self.conn.commit()

        encargo = self.conn.execute(
            """
            SELECT i.estado, c.etapa
            FROM inmuebles i
            LEFT JOIN captaciones c ON c.inmueble_id = i.id
            WHERE i.id = ?
            LIMIT 1
            """,
            (inmueble_id,),
        ).fetchone()
        self.assertEqual(encargo["estado"], "Encargo")
        self.assertEqual(encargo["etapa"], "Encargo")
        self.assertIsNone(server.validate_inmo_action_result("Cita contrato privado", "Completada", "Firmado"))
        self.assertIsNone(server.validate_inmo_action_result("Cita notaria", "Completada", "Firmada"))

        action_id = os.urandom(16).hex()
        self.conn.execute(
            """
            INSERT INTO acciones (
              id, empresa_id, servicio, cliente_id, inmueble_id, cliente_nombre,
              fecha, hora, asunto, tipo, responsable, estado, resultado_cierre,
              importe_propuesta, created_at, updated_at
            ) VALUES (
              ?, ?, 'inmobiliaria', ?, ?, 'INQUILINO PRUEBA CIERRE',
              '2026-06-10', '10:00', 'Firma contrato privado alquiler', 'Cita contrato privado',
              'tester', 'Completada', 'Firmado', 1200, datetime(?), datetime(?)
            )
            """,
            (action_id, self.empresa_id, tenant_id, inmueble_id, now, now),
        )

        res = server.close_inmueble_encargo_positive(
            self.conn,
            self.empresa_id,
            inmueble_id,
            now,
            usuario="tester",
            fecha_cierre="2026-06-10",
            importe_final=1200,
            honorarios=1200,
            numero_citas=1,
            tipo="Alquiler",
            notas="Cierre de alquiler desde contrato privado firmado",
            nuevo_propietario={
                "nombre": "INQUILINO PRUEBA CIERRE",
                "nif": "44444444D",
                "telefono": "600444444",
                "email": "buyer-close@example.test",
            },
            archive_pending=True,
        )
        self.conn.commit()

        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("tipo"), "Alquiler")
        self.assertTrue(res.get("operacion_id"))
        self.assertEqual(res.get("nuevo_propietario_id"), tenant_id)

        final_inmueble = self.conn.execute(
            "SELECT estado FROM inmuebles WHERE id = ? LIMIT 1",
            (inmueble_id,),
        ).fetchone()
        self.assertEqual(final_inmueble["estado"], "Inmueble")

        propietario = self.conn.execute(
            "SELECT cliente_id FROM inmueble_propietarios WHERE inmueble_id = ? LIMIT 1",
            (inmueble_id,),
        ).fetchone()
        self.assertEqual(propietario["cliente_id"], owner_id)

        operacion = self.conn.execute(
            "SELECT * FROM operaciones_inmobiliarias WHERE id = ? LIMIT 1",
            (res["operacion_id"],),
        ).fetchone()
        self.assertEqual(operacion["tipo_operacion"], "alquiler")
        self.assertEqual(operacion["propietario1_id"], owner_id)
        self.assertEqual(operacion["contraparte1_id"], tenant_id)
        self.assertAlmostEqual(float(operacion["precio_renta"]), 1200.0, places=2)
        self.assertAlmostEqual(float(operacion["honorarios"]), 1200.0, places=2)

        alquiler = self.conn.execute(
            "SELECT * FROM alquileres WHERE empresa_id = ? AND direccion = ? LIMIT 1",
            (self.empresa_id, "CALLE PRUEBA CIERRE 10"),
        ).fetchone()
        self.assertIsNotNone(alquiler)
        self.assertEqual(alquiler["inquilino"], "INQUILINO PRUEBA CIERRE")
        self.assertAlmostEqual(float(alquiler["importe_comision"]), 1200.0, places=2)

        cita = self.conn.execute(
            "SELECT estado, resultado_cierre FROM acciones WHERE id = ? LIMIT 1",
            (action_id,),
        ).fetchone()
        self.assertEqual(cita["estado"], "Completada")
        self.assertEqual(cita["resultado_cierre"], "Firmado")


if __name__ == "__main__":
    unittest.main()
