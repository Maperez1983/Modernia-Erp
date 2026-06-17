import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import render_backend_guard


class RenderBackendGuardTests(unittest.TestCase):
    def test_project_backend_mode_prefers_postgres_from_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("POSTGRES_URL=postgresql://demo\n", encoding="utf-8")
            with patch.object(render_backend_guard, "ENV_PATH", env_path):
                with patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(render_backend_guard.project_backend_mode(), "postgres")

    def test_guard_blocks_sqlite_sync_when_project_is_postgres(self):
        with patch.object(render_backend_guard, "project_backend_mode", return_value="postgres"):
            with self.assertRaises(SystemExit) as ctx:
                render_backend_guard.guard_remote_sqlite_sync(script_name="sync_compraventas_to_render.py")
        self.assertIn("Postgres", str(ctx.exception))

    def test_guard_allows_force_override(self):
        with patch.object(render_backend_guard, "project_backend_mode", return_value="postgres"):
            render_backend_guard.guard_remote_sqlite_sync(force=True, script_name="sync_compraventas_to_render.py")


if __name__ == "__main__":
    unittest.main()
