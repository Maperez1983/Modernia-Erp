import os
import sqlite3
import sys
import types
import unittest

try:
    import PIL  # noqa: F401
except Exception:
    if "PIL" not in sys.modules:
        pil_stub = types.ModuleType("PIL")
        pil_stub.Image = object()
        pil_stub.ImageDraw = object()
        pil_stub.ImageEnhance = object()
        pil_stub.ImageFilter = object()
        pil_stub.ImageFont = object()
        pil_stub.ImageOps = object()
        sys.modules["PIL"] = pil_stub

from web.server import is_superadmin_actor
from web.server import workspace_actor_is_privileged


class PrivilegeRefreshTests(unittest.TestCase):
    def setUp(self):
        self._superadmin_enforce = os.environ.get("APP_SUPERADMIN_ENFORCE")
        self._superadmin_usernames = os.environ.get("APP_SUPERADMIN_USERNAMES")
        self._superadmin_emails = os.environ.get("APP_SUPERADMIN_EMAILS")
        self._superadmin_ids = os.environ.get("APP_SUPERADMIN_IDS")
        os.environ.pop("APP_SUPERADMIN_ENFORCE", None)
        os.environ.pop("APP_SUPERADMIN_USERNAMES", None)
        os.environ.pop("APP_SUPERADMIN_EMAILS", None)
        os.environ.pop("APP_SUPERADMIN_IDS", None)
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE usuarios (
              id TEXT PRIMARY KEY,
              rol TEXT,
              servicio TEXT,
              activo INTEGER DEFAULT 1
            );
            """
        )

    def tearDown(self):
        if self._superadmin_enforce is None:
            os.environ.pop("APP_SUPERADMIN_ENFORCE", None)
        else:
            os.environ["APP_SUPERADMIN_ENFORCE"] = self._superadmin_enforce
        if self._superadmin_usernames is None:
            os.environ.pop("APP_SUPERADMIN_USERNAMES", None)
        else:
            os.environ["APP_SUPERADMIN_USERNAMES"] = self._superadmin_usernames
        if self._superadmin_emails is None:
            os.environ.pop("APP_SUPERADMIN_EMAILS", None)
        else:
            os.environ["APP_SUPERADMIN_EMAILS"] = self._superadmin_emails
        if self._superadmin_ids is None:
            os.environ.pop("APP_SUPERADMIN_IDS", None)
        else:
            os.environ["APP_SUPERADMIN_IDS"] = self._superadmin_ids
        self.conn.close()

    def test_refreshes_privilege_from_db_when_session_is_stale(self):
        self.conn.execute(
            "INSERT INTO usuarios (id, rol, servicio, activo) VALUES ('u1', 'Administrador', '', 1)"
        )
        session = {"token": "t", "user_id": "u1", "rol": "", "servicio": ""}
        self.assertTrue(workspace_actor_is_privileged(self.conn, session))

    def test_denies_when_db_user_is_inactive(self):
        self.conn.execute(
            "INSERT INTO usuarios (id, rol, servicio, activo) VALUES ('u1', 'Administrador', '', 0)"
        )
        session = {"token": "t", "user_id": "u1", "rol": "", "servicio": ""}
        self.assertFalse(workspace_actor_is_privileged(self.conn, session))

    def test_treats_privileged_services_as_privileged(self):
        session = {"token": "t", "user_id": "u1", "rol": "Lectura", "servicio": "Dirección"}
        self.assertTrue(workspace_actor_is_privileged(self.conn, session))

    def test_superadmin_falls_back_to_privileged_session_when_allowlist_is_empty(self):
        session = {"token": "t", "user_id": "u1", "rol": "Administrador", "servicio": "Administración"}
        self.assertTrue(is_superadmin_actor(self.conn, session))


if __name__ == "__main__":
    unittest.main()
