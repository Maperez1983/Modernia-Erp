"""Presupuesto anual, liquidación y el enlace con el CRM de seguros.

Dos piezas distintas de la misma tanda.

**El ejercicio.** La contabilidad de la comunidad no es una lista de apuntes: es un
presupuesto aprobado en junta contra el que se compara lo que realmente se gasta.
Sin esa comparación no hay liquidación que llevar a la junta siguiente.

El **fondo de reserva** se calcula como porcentaje del presupuesto, pero el
porcentaje **no viene puesto**. La ley fija un mínimo y no lo voy a escribir de
memoria: un número inventado aquí acabaría en una liquidación firmada. Mientras esté
a cero la pantalla lo dice, en vez de calcular con un valor falso.

**El enlace con seguros.** Una incidencia puede apuntar a la póliza de la comunidad y
a la referencia de siniestro que dé la compañía. Es la ventaja que tiene Fincas
Velázquez por llevar los dos CRM en la misma base y que una aplicación suelta de
fincas no puede dar: el parte de agua se gestiona con la póliza delante.
"""

import datetime
import os
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
os.environ.pop("DATABASE_URL", None)
from web import server  # noqa: E402


class BaseEjercicio(unittest.TestCase):
    def setUp(self):
        self.conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(self.conn)
        self.ahora = datetime.datetime.now().isoformat(timespec="seconds")
        self.ws, self.com = "ws1", "com1"
        self.conn.execute(
            "INSERT INTO workspace_fincas_comunidades (id, workspace_id, nombre, estado, created_at, updated_at) "
            "VALUES (?,?,?,'Activa',datetime(?),datetime(?))",
            (self.com, self.ws, "C.P. Prueba", self.ahora, self.ahora),
        )
        self.conn.commit()

    def presupuesto(self, fondo_pct=0, partidas=(("Limpieza", 6000), ("Ascensor", 3600))):
        self.conn.execute(
            "INSERT INTO workspace_fincas_presupuesto_anual (id, workspace_id, comunidad_id, ejercicio, estado, "
            "fondo_reserva_pct, created_at, updated_at) VALUES ('p1',?,?,'2026','Aprobado',?,datetime(?),datetime(?))",
            (self.ws, self.com, fondo_pct, self.ahora, self.ahora),
        )
        for n, (concepto, importe) in enumerate(partidas, start=1):
            self.conn.execute(
                "INSERT INTO workspace_fincas_presupuesto_partidas (id, workspace_id, presupuesto_id, orden, "
                "concepto, importe, created_at, updated_at) VALUES (?,?, 'p1', ?, ?, ?, datetime(?), datetime(?))",
                (f"pp{n}", self.ws, n, concepto, importe, self.ahora, self.ahora),
            )
        self.conn.commit()

    def apunte(self, concepto, importe, tipo="Gasto", fecha="2026-01-15"):
        self.conn.execute(
            "INSERT INTO workspace_fincas_contabilidad (id, workspace_id, comunidad_id, fecha, tipo, concepto, "
            "importe, created_at, updated_at) VALUES (?,?,?,?,?,?,?,datetime(?),datetime(?))",
            (os.urandom(8).hex(), self.ws, self.com, fecha, tipo, concepto, importe, self.ahora, self.ahora),
        )
        self.conn.commit()

    def ejercicio(self, anyo="2026"):
        return server.fetch_workspace_fincas_ejercicio(self.conn, self.ws, self.com, anyo)


class LoPresupuestadoContraLoGastadoTests(BaseEjercicio):
    def test_suma_las_partidas(self):
        self.presupuesto()
        self.assertEqual(self.ejercicio()["resumen"]["presupuestado"], 9600.0)

    def test_separa_gastos_de_ingresos(self):
        self.presupuesto()
        self.apunte("Limpieza enero", 500, "Gasto")
        self.apunte("Derrama", 1000, "Ingreso")
        r = self.ejercicio()["resumen"]
        self.assertEqual(r["gastado"], 500.0)
        self.assertEqual(r["ingresado"], 1000.0)

    def test_la_desviacion_es_lo_que_queda_por_gastar(self):
        self.presupuesto()
        self.apunte("Limpieza enero", 500)
        self.assertEqual(self.ejercicio()["resumen"]["desviacion"], 9100.0)

    def test_los_apuntes_de_otro_ano_no_cuentan(self):
        self.presupuesto()
        self.apunte("Gasto de 2025", 999, "Gasto", fecha="2025-12-31")
        self.assertEqual(self.ejercicio()["resumen"]["gastado"], 0.0)

    def test_sin_presupuesto_no_revienta(self):
        r = self.ejercicio()
        self.assertIsNone(r["presupuesto"])
        self.assertEqual(r["resumen"]["presupuestado"], 0.0)

    def test_cuenta_los_recibos_cobrados_y_los_que_no(self):
        """De ahí sale el dinero de verdad, no del libro de apuntes."""
        self.presupuesto()
        for periodo, estado, importe in (("2026-01", "Cobrado", 300), ("2026-02", "Pendiente", 300),
                                         ("2026-03", "Devuelto", 300), ("2025-12", "Cobrado", 999)):
            self.conn.execute(
                "INSERT INTO workspace_fincas_recibos (id, workspace_id, comunidad_id, vecino_id, periodo, "
                "concepto, importe, estado, created_at, updated_at) "
                "VALUES (?,?,?,'v1',?,'Cuota',?,?,datetime(?),datetime(?))",
                (os.urandom(8).hex(), self.ws, self.com, periodo, importe, estado, self.ahora, self.ahora),
            )
        self.conn.commit()
        r = self.ejercicio()["resumen"]
        self.assertEqual(r["recibos_cobrados"], 300.0)
        self.assertEqual(r["recibos_pendientes"], 600.0)


class ElFondoDeReservaNoSeInventaTests(BaseEjercicio):
    def test_sin_configurar_no_se_calcula(self):
        self.presupuesto(fondo_pct=0)
        r = self.ejercicio()["resumen"]
        self.assertTrue(r["fondo_reserva_sin_configurar"])
        self.assertEqual(r["fondo_reserva"], 0.0)

    def test_configurado_se_calcula_sobre_el_presupuesto(self):
        self.presupuesto(fondo_pct=10)
        r = self.ejercicio()["resumen"]
        self.assertFalse(r["fondo_reserva_sin_configurar"])
        self.assertEqual(r["fondo_reserva"], 960.0)

    def test_no_hay_ningun_porcentaje_escrito_en_el_codigo(self):
        i = SERVER.index("def fetch_workspace_fincas_ejercicio")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        for sospechoso in ("* 0.05", "* 0.10", "= 5.0", "= 10.0"):
            with self.subTest(sospechoso=sospechoso):
                self.assertNotIn(sospechoso, cuerpo)

    def test_la_pantalla_lo_dice_en_vez_de_calcular(self):
        self.assertIn("El fondo de reserva no está configurado", APP)
        self.assertIn("confírmalo con el Colegio", APP)


class LaIncidenciaSeEnlazaConLaPolizaTests(unittest.TestCase):
    def test_la_incidencia_guarda_poliza_y_siniestro(self):
        conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(conn)
        ahora = datetime.datetime.now().isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO workspace_fincas_incidencias (id, workspace_id, comunidad_id, titulo, estado, "
            "seguro_id, siniestro_ref, created_at, updated_at) "
            "VALUES ('i1','ws1','com1','Fuga en el garaje','Abierta','seg-123','SIN-2026-0044',datetime(?),datetime(?))",
            (ahora, ahora),
        )
        conn.commit()
        fila = conn.execute("SELECT seguro_id, siniestro_ref FROM workspace_fincas_incidencias WHERE id='i1'").fetchone()
        self.assertEqual(server.row_value(fila, "seguro_id", ""), "seg-123")
        self.assertEqual(server.row_value(fila, "siniestro_ref", ""), "SIN-2026-0044")

    def test_el_endpoint_lee_los_dos_campos(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_incidencias"')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn('payload.get("seguro_id")', cuerpo)
        self.assertIn('payload.get("siniestro_ref")', cuerpo)
        self.assertIn("seguro_id, siniestro_ref, created_at, updated_at", cuerpo)

    def test_el_listado_de_polizas_esta_guardado(self):
        i = SERVER.index('if path == "/api/workspace_fincas_polizas"')
        cuerpo = SERVER[i: i + 1500]
        self.assertIn("enforce_workspace_membership", cuerpo)
        self.assertIn("WHERE workspace_id = ?", cuerpo)

    def test_el_listado_de_polizas_no_devuelve_de_mas(self):
        """En un desplegable no pintan nada ni los importes ni los datos del tomador."""
        i = SERVER.index('if path == "/api/workspace_fincas_polizas"')
        cuerpo = SERVER[i: i + 1500]
        for columna in ("prima", "iban", "nif", "telefono", "email"):
            with self.subTest(columna=columna):
                self.assertNotIn(f"{columna},", cuerpo)

    def test_el_formulario_ofrece_la_poliza(self):
        self.assertIn('name="seguro_id"', APP)
        self.assertIn('name="siniestro_ref"', APP)


class LaPantallaDelEjercicioExisteTests(unittest.TestCase):
    def test_hay_pestana(self):
        self.assertIn('data-community-ficha-tab="ejercicio"', HTML)

    def test_el_post_esta_dado_de_alta_y_guardado(self):
        self.assertIn('"/api/workspace_fincas_presupuesto_anual",', SERVER)
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_presupuesto_anual"')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn("enforce_workspace_membership(conn, session, workspace_id, write=True)", cuerpo)

    def test_el_get_del_ejercicio_comprueba_pertenencia(self):
        i = SERVER.index('if path == "/api/workspace_fincas_ejercicio"')
        self.assertIn("enforce_workspace_membership", SERVER[i: i + 1400])

    def test_solo_hay_un_presupuesto_por_ejercicio(self):
        """Dos presupuestos del mismo año son dos liquidaciones distintas."""
        self.assertIn("idx_fincas_presupuesto_anual_unico", SERVER)


if __name__ == "__main__":
    unittest.main()
