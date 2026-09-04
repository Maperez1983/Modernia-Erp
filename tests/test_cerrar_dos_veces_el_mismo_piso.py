"""Cada vez que se pulsaba «cerrar», la agencia se apuntaba otra comisión.

El cierre es el momento en que entra el dinero: el importe de la operación y los
honorarios. Y es un botón que se pulsa una vez al año por inmueble, o sea que cuando
falla, falla en silencio y no se nota hasta que alguien cuadra el año.

Pulsándolo cinco veces sobre el mismo piso quedaban **cinco cierres**, y los paneles
sumaban 417.850 € de honorarios de una venta de 285.000 €. Nadie duplica un cierre a
propósito, pero sí se pulsa dos veces cuando la primera parece que no ha respondido, y
sí se vuelve a entrar para corregir un importe mal tecleado.

Por el camino entraban además tres importes que no pueden ser: una venta en negativo,
unos honorarios en negativo y unos honorarios mayores que el precio de venta.

Los criterios son los que ya se fijaron en fincas: **los negativos se rechazan siempre**
y **lo absurdo se pregunta**. Aquí eso significa que volver a cerrar no acumula: avisa de
lo que ya hay —tipo, fecha, importe y honorarios— y, si se confirma, **sustituye** aquel
cierre en vez de añadir uno nuevo. Que es lo que quiere quien está corrigiendo.
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
AHORA = "2026-08-24 09:00:00"
PRECIO = 285000.0
HONORARIOS = 8550.0


class CerrarDosVecesElMismoPisoTests(unittest.TestCase):
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
        self._ins("empresas", dict(id="emp1", nombre="Inmobiliaria Modernia",
                                   nif="B29123456", activo=1, **b))
        self._ins("workspace_empresas", dict(id="we1", workspace_id=self.ws,
                                             empresa_id="emp1", **b))
        self._ins("usuarios", dict(id="u1", nombre="Sebastián", usuario="sebas",
                                   email="s@x.test", rol="Administrador",
                                   servicio="Inmobiliaria", activo=1,
                                   password_hash=S.hash_password(CLAVE), **b))
        self._ins("workspace_miembros", dict(id="wm1", workspace_id=self.ws,
                                             usuario_id="u1", rol="Owner", **b))
        for i, (calle, operacion) in enumerate((("Calle Larios 3, 4º A", "venta"),
                                                ("Alameda Principal 20", "alquiler")), start=1):
            self._ins("inmuebles", dict(id=f"inm{i}", workspace_id=self.ws,
                                        empresa_id="emp1", direccion=calle,
                                        estado="Encargo", tipo_operacion=operacion,
                                        precio_objetivo=300000, **b))
            self._ins("captaciones", dict(id=f"cap{i}", workspace_id=self.ws,
                                          empresa_id="emp1", inmueble_id=f"inm{i}",
                                          etapa="Encargo", situacion_comercial="Encargo",
                                          direccion=calle, **b))
        anterior = getattr(S.Handler, "db_path", None)
        S.Handler.db_path = str(self.db)
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
                                    headers={"Content-Type": "application/json"},
                                    method="POST")
        if cookie:
            rq.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(rq, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}"), r.headers.get("Set-Cookie")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), None

    def _cierra(self, inmueble="inm1", tipo="vendido", **extra):
        cuerpo = {"workspace_id": self.ws, "empresa_id": "emp1", "id": inmueble,
                  "inmueble_id": inmueble, "tipo": tipo, "importe_final": PRECIO,
                  "honorarios": HONORARIOS, "fecha_cierre": "2026-09-15"}
        cuerpo.update(extra)
        return self._post("/api/inmueble_encargo_close", cuerpo, self.cookie)

    def _cierres(self, inmueble="inm1"):
        c = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        try:
            return [dict(x) for x in c.execute(
                "SELECT tipo, importe_final, honorarios FROM inmueble_cierres "
                "WHERE inmueble_id = ?", (inmueble,)).fetchall()]
        finally:
            c.close()

    # --- importes que no pueden ser --------------------------------------------------

    def test_un_importe_de_venta_negativo_no_entra(self):
        estado, r, _ = self._cierra(importe_final=-PRECIO)
        self.assertEqual(estado, 400, r)
        self.assertIn("no puede ser negativo", r.get("error", ""))
        self.assertEqual(self._cierres(), [])

    def test_unos_honorarios_negativos_tampoco(self):
        estado, r, _ = self._cierra(honorarios=-HONORARIOS)
        self.assertEqual(estado, 400, r)
        self.assertEqual(self._cierres(), [])

    def test_honorarios_mayores_que_la_venta_se_preguntan(self):
        """No se bloquea: puede haber un encargo con mínimo pactado."""
        estado, r, _ = self._cierra(honorarios=400000)
        self.assertEqual(estado, 409, r)
        self.assertTrue(r.get("requiere_confirmacion"))
        self.assertEqual(self._cierres(), [])

    def test_y_confirmándolo_entran(self):
        estado, r, _ = self._cierra(honorarios=400000, confirmado=True)
        self.assertEqual(estado, 200, r)

    def test_en_un_alquiler_los_honorarios_iguales_a_la_renta_no_molestan(self):
        """Una mensualidad de honorarios es lo normal: igual no es mayor."""
        estado, r, _ = self._cierra("inm2", tipo="alquiler", importe_final=1200,
                                    honorarios=1200)
        self.assertEqual(estado, 200, r)

    # --- cerrar dos veces --------------------------------------------------------------

    def test_el_cierre_bueno_entra(self):
        estado, r, _ = self._cierra()
        self.assertEqual(estado, 200, r)
        self.assertEqual(len(self._cierres()), 1)

    def test_volver_a_cerrar_avisa_en_vez_de_acumular(self):
        self._cierra()
        estado, r, _ = self._cierra(importe_final=310000, honorarios=9300)
        self.assertEqual(estado, 409, r)
        self.assertEqual(r.get("code"), "ya_cerrado")
        self.assertEqual(len(self._cierres()), 1)

    def test_y_el_aviso_dice_qué_hay_apuntado_ya(self):
        self._cierra()
        _, r, _ = self._cierra(importe_final=310000)
        aviso = r.get("error", "")
        self.assertIn("285.000,00", aviso)
        self.assertIn("8.550,00", aviso)
        self.assertIn("2026-09-15", aviso)
        self.assertTrue(r.get("cierre_anterior"))

    def test_confirmando_se_sustituye_y_no_se_suma(self):
        """Quien vuelve a entrar está corrigiendo, no vendiendo el piso otra vez."""
        self._cierra()
        estado, r, _ = self._cierra(importe_final=310000, honorarios=9300, confirmado=True)
        self.assertEqual(estado, 200, r)
        cierres = self._cierres()
        self.assertEqual(len(cierres), 1, cierres)
        self.assertAlmostEqual(float(cierres[0]["importe_final"]), 310000.0, places=2)
        self.assertAlmostEqual(float(cierres[0]["honorarios"]), 9300.0, places=2)

    def test_cinco_pulsaciones_no_son_cinco_comisiones(self):
        """Era el fallo tal cual: 417.850 € de honorarios de una venta de 285.000 €."""
        self._cierra()
        for _ in range(4):
            self._cierra(honorarios=HONORARIOS)
        cierres = self._cierres()
        self.assertEqual(len(cierres), 1, cierres)
        self.assertAlmostEqual(
            sum(float(c["honorarios"] or 0) for c in cierres), HONORARIOS, places=2)

    def test_otro_inmueble_se_cierra_sin_problema(self):
        """El control es por inmueble, no por agencia."""
        self._cierra()
        estado, r, _ = self._cierra("inm2", tipo="alquiler", importe_final=1200,
                                    honorarios=1200)
        self.assertEqual(estado, 200, r)
        self.assertEqual(len(self._cierres("inm2")), 1)

    # --- y lo que ya funcionaba ---------------------------------------------------------

    def test_el_alquiler_sigue_quedando_como_alquilado(self):
        self._cierra("inm2", tipo="alquiler", importe_final=1200, honorarios=1200)
        fila = self.conn.execute("SELECT estado FROM inmuebles WHERE id = 'inm2'").fetchone()
        self.assertEqual(dict(fila)["estado"], "Alquilado")

    def test_y_la_venta_como_vendido(self):
        self._cierra()
        fila = self.conn.execute("SELECT estado FROM inmuebles WHERE id = 'inm1'").fetchone()
        self.assertEqual(dict(fila)["estado"], "Vendido")


if __name__ == "__main__":
    unittest.main()
