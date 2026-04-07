import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.import_rentas_2024_to_crm import (
    apply_to_db,
    build_review_queue,
    build_validation_summary,
    classify_pdf,
    finalize_record,
    should_skip_auxiliary_record,
    parse_datos_fiscales_text,
    parse_modelo_100_text,
)


MODELO_SAMPLE = """
INFORMACIÓN DE LA PRESENTACIÓN DE LA DECLARACIÓN
Presentación realizada el: 03-05-2025 a las 15:50:45
Expediente/Referencia (nº registro asignado): 202410022580766Y
Código Seguro de Verificación: H3BP4VD2VEGENNV2
Primer declarante
NIF
Apellidos y nombre
Sexo del primer declarante
Estado civil (el 31-12-2024)
Fecha de nacimiento
74822580S 0001
TRUJILLO GONZALEZ CRISTOBAL 0002
Hombre 0005
(2) Casado/a 0007
19/03/1977 0010
Cónyuge
NIF
74845153W 0013
Apellidos y nombre
GOMEZ GONZALEZ CARMEN 0014
Fecha de nacimiento del cónyuge
06/11/1978 0060
Situación familiar
NIF
79444652F 0075
Apellidos y nombre
TRUJILLO GOMEZ MARTA 0076
Fecha de nacimiento
12/07/2010 0077
Rendimientos del trabajo
33.471,49 0012
28.993,17 0022
28.993,17 0432
0,10 0460
4.792,98 0595
-576,37 0670
"""


MODELO_PRESENTADOR_SAMPLE = """
INFORMACIÓN DE LA PRESENTACIÓN DE LA DECLARACIÓN
Presentación realizada el: 11-04-2025 a las 09:21:02
Apellidos y Nombre / Razón social: ASESORIA MODERNIA SL
En calidad de: Colaborador social
NIF Presentador: B12345678
"""


FISCALES_SAMPLE = """
Consulta de Datos Fiscales 2024
DATOS IDENTIFICATIVOS
NIF:
79018863V
NOMBRE:
RODRIGUEZ MEDEL ESPERANZA LIBERTAD
DOMICILIO FISCAL
Tipo Vía
CALLE
Nombre largo Vía
NAVEGANTE ISIDORO
NUM
15
Código Postal Municipio
29130
ALHAURÍN DE LA TORRE
Provincia
MALAGA
Referencia Catastral
3087142UF6538N0002OD
TOTAL
8,86
1,68
Cuenta
3650938313
"""


FISCALES_INLINE_SAMPLE = """
Consulta de Datos Fiscales 2024
DATOS IDENTIFICATIVOS
NIF: NOMBRE: 79018863V RODRIGUEZ MEDEL ESPERANZA LIBERTAD
DOMICILIO FISCAL
Tipo Vía
CALLE
Nombre largo Vía
NAVEGANTE ISIDORO
NUM
15
Código Postal Municipio
29130
ALHAURÍN DE LA TORRE
Provincia
MALAGA
Cuenta
3650938313
"""


MODELO_ACTIVITY_SAMPLE = """
INFORMACIÓN DE LA PRESENTACIÓN DE LA DECLARACIÓN
Modelo 100
Impuesto sobre la Renta de las Personas Físicas
74887470E 0001
BARBERO GARCIA JUAN 0002
Hombre 0005
(1) Soltero/a 0006
13/07/1985 0010
Suma del rendimiento neto reducido total de las actividades económicas en estimación directa

611,60 0198
5.581,88 0199
210,00 0217
17.825,19 0218
20.050,31 0221
1.002,52 0222
150,00 0670
"""


MODELO_IBAN_SAMPLE = """
INFORMACIÓN DE LA PRESENTACIÓN DE LA DECLARACIÓN
Modelo 100
74871528L 0001
BUENO SANTANA PAULA MACARENA 0002
Mujer 0005
(1) Soltero/a 0006
29/08/1982 0010
8.447,50 0171
5.595,50 0235
376,94 0670
DOMICILIACIÓN DEL IMPORTE A INGRESAR
Código IBAN
ES1601825332100203546780
"""


MODELO_OCR_RELAXED_SAMPLE = """
INFORMACION DE LA PRESENTACION DE LA DECLARACION
Modelo 100 Ejercicio 2024
NIF Presentador: 74841 155Y
Apellidos y Nombre / Razon social: MARTIN ILLANEZ JOSE MANUEL
Fecha de nacimiento 18/02/1977 [ooto]
Total ingresos integros computables [(03)+(07)+(08)+(24)+(09)+(10)-(11)] 21.880,73 [oo12]
Resultado de la declaracién -125,04 [oe70]
"""


FISCALES_AYUDAS_SAMPLE = """
Consulta de Datos Fiscales 2024
NIF:
Y9736585D
NOMBRE:
AMBROSELLI MARTORELL ANTONELLA
OTRAS SUBVENCIONES, AUXILIOS Y AYUDAS SATISFECHOS POR LAS ADMINISTRACIONES PÚBLICAS
Código
IP00001
Importe
JUNTA DE ANDALUCIA
6.035,17
PAGOS FRACCIONADOS DE EMPRESAS Y PROFESIONALES
"""


MODELO_INCOHERENT_AMOUNTS_SAMPLE = """
INFORMACIÓN DE LA PRESENTACIÓN DE LA DECLARACIÓN
Modelo 100
Impuesto sobre la Renta de las Personas Físicas
52588440K 0001
AGUAYO COBO SAUL 0002
Hombre 0005
(1) Soltero/a 0006
01/01/1980 0010
13.809,24 0505
868,32 0670
2.643.216,00 1484
"""


MODELO_OCR_BIRTHDATE_SAMPLE = """
INFORMACION DE LA PRESENTACION DE LA DECLARACION
Modelo 100 Ejercicio 2024
NIF Presentador: 76882248X
Apellidos y Nombre / Razon social: LEIVA GARCIA MARIA SOLEDAD
En calidad de: Titular
NEGATIVA/SIN ACTIVIDAD/RESULTADO CERO
Primer declarante
NIF
76882248X |o001]
Apellidos y nombre
LEIVA GARCIA MARIA SOLEDAD |[oo02]
Sexo del primer declarante
Estado civil (el 31-12-2024)
Fecha de nacimiento
Mujer |ooos
(1) Soltero/a [ooos]
28/05/2000 [oor0]
14.903,52 |o218
-6.215,91 |o432
"""


MODELO_OCR_PRESENTACION_SAMPLE = """
INFORMACION DE LA PRESENTACION DE LA DECLARACION
Modelo 100 Ejercicio 2024
Registro
Presentacion realizada el: 10-06-2025 a las 12:48:21
Expediente/Referencia (n° registro asignado): 202410028581770L
Codigo Seguro de Verificacion: ZYDH7SW7Q8ZYDB3T
Numero de justificante: 1005234323371
NIF Presentador: X6828588A
Apellidos y Nombre / Razon social: MACHADO ROCHA RODRIGO WALDEMAR
En calidad de: Titular
Fecha de nacimiento 09/04/1974 [oor0]
"""


MODELO_OCR_DECLARANTE_NIF_SAMPLE = """
INFORMACION DE LA PRESENTACION DE LA DECLARACION
Modelo 100 Ejercicio 2024
Registro Presentacion realizada el: 13-06-2025 a las 18:17:14
Expediente/Referencia (n° registro asignado): 202410066761892X
NIF Presentador: 74866767L
Apellidos y Nombre / Razon social: ACEBES ACEBES PATRICIA
En calidad de: Titular
Primer declarante 0001
NIF 74866767L
Apellidos y nombre ACEBES ACEBES PATRICIA 0002
Sexo del primer declarante Mujer 0005
Estado civil (el 31-12-2024) (1) Soltero/a 0006
Fecha de nacimiento 30/06/1982 0010
Contribuyente que obtiene los rendimientos DECLARANTE 0001
"""


MODELO_OCR_DECLARANTE_NIF_CASADO_SAMPLE = """
INFORMACION DE LA PRESENTACION DE LA DECLARACION
Modelo 100 Ejercicio 2024
Registro Presentacion realizada el: 11-05-2025 a las 10:48:06
Expediente/Referencia (n° registro asignado): 202410012900884F
NIF Presentador: 70312903V
Apellidos y Nombre / Razon social: MEGIAS HERENCIAS SANTOS
En calidad de: Titular
Primer declarante NIF 70312903V 0001
Apellidos y nombre MEGIAS HERENCIAS SANTOS 0002
Sexo del primer declarante Hombre 0005
Estado civil (el 31-12-2024) (2) Casado/a 0007
Fecha de nacimiento 03/06/1944 0010
Conyuge NIF 74785936H 0013
Apellidos y nombre MEDINA BOZA MARIA 0014
"""


MODELO_OCR_WORK_AND_ACTIVITY_SAMPLE = """
INFORMACION DE LA PRESENTACION DE LA DECLARACION
Modelo 100 Ejercicio 2024
Primer declarante NIF 74865829R 0001
Apellidos y nombre CALLE SERON ALEJANDRO 0002
Retribuciones dinerarias 57.597,81 0003
Valoracion retribucion en especie 393,36 0004
Total ingresos integros computables 57.991,17 0012
Cotizac. Seguridad Social 1.574,16 0013
Rendimiento neto reducido total de actividades economicas 56.284,73
50.527,03 0505
7.198,25 0670
"""


MODELO_OCR_MAIN_INCOME_SAMPLE = """
INFORMACION DE LA PRESENTACION DE LA DECLARACION
Modelo 100 Ejercicio 2024
Primer declarante NIF X4499144E 0001
Apellidos y nombre BENABDALLAH ADIL 0002
2.386,71 1484
65.701,92 0149
26.941,68 0505
3.913,35 0670
"""


def create_test_schema(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE empresas (
              id TEXT PRIMARY KEY,
              nombre TEXT NOT NULL UNIQUE,
              activo INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE clientes (
              id TEXT PRIMARY KEY,
              nombre TEXT NOT NULL,
              tipo_persona TEXT,
              nif TEXT,
              telefono TEXT,
              email TEXT,
              fecha_nacimiento TEXT,
              direccion TEXT,
              codigo_postal TEXT,
              poblacion TEXT,
              provincia TEXT,
              estado TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE clientes_empresas (
              id TEXT PRIMARY KEY,
              cliente_id TEXT NOT NULL,
              empresa_id TEXT NOT NULL,
              servicio TEXT NOT NULL,
              estado TEXT,
              fecha_inicio TEXT,
              fecha_fin TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE cliente_gestoria (
              id TEXT PRIMARY KEY,
              cliente_id TEXT UNIQUE,
              tipo_cliente TEXT,
              mod_fiscal INTEGER,
              mod_laboral INTEGER,
              mod_contable INTEGER,
              mod_renta INTEGER,
              mod_registro INTEGER,
              mod_trafico INTEGER,
              mod_puntuales INTEGER,
              renta_detalles TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE gestoria_trabajos (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              tipo_trabajo TEXT,
              estado TEXT,
              fecha_inicio TEXT,
              fecha_fin TEXT,
              responsable TEXT,
              importe REAL,
              notas TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE asesoramientos_financiacion (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              origen TEXT,
              inmobiliaria_asesor TEXT,
              asesor TEXT,
              fecha TEXT,
              estado TEXT,
              cliente1_id TEXT,
              cliente1_nombre TEXT,
              cliente1_dni TEXT,
              cliente1_telefono TEXT,
              cliente1_email TEXT,
              cliente1_fecha_nacimiento TEXT,
              cliente1_estado_civil TEXT,
              cliente1_hijos TEXT,
              cliente1_profesion TEXT,
              cliente1_tipo_contrato TEXT,
              cliente1_ingresos REAL,
              cliente1_patrimonio TEXT,
              cliente1_prestamos TEXT,
              cliente2_id TEXT,
              cliente2_nombre TEXT,
              cliente2_dni TEXT,
              cliente2_telefono TEXT,
              cliente2_email TEXT,
              cliente2_fecha_nacimiento TEXT,
              cliente2_estado_civil TEXT,
              cliente2_hijos TEXT,
              cliente2_profesion TEXT,
              cliente2_tipo_contrato TEXT,
              cliente2_ingresos REAL,
              cliente2_patrimonio TEXT,
              cliente2_prestamos TEXT,
              ingresos_conjuntos REAL,
              entidades_financieras TEXT,
              avalistas TEXT,
              aportacion_cv REAL,
              notas TEXT,
              notas_ocr TEXT,
              calidad_ocr TEXT,
              campos_ocr TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            INSERT INTO empresas (id, nombre, activo, created_at, updated_at)
            VALUES ('emp1', 'Financiaciones Modernia', 1, datetime('now'), datetime('now'));
            INSERT INTO empresas (id, nombre, activo, created_at, updated_at)
            VALUES ('emp2', 'Fincas Velazquez', 1, datetime('now'), datetime('now'));
            """
        )
        conn.commit()
    finally:
        conn.close()


class RentasImportTests(unittest.TestCase):
    def test_parse_modelo_100_extracts_key_personal_and_financial_fields(self):
        parsed = parse_modelo_100_text(MODELO_SAMPLE)
        self.assertEqual(parsed["cliente_nif"], "74822580S")
        self.assertEqual(parsed["cliente_nombre"], "TRUJILLO GONZALEZ CRISTOBAL")
        self.assertEqual(parsed["cliente_nombre_source"], "modelo_100")
        self.assertEqual(parsed["cliente_fecha_nacimiento"], "1977-03-19")
        self.assertEqual(parsed["cliente_estado_civil"], "Casado/a")
        self.assertEqual(parsed["conyuge_nif"], "74845153W")
        self.assertEqual(parsed["hijos_count"], 1)
        self.assertAlmostEqual(parsed["rendimientos_trabajo_total"], 33471.49, places=2)
        self.assertAlmostEqual(parsed["ingresos_principales_total"], 33471.49, places=2)
        self.assertAlmostEqual(parsed["base_imponible_general"], 28993.17, places=2)
        self.assertAlmostEqual(parsed["casilla_505"], 28993.17, places=2)
        self.assertAlmostEqual(parsed["resultado_declaracion"], -576.37, places=2)

    def test_parse_modelo_100_presentador_fallback_marks_sources(self):
        parsed = parse_modelo_100_text(MODELO_PRESENTADOR_SAMPLE)
        self.assertEqual(parsed["cliente_nombre"], "ASESORIA MODERNIA SL")
        self.assertEqual(parsed["cliente_nombre_source"], "presentador")
        self.assertEqual(parsed["cliente_nif"], "B12345678")
        self.assertEqual(parsed["cliente_nif_source"], "presentador")

    def test_parse_modelo_100_prefers_declarante_over_presentador_when_available(self):
        text = """
        INFORMACIÓN DE LA PRESENTACIÓN DE LA DECLARACIÓN
        NIF Presentador: 11111111H
        Apellidos y Nombre / Razón social: PRESENTADOR TEST
        En calidad de: Titular
        Primer declarante
        NIF
        22222222J 0001
        Apellidos y nombre
        CLIENTE REAL PRUEBA 0002
        Sexo del primer declarante
        Hombre 0005
        Estado civil (el 31-12-2024)
        (1) Soltero/a 0006
        Fecha de nacimiento
        08/03/1973 0010
        8.500,00 0012
        250,00 0670
        """
        parsed = parse_modelo_100_text(text)
        self.assertEqual(parsed["cliente_nif"], "22222222J")
        self.assertEqual(parsed["cliente_nombre"], "CLIENTE REAL PRUEBA")
        self.assertEqual(parsed["cliente_nombre_source"], "modelo_100")
        self.assertEqual(parsed["cliente_fecha_nacimiento"], "1973-03-08")
        self.assertEqual(parsed["cliente_estado_civil"], "Soltero/a")

    def test_parse_modelo_100_uses_rental_income_when_work_income_missing(self):
        text = """
        Modelo 100
        Impuesto sobre la Renta de las Personas Físicas
        52588440K 0001
        AGUAYO COBO SAUL 0002
        Hombre 0005
        (1) Soltero/a 0006
        08/03/1973 0010
        4.377,30 0149
        4.958,12 0149
        3.393,82 0149
        125,00 0670
        """
        parsed = parse_modelo_100_text(text)
        self.assertEqual(parsed["cliente_fecha_nacimiento"], "1973-03-08")
        self.assertAlmostEqual(parsed["rendimientos_capital_inmobiliario_total"], 12729.24, places=2)
        self.assertAlmostEqual(parsed["ingresos_principales_total"], 12729.24, places=2)

    def test_parse_modelo_100_normalizes_incoherent_activity_amounts(self):
        parsed = parse_modelo_100_text(MODELO_INCOHERENT_AMOUNTS_SAMPLE)
        self.assertEqual(parsed["casilla_505"], 13809.24)
        self.assertEqual(parsed["resultado_declaracion"], 868.32)
        self.assertIsNone(parsed.get("rendimientos_actividades_economicas_total"))
        self.assertAlmostEqual(parsed["ingresos_principales_total"], 13809.24, places=2)

    def test_parse_modelo_100_recovers_birthdate_from_ocr_layout(self):
        parsed = parse_modelo_100_text(MODELO_OCR_BIRTHDATE_SAMPLE)
        self.assertEqual(parsed["cliente_fecha_nacimiento"], "2000-05-28")

    def test_parse_modelo_100_recovers_presentacion_fecha_from_ocr_header(self):
        parsed = parse_modelo_100_text(MODELO_OCR_PRESENTACION_SAMPLE)
        self.assertEqual(parsed["presentacion_fecha"], "2025-06-10")

    def test_parse_modelo_100_prefers_real_primer_declarante_nif_over_placeholder(self):
        parsed = parse_modelo_100_text(MODELO_OCR_DECLARANTE_NIF_SAMPLE)
        self.assertEqual(parsed["cliente_nif"], "74866767L")
        self.assertEqual(parsed["cliente_nombre"], "ACEBES ACEBES PATRICIA")

    def test_parse_modelo_100_recovers_declarante_nif_with_marriage_block(self):
        parsed = parse_modelo_100_text(MODELO_OCR_DECLARANTE_NIF_CASADO_SAMPLE)
        self.assertEqual(parsed["cliente_nif"], "70312903V")
        self.assertEqual(parsed["cliente_nombre"], "MEGIAS HERENCIAS SANTOS")

    def test_parse_modelo_100_uses_highest_work_income_candidate(self):
        parsed = parse_modelo_100_text(MODELO_OCR_WORK_AND_ACTIVITY_SAMPLE)
        self.assertAlmostEqual(parsed["rendimientos_trabajo_total"], 57991.17, places=2)
        self.assertAlmostEqual(parsed["ingresos_principales_total"], 57991.17, places=2)

    def test_parse_modelo_100_uses_main_income_amount_over_smaller_activity(self):
        parsed = parse_modelo_100_text(MODELO_OCR_MAIN_INCOME_SAMPLE)
        self.assertAlmostEqual(parsed["rendimientos_actividades_economicas_total"], 2386.71, places=2)
        self.assertAlmostEqual(parsed["rendimientos_capital_inmobiliario_total"], 65701.92, places=2)
        self.assertAlmostEqual(parsed["ingresos_principales_total"], 65701.92, places=2)

    def test_parse_modelo_100_rebuilds_result_from_installments(self):
        text = """
        Modelo 100
        Impuesto sobre la Renta de las Personas Físicas
        24777151X 0001
        ALVAREZ PONCE CONCEPCION 0002
        Mujer 0005
        (3) Viudo/a 0008
        17/12/1941 0010
        5.000,00 0012
        Importe del primer plazo (60% del resultado de la declaración)
        63,78
        Importe del segundo plazo (40% del resultado de la declaración)
        42,52
        """
        parsed = parse_modelo_100_text(text)
        self.assertEqual(parsed["cliente_nombre"], "ALVAREZ PONCE CONCEPCION")
        self.assertAlmostEqual(parsed["resultado_declaracion"], 106.30, places=2)

    def test_parse_modelo_100_uses_capital_mobiliario_when_no_other_income(self):
        text = """
        Modelo 100
        Impuesto sobre la Renta de las Personas Físicas
        25095751Z 0001
        BUENO DIAZ EVA 0002
        Mujer 0005
        (1) Soltero/a 0006
        18/01/1967 0010
        920,00 0041
        -174,80 0670
        """
        parsed = parse_modelo_100_text(text)
        self.assertAlmostEqual(parsed["rendimientos_capital_mobiliario_total"], 920.00, places=2)
        self.assertAlmostEqual(parsed["ingresos_principales_total"], 920.00, places=2)

    def test_parse_modelo_100_uses_activity_fallback_when_income_code_is_missing(self):
        parsed = parse_modelo_100_text(MODELO_ACTIVITY_SAMPLE)
        self.assertEqual(parsed["cliente_nif"], "74887470E")
        self.assertAlmostEqual(parsed["rendimientos_actividades_economicas_total"], 20050.31, places=2)
        self.assertAlmostEqual(parsed["ingresos_principales_total"], 20050.31, places=2)

    def test_parse_modelo_100_extracts_iban_accounts(self):
        parsed = parse_modelo_100_text(MODELO_IBAN_SAMPLE)
        self.assertIn("ES1601825332100203546780", parsed["cuentas_detectadas"])

    def test_parse_modelo_100_handles_relaxed_ocr_nif_and_birthdate(self):
        parsed = parse_modelo_100_text(MODELO_OCR_RELAXED_SAMPLE)
        self.assertEqual(parsed["cliente_nif"], "74841155Y")
        self.assertEqual(parsed["cliente_fecha_nacimiento"], "1977-02-18")
        self.assertAlmostEqual(parsed["ingresos_principales_total"], 21880.73, places=2)
        self.assertAlmostEqual(parsed["resultado_declaracion"], -125.04, places=2)

    def test_classify_pdf_support_documents(self):
        aplazamiento = "DETALLE DE LA SOLICITUD Tipo Solicitud: Aplaz/Fracc"
        dt2 = "Modelo DT2 Solicitud devolución por aportaciones a Mutualidades"
        self.assertEqual(classify_pdf(aplazamiento, Path("/tmp/aplazamiento.pdf")), "soporte_cliente")
        self.assertEqual(classify_pdf(dt2, Path("/tmp/dt2.pdf")), "soporte_cliente")
        self.assertEqual(classify_pdf("", Path("/tmp/cliente FRACCIONAMIENTO 2 PLAZO.pdf")), "soporte_cliente")

    def test_parse_datos_fiscales_extracts_address_and_accounts(self):
        parsed = parse_datos_fiscales_text(FISCALES_SAMPLE)
        self.assertEqual(parsed["cliente_nif"], "79018863V")
        self.assertEqual(parsed["cliente_nombre"], "RODRIGUEZ MEDEL ESPERANZA LIBERTAD")
        self.assertEqual(parsed["cliente_nombre_source"], "datos_fiscales")
        self.assertEqual(parsed["direccion"], "CALLE NAVEGANTE ISIDORO 15")
        self.assertEqual(parsed["codigo_postal"], "29130")
        self.assertEqual(parsed["poblacion"], "ALHAURÍN DE LA TORRE")
        self.assertEqual(parsed["provincia"], "MALAGA")
        self.assertIn("3650938313", parsed["cuentas_detectadas"])

    def test_parse_datos_fiscales_handles_inline_layout(self):
        parsed = parse_datos_fiscales_text(FISCALES_INLINE_SAMPLE)
        self.assertEqual(parsed["cliente_nif"], "79018863V")
        self.assertEqual(parsed["cliente_nombre"], "RODRIGUEZ MEDEL ESPERANZA LIBERTAD")

    def test_parse_datos_fiscales_uses_public_aids_as_income_fallback(self):
        parsed = parse_datos_fiscales_text(FISCALES_AYUDAS_SAMPLE)
        self.assertAlmostEqual(parsed["rendimientos_actividades_economicas_total"], 6035.17, places=2)
        self.assertAlmostEqual(parsed["ingresos_principales_total"], 6035.17, places=2)

    def test_parse_modelo_100_discards_spouse_name_when_it_looks_like_an_address(self):
        text = """
        Modelo 100
        11111111H 0001
        CLIENTE PRUEBA 0002
        Hombre 0005
        (2) Casado/a 0007
        01/01/1980 0010
        22222222J 0013
        CL ANTONIO MACHADO 0014
        100,00 0670
        """
        parsed = parse_modelo_100_text(text)
        self.assertEqual(parsed["conyuge_nif"], "22222222J")
        self.assertFalse(parsed.get("conyuge_nombre"))

    def test_finalize_record_marks_filename_only_records_for_review(self):
        record = finalize_record(
            {
                "cliente_nombre": "JUAN PRUEBA",
                "cliente_nombre_source": "filename",
                "source_types": ["pdf_desconocido"],
                "source_files": ["/tmp/JUAN PRUEBA.pdf"],
            }
        )
        self.assertFalse(record["safe_to_apply"])
        self.assertIn("nombre_desde_filename", record["review_flags"])
        self.assertIn("faltan_campos_criticos", record["review_flags"])
        self.assertEqual(record["review_status"], "review")

    def test_build_validation_summary_counts_quality_metrics(self):
        records = [
            finalize_record(
                {
                    "cliente_nombre": "A",
                    "cliente_nombre_source": "modelo_100",
                    "cliente_nif": "11111111H",
                    "cliente_fecha_nacimiento": "1980-01-01",
                    "ingresos_principales_total": 1200.0,
                    "resultado_declaracion": 10.0,
                    "source_types": ["modelo_100"],
                    "source_files": ["/tmp/a.pdf"],
                }
            ),
            finalize_record(
                {
                    "cliente_nombre": "A",
                    "cliente_nombre_source": "filename",
                    "source_types": ["pdf_desconocido"],
                    "source_files": ["/tmp/a-2.pdf"],
                }
            ),
        ]
        summary = build_validation_summary(records)
        self.assertEqual(summary["total_registros"], 2)
        self.assertEqual(summary["con_nombre_y_nif"], 1)
        self.assertEqual(summary["con_fecha_nacimiento"], 1)
        self.assertEqual(summary["con_ingresos_y_resultado"], 1)
        self.assertEqual(summary["pdf_desconocido"], 1)
        self.assertEqual(summary["posibles_duplicados_nombre"], 1)
        self.assertEqual(summary["seguros_para_apply"], 1)
        self.assertEqual(summary["pendientes_revision"], 1)

    def test_review_queue_only_contains_non_safe_records(self):
        safe = finalize_record(
            {
                "cliente_nombre": "CLIENTE SEGURO",
                "cliente_nombre_source": "modelo_100",
                "cliente_nif": "22222222J",
                "cliente_fecha_nacimiento": "1990-01-01",
                "ingresos_principales_total": 1500.0,
                "resultado_declaracion": -50.0,
                "source_types": ["modelo_100"],
                "source_files": ["/tmp/safe.pdf"],
            }
        )
        review = finalize_record(
            {
                "cliente_nombre": "CLIENTE DUDOSO",
                "cliente_nombre_source": "filename",
                "source_types": ["pdf_desconocido"],
                "source_files": ["/tmp/review.pdf"],
            }
        )
        queue = build_review_queue([safe, review])
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["cliente_nombre"], "CLIENTE DUDOSO")

    def test_finalize_record_marks_incoherent_renta_amounts_for_review(self):
        record = finalize_record(
            {
                "cliente_nombre": "CLIENTE DUDOSO",
                "cliente_nombre_source": "modelo_100",
                "cliente_nif": "11111111H",
                "cliente_fecha_nacimiento": "1980-01-01",
                "ingresos_principales_total": 9000000.0,
                "rendimientos_trabajo_total": 7876.22,
                "rendimientos_actividades_economicas_total": 9000000.0,
                "casilla_505": 14.64,
                "resultado_declaracion": 1577.18,
                "source_types": ["modelo_100"],
                "source_files": ["/tmp/incoherente.pdf"],
            }
        )
        self.assertFalse(record["safe_to_apply"])
        self.assertIn("renta_corregida", record["review_flags"])
        self.assertEqual(record["ingresos_principales_total"], 7876.22)
        self.assertIsNone(record["casilla_505"])

    def test_should_skip_auxiliary_record_without_modelo_100(self):
        self.assertTrue(
            should_skip_auxiliary_record(
                {
                    "source_types": ["soporte_cliente"],
                    "source_files": ["/tmp/modificacion cuenta.pdf"],
                }
            )
        )
        self.assertTrue(
            should_skip_auxiliary_record(
                {
                    "source_types": ["datos_fiscales"],
                    "cliente_nombre": "Cliente Fiscal",
                    "cliente_nif": "12345678A",
                }
            )
        )
        self.assertFalse(
            should_skip_auxiliary_record(
                {
                    "source_types": ["modelo_100"],
                    "cliente_nombre": "Cliente Modelo",
                    "cliente_nif": "12345678A",
                    "resultado_declaracion": 0.0,
                }
            )
        )

    def test_apply_to_db_only_imports_safe_records_and_avoids_duplicates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "rentas.sqlite"
            create_test_schema(db_path)
            safe_record = finalize_record(
                {
                    "cliente_nombre": "TRUJILLO GONZALEZ CRISTOBAL",
                    "cliente_nombre_source": "modelo_100",
                    "cliente_nif": "74822580S",
                    "cliente_fecha_nacimiento": "1977-03-19",
                    "cliente_estado_civil": "Casado/a",
                    "conyuge_nombre": "GOMEZ GONZALEZ CARMEN",
                    "conyuge_nif": "74845153W",
                    "conyuge_fecha_nacimiento": "1978-11-06",
                    "hijos_count": 1,
                    "ingresos_principales_total": 33471.49,
                    "rendimientos_trabajo_total": 33471.49,
                    "resultado_declaracion": -576.37,
                    "base_imponible_general": 28993.17,
                    "source_types": ["modelo_100", "datos_fiscales"],
                    "source_files": ["/tmp/modelo.pdf", "/tmp/fiscales.pdf"],
                    "direccion": "CALLE PRUEBA 15",
                    "codigo_postal": "29001",
                    "poblacion": "MALAGA",
                    "provincia": "MALAGA",
                }
            )
            duplicate_safe_record = finalize_record(
                {
                    **safe_record,
                    "source_files": ["/tmp/modelo-dup.pdf"],
                }
            )
            review_record = finalize_record(
                {
                    "cliente_nombre": "CLIENTE DUDOSO",
                    "cliente_nombre_source": "filename",
                    "source_types": ["pdf_desconocido"],
                    "source_files": ["/tmp/dudoso.pdf"],
                }
            )
            result = apply_to_db(
                db_path,
                [safe_record, duplicate_safe_record, review_record],
                "Fincas Velazquez",
            )
            self.assertEqual(result["records_upserted"], 2)
            self.assertEqual(result["spouses_linked"], 2)
            self.assertEqual(result["skipped_for_review"], 1)

            conn = sqlite3.connect(str(db_path))
            try:
                clientes_count = conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
                links_count = conn.execute("SELECT COUNT(*) FROM clientes_empresas").fetchone()[0]
                gestoria_count = conn.execute("SELECT COUNT(*) FROM cliente_gestoria WHERE mod_renta = 1").fetchone()[0]
                trabajos_count = conn.execute("SELECT COUNT(*) FROM gestoria_trabajos").fetchone()[0]
                titular_count = conn.execute(
                    "SELECT COUNT(*) FROM clientes WHERE nif = '74822580S'"
                ).fetchone()[0]
                dudoso_count = conn.execute(
                    "SELECT COUNT(*) FROM clientes WHERE nombre = 'CLIENTE DUDOSO'"
                ).fetchone()[0]
                servicio = conn.execute(
                    "SELECT servicio FROM clientes_empresas WHERE cliente_id IN (SELECT id FROM clientes WHERE nif = '74822580S') LIMIT 1"
                ).fetchone()[0]
                renta_detalles = conn.execute(
                    "SELECT renta_detalles FROM cliente_gestoria WHERE cliente_id IN (SELECT id FROM clientes WHERE nif = '74822580S')"
                ).fetchone()[0]
            finally:
                conn.close()

            self.assertEqual(clientes_count, 2)
            self.assertEqual(links_count, 2)
            self.assertEqual(gestoria_count, 1)
            self.assertEqual(trabajos_count, 1)
            self.assertEqual(titular_count, 1)
            self.assertEqual(dudoso_count, 0)
            self.assertEqual(servicio, "gestoria")
            self.assertIn('"entries"', renta_detalles)


if __name__ == "__main__":
    unittest.main()
