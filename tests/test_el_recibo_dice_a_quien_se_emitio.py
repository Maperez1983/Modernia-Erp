"""Vendías el piso y tus recibos impagados pasaban a nombre del comprador.

Salió simulando el año de una administradora fuera del mes normal. El 1º A se vende en
junio. La única forma de meter al comprador en el censo es editar la ficha del vecino, y
eso es un `UPDATE` sobre la misma fila: los recibos que se le emitieron a la vendedora
—4.050 € sin pagar— pasaban a figurar a nombre del comprador, y la vendedora desaparecía
del histórico de la comunidad.

La deuda **sí** viaja con el piso: el comprador responde de la del año en curso y los
tres anteriores (LPH art. 9.1.e), así que el importe estaba bien. Lo que estaba mal es
que un recibo dijera que se le emitió a quien no se le emitió. Y eso sale del CRM en un
papel: el certificado de deuda, que se pide para vender y se enseña en una notaría, listaba
la deuda de la vendedora bajo el nombre del comprador sin decirlo.

Ahora el recibo guarda el nombre y el NIF del propietario **el día de emitirlo**, y ya no
se mueve. El certificado sigue saliendo a nombre de quien es dueño hoy —es quien
responde—, pero cuando hay recibos de otro los enseña en su columna y lo explica. Lo que
no hace es decidir quién paga: eso no lo determina un programa.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("POSTGRES_URL", "")

from web import server as S  # noqa: E402

CLAVE = "Administradora1234!"
AHORA = "2026-08-23 09:00:00"
VENDEDORA = "Dolores Sánchez"
COMPRADOR = "Alberto Ruiz"


class ElReciboDiceAQuienSeEmitioTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "a.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        for fn in ("ensure_workspace_core_tables", "ensure_workspace_product_tables"):
            try:
                getattr(S, fn)(self.conn)
            except Exception:
                pass
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        b = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("empresas", dict(id="emp1", nombre="Fincas Modernia", nif="B29123456",
                                   activo=1, administra_fincas=1, **b))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=self.ws,
                                             empresa_id="emp1", **b))
        self._ins("usuarios", dict(id="u1", nombre="Ana", usuario="ana", email="a@x.test",
                                   rol="Administrador", servicio="Fincas", activo=1,
                                   password_hash=S.hash_password(CLAVE), **b))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=self.ws,
                                             usuario_id="u1", rol="Owner", **b))
        self._ins("workspace_fincas_comunidades",
                  dict(id="com1", workspace_id=self.ws, empresa_id="emp1",
                       nombre="C.P Los Naranjos", direccion="Avenida Europa 110",
                       cif="H29123456", estado="Activa", **b))
        # Dos pisos al 50 %, para que el reparto cuadre sin decimales raros.
        self._ins("workspace_fincas_vecinos",
                  dict(id="v1", workspace_id=self.ws, comunidad_id="com1",
                       nombre=VENDEDORA, piso="1º A", coeficiente=50.0, nif="25111111A",
                       iban="ES2321000418400000000001", **b))
        self._ins("workspace_fincas_vecinos",
                  dict(id="v2", workspace_id=self.ws, comunidad_id="com1",
                       nombre="Manuel Ortega", piso="1º B", coeficiente=50.0,
                       nif="25111112B", iban="ES2321000418400000000001", **b))
        anterior = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        if anterior is not None:
            self.addCleanup(setattr, S.Handler, "db_path", anterior)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.puerto = self.httpd.server_address[1]
        _, _, galleta = self._post("/api/login", {"usuario": "ana", "password": CLAVE})
        self.cookie = galleta.split(";")[0]
        # Mayo: la vendedora deja este recibo sin pagar. Un mes ya pasado, para que
        # cuente como deuda de verdad y no como recibo recién emitido.
        estado, r, _ = self._post("/api/workspace_fincas_recibos_emitir", {
            "workspace_id": self.ws, "comunidad_id": "com1", "periodo": "2026-05",
            "importe": 1000.0, "concepto": "Cuota mayo"}, self.cookie)
        self.assertEqual(estado, 200, r)

    def _ins(self, tabla, datos):
        cols = {c[1] for c in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in cols}
        self.conn.execute(f"INSERT OR REPLACE INTO {tabla} ({','.join(d)}) "
                          f"VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        self.conn.commit()

    def _post(self, ruta, cuerpo, cookie=None):
        rq = urllib.request.Request(f"http://127.0.0.1:{self.puerto}{ruta}",
                                    data=json.dumps(cuerpo).encode(),
                                    headers={"Content-Type": "application/json"},
                                    method="POST")
        if cookie:
            rq.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(rq, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}"), r.headers.get("Set-Cookie")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), None

    def _get(self, ruta, **params):
        url = f"http://127.0.0.1:{self.puerto}{ruta}?" + urllib.parse.urlencode(params)
        rq = urllib.request.Request(url, headers={"Cookie": self.cookie})
        try:
            with urllib.request.urlopen(rq, timeout=60) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def _vende_el_piso(self):
        """Lo único que puede hacer la administradora: cambiar la ficha del vecino."""
        estado, r, _ = self._post("/api/workspace_fincas_vecinos", {
            "workspace_id": self.ws, "comunidad_id": "com1", "id": "v1",
            "nombre": COMPRADOR, "piso": "1º A", "coeficiente": 50.0, "nif": "25999999Z",
            "iban": "ES2321000418400000000009"}, self.cookie)
        self.assertEqual(estado, 200, r)

    def _fresco(self, sql, args=()):
        c = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        try:
            return [dict(x) for x in c.execute(sql, args).fetchall()]
        finally:
            c.close()

    def _texto_del_certificado(self, vecino_id="v1"):
        estado, crudo = self._get("/api/workspace_fincas_certificado_deuda",
                                  workspace_id=self.ws, vecino_id=vecino_id)
        self.assertEqual(estado, 200, crudo[:200])
        self.assertEqual(crudo[:4], b"%PDF", "no ha salido un PDF")
        from pypdf import PdfReader
        import io
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(crudo)).pages)

    # --- el recibo --------------------------------------------------------------

    def test_el_recibo_guarda_a_quien_se_le_emitio(self):
        fila = self._fresco("SELECT vecino_nombre, vecino_nif FROM workspace_fincas_recibos "
                            "WHERE vecino_id = 'v1'")[0]
        self.assertEqual(fila["vecino_nombre"], VENDEDORA)
        self.assertEqual(fila["vecino_nif"], "25111111A")

    def test_vender_el_piso_no_reescribe_el_recibo(self):
        self._vende_el_piso()
        fila = self._fresco("SELECT vecino_nombre FROM workspace_fincas_recibos "
                            "WHERE vecino_id = 'v1'")[0]
        self.assertEqual(fila["vecino_nombre"], VENDEDORA)

    def test_pero_la_ficha_del_piso_sí_es_del_comprador(self):
        self._vende_el_piso()
        fila = self._fresco("SELECT nombre FROM workspace_fincas_vecinos WHERE id = 'v1'")[0]
        self.assertEqual(fila["nombre"], COMPRADOR)

    def test_el_listado_enseña_las_dos_cosas(self):
        self._vende_el_piso()
        estado, crudo = self._get("/api/workspace_fincas_recibos",
                                  workspace_id=self.ws, comunidad_id="com1")
        self.assertEqual(estado, 200)
        filas = json.loads(crudo).get("rows") or json.loads(crudo).get("recibos") or []
        nuestro = [f for f in filas if f.get("vecino_id") == "v1"]
        self.assertEqual(len(nuestro), 1, filas)
        self.assertEqual(nuestro[0].get("emitido_a"), VENDEDORA)
        self.assertEqual(nuestro[0].get("nombre"), COMPRADOR)

    # --- el certificado, que es lo que se enseña en una notaría ------------------

    def test_el_certificado_sale_a_nombre_del_propietario_de_hoy(self):
        """Es quien responde de la deuda del piso, y quien lo va a enseñar."""
        self._vende_el_piso()
        self.assertIn(COMPRADOR, self._texto_del_certificado())

    def test_y_dice_que_ese_recibo_se_emitió_a_la_anterior(self):
        self._vende_el_piso()
        texto = self._texto_del_certificado()
        self.assertIn(VENDEDORA, texto)
        self.assertIn("propietario anterior", texto)

    def test_no_decide_quién_paga(self):
        """Un programa sin firma no reparte responsabilidades."""
        self._vende_el_piso()
        texto = self._texto_del_certificado().lower()
        self.assertIn("no lo determina este documento", texto)
        for palabra in ("art.", "artículo", "9.1"):
            self.assertNotIn(palabra, texto)

    def test_sin_cambio_de_dueño_el_certificado_no_cambia(self):
        """La columna de más sólo aparece cuando hace falta: si no, estorba."""
        texto = self._texto_del_certificado()
        self.assertIn(VENDEDORA, texto)
        self.assertNotIn("propietario anterior", texto)
        self.assertNotIn("Emitido a", texto)

    def test_quien_está_al_corriente_sigue_teniendo_su_certificado(self):
        self._post("/api/workspace_fincas_recibo_estado",
                   {"workspace_id": self.ws,
                    "id": self._fresco("SELECT id FROM workspace_fincas_recibos "
                                       "WHERE vecino_id = 'v2'")[0]["id"],
                    "estado": "Cobrado"}, self.cookie)
        texto = self._texto_del_certificado("v2")
        self.assertIn("Manuel Ortega", texto)
        self.assertIn("SÍ está al corriente", texto)


if __name__ == "__main__":
    unittest.main()
