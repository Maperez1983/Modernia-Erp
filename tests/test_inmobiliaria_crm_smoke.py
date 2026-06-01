import os
import tempfile
import unittest
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path

from web import server


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _make_pdf_bytes(title="Smoke"):
    header = f"%PDF-1.4\n% Smoke: {title}\n".encode("utf-8", "ignore")
    body = b"1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    return header + body


def _extract_pdf_text(pdf_bytes):
    if server.PdfReader is not None:
        reader = server.PdfReader(BytesIO(pdf_bytes))
        chunks = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
        text = "\n".join(chunks)
        if text.strip():
            return text
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
            tmp_file.write(pdf_bytes)
            tmp_path = tmp_file.name
        text, _err = server.pdftotext_extract(tmp_path, pages=6)
        if text.strip():
            return text
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    return ""


class InmobiliariaCrmSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "smoke.sqlite"
        # En local suele existir `DATABASE_URL` (Render). Para tests queremos forzar SQLite
        # pasando un `Path` a `ensure_tables()`.
        server.ensure_tables(self.db_path)
        self.conn = server.open_sqlite_conn(str(self.db_path), with_row_factory=True)
        self.empresa_id = "emp-smoke"
        self.workspace_id = "ws-smoke"
        now = _now_iso()
        self.conn.execute(
            """
            INSERT INTO empresas (id, nombre, activo, created_at, updated_at)
            VALUES (?, ?, 1, datetime(?), datetime(?))
            """,
            (self.empresa_id, "EMPRESA SMOKE", now, now),
        )
        self.conn.execute(
            """
            INSERT INTO workspaces (id, nombre, slug, estado, plan, created_at, updated_at)
            VALUES (?, ?, ?, 'Activo', 'Enterprise', datetime(?), datetime(?))
            """,
            (self.workspace_id, "WORKSPACE SMOKE", "workspace-smoke", now, now),
        )
        self.conn.execute(
            """
            INSERT INTO workspace_empresas (id, workspace_id, empresa_id, rol, created_at, updated_at)
            VALUES (?, ?, ?, 'Operadora', datetime(?), datetime(?))
            """,
            (os.urandom(16).hex(), self.workspace_id, self.empresa_id, now, now),
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

    def test_create_inmueble_agenda_and_pdf(self):
        now = _now_iso()
        cliente_id = server.ensure_cliente_for_inmobiliaria(
            self.conn,
            self.empresa_id,
            nombre="PROPIETARIO TEST",
            nif="12345678Z",
            now=now,
            extra={"telefono": "600000000", "email": "prop@test.local"},
        )
        self.assertTrue(cliente_id)

        inmueble_id = server.ensure_inmueble_for_compraventa(
            self.conn,
            self.empresa_id,
            payload={
                "tipo_inmueble": "Piso",
                "direccion": "CALLE FALSA 123",
                "referencia_catastral": "1234567UF7613S0001AB",
                "precio_encargo": "250000",
            },
            now=now,
        )
        self.assertTrue(inmueble_id)

        server.ensure_inmueble_propietario_link(self.conn, inmueble_id, cliente_id, now)
        cap_id = server.ensure_captacion_for_inmueble(self.conn, self.empresa_id, inmueble_id, now)
        self.assertTrue(cap_id)

        server.ensure_inmueble_checklist_defaults_if_empty(
            self.conn, inmueble_id, etapa="captacion", now=now, responsable="SMOKE"
        )
        server.ensure_pending_inmueble_stage_actions(
            self.conn, self.empresa_id, inmueble_id, etapa="captacion", now=now, responsable="SMOKE"
        )

        server.sync_inmueble_stage_for_action(self.conn, inmueble_id, destino="encargo", now=now)

        doc_row = server.persist_generated_inmueble_pdf(
            self.conn,
            inmueble_id=inmueble_id,
            tipo="hoja_visita",
            nombre="Hoja de visita (smoke)",
            pdf_bytes=_make_pdf_bytes("Hoja visita · Smoke"),
            filename_base="hoja_visita_smoke",
            now=now,
            replace_existing=False,
            empresa_id=self.empresa_id,
            usuario="smoke",
            plantilla_clave="hoja_visita",
            origen_tipo="smoke",
            origen_id=inmueble_id,
            payload_json={"source": "test"},
        )
        self.assertTrue(doc_row and doc_row.get("url"))

    def test_scoped_inmueble_and_demanda_helpers_reject_other_empresa(self):
        now = _now_iso()
        other_empresa = "emp-other"
        self.conn.execute(
            """
            INSERT INTO empresas (id, nombre, activo, created_at, updated_at)
            VALUES (?, ?, 1, datetime(?), datetime(?))
            """,
            (other_empresa, "EMPRESA OTHER", now, now),
        )
        own_inmueble = server.ensure_inmueble_for_compraventa(
            self.conn,
            self.empresa_id,
            payload={"tipo_inmueble": "Piso", "direccion": "CALLE PROPIA 1"},
            now=now,
        )
        foreign_inmueble = server.ensure_inmueble_for_compraventa(
            self.conn,
            other_empresa,
            payload={"tipo_inmueble": "Piso", "direccion": "CALLE AJENA 1"},
            now=now,
        )
        demanda_id = os.urandom(16).hex()
        self.conn.execute(
            """
            INSERT INTO demandas (
              id, empresa_id, tipo, zona, estado, created_at, updated_at
            ) VALUES (
              ?, ?, 'Compra', 'Centro', 'Activa', datetime(?), datetime(?)
            )
            """,
            (demanda_id, self.empresa_id, now, now),
        )
        foreign_demanda_id = os.urandom(16).hex()
        self.conn.execute(
            """
            INSERT INTO demandas (
              id, empresa_id, tipo, zona, estado, created_at, updated_at
            ) VALUES (
              ?, ?, 'Compra', 'Centro', 'Activa', datetime(?), datetime(?)
            )
            """,
            (foreign_demanda_id, other_empresa, now, now),
        )
        self.conn.commit()

        self.assertIsNotNone(server.fetch_inmueble_for_empresa(self.conn, own_inmueble, self.empresa_id))
        self.assertIsNone(server.fetch_inmueble_for_empresa(self.conn, foreign_inmueble, self.empresa_id))
        self.assertIsNotNone(server.fetch_demanda_for_empresa(self.conn, demanda_id, self.empresa_id))
        self.assertIsNone(server.fetch_demanda_for_empresa(self.conn, foreign_demanda_id, self.empresa_id))

    def test_inmueble_full_stage_flow_syncs_entities_tasks_and_close(self):
        now = _now_iso()
        inmueble_id = server.ensure_inmueble_for_compraventa(
            self.conn,
            self.empresa_id,
            payload={
                "tipo_inmueble": "Piso",
                "direccion": "CALLE FLUJO 10",
                "referencia_catastral": "7654321UF7613S0001ZZ",
                "precio_encargo": "220000",
            },
            now=now,
        )
        self.assertTrue(inmueble_id)

        stages = [
            ("noticia", "Noticia"),
            ("valoracion", "Valoración"),
            ("adquisicion", "Adquisición"),
            ("encargo", "Encargo"),
            ("propuesta", "Propuesta"),
            ("reservado", "Reservado"),
            ("arras", "Contrato de arras"),
        ]
        for raw_stage, expected_label in stages:
            server.sync_inmueble_stage_for_action(self.conn, inmueble_id, raw_stage, now)
            self.conn.commit()
            inmueble = self.conn.execute(
                "SELECT estado FROM inmuebles WHERE id = ? LIMIT 1",
                (inmueble_id,),
            ).fetchone()
            captacion = self.conn.execute(
                "SELECT etapa, situacion_comercial, noticia_verificada FROM captaciones WHERE inmueble_id = ? LIMIT 1",
                (inmueble_id,),
            ).fetchone()
            self.assertEqual(inmueble["estado"], expected_label)
            self.assertEqual(captacion["etapa"], expected_label)
            self.assertEqual(captacion["situacion_comercial"], expected_label)
            if expected_label == "Encargo":
                self.assertEqual(int(captacion["noticia_verificada"] or 0), 1)
            checklist_count = self.conn.execute(
                "SELECT COUNT(*) AS total FROM inmueble_checklist WHERE inmueble_id = ? AND etapa = ?",
                (inmueble_id, expected_label),
            ).fetchone()["total"]
            self.assertGreater(checklist_count, 0, expected_label)

        expected_actions = {
            "Primera llamada de contacto",
            "Preparar valoración",
            "Compartir valoración con propietario",
            "Concertar cita de adquisición",
            "Firmar encargo",
            "Preparar anuncio",
            "Revisar propuesta/oferta",
            "Subir reserva firmada",
            "Subir contrato de arras",
        }
        action_rows = self.conn.execute(
            """
            SELECT asunto
            FROM acciones
            WHERE empresa_id = ? AND inmueble_id = ? AND servicio = 'inmobiliaria'
            """,
            (self.empresa_id, inmueble_id),
        ).fetchall()
        self.assertTrue(expected_actions.issubset({row["asunto"] for row in action_rows}))

        close = server.close_inmueble_encargo_positive(
            self.conn,
            self.empresa_id,
            inmueble_id,
            now,
            usuario="tester",
            fecha_cierre="2026-05-29",
            importe_final=215000,
            numero_citas=5,
            tipo="Vendido",
            notas="Cierre test flujo completo",
            archive_pending=True,
        )
        self.conn.commit()
        self.assertTrue(close.get("ok"))
        self.assertGreater(int(close.get("archived") or 0), 0)
        final_inmueble = self.conn.execute(
            "SELECT estado FROM inmuebles WHERE id = ? LIMIT 1",
            (inmueble_id,),
        ).fetchone()
        final_captacion = self.conn.execute(
            "SELECT etapa FROM captaciones WHERE inmueble_id = ? LIMIT 1",
            (inmueble_id,),
        ).fetchone()
        self.assertEqual(final_inmueble["estado"], "Vendido")
        self.assertEqual(final_captacion["etapa"], "Vendido")
        pending = self.conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM acciones
            WHERE empresa_id = ? AND inmueble_id = ? AND servicio = 'inmobiliaria'
              AND LOWER(COALESCE(estado, '')) = 'pendiente'
            """,
            (self.empresa_id, inmueble_id),
        ).fetchone()["total"]
        self.assertEqual(int(pending or 0), 0)

    def test_demanda_buyer_matching_iteration_and_visit_link_offer_and_demand(self):
        now = _now_iso()
        buyer_id = server.ensure_cliente_for_inmobiliaria(
            self.conn,
            self.empresa_id,
            nombre="COMPRADOR MATCH",
            nif="33333333P",
            now=now,
            extra={"telefono": "633333333", "email": "match@test.local"},
        )
        matching_inmueble = server.ensure_inmueble_for_compraventa(
            self.conn,
            self.empresa_id,
            payload={
                "tipo_inmueble": "Piso",
                "direccion": "CALLE MATCH 1",
                "referencia_catastral": "2468135UF7613S0001BB",
                "precio_encargo": "180000",
            },
            now=now,
        )
        self.conn.execute(
            """
            UPDATE inmuebles
            SET zona = 'Centro', m2 = 82, habitaciones = 3, banos = 2,
                tipo_operacion = 'venta', estado = 'Encargo', updated_at = datetime(?)
            WHERE id = ?
            """,
            (now, matching_inmueble),
        )
        expensive_inmueble = server.ensure_inmueble_for_compraventa(
            self.conn,
            self.empresa_id,
            payload={
                "tipo_inmueble": "Piso",
                "direccion": "CALLE CARA 99",
                "referencia_catastral": "2468135UF7613S0001CC",
                "precio_encargo": "350000",
            },
            now=now,
        )
        self.conn.execute(
            """
            UPDATE inmuebles
            SET zona = 'Centro', m2 = 95, habitaciones = 4, banos = 2,
                tipo_operacion = 'venta', estado = 'Encargo', updated_at = datetime(?)
            WHERE id = ?
            """,
            (now, expensive_inmueble),
        )
        demanda_id = os.urandom(16).hex()
        self.conn.execute(
            """
            INSERT INTO demandas (
              id, empresa_id, cliente_id, pedido, tipo, zona, tipologia,
              precio_max, m2_min, habitaciones_min, banos_min, estado, fase,
              prioridad, responsable, notas, created_at, updated_at
            ) VALUES (
              ?, ?, ?, 'Pedido comprador match', 'Compra', 'Centro', 'Piso',
              220000, 70, 3, 1, 'Activa', 'En gestión',
              'Alta', 'SMOKE', 'Busca piso centro', datetime(?), datetime(?)
            )
            """,
            (demanda_id, self.empresa_id, buyer_id, now, now),
        )
        self.conn.commit()

        inmueble_matches = server.fetch_inmueble_matches_for_demanda(
            self.conn,
            self.empresa_id,
            demanda_id,
            limit=10,
        )
        self.assertTrue(inmueble_matches)
        self.assertEqual(inmueble_matches[0]["id"], matching_inmueble)
        self.assertNotIn(expensive_inmueble, {row["id"] for row in inmueble_matches})
        self.assertGreaterEqual(int(inmueble_matches[0]["score"] or 0), 80)
        self.assertIn("precio", inmueble_matches[0]["match_reasons"])

        demanda_matches = server.fetch_demanda_matches_for_inmueble(
            self.conn,
            matching_inmueble,
            limit=10,
        )
        self.assertTrue(demanda_matches)
        self.assertEqual(demanda_matches[0]["demanda_id"], demanda_id)
        self.assertEqual(demanda_matches[0]["cliente_id"], buyer_id)
        self.assertEqual(demanda_matches[0]["cliente"], "COMPRADOR MATCH")

        self.conn.execute(
            """
            INSERT INTO inmueble_compradores (
              id, empresa_id, inmueble_id, demanda_id, cliente_id, estado,
              fecha_ultimo_contacto, notas, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, 'Pendiente', ?, 'Añadido desde matching',
              datetime(?), datetime(?)
            )
            """,
            (os.urandom(16).hex(), self.empresa_id, matching_inmueble, demanda_id, buyer_id, now[:10], now, now),
        )
        self.conn.execute(
            """
            INSERT INTO visitas (
              id, empresa_id, inmueble_id, demanda_id, fecha, hora, estado,
              asesor, notas, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, '2026-05-30', '10:30', 'pendiente',
              'SMOKE', 'Visita desde cruce demanda/oferta', datetime(?), datetime(?)
            )
            """,
            (os.urandom(16).hex(), self.empresa_id, matching_inmueble, demanda_id, now, now),
        )
        self.conn.commit()

        buyer = server.resolve_inmobiliaria_contact_candidate(
            self.conn,
            self.empresa_id,
            {},
            demanda_id=demanda_id,
            inmueble_id=matching_inmueble,
        )
        self.assertEqual(buyer["cliente_id"], buyer_id)
        linked = self.conn.execute(
            """
            SELECT ic.demanda_id, ic.cliente_id, v.id AS visita_id
            FROM inmueble_compradores ic
            LEFT JOIN visitas v ON v.inmueble_id = ic.inmueble_id AND v.demanda_id = ic.demanda_id
            WHERE ic.inmueble_id = ? AND ic.demanda_id = ?
            LIMIT 1
            """,
            (matching_inmueble, demanda_id),
        ).fetchone()
        self.assertIsNotNone(linked)
        self.assertEqual(linked["cliente_id"], buyer_id)
        self.assertTrue(linked["visita_id"])

    def test_verifika2_public_portal_only_exposes_verified_published_active_inmuebles(self):
        now = _now_iso()
        owner_id = server.ensure_cliente_for_inmobiliaria(
            self.conn,
            self.empresa_id,
            nombre="PROPIETARIO PORTAL PRIVADO",
            nif="44444444A",
            now=now,
            extra={"telefono": "644444444", "email": "portal-owner@test.local"},
        )
        published_id = server.ensure_inmueble_for_compraventa(
            self.conn,
            self.empresa_id,
            payload={
                "tipo_inmueble": "Piso",
                "direccion": "CALLE PORTAL 1",
                "referencia_catastral": "1111111UF7613S0001AA",
                "precio_encargo": "210000",
            },
            now=now,
        )
        hidden_id = server.ensure_inmueble_for_compraventa(
            self.conn,
            self.empresa_id,
            payload={
                "tipo_inmueble": "Piso",
                "direccion": "CALLE OCULTA 2",
                "referencia_catastral": "1111111UF7613S0001AB",
                "precio_encargo": "200000",
            },
            now=now,
        )
        unverified_id = server.ensure_inmueble_for_compraventa(
            self.conn,
            self.empresa_id,
            payload={
                "tipo_inmueble": "Piso",
                "direccion": "CALLE NO VERIFICADA 3",
                "referencia_catastral": "1111111UF7613S0001AC",
                "precio_encargo": "190000",
            },
            now=now,
        )
        sold_id = server.ensure_inmueble_for_compraventa(
            self.conn,
            self.empresa_id,
            payload={
                "tipo_inmueble": "Piso",
                "direccion": "CALLE VENDIDA 4",
                "referencia_catastral": "1111111UF7613S0001AD",
                "precio_encargo": "180000",
            },
            now=now,
        )
        for inmueble_id in (published_id, hidden_id, unverified_id, sold_id):
            server.ensure_captacion_for_inmueble(self.conn, self.empresa_id, inmueble_id, now)
        server.ensure_inmueble_propietario_link(self.conn, published_id, owner_id, now)
        self.conn.execute(
            """
            UPDATE inmuebles
            SET estado = 'Encargo', portal_publicado = 1, portal_publicado_at = datetime(?),
                m2 = 90, habitaciones = 3, banos = 2, descripcion = 'Piso publicado en Verifika2',
                certificado = 1, updated_at = datetime(?)
            WHERE id = ?
            """,
            (now, now, published_id),
        )
        self.conn.execute(
            """
            UPDATE captaciones
            SET etapa = 'Encargo', situacion_comercial = 'Encargo', noticia_verificada = 1, updated_at = datetime(?)
            WHERE inmueble_id = ?
            """,
            (now, published_id),
        )
        self.conn.execute(
            "UPDATE inmuebles SET estado = 'Encargo', portal_publicado = 0, updated_at = datetime(?) WHERE id = ?",
            (now, hidden_id),
        )
        self.conn.execute(
            "UPDATE captaciones SET noticia_verificada = 1, updated_at = datetime(?) WHERE inmueble_id = ?",
            (now, hidden_id),
        )
        self.conn.execute(
            "UPDATE inmuebles SET estado = 'Encargo', portal_publicado = 1, portal_publicado_at = datetime(?), updated_at = datetime(?) WHERE id = ?",
            (now, now, unverified_id),
        )
        self.conn.execute(
            "UPDATE captaciones SET noticia_verificada = 0, updated_at = datetime(?) WHERE inmueble_id = ?",
            (now, unverified_id),
        )
        self.conn.execute(
            "UPDATE inmuebles SET estado = 'Vendido', portal_publicado = 1, portal_publicado_at = datetime(?), updated_at = datetime(?) WHERE id = ?",
            (now, now, sold_id),
        )
        self.conn.execute(
            "UPDATE captaciones SET noticia_verificada = 1, updated_at = datetime(?) WHERE inmueble_id = ?",
            (now, sold_id),
        )
        self.conn.execute(
            """
            INSERT INTO inmueble_docs (
              id, inmueble_id, nombre, url, tipo, estado, version, created_at, updated_at
            ) VALUES (
              ?, ?, 'Foto portal', '/uploads/inmuebles/portal/foto.jpg', 'Foto', 'Vigente', 1, datetime(?), datetime(?)
            )
            """,
            (os.urandom(16).hex(), published_id, now, now),
        )
        self.conn.commit()

        rows = server.fetch_portal_inmuebles_public(self.conn)
        ids = {row["id"] for row in rows}
        self.assertIn(published_id, ids)
        self.assertNotIn(hidden_id, ids)
        self.assertNotIn(unverified_id, ids)
        self.assertNotIn(sold_id, ids)
        row = next(item for item in rows if item["id"] == published_id)
        self.assertEqual(row["direccion"], "CALLE PORTAL 1")
        self.assertEqual(row["precio"], 210000)
        self.assertEqual(row["foto"], "/uploads/inmuebles/portal/foto.jpg")
        self.assertEqual(row["certificado"], 1)
        self.assertEqual(row["verificado"], 1)
        self.assertNotIn("propietarios", row)
        self.assertNotIn("cliente", row)

    def test_encargo_and_visit_pdfs_are_generated_with_real_case_data(self):
        now = _now_iso()
        owner_id = server.ensure_cliente_for_inmobiliaria(
            self.conn,
            self.empresa_id,
            nombre="PROPIETARIO PDF",
            nif="11111111H",
            now=now,
            extra={
                "telefono": "611111111",
                "email": "propietario.pdf@test.local",
                "direccion": "CALLE PROPIETARIO 7",
            },
        )
        buyer_id = server.ensure_cliente_for_inmobiliaria(
            self.conn,
            self.empresa_id,
            nombre="COMPRADOR PDF",
            nif="22222222J",
            now=now,
            extra={
                "telefono": "622222222",
                "email": "comprador.pdf@test.local",
                "direccion": "CALLE COMPRADOR 8",
            },
        )
        inmueble_id = server.ensure_inmueble_for_compraventa(
            self.conn,
            self.empresa_id,
            payload={
                "tipo_inmueble": "Piso",
                "direccion": "CALLE PDF ENCARGO 12",
                "referencia_catastral": "1357913UF7613S0001AA",
                "precio_encargo": "220000",
            },
            now=now,
        )
        server.ensure_inmueble_propietario_link(self.conn, inmueble_id, owner_id, now)
        server.sync_inmueble_stage_for_action(self.conn, inmueble_id, destino="encargo", now=now)
        self.conn.commit()

        empresa = dict(self.conn.execute("SELECT * FROM empresas WHERE id = ?", (self.empresa_id,)).fetchone())
        inmueble = dict(self.conn.execute("SELECT * FROM inmuebles WHERE id = ?", (inmueble_id,)).fetchone())
        captacion = dict(
            self.conn.execute(
                "SELECT * FROM captaciones WHERE inmueble_id = ? ORDER BY created_at DESC LIMIT 1",
                (inmueble_id,),
            ).fetchone()
        )
        owners = server.get_inmueble_propietarios(self.conn, inmueble_id)
        self.assertEqual(captacion["situacion_comercial"], "Encargo")
        self.assertEqual(captacion["etapa"], "Encargo")
        self.assertTrue(owners)

        encargo_pdf = server.build_inmueble_nota_encargo_pdf_final(
            empresa,
            inmueble,
            captacion,
            owners,
            extra={
                "tipo_operacion": "venta",
                "precio_venta": "220000",
                "honorarios_pct": "3",
                "iva_pct": "21",
                "fecha_inicio": "2026-05-29",
                "fecha_fin": "2026-11-29",
                "lugar_firma": "Madrid",
                "fecha_firma": "2026-05-29",
            },
        )
        self.assertTrue(encargo_pdf.startswith(b"%PDF"))
        self.assertGreater(len(encargo_pdf), 1000)
        encargo_text = _extract_pdf_text(encargo_pdf).upper()
        if encargo_text:
            self.assertIn("PDF ENCARGO", encargo_text)
            self.assertIn("PROPIETARIO PDF", encargo_text)
            self.assertIn("11111111H", encargo_text)
            self.assertTrue("220.000" in encargo_text or "220000" in encargo_text)

        encargo_doc = server.persist_generated_inmueble_pdf(
            self.conn,
            inmueble_id=inmueble_id,
            tipo="Nota de encargo (PDF final)",
            nombre="Nota de encargo (final) · CALLE PDF ENCARGO 12",
            pdf_bytes=encargo_pdf,
            filename_base="nota_encargo_final_pdf_encargo_12",
            now=now,
            replace_existing=False,
            empresa_id=self.empresa_id,
            usuario="smoke",
            plantilla_clave="nota_encargo_final",
            origen_tipo="inmueble_encargo_pdf_final",
            origen_id=inmueble_id,
            payload_json={"tipo_operacion": "venta", "precio_venta": "220000"},
        )
        self.assertTrue(encargo_doc and encargo_doc.get("url"))

        ficha_pdf = server.build_inmueble_consumo_sale_sheet_pdf(empresa, inmueble, captacion, [])
        self.assertTrue(ficha_pdf.startswith(b"%PDF"))
        ficha_doc = server.persist_generated_inmueble_pdf(
            self.conn,
            inmueble_id=inmueble_id,
            tipo="Documento informativo abreviado",
            nombre="Documento informativo abreviado · CALLE PDF ENCARGO 12",
            pdf_bytes=ficha_pdf,
            filename_base="dia_venta_pdf_encargo_12",
            now=now,
            replace_existing=True,
            empresa_id=self.empresa_id,
            usuario="smoke",
            plantilla_clave="venta_ficha",
            origen_tipo="visita_docs",
            origen_id=inmueble_id,
            payload_json={"kind": "venta_ficha"},
        )
        self.assertTrue(ficha_doc and ficha_doc.get("url"))

        precio_pdf = server.build_inmueble_consumo_sale_price_note_pdf(empresa, inmueble, captacion)
        self.assertTrue(precio_pdf.startswith(b"%PDF"))
        precio_doc = server.persist_generated_inmueble_pdf(
            self.conn,
            inmueble_id=inmueble_id,
            tipo="Justificación de precio",
            nombre="Justificación de precio · CALLE PDF ENCARGO 12",
            pdf_bytes=precio_pdf,
            filename_base="justificacion_precio_pdf_encargo_12",
            now=now,
            replace_existing=True,
            empresa_id=self.empresa_id,
            usuario="smoke",
            plantilla_clave="venta_precio",
            origen_tipo="visita_docs",
            origen_id=inmueble_id,
            payload_json={"kind": "venta_precio"},
        )
        self.assertTrue(precio_doc and precio_doc.get("url"))

        demanda_id = os.urandom(16).hex()
        demanda_cols = server.table_columns(self.conn, "demandas") or set()
        demanda_payload = {
            "id": demanda_id,
            "empresa_id": self.empresa_id,
            "cliente_id": buyer_id,
            "tipo": "Compra",
            "zona": "Centro",
            "estado": "Activa",
            "fase": "Captación",
            "prioridad": "Media",
            "responsable": "SMOKE",
            "created_at": now,
            "updated_at": now,
        }
        demanda_keys = [key for key in demanda_payload if key in demanda_cols]
        self.conn.execute(
            f"INSERT INTO demandas ({', '.join(demanda_keys)}) VALUES ({', '.join(['?'] * len(demanda_keys))})",
            [demanda_payload[key] for key in demanda_keys],
        )
        visita_id = os.urandom(16).hex()
        visita_cols = server.table_columns(self.conn, "visitas") or set()
        visita_payload = {
            "id": visita_id,
            "empresa_id": self.empresa_id,
            "inmueble_id": inmueble_id,
            "demanda_id": demanda_id,
            "fecha": "2026-05-30",
            "hora": "12:00",
            "estado": "pendiente",
            "asesor": "SMOKE",
            "notas": "Visita smoke con comprador PDF",
            "created_at": now,
            "updated_at": now,
        }
        visita_keys = [key for key in visita_payload if key in visita_cols]
        self.conn.execute(
            f"INSERT INTO visitas ({', '.join(visita_keys)}) VALUES ({', '.join(['?'] * len(visita_keys))})",
            [visita_payload[key] for key in visita_keys],
        )
        self.conn.commit()

        buyer = server.resolve_inmobiliaria_contact_candidate(
            self.conn,
            self.empresa_id,
            {},
            demanda_id=demanda_id,
            inmueble_id=inmueble_id,
        )
        self.assertEqual(buyer["cliente_id"], buyer_id)
        demanda = dict(self.conn.execute("SELECT * FROM demandas WHERE id = ?", (demanda_id,)).fetchone())
        visita_pdf = server.build_inmueble_visit_sheet_pdf(
            empresa,
            inmueble,
            captacion,
            owners,
            buyer,
            demanda,
        )
        self.assertTrue(visita_pdf.startswith(b"%PDF"))
        self.assertGreater(len(visita_pdf), 1000)
        visita_text = _extract_pdf_text(visita_pdf).upper()
        if visita_text:
            self.assertIn("HOJA DE VISITA", visita_text)
            self.assertIn("COMPRADOR PDF", visita_text)
            self.assertIn("22222222", visita_text)
            self.assertIn("PDF ENCARGO", visita_text)

        honorarios_pdf = server.build_inmueble_honorarios_ack_pdf_editable(
            empresa,
            inmueble,
            buyer,
            {
                "id": demanda_id,
                "inmueble_id": inmueble_id,
                "cliente_id": buyer_id,
                "documento_tipo": "Reconocimiento de honorarios",
                "importe_propuesta": inmueble.get("precio_objetivo"),
                "fecha": "2026-05-30",
            },
            extra={"iva_pct": "21", "lugar_firma": "Madrid"},
        )
        self.assertTrue(honorarios_pdf.startswith(b"%PDF"))
        honorarios_doc = server.persist_generated_inmueble_pdf(
            self.conn,
            inmueble_id=inmueble_id,
            tipo="Reconocimiento de honorarios",
            nombre="Reconocimiento de honorarios · COMPRADOR PDF · CALLE PDF ENCARGO 12",
            pdf_bytes=honorarios_pdf,
            filename_base="reconocimiento_honorarios_pdf_encargo_12",
            now=now,
            replace_existing=True,
            empresa_id=self.empresa_id,
            usuario="smoke",
            plantilla_clave="reconocimiento_honorarios",
            origen_tipo="visita_docs",
            origen_id=demanda_id,
            payload_json={"demanda_id": demanda_id, "cliente_id": buyer_id},
        )
        self.assertTrue(honorarios_doc and honorarios_doc.get("url"))

        visita_doc = server.persist_generated_inmueble_pdf(
            self.conn,
            inmueble_id=inmueble_id,
            tipo="Hoja de visita",
            nombre="Hoja de visita · CALLE PDF ENCARGO 12",
            pdf_bytes=visita_pdf,
            filename_base="hoja_visita_pdf_encargo_12",
            now=now,
            replace_existing=True,
            empresa_id=self.empresa_id,
            usuario="smoke",
            plantilla_clave="hoja_visita",
            origen_tipo="inmueble_visita_pdf",
            origen_id=demanda_id,
        )
        self.assertTrue(visita_doc and visita_doc.get("url"))
        stored = self.conn.execute(
            """
            SELECT plantilla_clave, origen_tipo, COUNT(*) AS total
            FROM inmueble_docs
            WHERE inmueble_id = ?
              AND plantilla_clave IN (
                'nota_encargo_final',
                'venta_ficha',
                'venta_precio',
                'hoja_visita',
                'reconocimiento_honorarios'
              )
            GROUP BY plantilla_clave, origen_tipo
            """,
            (inmueble_id,),
        ).fetchall()
        stored_keys = {(row["plantilla_clave"], row["origen_tipo"]) for row in stored}
        self.assertIn(("nota_encargo_final", "inmueble_encargo_pdf_final"), stored_keys)
        self.assertIn(("venta_ficha", "visita_docs"), stored_keys)
        self.assertIn(("venta_precio", "visita_docs"), stored_keys)
        self.assertIn(("hoja_visita", "inmueble_visita_pdf"), stored_keys)
        self.assertIn(("reconocimiento_honorarios", "visita_docs"), stored_keys)


if __name__ == "__main__":
    unittest.main()
