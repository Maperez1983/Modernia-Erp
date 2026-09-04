"""El OCR de pólizas no reconocía a un cliente que ya existía.

Al subir una póliza real de una comunidad ya dada de alta, el sistema decía «cliente
no encontrado» y se acababa creando una ficha duplicada. La causa: la búsqueda de
cliente por nombre era un `LIKE '%texto%'` en un solo sentido — preguntaba si el
nombre GUARDADO contenía el texto entero del OCR. En una póliza el tomador suele
venir con el nombre legal completo («COMUNIDAD DE PROPIETARIOS CALLE BARCELÓ Nº 4»)
mientras que en el CRM la comunidad puede estar de alta con un nombre más corto
(«CP Barceló 4»); el texto largo del OCR nunca aparece literal dentro del corto, así
que nunca encontraba nada.

Y aunque se encontrara al cliente, si ya tenía una póliza de ese ramo con otro número
—lo normal en una renovación o un cambio de compañía— se guardaba como fila suelta
sin enlazar con la anterior, en vez de ofrecer renovar o cambiar de compañía sobre la
que ya existía.
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

CLAVE = "Corredora1234!"
AHORA = "2026-09-01 09:00:00"


class Base(unittest.TestCase):
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

    def _get(self, ruta, cookie=None):
        rq = urllib.request.Request(f"http://127.0.0.1:{self.puerto}{ruta}")
        if cookie:
            rq.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(rq, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def _fresco(self, sql, args=()):
        c = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        try:
            return [dict(x) for x in c.execute(sql, args).fetchall()]
        finally:
            c.close()

    def _cliente(self, nombre, nif=""):
        self._post("/api/clientes", {"workspace_id": self.ws, "empresa_id": "emp1",
                                     "nombre": nombre, "nif": nif,
                                     "servicio": "seguros"}, self.cookie)
        fila = self._fresco("SELECT id FROM clientes WHERE nombre = ?", (nombre,))[0]
        return fila["id"]

    def _poliza(self, cliente_id, numero, compania, ramo="Hogar", estado="En vigor",
               fecha_vencimiento="2027-01-01"):
        self._ins("seguros", dict(
            id=f"pol-{numero}", empresa_id="emp1", cliente_id=cliente_id,
            tomador="", compania=compania, ramo=ramo, poliza_numero=numero,
            estado=estado, fecha_efecto="2026-01-01",
            fecha_vencimiento=fecha_vencimiento, prima_total=400.0,
            poliza_key=f"polizas/{numero}.pdf",
            created_at=AHORA, updated_at=AHORA,
        ))
        return f"pol-{numero}"


class LaBusquedaPorNombreEsEnLosDosSentidosTests(Base):
    def test_encuentra_al_cliente_aunque_el_tomador_del_ocr_sea_mas_largo(self):
        """«CP Barceló 4» en el CRM, con una póliza ya de antes; el OCR de la
        renovación trae el nombre legal completo, más largo."""
        cli = self._cliente("CP Barceló 4")
        self._poliza(cli, "Z-100", "Zurich")
        q = urllib.parse.quote("COMUNIDAD DE PROPIETARIOS CALLE BARCELO NUMERO 4")
        estado, r = self._get(
            f"/api/clientes?empresa_id=emp1&servicio=seguros&q={q}&include_id=1", self.cookie)
        self.assertEqual(estado, 200, r)
        nombres = [row[r["columns"].index("nombre")] for row in r["rows"]]
        self.assertIn("CP Barceló 4", nombres)

    def test_sigue_encontrando_por_el_camino_de_toda_la_vida(self):
        """El nombre guardado contenido en el texto de búsqueda: lo que ya funcionaba."""
        cli = self._cliente("Comunidad de Propietarios Barcelo 4")
        self._poliza(cli, "Z-100", "Zurich")
        estado, r = self._get(
            "/api/clientes?empresa_id=emp1&servicio=seguros&q=Barcelo&include_id=1", self.cookie)
        self.assertEqual(estado, 200, r)
        self.assertTrue(r["rows"])

    def test_una_palabra_corta_no_basta_para_no_traer_media_base(self):
        """Palabras de menos de 4 letras no entran en la búsqueda por palabra suelta."""
        cli1 = self._cliente("Comunidad Los Pinos")
        self._poliza(cli1, "Z-100", "Zurich")
        cli2 = self._cliente("Otro cliente sin relacion")
        self._poliza(cli2, "Z-101", "Zurich")
        estado, r = self._get(
            "/api/clientes?empresa_id=emp1&servicio=seguros&q=de+los&include_id=1", self.cookie)
        self.assertEqual(estado, 200, r)
        # "de" y "los" tienen menos de 4 letras: no deberían traer "Otro cliente sin relacion".
        nombres = [row[r["columns"].index("nombre")] for row in r["rows"]]
        self.assertNotIn("Otro cliente sin relacion", nombres)


class LaPolizaExistenteDelClienteTests(Base):
    def test_encuentra_la_poliza_activa_del_mismo_ramo(self):
        cli = self._cliente("CP Barceló 4")
        self._poliza(cli, "Z-100", "Zurich", ramo="Hogar")
        estado, r = self._get(
            f"/api/seguros_cliente_poliza_existente?empresa_id=emp1&cliente_id={cli}&ramo=Hogar",
            self.cookie)
        self.assertEqual(estado, 200, r)
        self.assertIsNotNone(r.get("poliza_existente"))
        self.assertEqual(r["poliza_existente"]["compania"], "Zurich")
        self.assertEqual(r["poliza_existente"]["poliza_numero"], "Z-100")

    def test_no_hay_nada_si_es_el_mismo_numero_que_ya_tiene(self):
        """Mismo número: eso lo trata la deduplicación por número, no la renovación."""
        cli = self._cliente("CP Barceló 4")
        self._poliza(cli, "Z-100", "Zurich", ramo="Hogar")
        estado, r = self._get(
            f"/api/seguros_cliente_poliza_existente?empresa_id=emp1&cliente_id={cli}"
            "&ramo=Hogar&exclude_poliza_numero=Z-100",
            self.cookie)
        self.assertEqual(estado, 200, r)
        self.assertIsNone(r.get("poliza_existente"))

    def test_no_hay_nada_de_otro_ramo(self):
        cli = self._cliente("CP Barceló 4")
        self._poliza(cli, "Z-100", "Zurich", ramo="Hogar")
        estado, r = self._get(
            f"/api/seguros_cliente_poliza_existente?empresa_id=emp1&cliente_id={cli}&ramo=Auto",
            self.cookie)
        self.assertEqual(estado, 200, r)
        self.assertIsNone(r.get("poliza_existente"))

    def test_ignora_pólizas_anuladas_o_sustituidas(self):
        cli = self._cliente("CP Barceló 4")
        self._poliza(cli, "Z-100", "Zurich", ramo="Hogar", estado="Anulada")
        self._poliza(cli, "Z-099", "Zurich", ramo="Hogar", estado="Sustituida")
        estado, r = self._get(
            f"/api/seguros_cliente_poliza_existente?empresa_id=emp1&cliente_id={cli}&ramo=Hogar",
            self.cookie)
        self.assertEqual(estado, 200, r)
        self.assertIsNone(r.get("poliza_existente"))

    def test_ignora_la_base_migrada_legada(self):
        """La base legada está aislada a propósito: no se opera sobre ella con altas nuevas."""
        cli = self._cliente("CP Barceló 4")
        self._poliza(cli, "OLD-1", "Mapfre", ramo="Hogar", estado="Migrado legado")
        estado, r = self._get(
            f"/api/seguros_cliente_poliza_existente?empresa_id=emp1&cliente_id={cli}&ramo=Hogar",
            self.cookie)
        self.assertEqual(estado, 200, r)
        self.assertIsNone(r.get("poliza_existente"))

    def test_sin_cliente_o_sin_empresa_no_revienta(self):
        estado, r = self._get(
            "/api/seguros_cliente_poliza_existente?empresa_id=emp1&cliente_id=", self.cookie)
        self.assertEqual(estado, 200, r)
        self.assertIsNone(r.get("poliza_existente"))


class LaRenovacionYElCambioDeCompaniaDesdeElOcrTests(Base):
    """El botón nuevo del alta por OCR sobre una póliza que ya existe."""

    def test_renovar_misma_compania_actualiza_la_fila_existente_no_crea_otra(self):
        cli = self._cliente("CP Barceló 4")
        pol = self._poliza(cli, "Z-100", "Zurich", ramo="Hogar",
                           fecha_vencimiento="2026-12-31")
        estado, r, _ = self._post("/api/seguros_poliza_accion", {
            "workspace_id": self.ws, "empresa_id": "emp1", "id": pol,
            "accion": "renovar", "nueva_fecha_vencimiento": "2027-12-31",
        }, self.cookie)
        self.assertEqual(estado, 200, r)
        totales = self._fresco("SELECT COUNT(*) AS n FROM seguros WHERE cliente_id = ?", (cli,))
        self.assertEqual(totales[0]["n"], 1)
        fila = self._fresco("SELECT fecha_vencimiento FROM seguros WHERE id = ?", (pol,))[0]
        self.assertEqual(fila["fecha_vencimiento"], "2027-12-31")

    def test_cambio_de_compania_deja_la_vieja_sustituida_y_no_hereda_prima(self):
        cli = self._cliente("CP Barceló 4")
        pol = self._poliza(cli, "Z-100", "Zurich", ramo="Hogar")
        estado, r, _ = self._post("/api/seguros_cambio_compania", {
            "workspace_id": self.ws, "empresa_id": "emp1", "id": pol,
            "nueva_compania": "Generali", "nueva_poliza_numero": "G-9001",
            "fecha_cambio": "2026-09-01", "nueva_prima_total": 250.0,
            "poliza_key": "polizas/g-9001.pdf",
        }, self.cookie)
        self.assertEqual(estado, 200, r)
        vieja = self._fresco("SELECT estado FROM seguros WHERE id = ?", (pol,))[0]
        self.assertEqual(vieja["estado"], "Sustituida")
        nueva = self._fresco(
            "SELECT compania, prima_total, estado FROM seguros WHERE poliza_numero = 'G-9001'")[0]
        self.assertEqual(nueva["compania"], "Generali")
        self.assertAlmostEqual(float(nueva["prima_total"]), 250.0, places=2)
        self.assertEqual(nueva["estado"], "En vigor")
        totales = self._fresco("SELECT COUNT(*) AS n FROM seguros WHERE cliente_id = ?", (cli,))
        self.assertEqual(totales[0]["n"], 2)


if __name__ == "__main__":
    unittest.main()
