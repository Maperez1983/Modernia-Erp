"""Un arranque que falla no puede quedarse con las conexiones.

Esto tumbó producción seis horas. `ensure_tables` son 2.600 líneas con un solo
`conn.close()`, al final y sin `finally`. Cuando algo revienta por el camino la
conexión no vuelve al pool; y como el hilo `db-bootstrap` reintenta en bucle
mientras la base no esté lista, se perdía **una por reintento**.

A las dieciséis el pool se acababa y el error pasaba a ser «Pool Postgres
saturado», que tapa la causa original: reiniciar no servía de nada porque el
servidor volvía a quedarse sin conexiones a los dos segundos de arrancar. En
pantalla sólo se leía «DB no disponible».
"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ["DATABASE_URL"] = ""
os.environ["POSTGRES_URL"] = ""

from web import server as S  # noqa: E402


class ElArranqueDevuelveLaConexionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "arranque.sqlite"
        self.abiertas = []
        self.original = S.open_sqlite_conn

        def espia(*a, **k):
            conn = self.original(*a, **k)
            self.abiertas.append(conn)
            return conn

        S.open_sqlite_conn = espia
        self.addCleanup(setattr, S, "open_sqlite_conn", self.original)
        self.addCleanup(self.tmp.cleanup)

    def _cerradas(self):
        cerradas = 0
        for c in self.abiertas:
            try:
                c.execute("SELECT 1")
            except Exception:
                cerradas += 1
        return cerradas

    def test_cuando_va_bien_tambien_se_cierra(self):
        S.ensure_tables(self.db)
        self.assertEqual(self._cerradas(), len(self.abiertas),
                         "una conexión se ha quedado abierta tras un arranque correcto")

    def test_y_sobre_todo_cuando_va_mal(self):
        """El caso que costó las seis horas."""
        original = S.bootstrap_default_workspace

        def revienta(_conn):
            raise RuntimeError("lo que sea que falle a mitad del esquema")

        S.bootstrap_default_workspace = revienta
        self.addCleanup(setattr, S, "bootstrap_default_workspace", original)
        with self.assertRaises(RuntimeError):
            S.ensure_tables(self.db)
        self.assertGreater(len(self.abiertas), 0, "el espía no ha visto ninguna conexión")
        self.assertEqual(self._cerradas(), len(self.abiertas),
                         "el arranque ha fallado y se ha quedado con la conexión")

    def test_el_error_de_verdad_llega_arriba(self):
        """Si la conexión se pierde, el siguiente error es «pool saturado» y la
        causa real no se ve nunca. Cerrando bien, el error que sube es el suyo."""
        original = S.load_postal_catalog
        S.load_postal_catalog = lambda _c: (_ for _ in ()).throw(ValueError("catálogo roto"))
        self.addCleanup(setattr, S, "load_postal_catalog", original)
        with self.assertRaises(ValueError) as caja:
            S.ensure_tables(self.db)
        self.assertIn("catálogo roto", str(caja.exception))

    def test_reintentar_no_acumula_conexiones(self):
        """Dieciséis reintentos seguidos, que es lo que hace el hilo de arranque."""
        original = S.bootstrap_default_workspace
        S.bootstrap_default_workspace = lambda _c: (_ for _ in ()).throw(RuntimeError("falla"))
        self.addCleanup(setattr, S, "bootstrap_default_workspace", original)
        for _ in range(16):
            with self.assertRaises(RuntimeError):
                S.ensure_tables(self.db)
        self.assertEqual(self._cerradas(), len(self.abiertas),
                         f"de {len(self.abiertas)} conexiones han quedado "
                         f"{len(self.abiertas) - self._cerradas()} abiertas")


if __name__ == "__main__":
    unittest.main()
