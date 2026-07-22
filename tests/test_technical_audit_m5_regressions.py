import json
import sqlite3
import threading
import unittest
from datetime import datetime, timedelta
from unittest import mock

from web import server


FIXED_NOW = datetime(2026, 7, 14, 12, 0, 0)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FIXED_NOW
        return FIXED_NOW.replace(tzinfo=tz)


class CountingConnection:
    def __init__(self, conn):
        self._conn = conn
        self.execute_count = 0
        self.executed_sql = []

    def execute(self, sql, params=None):
        self.execute_count += 1
        self.executed_sql.append(str(sql).strip())
        if params is None:
            return self._conn.execute(sql)
        return self._conn.execute(sql, params)

    def executemany(self, sql, seq_of_params):
        self.executed_sql.append(str(sql).strip())
        return self._conn.executemany(sql, seq_of_params)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


class DummyConnection:
    def __init__(self):
        self.commit_count = 0

    def commit(self):
        self.commit_count += 1
        return None

    def rollback(self):
        return None

    def close(self):
        return None


class TechnicalAuditM5RegressionTests(unittest.TestCase):
    def setUp(self):
        self._datetime_patch = mock.patch.object(server, "datetime", FixedDateTime)
        self._datetime_patch.start()
        self.addCleanup(self._datetime_patch.stop)

    def _create_overview_conn(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        server.ensure_workspace_core_tables(conn)
        server.ensure_workspace_product_tables(conn)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS empresas (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              activo INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS clientes (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              nif TEXT,
              email TEXT,
              telefono TEXT,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS clientes_empresas (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              empresa_id TEXT,
              cliente_id TEXT,
              servicio TEXT,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS cliente_gestoria (
              id TEXT PRIMARY KEY,
              cliente_id TEXT NOT NULL,
              mod_renta INTEGER NOT NULL DEFAULT 0,
              renta_detalles TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS gestoria_modelos (
              id TEXT PRIMARY KEY,
              cliente_id TEXT,
              modelo TEXT,
              proxima_fecha TEXT,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS workspace_presupuestos (
              id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              empresa_id TEXT,
              cliente_id TEXT,
              servicio TEXT,
              referencia_tipo TEXT,
              referencia_id TEXT,
              titulo TEXT NOT NULL,
              estado TEXT NOT NULL DEFAULT 'Borrador',
              fecha TEXT,
              fecha_seguimiento TEXT,
              motivo_estado TEXT,
              responsable TEXT,
              forma_pago TEXT,
              encargo_estado TEXT,
              fecha_encargo TEXT,
              observaciones TEXT,
              subtotal REAL,
              impuestos REAL,
              total REAL,
              calculo_json TEXT,
              seguimiento_accion_id TEXT,
              encargo_accion_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS acciones (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              cliente_nombre TEXT,
              servicio TEXT,
              tipo TEXT,
              estado TEXT,
              fecha TEXT,
              hora TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS seguros (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              tomador TEXT,
              compania TEXT,
              ramo TEXT,
              estado TEXT,
              estado_poliza TEXT,
              poliza_numero TEXT,
              fecha_efecto TEXT,
              fecha_vencimiento TEXT,
              fecha_baja TEXT,
              prima_total REAL,
              prima_neta REAL,
              poliza_key TEXT,
              poliza_url TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              cliente TEXT,
              banco TEXT,
              estado TEXT,
              fecha_firma TEXT,
              fecha_encargo TEXT,
              encargo TEXT,
              comision REAL,
              comision_modernia REAL,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS asesoramientos_financiacion (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente1_id TEXT,
              cliente2_id TEXT,
              cliente1_nombre TEXT,
              cliente2_nombre TEXT,
              estado TEXT,
              fecha TEXT,
              ingresos_conjuntos REAL,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS gestoria_docs (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              referencia_tipo TEXT,
              referencia_id TEXT,
              nombre TEXT,
              tipo TEXT,
              fecha TEXT,
              estado TEXT,
              notas TEXT,
              doc_key TEXT,
              doc_url TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS inmuebles (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              direccion TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS inmueble_docs (
              id TEXT PRIMARY KEY,
              inmueble_id TEXT,
              nombre TEXT,
              tipo TEXT,
              url TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            """
        )

        today = FIXED_NOW.date()
        yesterday = today - timedelta(days=1)
        next_week = today + timedelta(days=7)
        next_10_days = today + timedelta(days=10)
        next_month = today + timedelta(days=40)
        last_year = today.year - 1

        conn.executemany(
            "INSERT INTO empresas (id, nombre, activo) VALUES (?, ?, ?)",
            [
                ("emp-1", "Empresa Uno", 1),
                ("emp-2", "Empresa Dos", 1),
            ],
        )
        conn.execute(
            "INSERT INTO workspaces (id, nombre, slug, estado, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("ws-main", "Workspace Principal", "workspace-principal", "Activo", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
        )
        conn.executemany(
            "INSERT INTO workspace_companies (id, workspace_id, legacy_empresa_id, nombre, activo, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("wc-1", "ws-main", "emp-1", "Empresa Uno", 1, FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
                ("wc-2", "ws-main", "emp-2", "Empresa Dos", 1, FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
            ],
        )
        conn.executemany(
            "INSERT INTO workspace_empresas (id, workspace_id, empresa_id, rol, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("we-1", "ws-main", "emp-1", "Principal", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
                ("we-2", "ws-main", "emp-2", "Secundaria", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
            ],
        )
        conn.execute(
            "INSERT INTO clientes (id, nombre, nif, email, telefono, estado, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "cli-1",
                "Cliente Uno",
                "12345678A",
                "cliente@example.com",
                "600000000",
                "Activo",
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
            ),
        )
        conn.execute(
            "INSERT INTO clientes_empresas (id, workspace_id, empresa_id, cliente_id, servicio, estado, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ce-1",
                "ws-main",
                "emp-1",
                "cli-1",
                "gestoria",
                "Activo",
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
            ),
        )
        renta_details = {
            "entries": [
                {
                    "id": "renta-1",
                    "ejercicio": str(last_year),
                    "estado_presentacion": "Borrador",
                    "presentacion_fecha": f"{last_year}-06-01",
                    "doc_key": "doc-renta-1",
                }
            ]
        }
        conn.execute(
            "INSERT INTO cliente_gestoria (id, cliente_id, mod_renta, renta_detalles, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "cg-1",
                "cli-1",
                1,
                json.dumps(renta_details, ensure_ascii=False),
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
            ),
        )
        conn.execute(
            "INSERT INTO gestoria_modelos (id, cliente_id, modelo, proxima_fecha, estado, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "gm-1",
                "cli-1",
                "Modelo 100",
                yesterday.isoformat(),
                "Pendiente",
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
            ),
        )
        conn.executemany(
            "INSERT INTO acciones (id, empresa_id, cliente_id, cliente_nombre, servicio, tipo, estado, fecha, hora, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "ac-gestoria-1",
                    "emp-1",
                    "cli-1",
                    "Cliente Uno",
                    "gestoria",
                    "Recordatorio",
                    "Pendiente",
                    today.isoformat(),
                    "09:00",
                    FIXED_NOW.isoformat(),
                    FIXED_NOW.isoformat(),
                ),
                (
                    "ac-gestoria-2",
                    "emp-1",
                    "cli-1",
                    "Cliente Uno",
                    "gestoria",
                    "Aviso",
                    "Pendiente",
                    yesterday.isoformat(),
                    "09:00",
                    FIXED_NOW.isoformat(),
                    FIXED_NOW.isoformat(),
                ),
                (
                    "ac-seguros-1",
                    "emp-1",
                    "cli-1",
                    "Cliente Uno",
                    "seguros",
                    "Llamada",
                    "Pendiente",
                    next_week.isoformat(),
                    "11:00",
                    FIXED_NOW.isoformat(),
                    FIXED_NOW.isoformat(),
                ),
                (
                    "ac-fin-1",
                    "emp-1",
                    "cli-1",
                    "Cliente Uno",
                    "financiaciones",
                    "Llamada",
                    "Pendiente",
                    next_week.isoformat(),
                    "12:00",
                    FIXED_NOW.isoformat(),
                    FIXED_NOW.isoformat(),
                ),
            ],
        )
        conn.execute(
            "INSERT INTO workspace_presupuestos (id, workspace_id, empresa_id, cliente_id, servicio, referencia_tipo, referencia_id, titulo, estado, fecha, fecha_seguimiento, motivo_estado, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "wp-1",
                "ws-main",
                "emp-1",
                "cli-1",
                "gestoria",
                "cliente",
                "cli-1",
                "Propuesta Gestoria",
                "Estudio",
                today.isoformat(),
                today.isoformat(),
                "Esperando docs",
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
            ),
        )
        conn.executemany(
            "INSERT INTO seguros (id, empresa_id, cliente_id, tomador, compania, ramo, estado, estado_poliza, fecha_efecto, fecha_vencimiento, fecha_baja, prima_total, prima_neta, poliza_key, poliza_url, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "seg-1",
                    "emp-1",
                    "cli-1",
                    "Cliente Uno",
                    "Mapfre",
                    "Hogar",
                    "En vigor",
                    "Activa",
                    today.replace(day=1).isoformat(),
                    next_10_days.isoformat(),
                    "",
                    120.0,
                    120.0,
                    "poliza-key-1",
                    "",
                    FIXED_NOW.isoformat(),
                    FIXED_NOW.isoformat(),
                ),
                (
                    "seg-2",
                    "emp-1",
                    "cli-1",
                    "Cliente Uno",
                    "Allianz",
                    "Vida",
                    "Presupuesto",
                    "",
                    next_month.isoformat(),
                    "",
                    "",
                    80.0,
                    80.0,
                    "",
                    "",
                    FIXED_NOW.isoformat(),
                    FIXED_NOW.isoformat(),
                ),
            ],
        )
        conn.execute(
            "INSERT INTO hipotecas (id, empresa_id, cliente_id, cliente, banco, estado, fecha_firma, fecha_encargo, encargo, comision, comision_modernia, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "hip-1",
                "emp-1",
                "cli-1",
                "Cliente Uno",
                "Banco A",
                "Firmada",
                today.isoformat(),
                today.isoformat(),
                "Pendiente",
                1000.0,
                0.0,
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
            ),
        )
        conn.execute(
            "INSERT INTO asesoramientos_financiacion (id, empresa_id, cliente1_id, cliente2_id, cliente1_nombre, cliente2_nombre, estado, fecha, ingresos_conjuntos, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ase-1",
                "emp-1",
                "cli-1",
                "",
                "Cliente Uno",
                "",
                "Pendiente",
                today.isoformat(),
                150000.0,
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
            ),
        )
        conn.executemany(
            "INSERT INTO gestoria_docs (id, empresa_id, cliente_id, referencia_tipo, referencia_id, nombre, tipo, fecha, estado, notas, doc_key, doc_url, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "gd-1",
                    "emp-1",
                    None,
                    "gestoria",
                    "",
                    "Factura 12345678A",
                    "Factura",
                    today.isoformat(),
                    "Vigente",
                    "12345678A",
                    "",
                    "/docs/gestoria.pdf",
                    FIXED_NOW.isoformat(),
                    FIXED_NOW.isoformat(),
                ),
            ],
        )
        conn.execute(
            "INSERT INTO inmuebles (id, empresa_id, direccion, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("inm-1", "emp-1", "Calle Falsa 123", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO inmueble_docs (id, inmueble_id, nombre, tipo, url, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "idoc-1",
                "inm-1",
                "Nota simple",
                "Nota",
                "/docs/inmueble.pdf",
                yesterday.isoformat(),
                yesterday.isoformat(),
            ),
        )
        conn.commit()
        return conn

    def _create_sweep_conn(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        server.ensure_workspace_core_tables(conn)
        server.ensure_workspace_product_tables(conn)
        conn.execute(
            "INSERT INTO workspaces (id, nombre, slug, estado, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("ws-ok", "Workspace OK", "ws-ok", "Activo", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO workspaces (id, nombre, slug, estado, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("ws-inactive", "Workspace Inactive", "ws-inactive", "Inactivo", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO workspaces (id, nombre, slug, estado, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("ws-no-module", "Workspace No Module", "ws-no-module", "Activo", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
        )
        conn.execute(
            "INSERT INTO workspaces (id, nombre, slug, estado, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("ws-no-personal", "Workspace No Personal", "ws-no-personal", "Activo", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
        )
        conn.executemany(
            "INSERT INTO workspace_modulos (id, workspace_id, modulo_key, modulo_nombre, categoria, enabled, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("wm-1", "ws-ok", "registro_horario", "Registro horario", "rrhh", 1, 1, FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
                ("wm-2", "ws-inactive", "registro_horario", "Registro horario", "rrhh", 1, 1, FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
                ("wm-3", "ws-no-personal", "registro_horario", "Registro horario", "rrhh", 1, 1, FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
            ],
        )
        conn.executemany(
            "INSERT INTO workspace_registro_personal (id, workspace_id, empresa_id, nombre, activo, alert_missing_checkin, alert_missing_checkout, alert_notify_worker, alert_notify_admin, alert_admin_contact, alert_last_sent, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("rp-1", "ws-ok", "emp-1", "Persona OK", 1, 1, 1, 1, 1, "", "", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
                ("rp-2", "ws-inactive", "emp-1", "Persona Inactiva", 1, 1, 1, 1, 1, "", "", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
                ("rp-3", "ws-no-module", "emp-1", "Persona Sin Modulo", 1, 1, 1, 1, 1, "", "", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
                ("rp-4", "ws-no-personal", "emp-1", "Persona Desactivada", 0, 1, 1, 1, 1, "", "", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
            ],
        )
        conn.executemany(
            "INSERT INTO workspace_rrhh_turnos (id, workspace_id, persona_id, weekday, enabled, hora_inicio, hora_fin, pausa_min, notas, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("turn-1", "ws-ok", "rp-1", 2, 1, "09:00", "17:00", 0, "", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
                ("turn-2", "ws-inactive", "rp-2", 2, 1, "09:00", "17:00", 0, "", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
                ("turn-3", "ws-no-personal", "rp-4", 2, 1, "09:00", "17:00", 0, "", FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
            ],
        )
        conn.commit()
        return conn

    def test_gestoria_overview_counts_and_single_renta_query(self):
        conn = self._create_overview_conn()
        counting = CountingConnection(conn)

        with mock.patch.object(
            server,
            "table_columns",
            side_effect=lambda _conn, table: {
                "workspace_companies": {"workspace_id", "legacy_empresa_id", "activo", "nombre"},
                "workspace_empresas": {"workspace_id", "empresa_id"},
            }.get(table, set()),
        ):
            result = server.fetch_workspace_gestoria_overview(counting, "ws-main")

        self.assertEqual(result["counts"]["total"], 1)
        self.assertEqual(result["counts"]["activos"], 1)
        self.assertEqual(result["counts"]["modelos_mes"], 1)
        self.assertEqual(result["counts"]["rentas_pendientes_presentar"], 1)
        self.assertEqual(result["counts"]["acciones_pendientes"], 1)
        self.assertEqual(result["counts"]["presupuestos_estudio"], 1)
        self.assertEqual(len(result["modelos_vencidos"]), 1)
        self.assertEqual(len(result["rentas_pendientes"]), 1)
        self.assertEqual(len(result["acciones_vencidas"]), 1)
        self.assertEqual(len(result["presupuestos_estudio"]), 1)
        self.assertEqual(counting.execute_count, 8)
        conn.close()

    def test_gestoria_overview_counts_presupuestos_de_fincas_labels(self):
        conn = self._create_overview_conn()
        conn.execute(
            "INSERT INTO workspace_presupuestos (id, workspace_id, empresa_id, cliente_id, servicio, referencia_tipo, referencia_id, titulo, estado, fecha, fecha_seguimiento, motivo_estado, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "wp-fincas",
                "ws-main",
                "emp-1",
                "cli-1",
                "administración de fincas",
                "cliente",
                "cli-1",
                "Propuesta Fincas",
                "Estudio",
                FIXED_NOW.date().isoformat(),
                FIXED_NOW.date().isoformat(),
                "Esperando docs",
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
            ),
        )
        conn.execute(
            "INSERT INTO workspace_presupuestos (id, workspace_id, empresa_id, cliente_id, servicio, referencia_tipo, referencia_id, titulo, estado, fecha, fecha_seguimiento, motivo_estado, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "wp-comunidad",
                "ws-main",
                "emp-1",
                "cli-1",
                "Comunidades Velazquez",
                "cliente",
                "cli-1",
                "Propuesta Comunidad",
                "Estudio",
                FIXED_NOW.date().isoformat(),
                FIXED_NOW.date().isoformat(),
                "Esperando docs",
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
            ),
        )

        result = server.fetch_workspace_gestoria_overview(conn, "ws-main")
        presupuestos = {row["titulo"] for row in result["presupuestos_estudio"]}
        conn.close()

        self.assertEqual(result["counts"]["presupuestos_estudio"], 3)
        self.assertEqual(presupuestos, {"Propuesta Gestoria", "Propuesta Fincas", "Propuesta Comunidad"})

    def test_overviews_keep_expected_shapes_and_counts(self):
        conn = self._create_overview_conn()

        gestoria = server.fetch_workspace_gestoria_overview(conn, "ws-main")
        seguros = server.fetch_workspace_seguros_overview(conn, "ws-main")
        fin = server.fetch_workspace_fin_overview(conn, "ws-main")
        docs = server.fetch_workspace_document_hub(conn, "ws-main", limit=20)

        self.assertEqual(gestoria["counts"]["total"], 1)
        self.assertEqual(gestoria["counts"]["activos"], 1)
        self.assertEqual(gestoria["counts"]["modelos_mes"], 1)
        self.assertEqual(gestoria["counts"]["rentas_pendientes_presentar"], 1)
        self.assertEqual(gestoria["counts"]["acciones_pendientes"], 1)
        self.assertEqual(gestoria["counts"]["presupuestos_estudio"], 1)

        self.assertEqual(seguros["counts"]["total"], 2)
        self.assertEqual(seguros["counts"]["en_vigor"], 1)
        self.assertEqual(seguros["counts"]["presupuesto"], 1)
        self.assertEqual(seguros["counts"]["renovaciones_30d"], 1)
        self.assertEqual(seguros["counts"]["subidas_total"], 1)
        self.assertEqual(seguros["counts"]["subidas_en_vigor"], 1)
        self.assertEqual(seguros["counts"]["alertas_abiertas"], 1)
        self.assertEqual(len(seguros["renovaciones_proximas"]), 1)
        self.assertEqual(len(seguros["alertas_comerciales"]), 1)
        self.assertEqual(len(seguros["top_companias"]), 2)
        self.assertEqual(len(seguros["top_ramos"]), 2)
        self.assertEqual(len(seguros["entradas_mes"]), 1)
        self.assertEqual(len(seguros["en_vigor_por_mes"]["labels"]), 12)
        self.assertEqual(len(seguros["en_vigor_por_mes"]["values"]), 12)

        self.assertEqual(fin["counts"]["total"], 1)
        self.assertEqual(fin["counts"]["firmadas"], 1)
        self.assertEqual(fin["counts"]["asesoramientos_abiertos"], 1)
        self.assertEqual(fin["counts"]["encargos_abiertos"], 1)
        self.assertEqual(fin["counts"]["alertas_abiertas"], 1)
        self.assertEqual(len(fin["asesoramientos_abiertos"]), 1)
        self.assertEqual(len(fin["firmas_recientes"]), 1)
        self.assertEqual(len(fin["alertas_comerciales"]), 1)
        self.assertEqual(len(fin["top_bancos"]), 1)

        self.assertEqual(docs["summary"]["documentos_total"], 2)
        self.assertEqual(docs["summary"]["pendientes_asignacion"], 1)
        self.assertEqual(len(docs["rows"]), 2)
        self.assertEqual(docs["rows"][0]["assignable"], 1)
        self.assertEqual(docs["rows"][0]["suggested_cliente_id"], "cli-1")
        self.assertEqual(docs["rows"][1]["assignable"], 0)
        conn.close()

    def test_workspace_time_sweep_skips_inactive_and_unconfigured_workspaces(self):
        conn = self._create_sweep_conn()
        ids = server._workspace_time_sweep_candidate_rows(conn, batch_size=10)
        self.assertEqual(ids, ["ws-ok"])
        conn.close()

    def test_workspace_time_sweep_cycle_does_not_overlap(self):
        conn = DummyConnection()
        call_started = threading.Event()
        release_call = threading.Event()
        results = []

        def run_side_effect(conn_arg, workspace_id, now=None):
            call_started.set()
            release_call.wait(timeout=2)
            return []

        with mock.patch.object(server, "_ensure_workspace_time_sweep_schema", return_value=True):
            with mock.patch.object(server, "_workspace_time_sweep_candidate_rows", return_value=["ws-1"]):
                with mock.patch.object(server, "run_workspace_time_missing_sweep", side_effect=run_side_effect) as sweep_mock:
                    def target():
                        results.append(server._run_workspace_time_sweep_cycle(conn, batch_size=5))

                    thread = threading.Thread(target=target)
                    thread.start()
                    self.assertTrue(call_started.wait(timeout=2))
                    skipped = server._run_workspace_time_sweep_cycle(conn, batch_size=5)
                    release_call.set()
                    thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(sweep_mock.call_count, 1)
        self.assertEqual(skipped["skipped"], True)
        self.assertEqual(results[0]["skipped"], False)
        self.assertEqual(results[0]["workspaces"], 1)

    def test_workspace_time_sweep_cycle_continues_after_workspace_error(self):
        conn = DummyConnection()
        seen = []

        def run_side_effect(conn_arg, workspace_id, now=None):
            seen.append(workspace_id)
            if workspace_id == "ws-bad":
                raise RuntimeError("boom")
            return []

        with mock.patch.object(server, "_ensure_workspace_time_sweep_schema", return_value=True):
            with mock.patch.object(server, "_workspace_time_sweep_candidate_rows", return_value=["ws-good", "ws-bad", "ws-after"]):
                with mock.patch.object(server, "run_workspace_time_missing_sweep", side_effect=run_side_effect):
                    result = server._run_workspace_time_sweep_cycle(conn, batch_size=10)

        self.assertEqual(seen, ["ws-good", "ws-bad", "ws-after"])
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["workspaces"], 3)
        self.assertFalse(result["skipped"])

    def test_workspace_time_sweep_cycle_commits_bootstrap_on_quiet_cycles(self):
        conn = DummyConnection()

        with mock.patch.object(server, "_ensure_workspace_time_sweep_schema", return_value=True):
            with mock.patch.object(server, "_workspace_time_sweep_candidate_rows", return_value=[]):
                result = server._run_workspace_time_sweep_cycle(conn, batch_size=10)

        self.assertFalse(result["skipped"])
        self.assertEqual(conn.commit_count, 1)

    def test_run_workspace_time_missing_sweep_avoids_n_plus_one(self):
        conn = self._create_sweep_conn()
        for idx in range(5):
            persona_id = f"rp-q-{idx}"
            conn.execute(
                "INSERT INTO workspace_registro_personal (id, workspace_id, empresa_id, nombre, activo, alert_missing_checkin, alert_missing_checkout, alert_notify_worker, alert_notify_admin, alert_admin_contact, alert_last_sent, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    persona_id,
                    "ws-ok",
                    "emp-1",
                    f"Persona {idx}",
                    1,
                    1,
                    1,
                    0,
                    0,
                    "",
                    "",
                    FIXED_NOW.isoformat(),
                    FIXED_NOW.isoformat(),
                ),
            )
            conn.execute(
                "INSERT INTO workspace_rrhh_turnos (id, workspace_id, persona_id, weekday, enabled, hora_inicio, hora_fin, pausa_min, notas, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"turn-q-{idx}",
                    "ws-ok",
                    persona_id,
                    2,
                    1,
                    "09:00",
                    "17:00",
                    0,
                    "",
                    FIXED_NOW.isoformat(),
                    FIXED_NOW.isoformat(),
                ),
            )
        conn.commit()
        counting = CountingConnection(conn)

        result = server.run_workspace_time_missing_sweep(
            counting,
            "ws-ok",
            now="2026-07-14T08:00:00+00:00",
        )

        self.assertEqual(result, [])
        self.assertEqual(counting.execute_count, 4)
        self.assertTrue(any("ROW_NUMBER() OVER" in sql for sql in counting.executed_sql))
        counting.close()

    def test_compute_worked_minutes_wraps_across_midnight(self):
        self.assertEqual(server.compute_worked_minutes("22:00", "06:30", 30), 480)
        self.assertEqual(server.compute_worked_minutes("23:15", "00:15", 0), 60)

    def test_fetch_workspace_latest_time_entry_returns_previous_day_open_shift(self):
        conn = self._create_sweep_conn()
        yesterday = (FIXED_NOW.date() - timedelta(days=1)).isoformat()
        conn.execute(
            """
            INSERT INTO workspace_registro_horario (
              id, workspace_id, empresa_id, persona_id, usuario_id, persona_nombre,
              fecha, hora_inicio, hora_fin, pausa_min, minutos_trabajados, metodo_registro,
              estado, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "time-overnight",
                "ws-ok",
                "emp-1",
                "rp-1",
                "u-1",
                "Persona OK",
                yesterday,
                "22:00",
                "",
                0,
                0,
                "Manual",
                "Abierto",
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
            ),
        )
        conn.commit()

        try:
            row = server.fetch_workspace_latest_time_entry(conn, "ws-ok", "rp-1", upto_date=FIXED_NOW.date().isoformat(), only_open=True)
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["fecha"], yesterday)
        self.assertEqual(row["hora_inicio"], "22:00")
        self.assertEqual(row["hora_fin"], "")

    def test_run_workspace_time_missing_sweep_detects_overnight_open_shift(self):
        conn = self._create_sweep_conn()
        yesterday = (FIXED_NOW.date() - timedelta(days=1)).isoformat()
        conn.execute(
            """
            INSERT INTO workspace_registro_horario (
              id, workspace_id, empresa_id, persona_id, usuario_id, persona_nombre,
              fecha, hora_inicio, hora_fin, pausa_min, minutos_trabajados, metodo_registro,
              estado, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "time-overnight",
                "ws-ok",
                "emp-1",
                "rp-1",
                "u-1",
                "Persona OK",
                yesterday,
                "22:00",
                "",
                0,
                0,
                "Manual",
                "Abierto",
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
            ),
        )
        conn.commit()

        try:
            created = server.run_workspace_time_missing_sweep(
                conn,
                "ws-ok",
                now="2026-07-14T19:00:00+00:00",
            )
        finally:
            conn.close()

        self.assertIn("worker_missing_checkout", created)
        self.assertIn("admin_missing_checkout", created)

    def test_m5_perf_indexes_are_created_once_on_sqlite(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE workspaces (
              id TEXT PRIMARY KEY,
              estado TEXT,
              updated_at TEXT,
              created_at TEXT,
              nombre TEXT
            );
            CREATE TABLE workspace_registro_personal (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              activo INTEGER,
              nombre TEXT
            );
            CREATE TABLE workspace_registro_alerts (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              persona_id TEXT
            );
            CREATE TABLE workspace_registro_horario (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              persona_id TEXT,
              fecha TEXT,
              hora_inicio TEXT
            );
            CREATE TABLE gestoria_docs (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              created_at TEXT
            );
            CREATE TABLE hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              fecha_firma TEXT
            );
            CREATE TABLE asesoramientos_financiacion (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              estado TEXT,
              fecha TEXT
            );
            """
        )
        counting = CountingConnection(conn)

        first = server._ensure_m5_perf_indexes(counting)
        second = server._ensure_m5_perf_indexes(counting)
        index_sql = [sql for sql in counting.executed_sql if sql.upper().startswith("CREATE INDEX")]

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(index_sql), 7)
        self.assertEqual(
            counting.execute(
                "SELECT COUNT(*) AS total FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%'"
            ).fetchone()["total"],
            7,
        )
        counting.close()

    def test_m5_perf_indexes_use_standard_ddl_on_postgres(self):
        class FakeResult:
            def fetchone(self):
                return None

            def fetchall(self):
                return []

        class FakeConn:
            def __init__(self):
                self.sql = []

            def execute(self, sql, params=None):
                self.sql.append(str(sql).strip())
                return FakeResult()

        fake_conn = FakeConn()
        with mock.patch.object(server, "_db_backend_name", return_value="postgres"):
            with mock.patch.object(server, "_m5_migration_done", return_value=False):
                with mock.patch.object(server, "_m5_migration_mark", return_value=None):
                    result = server._ensure_m5_perf_indexes(fake_conn)

        self.assertTrue(result)
        self.assertTrue(
            any(
                "CREATE INDEX IF NOT EXISTS idx_workspaces_estado_updated_nombre" in sql
                for sql in fake_conn.sql
            )
        )
        self.assertFalse(any("CONCURRENTLY" in sql for sql in fake_conn.sql))


if __name__ == "__main__":
    unittest.main()
