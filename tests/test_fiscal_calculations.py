"""Tests de regresión para los calculadores fiscales del CRM.

Cubre las funciones puras (y algunas de integración con SQLite en memoria) de
`web/server.py` que hasta ahora tenían CERO cobertura:

  IIVTNU (plusvalía municipal):
    - _iivtnu_max_coefs_for_devengo   (selección de tabla de coeficientes por RDL)
    - _iivtnu_full_years / _iivtnu_full_months
    - _iivtnu_objective_coef          (método objetivo: base = suelo x coef)
    - _iivtnu_simulate                (no sujeción por inexistencia de incremento)

  IRPF (ganancia patrimonial):
    - _irpf_savings_scale_for_year / _irpf_tax_progressive  (tramos del ahorro)
    - _irpf_years_to_1996_rounded_up
    - _irpf_abatimiento_reduction_pct
    - _irpf_apply_abatimiento_dt9     (régimen transitorio DT 9ª)
    - _irpf_ganancia_simulate         (ganancia, exención >65 vivienda habitual)

Cada valor esperado está calculado A MANO en el comentario adyacente y verificado
contra el comportamiento actual del código. Los tests documentan el
comportamiento correcto ya validado; si en el futuro un cambio los rompe, revísese
si el cambio es intencional.
"""

import sqlite3
import unittest
from datetime import date

from web import server


class IivtnuCoefTableTests(unittest.TestCase):
    """Selección de la tabla de coeficientes máximos según la fecha de devengo."""

    def test_rdl_26_2021_table_selected_for_2022(self):
        # Devengo dentro de la vigencia de RDL 26/2021 (10/11/2021 - 31/12/2022).
        tbl, src = server._iivtnu_max_coefs_for_devengo(date(2022, 6, 15))
        self.assertIn("RDL 26/2021", src["source_label"])
        # Valores concretos de la tabla RDL 26/2021 (BOE-A-2021-18276).
        self.assertAlmostEqual(tbl["lt1"], 0.14, places=6)
        self.assertAlmostEqual(tbl["1"], 0.13, places=6)
        self.assertAlmostEqual(tbl["14"], 0.10, places=6)
        self.assertAlmostEqual(tbl["20+"], 0.45, places=6)

    def test_ley_31_2022_table_selected_for_2023(self):
        tbl, src = server._iivtnu_max_coefs_for_devengo(date(2023, 3, 1))
        self.assertIn("Ley 31/2022", src["source_label"])
        self.assertAlmostEqual(tbl["1"], 0.15, places=6)
        self.assertAlmostEqual(tbl["19"], 0.29, places=6)

    def test_rdl_8_2023_table_selected_for_2024(self):
        tbl, src = server._iivtnu_max_coefs_for_devengo(date(2024, 1, 1))
        self.assertIn("RDL 8/2023", src["source_label"])
        self.assertAlmostEqual(tbl["14"], 0.09, places=6)
        self.assertAlmostEqual(tbl["20+"], 0.40, places=6)


class IivtnuFullYearsMonthsTests(unittest.TestCase):
    """Número de años/meses completos entre adquisición y devengo."""

    def test_full_years_one_day_before_anniversary(self):
        # 2010-06-15 -> 2020-06-14: aún no se cumple el 10º aniversario => 9 años.
        self.assertEqual(
            server._iivtnu_full_years(date(2010, 6, 15), date(2020, 6, 14)), 9
        )

    def test_full_years_exact_anniversary(self):
        # 2010-06-15 -> 2020-06-15: se cumple el 10º aniversario => 10 años.
        self.assertEqual(
            server._iivtnu_full_years(date(2010, 6, 15), date(2020, 6, 15)), 10
        )

    def test_full_months_partial(self):
        # 2021-10-01 -> 2022-04-01: 6 meses completos.
        self.assertEqual(
            server._iivtnu_full_months(date(2021, 10, 1), date(2022, 4, 1)), 6
        )

    def test_full_months_day_short(self):
        # 2021-10-15 -> 2022-04-10: el día de devengo (10) < día de adquisición (15)
        # => se descuenta un mes => 5 meses.
        self.assertEqual(
            server._iivtnu_full_months(date(2021, 10, 15), date(2022, 4, 10)), 5
        )

    def test_full_years_non_date_returns_zero(self):
        self.assertEqual(server._iivtnu_full_years(None, date(2020, 1, 1)), 0)


class IivtnuObjectiveCoefTests(unittest.TestCase):
    """Método objetivo: coef según años completos, prorrateo <1 año y tope de 20 años."""

    def test_objective_coef_14_years_rdl_26_2021(self):
        # Adquisición 2008-03-10, devengo 2022-03-10 => 14 años completos.
        # Tabla RDL 26/2021 (devengo 2022), coef[14] = 0.10.
        acq, dev = date(2008, 3, 10), date(2022, 3, 10)
        tbl, _ = server._iivtnu_max_coefs_for_devengo(dev)
        info = server._iivtnu_objective_coef(acq, dev, tbl)
        self.assertEqual(info["years"], 14)
        self.assertAlmostEqual(info["coef_objetivo"], 0.10, places=6)
        # base = suelo x coef = 50.000 x 0.10 = 5.000,00
        base = round(50000.0 * info["coef_objetivo"], 2)
        self.assertAlmostEqual(base, 5000.00, places=2)

    def test_objective_coef_less_than_one_year_prorated(self):
        # 2021-10-01 -> 2022-04-01: 6 meses. Prorrateo: coef[lt1] x (6/12).
        # RDL 26/2021 lt1 = 0.14 => 0.14 x 0.5 = 0.07.
        acq, dev = date(2021, 10, 1), date(2022, 4, 1)
        tbl, _ = server._iivtnu_max_coefs_for_devengo(dev)
        info = server._iivtnu_objective_coef(acq, dev, tbl)
        self.assertEqual(info["years"], 0)
        self.assertEqual(info["months"], 6)
        self.assertAlmostEqual(info["coef_objetivo"], 0.07, places=6)

    def test_objective_coef_caps_at_20_years(self):
        # 1995-01-01 -> 2020-01-01 = 25 años reales, pero el tope legal son 20.
        # Se usa coef[20+]; RDL 26/2021 = 0.45.
        acq, dev = date(1995, 1, 1), date(2020, 1, 1)
        tbl, _ = server._iivtnu_max_coefs_for_devengo(dev)
        info = server._iivtnu_objective_coef(acq, dev, tbl)
        self.assertEqual(info["years"], 20)
        self.assertAlmostEqual(info["coef_objetivo"], 0.45, places=6)


class IivtnuSimulateTests(unittest.TestCase):
    """Integración de _iivtnu_simulate con SQLite en memoria (semilla Málaga)."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()

    def _base_payload(self, **over):
        p = {
            "municipio_ine": "29067",  # Málaga (semilla automática).
            "fecha_adquisicion": "2010-01-01",
            "fecha_transmision": "2024-01-01",
            "valor_suelo": 50000,
        }
        p.update(over)
        return p

    def test_objetivo_base_equals_suelo_times_coef(self):
        # 2010-01-01 -> 2024-01-01 = 14 años. Tabla RDL 8/2023 (devengo 2024),
        # coef[14] = 0.09. base objetiva = 50.000 x 0.09 = 4.500,00
        # (pleno dominio y participación 100%, factores = 1).
        out = server._iivtnu_simulate(self.conn, self._base_payload())
        res = out["result"]
        self.assertEqual(res["years"], 14)
        self.assertAlmostEqual(res["coef_objetivo"], 0.09, places=6)
        self.assertAlmostEqual(res["base_imponible"], 4500.00, places=2)

    def test_no_sujecion_por_ausencia_de_incremento(self):
        # Se transmite por debajo del valor de adquisición => no hay incremento de
        # valor => no sujeto (STC 59/2017; art. 104.5 TRLRHL).
        payload = self._base_payload(
            valor_adquisicion=300000,
            valor_transmision=250000,
            valor_catastral_total=100000,
        )
        out = server._iivtnu_simulate(self.conn, payload)
        res = out["result"]
        self.assertEqual(res["metodo_recomendado"], "no_sujecion")
        self.assertEqual(res["cuota_recomendada"], 0.0)
        self.assertEqual(res["real"]["no_incremento"], 1)
        # ganancia_total = (250000) - (300000) = -50.000
        self.assertAlmostEqual(res["real"]["ganancia_total"], -50000.0, places=2)

    def test_situacion_especial_exento_forces_zero(self):
        payload = self._base_payload(situacion_especial="exento")
        out = server._iivtnu_simulate(self.conn, payload)
        res = out["result"]
        self.assertEqual(res["metodo_recomendado"], "exencion")
        self.assertEqual(res["cuota_recomendada"], 0.0)

    def test_transmision_anterior_a_adquisicion_error(self):
        payload = self._base_payload(
            fecha_adquisicion="2024-01-01", fecha_transmision="2010-01-01"
        )
        with self.assertRaises(ValueError):
            server._iivtnu_simulate(self.conn, payload)


class IrpfSavingsScaleTests(unittest.TestCase):
    """Escala del ahorro (base liquidable del ahorro) por ejercicio."""

    def test_scale_2024_brackets(self):
        # 2024: 19% / 21% / 23% / 27% / 28%.
        year, brackets, assumed = server._irpf_savings_scale_for_year(2024)
        self.assertEqual(year, 2024)
        self.assertEqual(assumed, False)
        rates = [round(b[2], 3) for b in brackets]
        self.assertEqual(rates, [0.19, 0.21, 0.23, 0.27, 0.28])

    def test_progressive_250000_year_2024(self):
        # Ganancia 250.000 con escala 2024:
        #   6.000 x 0,19       = 1.140,00
        #  44.000 x 0,21       = 9.240,00   (6.000 -> 50.000)
        # 150.000 x 0,23       = 34.500,00  (50.000 -> 200.000)
        #  50.000 x 0,27       = 13.500,00  (200.000 -> 250.000)
        # -----------------------------------
        # total                = 58.380,00
        _, brackets, _ = server._irpf_savings_scale_for_year(2024)
        self.assertAlmostEqual(
            server._irpf_tax_progressive(250000.0, brackets), 58380.00, places=2
        )

    def test_progressive_350000_reaches_28pct_bracket(self):
        #   6.000 x 0,19  = 1.140,00
        #  44.000 x 0,21  = 9.240,00
        # 150.000 x 0,23  = 34.500,00
        # 100.000 x 0,27  = 27.000,00  (200.000 -> 300.000)
        #  50.000 x 0,28  = 14.000,00  (300.000 -> 350.000)
        # ---------------------------------
        # total           = 85.880,00
        _, brackets, _ = server._irpf_savings_scale_for_year(2024)
        self.assertAlmostEqual(
            server._irpf_tax_progressive(350000.0, brackets), 85880.00, places=2
        )

    def test_progressive_100000_year_2018(self):
        # 2018: 19 / 21 / 23.
        #  6.000 x 0,19 = 1.140,00
        # 44.000 x 0,21 = 9.240,00
        # 50.000 x 0,23 = 11.500,00
        # ------------------------
        # total         = 21.880,00
        _, brackets, _ = server._irpf_savings_scale_for_year(2018)
        self.assertAlmostEqual(
            server._irpf_tax_progressive(100000.0, brackets), 21880.00, places=2
        )

    def test_year_below_minimum_raises(self):
        with self.assertRaises(ValueError):
            server._irpf_savings_scale_for_year(2010)


class IrpfAbatimientoHelpersTests(unittest.TestCase):
    """Helpers puros del régimen transitorio DT 9ª."""

    def test_years_to_1996_rounded_up(self):
        # 1990-01-01 -> 31/12/1996: ~6,99 años, redondeado por exceso => 7.
        self.assertEqual(
            server._irpf_years_to_1996_rounded_up(date(1990, 1, 1)), 7
        )
        # 1985-01-01 => 12 años.
        self.assertEqual(
            server._irpf_years_to_1996_rounded_up(date(1985, 1, 1)), 12
        )
        # Adquisición posterior a 1996 => 0.
        self.assertEqual(
            server._irpf_years_to_1996_rounded_up(date(2000, 1, 1)), 0
        )

    def test_reduction_pct_inmueble(self):
        # Inmueble: 11,11% por cada año > 2; 100% a partir de >10 años.
        self.assertAlmostEqual(
            server._irpf_abatimiento_reduction_pct("inmueble", 7), 55.55, places=2
        )
        self.assertAlmostEqual(
            server._irpf_abatimiento_reduction_pct("inmueble", 11), 100.0, places=2
        )
        self.assertAlmostEqual(
            server._irpf_abatimiento_reduction_pct("inmueble", 2), 0.0, places=2
        )

    def test_reduction_pct_valores_cotizados(self):
        # Valores cotizados: 25% por año > 2; 100% a partir de >5 años.
        # y=5 => (5-2)*25 = 75%.
        self.assertAlmostEqual(
            server._irpf_abatimiento_reduction_pct("valores_cotizados", 5), 75.0, places=2
        )
        self.assertAlmostEqual(
            server._irpf_abatimiento_reduction_pct("valores_cotizados", 6), 100.0, places=2
        )

    def test_reduction_pct_otros(self):
        # Otros: 14,28% por año > 2; y=8 => (8-2)*14,28 = 85,68%.
        self.assertAlmostEqual(
            server._irpf_abatimiento_reduction_pct("otros", 8), 85.68, places=2
        )


class IrpfAbatimientoDt9Tests(unittest.TestCase):
    """_irpf_apply_abatimiento_dt9: reparto por días pre-20/01/2006 y límite 400.000."""

    def test_inmueble_adquisicion_1990(self):
        # Adquisición 1990-01-01, transmisión 2020-01-01, ganancia 100.000
        # (toda sujeta), valor transmisión 300.000 (< 400.000, vt1=0).
        #
        # días totales  = (2020-01-01 - 1990-01-01) - 1 = 10.957 - 1 = 10.956
        # días pre-2006 = (2006-01-19 - 1990-01-01)      = 5.862
        # ratio_pre     = 5.862 / 10.956 = 0,53504929
        # ganancia pre  = 100.000 x 0,53504929 = 53.504,93
        # ganancia post = 100.000 - 53.504,93  = 46.495,07
        # años a 1996   = 7 => pct = (7-2) x 11,11 = 55,55%
        # reducción     = 53.504,93 x 0,5555 = 29.721,99
        # pre reducida  = 53.504,93 - 29.721,99 = 23.782,94
        # computable    = 46.495,07 + 23.782,94 = 70.278,01
        comp, det = server._irpf_apply_abatimiento_dt9(
            acq=date(1990, 1, 1),
            devengo=date(2020, 1, 1),
            ganancia_total=100000.0,
            ganancia_sujeta=100000.0,
            valor_transmision_calc=300000.0,
            vt2_override=None,
            vt1_acumulado_2015=0.0,
            tipo_elemento="inmueble",
        )
        self.assertEqual(det["days_total"], 10956)
        self.assertEqual(det["days_pre_2006"], 5862)
        self.assertEqual(det["years_to_1996_rounded_up"], 7)
        self.assertAlmostEqual(det["ganancia_pre_2006_sujeta"], 53504.93, places=2)
        self.assertAlmostEqual(det["pct_reduccion"], 55.55, places=2)
        self.assertAlmostEqual(det["reduccion_importe"], 29721.99, places=2)
        self.assertAlmostEqual(comp, 70278.01, places=2)

    def test_inmueble_mas_de_10_anios_abate_totalmente_tramo_pre_2006(self):
        # Adquisición 1985-01-01 => 12 años a 1996 => pct 100% (inmueble >10 años):
        # el tramo pre-20/01/2006 queda TOTALMENTE reducido (no sujeto).
        # ganancia pre-2006 = 60.147,08 ; reducción = 60.147,08 ; queda sólo el
        # tramo post-2006: computable = 100.000 - 60.147,08 = 39.852,92.
        comp, det = server._irpf_apply_abatimiento_dt9(
            acq=date(1985, 1, 1),
            devengo=date(2020, 1, 1),
            ganancia_total=100000.0,
            ganancia_sujeta=100000.0,
            valor_transmision_calc=300000.0,
            vt2_override=None,
            vt1_acumulado_2015=0.0,
            tipo_elemento="inmueble",
        )
        self.assertEqual(det["years_to_1996_rounded_up"], 12)
        self.assertAlmostEqual(det["pct_reduccion"], 100.0, places=2)
        self.assertAlmostEqual(det["ganancia_pre_2006_sujeta"], 60147.08, places=2)
        self.assertAlmostEqual(det["reduccion_importe"], 60147.08, places=2)
        self.assertAlmostEqual(comp, 39852.92, places=2)

    def test_limite_conjunto_400000(self):
        # Igual que el primer caso pero con valor de transmisión 500.000 (> 400.000).
        # Sólo es susceptible de reducción la parte proporcional al límite:
        #   ratio_cap  = 400.000 / 500.000 = 0,8
        #   susceptible = 53.504,93 x 0,8 = 42.803,94
        #   reducción   = 42.803,94 x 0,5555 = 23.777,59
        #   computable  = 46.495,07 + (53.504,93 - 23.777,59) = 76.222,41
        comp, det = server._irpf_apply_abatimiento_dt9(
            acq=date(1990, 1, 1),
            devengo=date(2020, 1, 1),
            ganancia_total=100000.0,
            ganancia_sujeta=100000.0,
            valor_transmision_calc=500000.0,
            vt2_override=None,
            vt1_acumulado_2015=0.0,
            tipo_elemento="inmueble",
        )
        self.assertAlmostEqual(det["vt2_usado_400k"], 500000.0, places=2)
        self.assertAlmostEqual(
            det["ganancia_susceptible_reduccion"], 42803.94, places=2
        )
        self.assertAlmostEqual(det["reduccion_importe"], 23777.59, places=2)
        self.assertAlmostEqual(comp, 76222.41, places=2)

    def test_no_aplica_adquisicion_posterior_1994(self):
        # Adquisición >= 31/12/1994 => no procede el régimen transitorio.
        comp, det = server._irpf_apply_abatimiento_dt9(
            acq=date(2000, 1, 1),
            devengo=date(2020, 1, 1),
            ganancia_total=100000.0,
            ganancia_sujeta=100000.0,
            valor_transmision_calc=300000.0,
            vt2_override=None,
            vt1_acumulado_2015=0.0,
            tipo_elemento="inmueble",
        )
        self.assertEqual(det["aplicable"], 0)
        self.assertIn("31/12/1994", det["motivo"])
        self.assertAlmostEqual(comp, 100000.0, places=2)


class IrpfGananciaSimulateTests(unittest.TestCase):
    """_irpf_ganancia_simulate: ganancia, cuota y exención >65 vivienda habitual."""

    def _payload(self, **over):
        p = {
            "fecha_adquisicion": "2015-01-01",
            "fecha_transmision": "2024-06-01",
            "valor_adquisicion": 200000,
            "valor_transmision": 300000,
            "ejercicio": 2024,
        }
        p.update(over)
        return p

    def test_ganancia_simple_y_cuota_2024(self):
        # ganancia = 300.000 - 200.000 = 100.000. Sin abatimiento (adq 2015 >= 1994).
        # cuota escala 2024 sobre 100.000 = 1.140 + 9.240 + 11.500 = 21.880,00.
        out = server._irpf_ganancia_simulate(self._payload())
        res = out["result"]
        self.assertAlmostEqual(res["ganancia_patrimonial"], 100000.0, places=2)
        self.assertAlmostEqual(res["base_ahorro_sujeta"], 100000.0, places=2)
        self.assertAlmostEqual(res["cuota_ahorro_estimada"], 21880.00, places=2)
        self.assertEqual(out["params"]["escala_ejercicio"], 2024)

    def test_exencion_mayor_65_forzada(self):
        # Vivienda habitual + exención >65 forzada => toda la ganancia exenta,
        # base 0 y cuota 0.
        out = server._irpf_ganancia_simulate(
            self._payload(vivienda_habitual=True, exencion_mayor_65=True)
        )
        res = out["result"]
        self.assertAlmostEqual(res["exento"], 100000.0, places=2)
        self.assertAlmostEqual(res["ganancia_sujeta"], 0.0, places=2)
        self.assertAlmostEqual(res["cuota_ahorro_estimada"], 0.0, places=2)

    def test_exencion_mayor_65_automatica_por_fecha_nacimiento(self):
        # Nacido en 1950 => 74 años en la transmisión (>= 65) + vivienda habitual
        # => exención total automática.
        out = server._irpf_ganancia_simulate(
            self._payload(vivienda_habitual=True, fecha_nacimiento="1950-01-01")
        )
        res = out["result"]
        self.assertEqual(res["edad_transmision"], 74)
        self.assertAlmostEqual(res["exento"], 100000.0, places=2)
        self.assertAlmostEqual(res["cuota_ahorro_estimada"], 0.0, places=2)

    def test_sin_ganancia_no_hay_cuota(self):
        # Transmisión por debajo del coste => no hay ganancia sujeta => cuota 0.
        out = server._irpf_ganancia_simulate(
            self._payload(valor_adquisicion=300000, valor_transmision=250000)
        )
        res = out["result"]
        self.assertLessEqual(res["ganancia_patrimonial"], 0.0)
        self.assertAlmostEqual(res["base_ahorro_sujeta"], 0.0, places=2)
        self.assertAlmostEqual(res["cuota_ahorro_estimada"], 0.0, places=2)


if __name__ == "__main__":
    unittest.main()
