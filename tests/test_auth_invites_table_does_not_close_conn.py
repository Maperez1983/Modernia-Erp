import sqlite3
import unittest

from web.server import ensure_auth_invites_table


class AuthInvitesTableConnTests(unittest.TestCase):
    def test_ensure_auth_invites_table_does_not_close_connection(self):
        conn = sqlite3.connect(":memory:")
        try:
            ensure_auth_invites_table(conn)
            # Debe seguir usable: si está cerrada, esto lanza ProgrammingError.
            conn.execute("SELECT 1")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()

