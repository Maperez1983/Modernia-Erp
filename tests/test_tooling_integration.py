import os
import sqlite3
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock
import subprocess
import sys
from urllib.parse import quote

from freezegun import freeze_time
from hypothesis import given, settings, strategies as st
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult

from web import public_links
from web import server


def _label_strategy():
    return st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=10)


def _path_segment_strategy():
    return st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_", min_size=1, max_size=10)


def _userinfo_strategy():
    return st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-", min_size=1, max_size=10)


class ToolingUrlPropertyTests(unittest.TestCase):
    @settings(max_examples=40, deadline=None)
    @given(
        scheme=st.sampled_from(("http", "https")),
        host_parts=st.lists(_label_strategy(), min_size=2, max_size=3),
        port=st.one_of(st.none(), st.integers(min_value=1, max_value=65535)),
        username=_userinfo_strategy(),
        password=_userinfo_strategy(),
        path_parts=st.lists(_path_segment_strategy(), min_size=0, max_size=3),
        query_value=st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.", min_size=0, max_size=12),
        fragment=st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.", min_size=0, max_size=12),
    )
    def test_url_sanitizers_strip_userinfo_query_and_fragment(
        self,
        scheme,
        host_parts,
        port,
        username,
        password,
        path_parts,
        query_value,
        fragment,
    ):
        host = ".".join(host_parts)
        path = f"/{'/'.join(path_parts)}" if path_parts else ""
        port_suffix = f":{port}" if port else ""
        raw = (
            f"{scheme}://{username}:{password}@{host}{port_suffix}{path}"
            f"?token={quote(query_value)}#frag={quote(fragment)}"
        )
        expected = f"{scheme}://{host}{port_suffix}{path}"

        self.assertEqual(server._sanitize_telemetry_path(raw), expected)
        self.assertEqual(public_links._normalize_url(raw), expected)

    @settings(max_examples=25, deadline=None)
    @given(
        base=st.sampled_from(("https://crm.example.com", "https://crm.example.com/base/")),
        fragment_key=st.sampled_from(("token", "activar_token", "portal_token")),
        token=st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.", min_size=0, max_size=12),
        path=st.sampled_from(("", "kiosk", "/kiosk")),
    )
    def test_public_fragment_urls_keep_expected_path(self, base, fragment_key, token, path):
        url = public_links.build_public_fragment_url(fragment_key, token, base_url=base, path=path)
        normalized_base = public_links._normalize_url(base)
        expected_path = "/kiosk" if path in {"kiosk", "/kiosk"} else ""
        expected = f"{normalized_base}{expected_path}#{fragment_key}={quote(token)}"
        self.assertEqual(url, expected)


class ToolingTimeTests(unittest.TestCase):
    def test_auth_session_expires_and_is_cleaned_up_with_freezegun(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "auth.sqlite"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            server.ensure_auth_sessions_table(conn)
            conn.close()

            def open_auth_store_conn(with_row_factory=True):
                connection = sqlite3.connect(db_path)
                if with_row_factory:
                    connection.row_factory = sqlite3.Row
                return connection

            user_row = {
                "id": "u-1",
                "usuario": "ana",
                "nombre": "Ana",
                "apellido": "López",
                "rol": "Miembro",
                "email": "ana@example.com",
                "servicio": "Gestoría",
            }

            auth_sessions = server.AUTH_SESSIONS
            auth_refresh = server.AUTH_SESSION_DB_REFRESH_AT
            auth_sessions.clear()
            auth_refresh.clear()
            try:
                with mock.patch.object(server, "open_auth_store_conn", side_effect=open_auth_store_conn):
                    with mock.patch.object(server, "APP_SESSION_TTL_SECONDS", 10):
                        with freeze_time("2026-07-19 10:00:00", tz_offset=0):
                            session = server.create_auth_session(user_row)
                            self.assertEqual(session["user_id"], "u-1")
                            self.assertAlmostEqual(session["expires_at"], time.time() + 10, delta=0.01)
                            self.assertIsNotNone(server.get_auth_session(session["token"]))

                        with freeze_time("2026-07-19 10:00:11", tz_offset=0):
                            server._cleanup_expired_sessions()
                            self.assertIsNone(server.AUTH_SESSIONS.get(session["token"]))
                            self.assertIsNone(server.get_auth_session(session["token"]))
                            conn = sqlite3.connect(db_path)
                            conn.row_factory = sqlite3.Row
                            try:
                                self.assertIsNone(
                                    conn.execute(
                                        "SELECT 1 FROM auth_sessions WHERE token = ?",
                                        [session["token"]],
                                    ).fetchone()
                                )
                            finally:
                                conn.close()
            finally:
                auth_sessions.clear()
                auth_refresh.clear()


class ToolingPostgresSmokeTests(unittest.TestCase):
    def test_open_db_conn_works_with_real_postgres_container(self):
        if not shutil.which("docker"):
            raise unittest.SkipTest("docker no está disponible")
        try:
            from testcontainers.postgres import PostgresContainer
        except Exception as exc:
            raise unittest.SkipTest(f"testcontainers postgres no disponible: {exc}") from exc

        image = os.environ.get("TESTCONTAINERS_POSTGRES_IMAGE") or "postgres:16-alpine"
        with PostgresContainer(image) as postgres:
            postgres_url = postgres.get_connection_url()
            with mock.patch.dict(
                os.environ,
                {
                    "APP_DB_BACKEND": "postgres",
                    "DATABASE_URL": postgres_url,
                    "POSTGRES_URL": postgres_url,
                },
                clear=False,
            ):
                conn = server.open_db_conn(str(Path(tempfile.gettempdir()) / "crm-modernia-postgres.sqlite"), with_row_factory=True)
                try:
                    self.assertEqual(getattr(conn, "__crm_backend__", ""), "postgres")
                    conn.execute("CREATE TABLE IF NOT EXISTS tooling_smoke (id TEXT PRIMARY KEY, value TEXT)")
                    conn.execute("INSERT INTO tooling_smoke (id, value) VALUES (?, ?)", ("1", "ok"))
                    conn.commit()
                    row = conn.execute("SELECT value FROM tooling_smoke WHERE id = ?", ("1",)).fetchone()
                    self.assertIsNotNone(row)
                    self.assertEqual(row["value"], "ok")
                finally:
                    conn.close()


class ToolingLocustTests(unittest.TestCase):
    def test_locustfile_imports_and_declares_expected_tasks(self):
        env = os.environ.copy()
        env["LOCUST_SKIP_MONKEY_PATCH"] = "1"
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "from loadtests.locustfile import CRMUser; assert CRMUser.host",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)


class ToolingTelemetryTests(unittest.TestCase):
    def test_opentelemetry_sdk_exports_a_span(self):
        class _MemoryExporter:
            def __init__(self):
                self.spans = []

            def export(self, spans):
                self.spans.extend(spans)
                return SpanExportResult.SUCCESS

            def shutdown(self):
                return None

            def force_flush(self, timeout_millis=None):
                return True

        exporter = _MemoryExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("crm-modernia-tests")
        with tracer.start_as_current_span("tooling-smoke"):
            pass
        spans = exporter.spans
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].name, "tooling-smoke")


class ToolingHttpMockTests(unittest.TestCase):
    def test_respx_can_mock_httpx_get(self):
        import httpx
        import respx

        with respx.mock(assert_all_called=True) as router:
            route = router.get("https://example.test/api").respond(200, json={"ok": True})
            response = httpx.get("https://example.test/api", timeout=5)

        self.assertTrue(route.called)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
