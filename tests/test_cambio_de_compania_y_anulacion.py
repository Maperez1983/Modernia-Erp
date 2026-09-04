"""Cambiar de compañía cobraba la prima de la anterior, y anular dejaba el recibo vivo.

Salió simulando lo que le pasa a una póliza cuando NO sigue el camino previsto. Cuatro
cosas, todas contestando 200:

1. **La póliza nueva entraba «En vigor» sin su PDF.** Por el camino normal eso se
   rechaza —«Debes adjuntar el PDF de la póliza antes de marcarla como Contratada/En
   vigor»—; por el cambio de compañía no lo miraba nadie. Dos caminos al mismo sitio y
   sólo uno con el control, que es el patrón que más veces ha salido en esta auditoría.

2. **Heredaba la prima.** El cliente se va de Mapfre a Generali por 415 € y la póliza
   nueva se guardaba con los 640 € de la anterior. Nadie cambia de compañía para pagar
   lo mismo: la prima nueva es justo el motivo del cambio.

3. **Y la comisión.** 96 € que eran de la póliza vieja, liquidados sobre la nueva.

4. **Anular dejaba su recibo pendiente cobrándose solo.** La póliza quedaba «Anulada»
   con su fecha de baja, correcto, y el recibo de 900 € seguía en «Pendiente»: sigue
   apareciendo en el resumen y entra en la remesa, o sea que se le pasa al cobro a quien
   ya no tiene póliza.

El cuarto se arregla en un ayudante compartido a propósito: la interfaz anula con un
`seguros_update` de estado y la API con `seguros_poliza_accion`, y poner el control en
uno solo es como no ponerlo.

Lo que **no** se toca: los recibos pendientes de una póliza *sustituida*. Una póliza que
se cambia a mitad de año puede deber legítimamente la prima del periodo transcurrido, y
anularlos ahí sería borrar deuda real.
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

RAIZ = Path(__file__).resolve().parents[1]
CLAVE = "Corredora1234!"
AHORA = "2026-08-24 09:00:00"
PRIMA_VIEJA = 640.0
COMISION_VIEJA = 96.0
PRIMA_NUEVA = 415.0
COMISION_NUEVA = 62.25


class CambioDeCompaniaYAnulacionTests(unittest.TestCase):
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
        self._ins("empresas", dict(id="emp1", nombre="Correduría Modernia",
                                   nif="B29123456", activo=1, **b))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=self.ws,
                                             empresa_id="emp1", **b))
        self._ins("usuarios", dict(id="u1", nombre="Bárbara", usuario="barbara",
                                   email="b@x.test", rol="Administrador",
                                   servicio="Seguros", activo=1,
                                   password_hash=S.hash_password(CLAVE), **b))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=self.ws,
                                             usuario_id="u1", rol="Owner", **b))
        anterior = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
        if anterior is not None:
            self.addCleanup(setattr, S.Handler, "db_path", anterior)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.puerto = self.httpd.server_address[1]
        _, _, galleta = self._post("/api/login", {"usuario": "barbara", "password": CLAVE})
        self.cookie = galleta.split(";")[0]
        self._post("/api/clientes", {"workspace_id": self.ws, "empresa_id": "emp1",
                                     "nombre": "Lucía Tomadora", "telefono": "600222333",
                                     "servicio": "seguros"}, self.cookie)
        self.cli = self._fresco("SELECT id FROM clientes LIMIT 1")[0]["id"]
        self.pol = self._alta("H-2026-0001", "Mapfre", PRIMA_VIEJA, COMISION_VIEJA)

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

    def _fresco(self, sql, args=()):
        c = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        try:
            return [dict(x) for x in c.execute(sql, args).fetchall()]
        finally:
            c.close()

    def _alta(self, numero, compania, prima, comision):
        self._post("/api/seguros", {
            "workspace_id": self.ws, "empresa_id": "emp1", "cliente_id": self.cli,
            "tomador": "Lucía Tomadora", "compania": compania, "ramo": "Hogar",
            "poliza_numero": numero, "fecha_efecto": "2026-01-01",
            "fecha_vencimiento": "2027-01-01", "prima_total": prima,
            "comision": comision, "estado": "Pendiente"}, self.cookie)
        return [f["id"] for f in self._fresco("SELECT id, poliza_numero FROM seguros")
                if f["poliza_numero"] == numero][0]

    def _recibo(self, poliza, prima):
        self._post("/api/seguros_recibos", {
            "workspace_id": self.ws, "empresa_id": "emp1", "seguro_id": poliza,
            "prima_total": prima, "estado": "Pendiente",
            "fecha_emision": "2026-01-01"}, self.cookie)

    def _cambia(self, **extra):
        cuerpo = {"workspace_id": self.ws, "empresa_id": "emp1", "id": self.pol,
                  "nueva_compania": "Generali", "nueva_poliza_numero": "G-2026-9001",
                  "fecha_cambio": "2026-07-01"}
        cuerpo.update(extra)
        return self._post("/api/seguros_cambio_compania", cuerpo, self.cookie)

    def _nueva(self):
        return self._fresco("SELECT * FROM seguros WHERE poliza_numero = 'G-2026-9001'")[0]

    # --- el PDF -------------------------------------------------------------------

    def test_la_poliza_nueva_no_entra_en_vigor_sin_pdf(self):
        """El camino normal lo rechaza; éste la metía «En vigor» con el hueco vacío."""
        estado, r, _ = self._cambia()
        self.assertEqual(estado, 200, r)
        self.assertEqual(self._nueva()["estado"], "Pendiente")
        self.assertEqual(r.get("estado_nueva"), "Pendiente")

    def test_y_se_dice_por_qué_se_queda_pendiente(self):
        _, r, _ = self._cambia()
        self.assertIn("PDF", r.get("aviso", ""))

    def test_con_su_pdf_sí_entra_en_vigor(self):
        estado, r, _ = self._cambia(poliza_key="polizas/g-2026-9001.pdf")
        self.assertEqual(estado, 200, r)
        self.assertEqual(self._nueva()["estado"], "En vigor")

    # --- la prima y la comisión ----------------------------------------------------

    def test_no_hereda_la_prima_de_la_poliza_vieja(self):
        self._cambia()
        self.assertNotEqual(self._nueva()["prima_total"], PRIMA_VIEJA)

    def test_ni_la_comision(self):
        self._cambia()
        self.assertNotEqual(self._nueva()["comision"], COMISION_VIEJA)

    def test_y_se_avisa_de_que_faltan(self):
        _, r, _ = self._cambia()
        aviso = r.get("aviso", "")
        self.assertIn("prima", aviso)
        self.assertIn("comisión", aviso)

    def test_si_se_dan_se_guardan_las_nuevas(self):
        self._cambia(nueva_prima_total=PRIMA_NUEVA, nueva_comision=COMISION_NUEVA)
        n = self._nueva()
        self.assertAlmostEqual(float(n["prima_total"]), PRIMA_NUEVA, places=2)
        self.assertAlmostEqual(float(n["comision"]), COMISION_NUEVA, places=2)

    def test_y_entonces_no_hay_nada_que_avisar(self):
        _, r, _ = self._cambia(nueva_prima_total=PRIMA_NUEVA, nueva_comision=COMISION_NUEVA,
                               poliza_key="polizas/g.pdf")
        self.assertEqual(r.get("aviso", ""), "")

    # --- lo que ya funcionaba sigue igual -------------------------------------------

    def test_la_vieja_queda_sustituida_y_enlazada(self):
        self._cambia()
        vieja = self._fresco("SELECT estado, fecha_baja, poliza_sustituta_id "
                             "FROM seguros WHERE id = ?", (self.pol,))[0]
        self.assertEqual(vieja["estado"], "Sustituida")
        self.assertEqual(vieja["fecha_baja"], "2026-07-01")
        self.assertTrue(vieja["poliza_sustituta_id"])

    def test_los_recibos_de_la_sustituida_no_se_tocan(self):
        """Puede deber la prima del periodo ya transcurrido: anularla sería borrar deuda."""
        self._recibo(self.pol, PRIMA_VIEJA)
        self._cambia()
        recibos = self._fresco("SELECT estado FROM seguros_recibos WHERE seguro_id = ?",
                               (self.pol,))
        self.assertEqual([r["estado"] for r in recibos], ["Pendiente"])

    # --- anular ---------------------------------------------------------------------

    def test_anular_deja_de_cobrar_lo_pendiente(self):
        otra = self._alta("C-2026-0002", "Allianz", 900.0, 135.0)
        self._recibo(otra, 900.0)
        estado, r, _ = self._post("/api/seguros_poliza_accion", {
            "workspace_id": self.ws, "empresa_id": "emp1", "id": otra, "accion": "ANULAR",
            "fecha_baja": "2026-08-01", "motivo_baja": "Vende el coche"}, self.cookie)
        self.assertEqual(estado, 200, r)
        self.assertEqual(r.get("recibos_anulados"), 1)
        recibos = self._fresco("SELECT estado, notas FROM seguros_recibos WHERE seguro_id = ?",
                               (otra,))
        self.assertEqual(recibos[0]["estado"], "Anulado")
        self.assertIn("Vende el coche", recibos[0]["notas"] or "")

    def test_tambien_por_el_camino_que_usa_la_interfaz(self):
        """La pantalla anula con un `seguros_update`, no con la acción: los dos o ninguno."""
        otra = self._alta("C-2026-0003", "Allianz", 700.0, 105.0)
        self._recibo(otra, 700.0)
        estado, r, _ = self._post("/api/seguros_update", {
            "workspace_id": self.ws, "empresa_id": "emp1", "id": otra,
            "estado": "Anulada", "fecha_baja": "2026-08-01",
            "motivo_baja": "Se da de baja"}, self.cookie)
        self.assertEqual(estado, 200, r)
        recibos = self._fresco("SELECT estado FROM seguros_recibos WHERE seguro_id = ?", (otra,))
        self.assertEqual(recibos[0]["estado"], "Anulado")

    def test_lo_ya_cobrado_no_se_deshace(self):
        """Si hay que devolver dinero eso es un extorno, y se anota como tal."""
        otra = self._alta("C-2026-0004", "Allianz", 500.0, 75.0)
        self._recibo(otra, 500.0)
        rec = self._fresco("SELECT id FROM seguros_recibos WHERE seguro_id = ?", (otra,))[0]
        self._post("/api/seguros_recibos_update",
                   {"workspace_id": self.ws, "empresa_id": "emp1", "id": rec["id"],
                    "estado": "Cobrado"}, self.cookie)
        self._post("/api/seguros_poliza_accion", {
            "workspace_id": self.ws, "empresa_id": "emp1", "id": otra, "accion": "ANULAR",
            "fecha_baja": "2026-08-01", "motivo_baja": "otros"}, self.cookie)
        recibos = self._fresco("SELECT estado FROM seguros_recibos WHERE seguro_id = ?", (otra,))
        self.assertEqual(recibos[0]["estado"], "Cobrado")

    def test_el_front_pide_la_prima_nueva_y_enseña_el_aviso(self):
        app = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("nueva_prima_total", app)
        self.assertIn("nueva_comision", app)
        self.assertIn("recibos_anulados", app)


if __name__ == "__main__":
    unittest.main()
