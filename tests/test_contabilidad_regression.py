"""Tests de regresión para la lógica de CONTABILIDAD / gestoría del CRM.

Cubren el código que maneja DINERO y asientos contables:
  - ensure_asiento_balanced       (cuadre debe/haber, detección de descuadre, ajuste de céntimos)
  - build_invoice_asiento         (generación de asientos de factura, IVA/IRPF, cuadre)
  - parse_money_value             (parseo de importes es-ES: miles, céntimos)
  - _money_decimal2               (redondeo a 2 decimales ROUND_HALF_UP)
  - infer_expense_account / infer_revenue_account (cuentas PGC)
  - compute_seguros_contabilidad_totals
  - compute_hipotecas_contabilidad_totals
  - delete_gestoria_contabilidad_record (borrado + exclusión anti-huérfanos)

Todos los valores esperados están calculados a mano y documentados en comentarios.
Los importes se comparan con 2 decimales (assertAlmostEqual/assertEqual sobre round(...,2)).
"""

import sqlite3
import unittest
from decimal import Decimal

from web.server import (
    build_invoice_asiento,
    compute_hipotecas_contabilidad_totals,
    compute_seguros_contabilidad_totals,
    delete_gestoria_contabilidad_record,
    ensure_asiento_balanced,
    infer_expense_account,
    infer_revenue_account,
    parse_money_value,
    _money_decimal2,
)


def _sum_debe(lines):
    return round(sum(float(item.get("debe") or 0.0) for item in lines), 2)


def _sum_haber(lines):
    return round(sum(float(item.get("haber") or 0.0) for item in lines), 2)


class EnsureAsientoBalancedTests(unittest.TestCase):
    """El corazón del cuadre contable: debe - haber debe ser 0."""

    def test_balanced_asiento_returns_unchanged_totals(self):
        # debe = 121.00 ; haber = 100.00 + 21.00 = 121.00 ; diff = 0
        lines = [
            {"cuenta": "430", "debe": 121.00, "haber": 0.0},
            {"cuenta": "700", "debe": 0.0, "haber": 100.00},
            {"cuenta": "477", "debe": 0.0, "haber": 21.00},
        ]
        norm, debe, haber = ensure_asiento_balanced(lines)
        self.assertAlmostEqual(debe, 121.00, places=2)
        self.assertAlmostEqual(haber, 121.00, places=2)
        self.assertAlmostEqual(debe - haber, 0.0, places=2)

    def test_descuadre_grande_raises(self):
        # debe = 100.00 ; haber = 90.00 ; diff = 10.00 -> NO es un redondeo, debe fallar
        lines = [
            {"cuenta": "629", "debe": 100.00, "haber": 0.0},
            {"cuenta": "400", "debe": 0.0, "haber": 90.00},
        ]
        with self.assertRaises(ValueError):
            ensure_asiento_balanced(lines, allow_adjustment=True)

    def test_descuadre_grande_raises_without_adjustment(self):
        lines = [
            {"cuenta": "629", "debe": 100.00, "haber": 0.0},
            {"cuenta": "400", "debe": 0.0, "haber": 90.00},
        ]
        with self.assertRaises(ValueError):
            ensure_asiento_balanced(lines, allow_adjustment=False)

    def test_tiny_rounding_diff_is_adjusted_when_allowed(self):
        # debe = 100.01 ; haber = 100.00 ; diff = 0.01 (<= 0.01) -> se corrige la mayor
        # línea de debe restándole 0.01 => 100.00 == 100.00
        lines = [
            {"cuenta": "629", "debe": 100.01, "haber": 0.0},
            {"cuenta": "400", "debe": 0.0, "haber": 100.00},
        ]
        norm, debe, haber = ensure_asiento_balanced(lines, allow_adjustment=True)
        self.assertAlmostEqual(debe, 100.00, places=2)
        self.assertAlmostEqual(haber, 100.00, places=2)
        self.assertAlmostEqual(debe - haber, 0.0, places=2)
        # El céntimo se descuenta de la línea de debe más grande.
        self.assertAlmostEqual(norm[0]["debe"], 100.00, places=2)

    def test_tiny_diff_negative_adjusts_haber_side(self):
        # debe = 100.00 ; haber = 100.01 ; diff = -0.01 -> corrige la mayor línea de haber
        lines = [
            {"cuenta": "629", "debe": 100.00, "haber": 0.0},
            {"cuenta": "400", "debe": 0.0, "haber": 100.01},
        ]
        norm, debe, haber = ensure_asiento_balanced(lines, allow_adjustment=True)
        self.assertAlmostEqual(debe - haber, 0.0, places=2)
        self.assertAlmostEqual(haber, 100.00, places=2)

    def test_tiny_diff_not_adjusted_when_not_allowed(self):
        # Sin allow_adjustment, incluso 0.01 de descuadre debe fallar (no se maquilla).
        lines = [
            {"cuenta": "629", "debe": 100.01, "haber": 0.0},
            {"cuenta": "400", "debe": 0.0, "haber": 100.00},
        ]
        with self.assertRaises(ValueError):
            ensure_asiento_balanced(lines, allow_adjustment=False)

    def test_non_dict_lines_are_ignored(self):
        lines = [
            {"cuenta": "629", "debe": 50.00, "haber": 0.0},
            "basura",
            None,
            {"cuenta": "400", "debe": 0.0, "haber": 50.00},
        ]
        norm, debe, haber = ensure_asiento_balanced(lines)
        self.assertEqual(len(norm), 2)
        self.assertAlmostEqual(debe, 50.00, places=2)
        self.assertAlmostEqual(haber, 50.00, places=2)


class BuildInvoiceAsientoTests(unittest.TestCase):
    """Generación de asientos a partir de una factura parseada. Deben cuadrar."""

    def test_compra_con_iva_cuadra(self):
        # base 100.00 + IVA 21.00 = total 121.00
        # gasto(629) debe 100.00 ; IVA soportado(472) debe 21.00 ; proveedor(400) haber 121.00
        parsed = {
            "tipo": "compra",
            "base_imponible": 100.00,
            "cuota_iva": 21.00,
            "total": 121.00,
            "descripcion": "Material varios",
        }
        lines, debe, haber = build_invoice_asiento(parsed, counterpart_account="400")
        self.assertAlmostEqual(debe, 121.00, places=2)
        self.assertAlmostEqual(haber, 121.00, places=2)
        self.assertAlmostEqual(debe - haber, 0.0, places=2)
        cuentas = {ln["cuenta"] for ln in lines}
        self.assertIn("472", cuentas)  # IVA soportado
        self.assertIn("400", cuentas)  # proveedor

    def test_venta_con_iva_cuadra(self):
        # base 100.00 + IVA 21.00 = total 121.00
        # cliente(430) debe 121.00 ; ingreso(700) haber 100.00 ; IVA repercutido(477) haber 21.00
        parsed = {
            "tipo": "venta",
            "base_imponible": 100.00,
            "cuota_iva": 21.00,
            "total": 121.00,
            "descripcion": "Servicio prestado",
        }
        lines, debe, haber = build_invoice_asiento(parsed, counterpart_account="430")
        self.assertAlmostEqual(debe, 121.00, places=2)
        self.assertAlmostEqual(haber, 121.00, places=2)
        cuentas = {ln["cuenta"] for ln in lines}
        self.assertIn("477", cuentas)  # IVA repercutido
        self.assertIn("430", cuentas)  # cliente

    def test_compra_con_irpf_cuadra(self):
        # base 1000 + IVA 210 - IRPF 150 => payable = 1060
        # DEBE: gasto 1000 + IVA soportado 210 = 1210
        # HABER: IRPF retención(4751) 150 + proveedor(400) 1060 = 1210
        parsed = {
            "tipo": "compra",
            "base_imponible": 1000.00,
            "cuota_iva": 210.00,
            "cuota_irpf": 150.00,
            "descripcion": "Honorarios profesional",
        }
        lines, debe, haber = build_invoice_asiento(parsed, counterpart_account="410")
        self.assertAlmostEqual(debe, 1210.00, places=2)
        self.assertAlmostEqual(haber, 1210.00, places=2)
        self.assertAlmostEqual(debe - haber, 0.0, places=2)
        # La cuenta de retención de IRPF debe aparecer.
        self.assertIn("4751", {ln["cuenta"] for ln in lines})

    def test_compra_con_centimos_cuadra(self):
        # base 33.33 + IVA 7.00 (sin total explícito) => payable = 40.33
        # DEBE: 33.33 + 7.00 = 40.33 ; HABER: proveedor 40.33
        parsed = {
            "tipo": "compra",
            "base_imponible": 33.33,
            "cuota_iva": 7.00,
            "descripcion": "Suministros",
        }
        lines, debe, haber = build_invoice_asiento(parsed, counterpart_account="400")
        self.assertAlmostEqual(debe, 40.33, places=2)
        self.assertAlmostEqual(haber, 40.33, places=2)
        self.assertAlmostEqual(debe - haber, 0.0, places=2)

    def test_compra_base_exenta_y_no_sujeta_cuadra(self):
        # base 0, exento 50.00, no sujeta 30.00, sin IVA/IRPF
        # payable = base(0)+iva(0)+special(50+30=80)-irpf(0) = 80.00
        # DEBE: gasto exento 50 + gasto no sujeto 30 = 80 ; HABER: proveedor 80
        parsed = {
            "tipo": "compra",
            "base_imponible": 0.0,
            "base_exenta": 50.00,
            "base_no_sujeta": 30.00,
            "descripcion": "Seguro anual",
        }
        lines, debe, haber = build_invoice_asiento(parsed, counterpart_account="400")
        self.assertAlmostEqual(debe, 80.00, places=2)
        self.assertAlmostEqual(haber, 80.00, places=2)


class AccountInferenceTests(unittest.TestCase):
    def test_infer_expense_account_mapping(self):
        self.assertEqual(infer_expense_account("Póliza de seguro anual"), "625")
        self.assertEqual(infer_expense_account("Alquiler local"), "621")
        self.assertEqual(infer_expense_account("Honorarios asesor profesional"), "623")
        self.assertEqual(infer_expense_account("Factura de luz"), "628")
        self.assertEqual(infer_expense_account("Compra genérica"), "629")  # default

    def test_infer_revenue_account_mapping(self):
        self.assertEqual(infer_revenue_account("Alquiler mensual"), "705")
        self.assertEqual(infer_revenue_account("Venta de servicios"), "700")  # default


class ParseMoneyValueTests(unittest.TestCase):
    """Parseo de importes en formato es-ES (peligro típico de pérdida de céntimos)."""

    def test_es_format_thousands_and_decimals(self):
        # "20.000,50" -> 20000.50 (punto miles, coma decimal)
        self.assertAlmostEqual(parse_money_value("20.000,50"), 20000.50, places=2)

    def test_es_format_with_currency_symbol(self):
        # "1.234,56 €" -> 1234.56
        self.assertAlmostEqual(parse_money_value("1.234,56 €"), 1234.56, places=2)

    def test_comma_only_decimal(self):
        # "20000,50" -> 20000.50
        self.assertAlmostEqual(parse_money_value("20000,50"), 20000.50, places=2)

    def test_dot_thousands_no_decimals(self):
        # "1.234" -> 1234.0 (punto como separador de miles, grupo de 3)
        self.assertAlmostEqual(parse_money_value("1.234"), 1234.0, places=2)

    def test_dot_decimal_us_style(self):
        # "1234.56" -> 1234.56 (punto decimal, no grupo de 3)
        self.assertAlmostEqual(parse_money_value("1234.56"), 1234.56, places=2)

    def test_float_and_int_passthrough(self):
        self.assertAlmostEqual(parse_money_value(1234.56), 1234.56, places=2)
        self.assertAlmostEqual(parse_money_value(1000), 1000.0, places=2)

    def test_empty_and_none_return_zero(self):
        self.assertEqual(parse_money_value(None), 0.0)
        self.assertEqual(parse_money_value(""), 0.0)
        self.assertEqual(parse_money_value("   "), 0.0)
        self.assertEqual(parse_money_value("-"), 0.0)

    def test_negative_amount(self):
        self.assertAlmostEqual(parse_money_value("-1.234,56"), -1234.56, places=2)


class MoneyDecimal2Tests(unittest.TestCase):
    def test_decimal_quantize_two_places(self):
        # "1.234,56" -> Decimal("1234.56")
        self.assertEqual(_money_decimal2("1.234,56"), Decimal("1234.56"))

    def test_decimal_half_up_rounding(self):
        # "10,555" -> parse 10.555 -> ROUND_HALF_UP a 2 decimales -> 10.56
        self.assertEqual(_money_decimal2("10,555"), Decimal("10.56"))

    def test_decimal_empty_is_zero(self):
        self.assertEqual(_money_decimal2(""), Decimal("0.00"))
        self.assertEqual(_money_decimal2(None), Decimal("0.00"))


CONTAB_SCHEMA = """
CREATE TABLE gestoria_contabilidad (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  cliente_id TEXT,
  cliente_ids_json TEXT,
  hipoteca_id TEXT,
  seguro_id TEXT,
  poliza_numero TEXT,
  fecha TEXT,
  concepto TEXT,
  gestion TEXT,
  tipo TEXT,
  importe REAL,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE hipotecas_contabilidad_excluidas (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  hipoteca_id TEXT NOT NULL,
  fecha TEXT NOT NULL,
  gestion TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (empresa_id, hipoteca_id, fecha, gestion)
);
"""


class ContabilidadTotalsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(CONTAB_SCHEMA)

    def tearDown(self):
        self.conn.close()

    def _insert(self, **kw):
        cols = {
            "id": kw["id"],
            "empresa_id": kw.get("empresa_id", "e1"),
            "hipoteca_id": kw.get("hipoteca_id"),
            "seguro_id": kw.get("seguro_id"),
            "poliza_numero": kw.get("poliza_numero"),
            "fecha": kw.get("fecha", "2025-05-01"),
            "gestion": kw.get("gestion", ""),
            "tipo": kw.get("tipo", "Ingreso"),
            "importe": kw.get("importe", 0.0),
            "notas": kw.get("notas", ""),
            "created_at": "2026-01-01",
            "updated_at": "2026-01-01",
        }
        self.conn.execute(
            """
            INSERT INTO gestoria_contabilidad
              (id, empresa_id, hipoteca_id, seguro_id, poliza_numero, fecha, gestion, tipo, importe, notas, created_at, updated_at)
            VALUES (:id, :empresa_id, :hipoteca_id, :seguro_id, :poliza_numero, :fecha, :gestion, :tipo, :importe, :notas, :created_at, :updated_at)
            """,
            cols,
        )
        self.conn.commit()

    # --- SEGUROS ---
    def test_seguros_totals_split_ingresos_gastos(self):
        # Ingreso comisión emisión 150.55 + Ingreso renovación 49.45 = 200.00 ingresos
        # Gasto extorno 30.00
        self._insert(id="s1", seguro_id="seg1", gestion="Comisión emisión", tipo="Ingreso", importe=150.55)
        self._insert(id="s2", seguro_id="seg1", gestion="Comisión renovación", tipo="Ingreso", importe=49.45)
        self._insert(id="s3", seguro_id="seg1", gestion="Extorno", tipo="Gasto", importe=30.00)
        totals = compute_seguros_contabilidad_totals(self.conn, "e1")
        self.assertAlmostEqual(totals["ingresos"], 200.00, places=2)
        self.assertAlmostEqual(totals["gastos"], 30.00, places=2)

    def test_seguros_totals_year_filter(self):
        self._insert(id="s1", seguro_id="seg1", gestion="Comisión emisión", tipo="Ingreso", importe=100.00, fecha="2025-03-01")
        self._insert(id="s2", seguro_id="seg1", gestion="Comisión emisión", tipo="Ingreso", importe=200.00, fecha="2024-03-01")
        totals_2025 = compute_seguros_contabilidad_totals(self.conn, "e1", year=2025)
        self.assertAlmostEqual(totals_2025["ingresos"], 100.00, places=2)

    def test_seguros_totals_ignores_non_seguro_rows(self):
        # Fila sin ninguna marca de seguro (sin seguro_id, poliza, notas o gestión reconocida)
        # no debe contarse en los totales de seguros.
        self._insert(id="x1", gestion="Otra cosa", tipo="Ingreso", importe=999.00)
        totals = compute_seguros_contabilidad_totals(self.conn, "e1")
        self.assertAlmostEqual(totals["ingresos"], 0.0, places=2)
        self.assertAlmostEqual(totals["gastos"], 0.0, places=2)

    # --- HIPOTECAS ---
    def test_hipotecas_totals_resultado_and_comision_cliente(self):
        # Ingresos: Comisión cliente 1000.00 + Cesión Juan 200.00 = 1200.00
        # Gastos: Gestoría 150.00
        # resultado = 1200 - 150 = 1050.00
        # comision_cliente = 1000.00
        # rentabilidad_ratio = 1050 / 150 = 7.0
        self._insert(id="h1", hipoteca_id="hip1", gestion="Comisión cliente", tipo="Ingreso", importe=1000.00)
        self._insert(id="h2", hipoteca_id="hip1", gestion="Cesión Juan", tipo="Ingreso", importe=200.00)
        self._insert(id="h3", hipoteca_id="hip1", gestion="Gestoría", tipo="Gasto", importe=150.00)
        totals = compute_hipotecas_contabilidad_totals(self.conn, "e1")
        self.assertAlmostEqual(totals["ingresos"], 1200.00, places=2)
        self.assertAlmostEqual(totals["gastos"], 150.00, places=2)
        self.assertAlmostEqual(totals["comision_cliente"], 1000.00, places=2)
        self.assertAlmostEqual(totals["resultado"], 1050.00, places=2)
        self.assertAlmostEqual(totals["rentabilidad_ratio"], 7.0, places=4)

    def test_hipotecas_totals_ratio_none_when_no_gastos(self):
        # Sin gastos -> rentabilidad_ratio debe ser None (no dividir por cero)
        self._insert(id="h1", hipoteca_id="hip1", gestion="Comisión cliente", tipo="Ingreso", importe=500.00)
        totals = compute_hipotecas_contabilidad_totals(self.conn, "e1")
        self.assertAlmostEqual(totals["resultado"], 500.00, places=2)
        self.assertIsNone(totals["rentabilidad_ratio"])

    def test_hipotecas_totals_centimos_preserved(self):
        # Comisión cliente 333.33 + 333.33 + 333.34 = 1000.00 (sin pérdida de céntimos)
        self._insert(id="h1", hipoteca_id="hip1", gestion="Comisión cliente", tipo="Ingreso", importe=333.33)
        self._insert(id="h2", hipoteca_id="hip1", gestion="Comisión cliente", tipo="Ingreso", importe=333.33)
        self._insert(id="h3", hipoteca_id="hip1", gestion="Comisión cliente", tipo="Ingreso", importe=333.34)
        totals = compute_hipotecas_contabilidad_totals(self.conn, "e1")
        self.assertAlmostEqual(totals["comision_cliente"], 1000.00, places=2)
        self.assertAlmostEqual(totals["ingresos"], 1000.00, places=2)


class DeleteGestoriaContabilidadRecordTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(CONTAB_SCHEMA)

    def tearDown(self):
        self.conn.close()

    def _insert(self, record_id, notas="", hipoteca_id=None, fecha="2025-02-10", gestion="Comisión cliente"):
        self.conn.execute(
            """
            INSERT INTO gestoria_contabilidad
              (id, empresa_id, hipoteca_id, fecha, gestion, tipo, importe, notas, created_at, updated_at)
            VALUES (?, 'e1', ?, ?, ?, 'Ingreso', 100.0, ?, '2026-01-01', '2026-01-01')
            """,
            (record_id, hipoteca_id, fecha, gestion, notas),
        )
        self.conn.commit()

    def test_delete_missing_returns_false(self):
        self.assertFalse(delete_gestoria_contabilidad_record(self.conn, "nope"))

    def test_delete_empty_id_returns_false(self):
        self.assertFalse(delete_gestoria_contabilidad_record(self.conn, ""))

    def test_delete_manual_record_removes_row_without_exclusion(self):
        # Registro manual (sin notas AUTO) -> se borra y NO crea exclusión.
        self._insert("m1", notas="", hipoteca_id=None)
        deleted = delete_gestoria_contabilidad_record(self.conn, "m1")
        self.assertTrue(deleted)
        remaining = self.conn.execute("SELECT COUNT(*) FROM gestoria_contabilidad WHERE id='m1'").fetchone()[0]
        self.assertEqual(remaining, 0)
        exclusions = self.conn.execute("SELECT COUNT(*) FROM hipotecas_contabilidad_excluidas").fetchone()[0]
        self.assertEqual(exclusions, 0)

    def test_delete_auto_hipoteca_record_creates_exclusion(self):
        # Registro AUTO ligado a hipoteca -> se borra y crea una fila de exclusión
        # para que el sync no lo recree (evita huérfanos / resurrección).
        self._insert("a1", notas="AUTO CRM HIPOTECAS h1", hipoteca_id="h1", fecha="2025-02-10", gestion="Comisión cliente")
        deleted = delete_gestoria_contabilidad_record(self.conn, "a1")
        self.assertTrue(deleted)
        gone = self.conn.execute("SELECT COUNT(*) FROM gestoria_contabilidad WHERE id='a1'").fetchone()[0]
        self.assertEqual(gone, 0)
        exclusion = self.conn.execute(
            """
            SELECT COUNT(*) FROM hipotecas_contabilidad_excluidas
            WHERE empresa_id='e1' AND hipoteca_id='h1' AND fecha='2025-02-10' AND gestion='Comisión cliente'
            """
        ).fetchone()[0]
        self.assertEqual(exclusion, 1)


if __name__ == "__main__":
    unittest.main()
