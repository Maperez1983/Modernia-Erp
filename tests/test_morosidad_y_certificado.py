"""Morosidad y certificado de deuda.

Lo que más quema el teléfono de un administrador. Antes no había ni una consulta:
la deuda de un propietario había que sacarla a mano de los recibos.

Dos decisiones que este test protege:

**Un recibo devuelto está impagado.** Contar solo los pendientes dejaba fuera justo
los que el banco rechazó, que son la mitad de la morosidad real y los que hay que
reclamar antes. Aquí cuentan los dos estados.

**El certificado no dice más de lo que el CRM sabe.** Enumera los recibos impagados,
sus periodos y su suma, y deja el pie de firma en blanco. No afirma nada sobre plazos,
intereses ni efectos legales, porque eso no lo decide un programa: el certificado lo
emite el secretario administrador con el visto bueno del presidente, y quien lo use
para una compraventa o un procedimiento tiene que revisarlo y firmarlo.
"""

import datetime
import os
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
os.environ.pop("DATABASE_URL", None)
from web import server  # noqa: E402

try:
    from pypdf import PdfReader

    HAY_PYPDF = True
except Exception:  # pragma: no cover
    HAY_PYPDF = False


class BaseConDeuda(unittest.TestCase):
    def setUp(self):
        self.conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(self.conn)
        ahora = datetime.datetime.now().isoformat(timespec="seconds")
        self.ws, self.com = "ws1", "com1"
        self.conn.execute(
            "INSERT INTO workspace_fincas_comunidades (id, workspace_id, nombre, direccion, cif, estado, "
            "created_at, updated_at) VALUES (?,?,?,?,?,'Activa',datetime(?),datetime(?))",
            (self.com, self.ws, "C.P. Velázquez 11", "Avenida Velázquez 11", "H12345678", ahora, ahora),
        )
        for vid, nombre, piso in (("v1", "Juan Pérez Gómez", "1A"), ("v2", "Ana Ruiz", "1B")):
            self.conn.execute(
                "INSERT INTO workspace_fincas_vecinos (id, workspace_id, comunidad_id, nombre, piso, nif, "
                "coeficiente, created_at, updated_at) VALUES (?,?,?,?,?,'12345678Z',4.1667,datetime(?),datetime(?))",
                (vid, self.ws, self.com, nombre, piso, ahora, ahora),
            )
        # Juan debe abril (pendiente), mayo (devuelto) y junio (pendiente); julio lo pagó.
        for i, (periodo, estado) in enumerate(
            (("2026-04", "Pendiente"), ("2026-05", "Devuelto"), ("2026-06", "Pendiente"), ("2026-07", "Cobrado"))
        ):
            self.conn.execute(
                "INSERT INTO workspace_fincas_recibos (id, workspace_id, comunidad_id, vecino_id, periodo, "
                "concepto, importe, estado, created_at, updated_at) "
                "VALUES (?,?,?,'v1',?,?,50.0,?,datetime(?),datetime(?))",
                (f"r{i}", self.ws, self.com, periodo, f"Cuota de comunidad {periodo}", estado, ahora, ahora),
            )
        # Ana está al corriente.
        self.conn.execute(
            "INSERT INTO workspace_fincas_recibos (id, workspace_id, comunidad_id, vecino_id, periodo, concepto, "
            "importe, estado, created_at, updated_at) "
            "VALUES ('r9',?,?,'v2','2026-07','Cuota',50.0,'Cobrado',datetime(?),datetime(?))",
            (self.ws, self.com, ahora, ahora),
        )
        self.conn.commit()

    def morosidad(self):
        return server.fetch_workspace_fincas_morosidad(self.conn, self.ws, self.com)


class QuienDebeYCuantoTests(BaseConDeuda):
    def test_solo_sale_quien_debe(self):
        datos = self.morosidad()
        self.assertEqual(datos["resumen"]["deudores"], 1)
        self.assertEqual(datos["rows"][0]["nombre"], "Juan Pérez Gómez")

    def test_un_recibo_devuelto_cuenta_como_deuda(self):
        """Contar solo los pendientes dejaba fuera la mitad de la morosidad real."""
        datos = self.morosidad()
        self.assertEqual(datos["resumen"]["deuda_total"], 150.0)
        self.assertEqual(datos["rows"][0]["recibos"], 3)

    def test_lo_cobrado_no_cuenta(self):
        datos = self.morosidad()
        self.assertNotIn("2026-07", (datos["rows"][0]["desde"], datos["rows"][0]["hasta"]))

    def test_dice_desde_cuando_se_debe(self):
        datos = self.morosidad()
        self.assertEqual(datos["rows"][0]["desde"], "2026-04")
        self.assertEqual(datos["rows"][0]["hasta"], "2026-06")

    def test_una_comunidad_al_corriente_no_tiene_deudores(self):
        self.conn.execute("UPDATE workspace_fincas_recibos SET estado = 'Cobrado'")
        self.conn.commit()
        datos = self.morosidad()
        self.assertEqual(datos["rows"], [])
        self.assertEqual(datos["resumen"]["deuda_total"], 0)

    def test_los_deudores_salen_por_deuda_descendente(self):
        ahora = datetime.datetime.now().isoformat(timespec="seconds")
        self.conn.execute(
            "INSERT INTO workspace_fincas_recibos (id, workspace_id, comunidad_id, vecino_id, periodo, concepto, "
            "importe, estado, created_at, updated_at) "
            "VALUES ('r20',?,?,'v2','2026-06','Cuota',500.0,'Pendiente',datetime(?),datetime(?))",
            (self.ws, self.com, ahora, ahora),
        )
        self.conn.commit()
        datos = self.morosidad()
        self.assertEqual([d["deuda"] for d in datos["rows"]], [500.0, 150.0])


@unittest.skipUnless(HAY_PYPDF, "hace falta pypdf")
class ElCertificadoTests(BaseConDeuda):
    def certificado(self):
        vecino = self.conn.execute("SELECT * FROM workspace_fincas_vecinos WHERE id='v1'").fetchone()
        comunidad = self.conn.execute("SELECT * FROM workspace_fincas_comunidades WHERE id=?", (self.com,)).fetchone()
        recibos = self.conn.execute(
            "SELECT periodo, concepto, importe, estado FROM workspace_fincas_recibos "
            "WHERE vecino_id='v1' AND estado IN ('Pendiente','Devuelto') ORDER BY periodo"
        ).fetchall()
        pdf = server.build_certificado_deuda_pdf(
            comunidad, vecino, recibos, workspace={"primary_color": "#3C6E71"}, company={"nombre": "Estudio Velazquez"}
        )
        import io

        texto = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages)
        return pdf, texto

    def test_es_texto_y_no_una_imagen(self):
        import io

        pdf, _t = self.certificado()
        for pagina in PdfReader(io.BytesIO(pdf)).pages:
            self.assertTrue(list((pagina.get("/Resources", {}) or {}).get("/Font") or {}))

    def test_dice_el_importe_y_los_recibos(self):
        _pdf, texto = self.certificado()
        self.assertIn("150,00", texto)
        self.assertIn("2026-04", texto)
        self.assertIn("2026-06", texto)

    def test_identifica_a_la_comunidad_y_al_propietario(self):
        _pdf, texto = self.certificado()
        self.assertIn("C.P. Velázquez 11", texto)
        self.assertIn("Juan Pérez Gómez", texto)
        self.assertIn("12345678Z", texto)

    def test_no_incluye_lo_ya_cobrado(self):
        _pdf, texto = self.certificado()
        self.assertNotIn("2026-07", texto)

    def test_deja_claro_que_hay_que_firmarlo(self):
        """Un programa no puede emitir por sí solo un certificado con efectos."""
        _pdf, texto = self.certificado()
        self.assertIn("secretario administrador", texto)
        self.assertIn("presidente", texto)

    def test_no_se_inventa_plazos_ni_intereses(self):
        """Se mira el documento, no el código: el comentario sí nombra lo que evita."""
        _pdf, texto = self.certificado()
        for palabra in ("interés", "intereses", "monitorio", "artículo", "recargo"):
            with self.subTest(palabra=palabra):
                self.assertNotIn(palabra, texto.lower())


class LosEndpointsEstanGuardadosTests(unittest.TestCase):
    def test_los_dos_get_comprueban_pertenencia(self):
        for ruta in ("/api/workspace_fincas_morosidad", "/api/workspace_fincas_certificado_deuda"):
            with self.subTest(ruta=ruta):
                i = SERVER.index(f'if path == "{ruta}"')
                self.assertIn("enforce_workspace_membership", SERVER[i: i + 1600])

    def test_el_certificado_solo_sale_de_un_propietario_del_workspace(self):
        i = SERVER.index('if path == "/api/workspace_fincas_certificado_deuda"')
        cuerpo = SERVER[i: i + 2200]
        self.assertIn("WHERE id = ? AND workspace_id = ?", cuerpo)

    def test_la_pantalla_ofrece_el_certificado(self):
        self.assertIn("Certificado de deuda", APP)
        self.assertIn("/api/workspace_fincas_certificado_deuda", APP)


if __name__ == "__main__":
    unittest.main()
