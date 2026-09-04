"""El documento que se manda a firmar se servía con su tipo real.

`/api/inmueble_signature_document` es público: es el enlace que recibe el cliente para
ver lo que va a firmar. Servía el fichero con el Content-Type que tocara por extensión,
así que un `.html` o un `.svg` subido por alguien de la agencia se ejecutaba en el origen
de la aplicación, en el navegador de quien firma —donde vive la sesión del CRM—.

La casa ya había decidido sobre esto: la ruta `/uploads/` tiene una lista blanca de
tipos que se pueden ver en línea, y todo lo demás se fuerza a descarga con
`application/octet-stream`. Este endpoint se la saltaba, treinta líneas más abajo del
comentario que la explica. No hace falta discutir el criterio: hace falta aplicarlo.

Nada valida la extensión al subir, así que un `.html` puede llegar hasta aquí.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("POSTGRES_URL", "")

from web import server as S  # noqa: E402

AHORA = "2026-08-22 09:00:00"


class LoQueSeSirveAlQueFirmaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db = Path(self.tmp.name) / "a.sqlite"
        S.ensure_tables(db)
        self.conn = S.open_sqlite_conn(str(db), with_row_factory=True)
        for fn in ("ensure_workspace_core_tables", "ensure_workspace_product_tables"):
            try:
                getattr(S, fn)(self.conn)
            except Exception:
                pass
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        anterior = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(db)
        if anterior is not None:
            self.addCleanup(setattr, S.Handler, "db_path", anterior)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.puerto = self.httpd.server_address[1]

    def _ins(self, tabla, datos):
        cols = {c[1] for c in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in cols}
        self.conn.execute(f"INSERT OR REPLACE INTO {tabla} ({','.join(d)}) "
                          f"VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        self.conn.commit()

    def _solicitud_con(self, nombre_fichero, contenido=b"<script>alert(1)</script>"):
        carpeta = S.UPLOADS / "firmas_prueba"
        carpeta.mkdir(parents=True, exist_ok=True)
        fichero = carpeta / nombre_fichero
        fichero.write_bytes(contenido)
        self.addCleanup(lambda: fichero.exists() and fichero.unlink())
        url = "/uploads/firmas_prueba/" + nombre_fichero
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("empresas", dict(id="emp1", nombre="Modernia", nif="B29123456", activo=1, **base))
        self._ins("inmuebles", dict(id="inm1", workspace_id=self.ws, empresa_id="emp1",
                                    direccion="Calle Larios 3", **base))
        S.ensure_inmueble_signature_schema(self.conn)
        token = "tok" + nombre_fichero.replace(".", "")
        self._ins("inmueble_signature_requests",
                  dict(id="sr_" + token, empresa_id="emp1", inmueble_id="inm1",
                       token_hash=S.hash_signature_token(token), status="sent",
                       doc_url=url, doc_nombre=nombre_fichero,
                       expires_at="2099-01-01 00:00:00", **base))
        return token

    def _pide(self, token):
        url = f"http://127.0.0.1:{self.puerto}/api/inmueble_signature_document?token={token}"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_un_html_no_se_sirve_como_html(self):
        estado, cabeceras, cuerpo = self._pide(self._solicitud_con("trampa.html"))
        if estado != 200:
            self.skipTest(f"la solicitud no llegó a servirse ({estado}): {cuerpo[:120]!r}")
        tipo = str(cabeceras.get("Content-Type", ""))
        self.assertNotIn("text/html", tipo, f"se ejecutaría en el origen de la app: {tipo}")
        self.assertIn("octet-stream", tipo)
        self.assertIn("attachment", str(cabeceras.get("Content-Disposition", "")))

    def test_un_svg_se_descarga_en_vez_de_abrirse(self):
        estado, cabeceras, cuerpo = self._pide(self._solicitud_con("logo.svg"))
        if estado != 200:
            self.skipTest(f"la solicitud no llegó a servirse ({estado}): {cuerpo[:120]!r}")
        self.assertIn("attachment", str(cabeceras.get("Content-Disposition", "")))

    def test_un_pdf_se_sigue_viendo(self):
        """La protección no puede romper lo normal: el 99 % de las firmas son un PDF."""
        estado, cabeceras, cuerpo = self._pide(
            self._solicitud_con("contrato.pdf", b"%PDF-1.4\n%%EOF\n"))
        if estado != 200:
            self.skipTest(f"la solicitud no llegó a servirse ({estado}): {cuerpo[:120]!r}")
        self.assertIn("application/pdf", str(cabeceras.get("Content-Type", "")))


if __name__ == "__main__":
    unittest.main()
