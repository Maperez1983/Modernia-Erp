"""Cerrabas la venta y el piso volvía al listado como si estuviera disponible.

Salió simulando el ciclo completo de un comercial —captación, encargo, anuncio,
comprador, visita, oferta y cierre—. Todo iba bien hasta el final: el cierre registraba
los 285.000 € y sus 8.550 € de honorarios, archivaba las gestiones pendientes y retiraba
el anuncio del portal. Y después, en el listado, el piso aparecía así:

    Calle Larios 3, 4º A · estado: Inmueble · 300.000 €

Nada decía que estuviera vendido. Estaban las dos líneas seguidas:

    sync_inmueble_stage_for_action(conn, inmueble_id, tipo_label, now)    # «Vendido»
    sync_inmueble_stage_for_action(conn, inmueble_id, final_stage, now)   # «Inmueble», lo pisaba

Y por el otro camino de cerrar una venta —convertir la captación con destino
«vendido»— sí quedaba en «Vendido», con una prueba que lo exigía. Los dos caminos
acababan en estados distintos y ninguna prueba fijaba este.

La ficha se queda contando lo que pasó. Si con el tiempo vuelve a salir a la venta se
retoma, que es lo que ya sabía hacer `captacion_convert`, y el cierre anterior se
conserva: reabrir es un acto, no el estado por defecto de lo que se acaba de cerrar.
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

CLAVE = "Comercial1234!"
AHORA = "2026-08-22 09:00:00"


class AlCerrarLaVentaTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Path(tmp.name) / "a.sqlite"
        S.ensure_tables(db)
        self.conn = S.open_sqlite_conn(str(db), with_row_factory=True)
        for fn in ("ensure_workspace_core_tables", "ensure_workspace_product_tables"):
            try:
                getattr(S, fn)(self.conn)
            except Exception:
                pass
        self.ws = self.conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()["id"]
        base = dict(created_at=AHORA, updated_at=AHORA)
        self._ins("empresas", dict(id="emp1", nombre="Inmobiliaria Modernia",
                                   nif="B29123456", activo=1, **base))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=self.ws,
                                             empresa_id="emp1", **base))
        self._ins("usuarios", dict(id="u1", nombre="Sebastián", usuario="sebas",
                                   email="s@x.test", rol="Inmobiliaria",
                                   servicio="Inmobiliaria", activo=1,
                                   password_hash=S.hash_password(CLAVE), **base))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=self.ws,
                                             usuario_id="u1", rol="Admin", **base))
        self._ins("inmuebles", dict(id="inm1", workspace_id=self.ws, empresa_id="emp1",
                                    direccion="Calle Larios 3, 4º A", estado="Encargo",
                                    precio_objetivo=300000, **base))
        self._ins("captaciones", dict(id="cap1", workspace_id=self.ws, empresa_id="emp1",
                                      inmueble_id="inm1", etapa="Encargo",
                                      situacion_comercial="Encargo",
                                      direccion="Calle Larios 3, 4º A", **base))
        anterior = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(db)
        if anterior is not None:
            self.addCleanup(setattr, S.Handler, "db_path", anterior)
        self.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)
        self.puerto = self.httpd.server_address[1]
        _, _, galleta = self._post("/api/login", {"usuario": "sebas", "password": CLAVE})
        self.cookie = galleta.split(";")[0]

    def _ins(self, tabla, datos):
        cols = {c[1] for c in self.conn.execute(f"pragma table_info({tabla})")}
        d = {k: v for k, v in datos.items() if k in cols}
        self.conn.execute(f"INSERT OR REPLACE INTO {tabla} ({','.join(d)}) "
                          f"VALUES ({','.join('?' * len(d))})", tuple(d.values()))
        self.conn.commit()

    def _post(self, ruta, cuerpo, cookie=None):
        rq = urllib.request.Request(f"http://127.0.0.1:{self.puerto}{ruta}",
                                    data=json.dumps(cuerpo).encode(),
                                    headers={"Content-Type": "application/json"}, method="POST")
        if cookie:
            rq.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(rq, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}"), r.headers.get("Set-Cookie")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), None

    def _estado(self):
        return dict(self.conn.execute(
            "SELECT estado FROM inmuebles WHERE id='inm1'").fetchone())["estado"]

    def _cierra(self, tipo="vendido"):
        return self._post("/api/inmueble_encargo_close",
                          {"workspace_id": self.ws, "empresa_id": "emp1", "id": "inm1",
                           "inmueble_id": "inm1", "tipo": tipo, "importe_final": 285000,
                           "honorarios": 8550, "fecha_cierre": "2026-09-15"}, self.cookie)

    def test_el_piso_queda_como_vendido(self):
        estado, cuerpo, _ = self._cierra()
        self.assertEqual(estado, 200, cuerpo)
        self.assertEqual(self._estado(), "Vendido")

    def test_y_asi_lo_ve_el_comercial_en_su_listado(self):
        """Es el sitio donde se notaba: un piso vendido no puede parecer disponible."""
        self._cierra()
        rq = urllib.request.Request(
            f"http://127.0.0.1:{self.puerto}/api/inmuebles?"
            f"workspace_id={self.ws}&empresa_id=emp1&limit=20",
            headers={"Cookie": self.cookie})
        with urllib.request.urlopen(rq, timeout=60) as r:
            filas = (json.loads(r.read() or b"{}").get("rows") or [])
        nuestro = [f for f in filas if str(f.get("direccion", "")).startswith("Calle Larios")]
        self.assertEqual(len(nuestro), 1, filas)
        self.assertEqual(nuestro[0].get("estado"), "Vendido")

    def test_el_cierre_guarda_el_importe_y_los_honorarios(self):
        self._cierra()
        cierre = dict(self.conn.execute("SELECT * FROM inmueble_cierres").fetchone())
        self.assertEqual(cierre["tipo"], "Vendido")
        self.assertAlmostEqual(float(cierre["importe_final"]), 285000.0, places=2)
        self.assertAlmostEqual(float(cierre["honorarios"]), 8550.0, places=2)

    def test_un_alquiler_queda_como_alquilado(self):
        """Antes volvía a «Noticia», o sea al circuito, como si no se hubiera alquilado.

        Y la fase se llamaba «Alquiler», que se lee como el escaparate; ahora dice
        «Alquilado», que es lo que ha pasado."""
        estado, cuerpo, _ = self._cierra(tipo="alquiler")
        self.assertEqual(estado, 200, cuerpo)
        self.assertEqual(self._estado(), "Alquilado")

    def test_si_vuelve_a_salir_a_la_venta_se_retoma(self):
        self._cierra()
        self.assertEqual(self._estado(), "Vendido")
        estado, cuerpo, _ = self._post("/api/captacion_convert",
                                       {"workspace_id": self.ws, "empresa_id": "emp1",
                                        "captacion_id": "cap1", "destino": "encargo"},
                                       self.cookie)
        self.assertEqual(estado, 200, cuerpo)
        self.assertEqual(self._estado(), "Encargo")
        # Y la venta anterior sigue en el histórico: retomar no borra lo que pasó.
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM inmueble_cierres").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
