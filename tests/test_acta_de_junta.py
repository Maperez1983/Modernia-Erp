"""El acta de la junta, contrastada con el artículo 19 de la LPH.

El acta ya existía y estaba bien resuelta en lo difícil —el recuento por cabezas y por
coeficiente, el denominador que cambia en segunda convocatoria, y no dictaminar un
acuerdo al que nadie le asignó mayoría—. Pero al leer el artículo 19.1 con el documento
delante faltaban cuatro de las seis letras:

    a) fecha y **lugar** de celebración            -> solo la fecha
    b) **el autor de la convocatoria**             -> no estaba
    c) carácter y primera/segunda convocatoria     -> sí
    d) asistentes **con sus cargos** y sus cuotas  -> sin los cargos
    e) **el orden del día**                        -> implícito en los acuerdos
    f) acuerdos con **los nombres** de quienes votaron a favor y en contra,
       y sus cuotas, cuando sea relevante para la validez  -> solo el recuento

Lo de la letra f es lo que más duele: los votos estaban en la base desde el principio
—`workspace_fincas_junta_votos` guarda quién votó qué— y `calcular_recuento_junta` los
contaba y tiraba los nombres.
"""

import sys
import unittest
from io import BytesIO
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
from web import server  # noqa: E402

COMUNIDAD = {
    "nombre": "C. P Urbanización Barceló Bl4",
    "direccion": "Avenida Europa 108, Málaga",
    "cif": "H29123456",
    "presidente": "ANTONIO LOBATO BARRAGAN",
    "secretario": "ANA PEREZ VILLAMIL",
}
PROPIETARIOS = [
    {"id": "1", "nombre": "ANTONIO LOBATO BARRAGAN", "piso": "4 A", "coeficiente": 2.13,
     "asiste": True, "representado_por": ""},
    {"id": "2", "nombre": "ANA PEREZ VILLAMIL", "piso": "6 C", "coeficiente": 1.98,
     "asiste": True, "representado_por": ""},
    {"id": "3", "nombre": "CARMEN TORRES TORRES", "piso": "8 D", "coeficiente": 2.13,
     "asiste": True, "representado_por": "Su hijo Manuel"},
]
ACUERDO = {
    "orden": 1, "titulo": "Instalación de ascensor", "descripcion": "Presupuestos y derrama.",
    "mayoria_etiqueta": "Tres quintos", "articulo": "art. 17.3",
    "favor": 2, "contra": 1, "abstencion": 0,
    "favor_propietarios": 66.67, "favor_coeficiente": 65.40,
    "sobre": "los asistentes", "aprobado": True,
    "votos_nominales": {
        "favor": [{"piso": "4 A", "nombre": "ANTONIO LOBATO BARRAGAN", "coeficiente": 2.13},
                  {"piso": "6 C", "nombre": "ANA PEREZ VILLAMIL", "coeficiente": 1.98}],
        "contra": [{"piso": "8 D", "nombre": "CARMEN TORRES TORRES", "coeficiente": 2.13}],
        "abstencion": [],
    },
}


def texto_de(junta=None, acuerdos=None, comunidad=None, propietarios=None):
    from pypdf import PdfReader

    base_junta = {"id": "j1", "fecha": "2026-09-18", "tipo": "ordinaria",
                  "lugar": "Portal del edificio", "convocada_por": "El presidente",
                  "segunda_convocatoria": 1}
    recuento = {
        "junta": dict(base_junta, **(junta or {})),
        "asistencia": {"propietarios_total": 48, "coeficiente_total": 100.0, "presentes": 2,
                       "representados": 1, "asistentes": 3,
                       "asistentes_pct_propietarios": 6.25, "asistentes_pct_coeficiente": 6.24,
                       "segunda_convocatoria": bool((junta or {}).get("segunda_convocatoria", 1))},
        "propietarios": PROPIETARIOS if propietarios is None else propietarios,
        "acuerdos": [ACUERDO] if acuerdos is None else acuerdos,
    }
    pdf = server.build_acta_junta_pdf(
        recuento, COMUNIDAD if comunidad is None else comunidad,
        workspace={}, company={"nombre": "Fincas Velazquez"},
    )
    return "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)


class LasSeisLetrasDelArticulo19Tests(unittest.TestCase):
    def test_a_fecha_y_lugar(self):
        texto = texto_de()
        self.assertIn("18 de septiembre de 2026", texto)
        self.assertIn("Portal del edificio", texto)

    def test_a_la_fecha_va_en_castellano(self):
        """Es un documento que se archiva en el libro de actas, no un registro."""
        self.assertNotIn("2026-09-18", texto_de())

    def test_b_quien_convoco(self):
        self.assertIn("Convocada por: El presidente", texto_de())

    def test_c_caracter_y_convocatoria(self):
        self.assertIn("Junta ordinaria", texto_de())
        self.assertIn("Celebrada en segunda convocatoria", texto_de())
        self.assertIn("Celebrada en primera convocatoria",
                      texto_de({"segunda_convocatoria": 0}))

    def test_d_asistentes_con_cargo_representacion_y_cuota(self):
        texto = texto_de()
        self.assertIn("Relación de asistentes", texto)
        self.assertIn("Presidente", texto)          # cargo deducido de la ficha
        self.assertIn("Secretario", texto)
        self.assertIn("Su hijo Manuel", texto)      # representado
        self.assertIn("2,1300 %", texto)            # cuota, con coma decimal

    def test_e_orden_del_dia(self):
        texto = texto_de()
        self.assertIn("Orden del día", texto)
        self.assertIn("1. Instalación de ascensor", texto)

    def test_f_los_nombres_de_quien_voto_y_su_cuota(self):
        texto = texto_de()
        self.assertIn("Votaron a favor:", texto)
        self.assertIn("ANTONIO LOBATO BARRAGAN (4 A, 2,1300 %)", texto)
        self.assertIn("Votaron en contra:", texto)
        self.assertIn("CARMEN TORRES TORRES (8 D, 2,1300 %)", texto)

    def test_los_porcentajes_llevan_coma_y_no_punto(self):
        """En un acta el punto es el separador de millares: «2.1300 %» se puede leer
        como dos mil ciento treinta, y la cuota de participación reparte el gasto."""
        import re as _re
        texto = texto_de()
        con_punto = _re.findall(r"\d+\.\d+\s*%", texto)
        self.assertEqual(con_punto, [], f"porcentajes con punto decimal: {con_punto}")
        self.assertIn("6,25 %", texto)

    def test_el_plazo_de_firma_de_los_diez_dias(self):
        self.assertEqual(server.FINCAS_DIAS_CIERRE_ACTA, 10)
        texto = texto_de()
        self.assertIn("10 días naturales siguientes", texto)
        self.assertIn("19.2", texto)


class LoQueNoSeSabeNoSeInventaTests(unittest.TestCase):
    def test_sin_lugar_lo_dice(self):
        self.assertIn("lugar no señalado", texto_de({"lugar": ""}))

    def test_sin_convocante_deja_el_hueco_y_cita_el_articulo(self):
        texto = texto_de({"convocada_por": ""})
        self.assertIn("19.1.b", texto)
        self.assertIn("no consta en el sistema", texto)

    def test_un_nombre_que_no_casa_no_recibe_cargo(self):
        """El cargo se deduce de la ficha de la comunidad. Si no coincide el nombre, en
        blanco: repartir cargos a ojo en un acta es peor que dejarlos sin poner."""
        texto = texto_de(comunidad=dict(COMUNIDAD, presidente="OTRA PERSONA", secretario=""))
        self.assertNotIn("Presidente\n", texto)

    def test_sin_votos_nominales_no_se_escriben_lineas_vacias(self):
        sin_nombres = dict(ACUERDO, votos_nominales={"favor": [], "contra": [], "abstencion": []})
        texto = texto_de(acuerdos=[sin_nombres])
        self.assertNotIn("Votaron a favor:", texto)
        self.assertIn("A favor: 2", texto)      # el recuento se mantiene

    def test_sigue_sin_dictaminar_lo_que_no_tiene_mayoria(self):
        """Lo que ya hacía bien y no se ha roto al ampliar el acta."""
        sin_mayoria = dict(ACUERDO, aprobado=None, mayoria_etiqueta="", articulo="")
        self.assertIn("el resultado no se dictamina", texto_de(acuerdos=[sin_mayoria]))


class ElRecuentoDevuelveLosNombresTests(unittest.TestCase):
    """Los votos estaban en la base y se tiraban al contarlos."""

    def test_el_recuento_incluye_los_votos_nominales(self):
        i = SERVER.index("def calcular_recuento_junta")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn('"votos_nominales"', cuerpo)
        self.assertIn("ficha_propietario", cuerpo)

    def test_la_junta_guarda_quien_convoca(self):
        self.assertIn('ensure_column(conn, "workspace_fincas_juntas", "convocada_por"', SERVER)


if __name__ == "__main__":
    unittest.main()
