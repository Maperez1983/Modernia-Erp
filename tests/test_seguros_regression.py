"""Tests de regresión para la lógica de SEGUROS del CRM.

Cubre las piezas puras y aisladas del dominio de seguros: normalización y
máquina de estados de pólizas, cálculo/selección de comisiones (dinero),
normalización de ramo/compañía y los agregados/contabilidad de comisiones
sobre sqlite en memoria.

Los valores esperados se calculan a mano y se documentan en comentarios.
"""

import sqlite3
import unittest
from datetime import date

# Funciones puras del módulo de estado de seguros (pequeño y sin dependencias).
from web.seguros_state import (
    normalize_seguro_estado_value,
    can_transition_seguro_estado,
)

# Funciones testeables de forma aislada dentro de web/server.py.
from web.server import (
    canonicalize_ramo,
    seguros_comision_tipo_from_produccion,
    parse_seguros_comision_ramo_tipo,
    score_seguros_comision_match,
    pick_seguros_comision_rule,
    seguro_estado_bucket_value,
    compute_seguros_contabilidad_totals,
    upsert_seguro_comision_contabilidad,
    find_existing_seguro_id,
    compute_seguro_display,
    normalize_company_key,
)


class SeguroEstadoNormalizationTests(unittest.TestCase):
    """normalize_seguro_estado_value: mapea variantes (acentos/mayúsculas) a
    los 5 estados canónicos: Presupuesto/Contratada/En vigor/Anulada/Rechazada."""

    def test_canonical_values_are_preserved(self):
        self.assertEqual(normalize_seguro_estado_value("Presupuesto"), "Presupuesto")
        self.assertEqual(normalize_seguro_estado_value("Contratada"), "Contratada")
        self.assertEqual(normalize_seguro_estado_value("En vigor"), "En vigor")
        self.assertEqual(normalize_seguro_estado_value("Anulada"), "Anulada")
        self.assertEqual(normalize_seguro_estado_value("Rechazada"), "Rechazada")

    def test_presupuesto_synonyms(self):
        # PROYECTO y PENDIENTE se consideran presupuesto.
        self.assertEqual(normalize_seguro_estado_value("proyecto"), "Presupuesto")
        self.assertEqual(normalize_seguro_estado_value("PENDIENTE"), "Presupuesto")

    def test_presupuestos_plural_normalized(self):
        # El plural "Presupuestos" se normaliza a "Presupuesto" (antes era inconsistente con
        # seguro_estado_bucket_value / la expresión SQL, que sí lo trataban como presupuesto).
        self.assertEqual(normalize_seguro_estado_value("Presupuestos"), "Presupuesto")

    def test_contratada_case_and_gender_variants(self):
        self.assertEqual(normalize_seguro_estado_value("contratado"), "Contratada")
        self.assertEqual(normalize_seguro_estado_value("CONTRATADA"), "Contratada")

    def test_en_vigor_variants_including_accents_and_spacing(self):
        # "ENVIGOR" (sin espacio), "Vigente", "Activa" -> "En vigor".
        self.assertEqual(normalize_seguro_estado_value("envigor"), "En vigor")
        self.assertEqual(normalize_seguro_estado_value("Vigente"), "En vigor")
        self.assertEqual(normalize_seguro_estado_value("Activa"), "En vigor")
        self.assertEqual(normalize_seguro_estado_value("activo"), "En vigor")

    def test_anulada_synonyms(self):
        self.assertEqual(normalize_seguro_estado_value("baja"), "Anulada")
        self.assertEqual(normalize_seguro_estado_value("Cancelada"), "Anulada")
        # Con acento fantasma para verificar el stripping NFKD.
        self.assertEqual(normalize_seguro_estado_value("Anuládá"), "Anulada")

    def test_rechazada_synonyms_and_prefix(self):
        self.assertEqual(normalize_seguro_estado_value("denegado"), "Rechazada")
        self.assertEqual(normalize_seguro_estado_value("No aceptada"), "Rechazada")
        # Prefijo "RECHAZADA <motivo>" también colapsa a Rechazada.
        self.assertEqual(normalize_seguro_estado_value("Rechazada por precio"), "Rechazada")

    def test_empty_and_unknown_values(self):
        self.assertEqual(normalize_seguro_estado_value(""), "")
        self.assertEqual(normalize_seguro_estado_value(None), "")
        # Valor desconocido: se conserva el texto original (sin canonicalizar).
        self.assertEqual(normalize_seguro_estado_value("  Situación rara  "), "Situación rara")


class SeguroEstadoTransitionTests(unittest.TestCase):
    """can_transition_seguro_estado: solo Presupuesto->En vigor está bloqueada."""

    def test_blocked_presupuesto_to_en_vigor(self):
        # Transición bloqueada de forma directa.
        self.assertFalse(can_transition_seguro_estado("Presupuesto", "En vigor"))

    def test_blocked_transition_via_synonyms(self):
        # Los sinónimos se normalizan antes de comprobar el bloqueo:
        # "pendiente" -> Presupuesto ; "vigente" -> En vigor => bloqueada.
        self.assertFalse(can_transition_seguro_estado("pendiente", "vigente"))

    def test_allowed_presupuesto_to_contratada(self):
        self.assertTrue(can_transition_seguro_estado("Presupuesto", "Contratada"))

    def test_allowed_contratada_to_en_vigor(self):
        self.assertTrue(can_transition_seguro_estado("Contratada", "En vigor"))

    def test_allowed_en_vigor_to_anulada(self):
        self.assertTrue(can_transition_seguro_estado("En vigor", "Anulada"))

    def test_same_state_is_allowed(self):
        self.assertTrue(can_transition_seguro_estado("En vigor", "En vigor"))

    def test_empty_current_or_target_is_allowed(self):
        self.assertTrue(can_transition_seguro_estado("", "En vigor"))
        self.assertTrue(can_transition_seguro_estado("Presupuesto", ""))


class CanonicalizeRamoTests(unittest.TestCase):
    def test_exact_canonical_matches(self):
        self.assertEqual(canonicalize_ramo("Auto"), "Auto")
        self.assertEqual(canonicalize_ramo("vida"), "Vida")
        self.assertEqual(canonicalize_ramo("SALUD"), "Salud")

    def test_alias_rc_maps_to_responsabilidad_civil(self):
        self.assertEqual(canonicalize_ramo("RC"), "Responsabilidad civil")

    def test_alias_moto_maps_to_auto(self):
        self.assertEqual(canonicalize_ramo("moto"), "Auto")

    def test_impago_alquiler_maps_to_proteccion_de_pagos(self):
        self.assertEqual(canonicalize_ramo("IMPAGO ALQUILER"), "Protección de pagos")

    def test_noisy_ocr_text_is_discarded(self):
        # Contiene un marcador de ruido normativo -> "".
        noisy = "Expectativa razonable del tomador sobre el producto contratado"
        self.assertEqual(canonicalize_ramo(noisy), "")

    def test_empty_value(self):
        self.assertEqual(canonicalize_ramo(""), "")
        self.assertEqual(canonicalize_ramo(None), "")

    def test_unknown_short_value_is_preserved(self):
        # No es ruido ni alias conocido -> se conserva para no perder edición manual.
        self.assertEqual(canonicalize_ramo("Mascotas"), "Mascotas")


class SegurosComisionHelperTests(unittest.TestCase):
    def test_produccion_default_is_nueva_produccion(self):
        self.assertEqual(seguros_comision_tipo_from_produccion(""), "nueva produccion")
        self.assertEqual(seguros_comision_tipo_from_produccion("Alta nueva"), "nueva produccion")

    def test_produccion_cambio_es_cartera(self):
        # Un cambio de compañía se clasifica como "cartera" (antes era un bug: la comparación
        # mayúsc/minúsc dejaba la rama muerta y devolvía "nueva produccion"). Ya corregido.
        self.assertEqual(
            seguros_comision_tipo_from_produccion("Cambio de compañía"),
            "cartera",
        )
        self.assertEqual(
            seguros_comision_tipo_from_produccion("CAMBIO DE COMPAÑIA"),
            "cartera",
        )

    def test_parse_ramo_tipo_with_bracket(self):
        # "Auto [nueva produccion]" -> ramo="Auto", tipo="nueva produccion".
        parsed = parse_seguros_comision_ramo_tipo("Auto [nueva produccion]")
        self.assertEqual(parsed, {"ramo": "Auto", "tipo": "nueva produccion"})

    def test_parse_ramo_tipo_without_bracket(self):
        self.assertEqual(
            parse_seguros_comision_ramo_tipo("Hogar"),
            {"ramo": "Hogar", "tipo": ""},
        )

    def test_parse_ramo_tipo_empty(self):
        self.assertEqual(parse_seguros_comision_ramo_tipo(""), {"ramo": "", "tipo": ""})


class ScoreSegurosComisionMatchTests(unittest.TestCase):
    def test_full_match_score(self):
        # base 10 + ramo exacto 60 + tipo exacto 30 = 100.
        rule = {"compania": "Mapfre", "ramo": "Auto[nueva produccion]", "porcentaje": 10}
        score = score_seguros_comision_match(
            rule,
            compania_key=normalize_company_key("Mapfre"),  # "MAPFRE"
            ramo_key="AUTO",
            tipo_key="NUEVA PRODUCCION",
        )
        self.assertEqual(score, 100)

    def test_company_mismatch_returns_minus_one(self):
        rule = {"compania": "Allianz", "ramo": "Auto[nueva produccion]", "porcentaje": 10}
        score = score_seguros_comision_match(
            rule,
            compania_key="MAPFRE",
            ramo_key="AUTO",
            tipo_key="NUEVA PRODUCCION",
        )
        self.assertEqual(score, -1)

    def test_partial_ramo_substring_match(self):
        # ramo "AUTO" es subcadena de "AUTOMOVILES" -> +35 ; tipo exacto -> +30.
        # base 10 + 35 + 30 = 75.
        rule = {"compania": "Mapfre", "ramo": "Automoviles[nueva produccion]", "porcentaje": 5}
        score = score_seguros_comision_match(
            rule,
            compania_key="MAPFRE",
            ramo_key="AUTO",
            tipo_key="NUEVA PRODUCCION",
        )
        self.assertEqual(score, 75)


class PickSegurosComisionRuleTests(unittest.TestCase):
    """pick_seguros_comision_rule elige la regla ganadora y devuelve el % (dinero)."""

    def setUp(self):
        self.rules = [
            {"compania": "Mapfre", "ramo": "Auto[nueva produccion]", "porcentaje": 10},
            {"compania": "Mapfre", "ramo": "Hogar[nueva produccion]", "porcentaje": 15},
        ]

    def test_selects_best_rule_and_returns_pct(self):
        # Auto+nueva produccion casa exactamente con la primera regla (score 100).
        result = pick_seguros_comision_rule(self.rules, "Mapfre", "Auto", produccion="Nueva")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["pct"], 10.0)
        self.assertIn("Auto", result["source"])

    def test_no_matching_company_returns_none(self):
        self.assertIsNone(pick_seguros_comision_rule(self.rules, "Allianz", "Auto"))

    def test_below_threshold_returns_none(self):
        # ramo no casa (-20) y tipo no casa (-10): score 10-20-10=-20 < 20 -> None.
        rules = [{"compania": "Mapfre", "ramo": "Hogar[cartera]", "porcentaje": 12}]
        self.assertIsNone(pick_seguros_comision_rule(rules, "Mapfre", "Auto", produccion="Nueva"))

    def test_fecha_ref_outside_vigencia_is_skipped(self):
        rules = [
            {
                "compania": "Mapfre",
                "ramo": "Auto[nueva produccion]",
                "porcentaje": 10,
                "vigencia_desde": "2025-01-01",
                "vigencia_hasta": "2025-12-31",
            }
        ]
        # Fuera de vigencia -> descartada -> None.
        self.assertIsNone(
            pick_seguros_comision_rule(rules, "Mapfre", "Auto", produccion="Nueva", fecha_ref="2024-06-01")
        )
        # Dentro de vigencia -> devuelve el %.
        inside = pick_seguros_comision_rule(rules, "Mapfre", "Auto", produccion="Nueva", fecha_ref="2025-06-01")
        self.assertIsNotNone(inside)
        self.assertAlmostEqual(inside["pct"], 10.0)


class SeguroEstadoBucketValueTests(unittest.TestCase):
    """seguro_estado_bucket_value: equivalente Python de la expresión SQL de bucket.

    Todos los tests pasan `today` explícito para ser deterministas.
    """

    TODAY = date(2026, 7, 28)

    def bucket(self, row):
        return seguro_estado_bucket_value(row, today=self.TODAY)

    def test_explicit_states(self):
        self.assertEqual(self.bucket({"estado": "Presupuesto"}), "presupuesto")
        self.assertEqual(self.bucket({"estado": "Rechazada"}), "rechazada")
        self.assertEqual(self.bucket({"estado": "Anulada"}), "anulada")
        self.assertEqual(self.bucket({"estado": "En vigor"}), "en_vigor")

    def test_estado_poliza_anulada_wins(self):
        self.assertEqual(self.bucket({"estado": "", "estado_poliza": "Anulada"}), "anulada")

    def test_explicit_estado_prevails_over_dates(self):
        # estado="Presupuesto" gana aunque la fecha de efecto ya haya pasado.
        row = {"estado": "Presupuesto", "fecha_efecto": "2020-01-01"}
        self.assertEqual(self.bucket(row), "presupuesto")

    def test_future_efecto_is_contratada(self):
        # fecha_efecto futura (> today) sin estado explícito -> contratada.
        self.assertEqual(self.bucket({"estado": "", "fecha_efecto": "2030-01-01"}), "contratada")

    def test_past_efecto_without_venc_is_en_vigor(self):
        # fecha_efecto <= today y sin vencimiento (aprox +1 año >= today) -> en_vigor.
        self.assertEqual(self.bucket({"estado": "", "fecha_efecto": "2026-01-01"}), "en_vigor")

    def test_past_efecto_and_past_venc_is_presupuesto(self):
        # Efecto y vencimiento ambos en el pasado -> no en vigor -> presupuesto (default).
        row = {"estado": "", "fecha_efecto": "2020-01-01", "fecha_vencimiento": "2021-01-01"}
        self.assertEqual(self.bucket(row), "presupuesto")

    def test_contratada_state_without_dates(self):
        self.assertEqual(self.bucket({"estado": "Contratada"}), "contratada")

    def test_empty_row_is_presupuesto(self):
        self.assertEqual(self.bucket({}), "presupuesto")
        self.assertEqual(seguro_estado_bucket_value(None, today=self.TODAY), "presupuesto")


class SegurosContabilidadTotalsTests(unittest.TestCase):
    """compute_seguros_contabilidad_totals: agrega ingresos/gastos (dinero) de las
    filas de contabilidad relacionadas con seguros."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
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
            """
        )
        rows = [
            # (id, empresa, seguro_id, poliza, fecha, gestion, tipo, importe, notas)
            ("g1", "e1", "s1", "", "2025-03-01", "Comisión emisión", "Ingreso", 100.0, ""),
            ("g2", "e1", "s1", "", "2025-04-01", "Comisión renovación", "Ingreso", 50.0, ""),
            ("g3", "e1", "s2", "", "2025-05-01", "Extorno", "Gasto", 30.0, ""),
            # Fila 2024: debe excluirse cuando se filtra por año 2025.
            ("g4", "e1", "s3", "", "2024-02-01", "Comisión emisión", "Ingreso", 999.0, ""),
            # Fila NO-seguro (sin seguro_id/poliza/nota/gestion de seguros): se ignora.
            ("g5", "e1", "", "", "2025-06-01", "Comisión cliente", "Ingreso", 777.0, ""),
        ]
        for rid, emp, sid, pol, fecha, gestion, tipo, importe, notas in rows:
            self.conn.execute(
                """
                INSERT INTO gestoria_contabilidad
                  (id, empresa_id, seguro_id, poliza_numero, fecha, concepto, gestion, tipo, importe, notas, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (rid, emp, sid or None, pol, fecha, gestion, gestion, tipo, importe, notas, "2026-01-01", "2026-01-01"),
            )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_totals_filtered_by_year(self):
        # 2025: ingresos = 100 + 50 = 150 ; gastos = 30. (La fila no-seguro y 2024 quedan fuera.)
        totals = compute_seguros_contabilidad_totals(self.conn, "e1", year="2025")
        self.assertAlmostEqual(totals["ingresos"], 150.0)
        self.assertAlmostEqual(totals["gastos"], 30.0)

    def test_totals_all_years_include_2024(self):
        # Sin filtro de año: ingresos = 100 + 50 + 999 = 1149 ; gastos = 30.
        totals = compute_seguros_contabilidad_totals(self.conn, "e1")
        self.assertAlmostEqual(totals["ingresos"], 1149.0)
        self.assertAlmostEqual(totals["gastos"], 30.0)


class UpsertSeguroComisionContabilidadTests(unittest.TestCase):
    """upsert_seguro_comision_contabilidad: crea/actualiza el asiento de comisión
    (dinero) respetando la máquina de estados (solo en_vigor salvo renovación)."""

    NOW = "2026-07-28T10:00:00+00:00"

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
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
            """
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _seguro(self, **overrides):
        base = {
            "id": "s1",
            "empresa_id": "e1",
            "cliente_id": "c1",
            "poliza_numero": "POL-1",
            "comision": 120.0,
            "fecha_efecto": "2025-06-01",
            "estado": "En vigor",
        }
        base.update(overrides)
        return base

    def test_emision_en_vigor_creates_income_entry(self):
        rid = upsert_seguro_comision_contabilidad(self.conn, self._seguro(), self.NOW)
        self.assertTrue(rid)
        row = self.conn.execute("SELECT * FROM gestoria_contabilidad WHERE id = ?", (rid,)).fetchone()
        self.assertEqual(row["gestion"], "Comisión emisión")
        self.assertEqual(row["tipo"], "Ingreso")
        self.assertAlmostEqual(row["importe"], 120.0)
        self.assertEqual(row["fecha"], "2025-06-01")  # de fecha_efecto
        self.assertEqual(row["seguro_id"], "s1")

    def test_emision_presupuesto_is_skipped(self):
        # Estado no en_vigor y no es renovación -> no se crea asiento.
        rid = upsert_seguro_comision_contabilidad(self.conn, self._seguro(estado="Presupuesto"), self.NOW)
        self.assertIsNone(rid)
        count = self.conn.execute("SELECT COUNT(*) FROM gestoria_contabilidad").fetchone()[0]
        self.assertEqual(count, 0)

    def test_renovacion_bypasses_state_check(self):
        # Renovación se registra aunque el estado no sea en_vigor.
        rid = upsert_seguro_comision_contabilidad(
            self.conn,
            self._seguro(estado="Presupuesto"),
            self.NOW,
            movimiento="renovacion",
            fecha="2025-07-15",
            importe=60.0,
        )
        self.assertTrue(rid)
        row = self.conn.execute("SELECT * FROM gestoria_contabilidad WHERE id = ?", (rid,)).fetchone()
        self.assertEqual(row["gestion"], "Comisión renovación")
        self.assertAlmostEqual(row["importe"], 60.0)
        self.assertEqual(row["fecha"], "2025-07-15")

    def test_importe_param_overrides_seguro_comision(self):
        # El parámetro `importe` tiene prioridad sobre seguro_row["comision"].
        rid = upsert_seguro_comision_contabilidad(self.conn, self._seguro(comision=120.0), self.NOW, importe=200.0)
        row = self.conn.execute("SELECT importe FROM gestoria_contabilidad WHERE id = ?", (rid,)).fetchone()
        self.assertAlmostEqual(row["importe"], 200.0)

    def test_zero_commission_is_skipped(self):
        # |comisión| < 0.005 -> no se crea asiento.
        rid = upsert_seguro_comision_contabilidad(self.conn, self._seguro(comision=0.0), self.NOW)
        self.assertIsNone(rid)

    def test_second_upsert_updates_existing_without_duplicating(self):
        rid1 = upsert_seguro_comision_contabilidad(self.conn, self._seguro(comision=120.0), self.NOW)
        # Mismo seguro/fecha/gestión con nuevo importe -> actualiza, no duplica.
        rid2 = upsert_seguro_comision_contabilidad(
            self.conn, self._seguro(comision=150.0), "2026-07-28T11:00:00+00:00"
        )
        self.assertEqual(rid1, rid2)
        rows = self.conn.execute("SELECT importe FROM gestoria_contabilidad WHERE seguro_id = 's1'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["importe"], 150.0)


class FindExistingSeguroIdTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE seguros (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              poliza_numero TEXT,
              compania TEXT,
              estado TEXT
            );
            """
        )
        self.conn.execute(
            "INSERT INTO seguros (id, empresa_id, poliza_numero, compania, estado) VALUES (?, ?, ?, ?, ?)",
            ("seg1", "e1", "POL-123", "Mapfre", "En vigor"),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_matches_by_normalized_poliza_and_company(self):
        # "pol 123" normaliza a "POL123" == "POL-123" normalizado.
        self.assertEqual(find_existing_seguro_id(self.conn, "e1", "pol 123", "Mapfre"), "seg1")

    def test_company_mismatch_returns_empty(self):
        # Misma póliza pero compañía distinta -> no se considera la misma póliza.
        self.assertEqual(find_existing_seguro_id(self.conn, "e1", "POL-123", "Allianz"), "")

    def test_exclude_id_skips_the_record(self):
        self.assertEqual(find_existing_seguro_id(self.conn, "e1", "POL-123", "Mapfre", exclude_id="seg1"), "")

    def test_empty_poliza_returns_empty(self):
        self.assertEqual(find_existing_seguro_id(self.conn, "e1", "", "Mapfre"), "")

    def test_legacy_migrated_record_is_ignored(self):
        self.conn.execute(
            "INSERT INTO seguros (id, empresa_id, poliza_numero, compania, estado) VALUES (?, ?, ?, ?, ?)",
            ("seg2", "e1", "POL-999", "Mapfre", "MIGRADO LEGADO"),
        )
        self.conn.commit()
        self.assertEqual(find_existing_seguro_id(self.conn, "e1", "POL-999", "Mapfre"), "")


class ComputeSeguroDisplayTests(unittest.TestCase):
    def test_future_policy_keeps_base_estado(self):
        # fecha_efecto muy futura -> vencimiento (+1 año) sigue en el futuro,
        # no se hace roll-forward y el estado base se conserva.
        row = {"estado": "En vigor", "fecha_efecto": "2030-01-01"}
        result = compute_seguro_display(row)
        self.assertEqual(result["vencimiento_display"], "2031-01-01")
        self.assertEqual(result["estado_display"], "En vigor")

    def test_expired_without_action_marks_renovada_automatica(self):
        # Vencimiento pasado y sin acción explícita de renovación -> "Renovada automática".
        row = {"estado": "En vigor", "fecha_efecto": "2019-01-01", "fecha_vencimiento": "2020-01-01"}
        result = compute_seguro_display(row)
        self.assertEqual(result["estado_display"], "Renovada automática")

    def test_expired_with_explicit_action_keeps_base_estado(self):
        # Acción explícita (estado_renovacion no automática) -> no roll-forward,
        # se conserva vencimiento y estado base.
        row = {
            "estado": "En vigor",
            "fecha_efecto": "2019-01-01",
            "fecha_vencimiento": "2020-01-01",
            "estado_renovacion": "Renovada manual",
        }
        result = compute_seguro_display(row)
        self.assertEqual(result["vencimiento_display"], "2020-01-01")
        self.assertEqual(result["estado_display"], "En vigor")

    def test_missing_vencimiento_returns_empty_display(self):
        # Sin fecha de efecto ni vencimiento -> no hay vencimiento calculable.
        result = compute_seguro_display({"estado": "Presupuesto"})
        self.assertEqual(result["vencimiento_display"], "")
        self.assertEqual(result["estado_display"], "Presupuesto")


class NormalizeCompanyKeyTests(unittest.TestCase):
    def test_basic_uppercasing(self):
        self.assertEqual(normalize_company_key("Mapfre"), "MAPFRE")

    def test_resuelve_el_alias_comercial_de_la_aseguradora(self):
        """El nombre comercial se resuelve a la entidad canónica.

        Antes se comparaba literalmente, así que "Allianz Seguros" y "ALLIANZ" daban
        claves distintas: la deduplicación de pólizas no saltaba y la póliza tampoco
        casaba con su regla de comisión. Decisión de negocio (2026-07-30): no
        distinguimos razones sociales, Allianz es Allianz.
        """
        self.assertEqual(normalize_company_key("MAPFRE, S.A."), "MAPFRE")
        self.assertEqual(normalize_company_key("Allianz Seguros"), "ALLIANZ")
        self.assertEqual(normalize_company_key("ALLIANZ SEGUROS S.A."), "ALLIANZ")
        self.assertEqual(normalize_company_key("Allianz Seguros"), normalize_company_key("ALLIANZ"))

    def test_no_fusiona_aseguradoras_distintas(self):
        """La clave sigue haciendo de guarda: Mapfre y AXA no pueden confundirse."""
        self.assertNotEqual(normalize_company_key("MAPFRE"), normalize_company_key("AXA"))

    def test_sin_alias_conocido_solo_normaliza_el_texto(self):
        """Una compañía que no está en el catálogo mantiene el comportamiento previo:
        mayúsculas y fuera todo lo que no sea A-Z0-9 (los acentos se eliminan, no se
        transliteran, de ahí CORREDURA)."""
        self.assertEqual(normalize_company_key("Aseguradora Rara, S.L."), "ASEGURADORARARASL")
        self.assertEqual(normalize_company_key("Correduría Rara"), "CORREDURARARA")

    def test_empty_value(self):
        self.assertEqual(normalize_company_key(""), "")
        self.assertEqual(normalize_company_key(None), "")


if __name__ == "__main__":
    unittest.main()
