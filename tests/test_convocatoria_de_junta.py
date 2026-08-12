"""La convocatoria de la junta, con lo que exige el artículo 16 de la LPH.

Había un endpoint llamado `workspace_fincas_junta_convocatoria` que sonaba a que
generaba el documento. Lo único que hacía era marcar un sí/no —si la junta se celebra
en segunda convocatoria— con una sola sentencia. No había plantilla, ni generador, ni
PDF: la convocatoria se escribía a mano fuera del CRM, con todos los datos dentro.

El artículo 16.2 exige cuatro cosas y estos tests vigilan las cuatro:

1. Los asuntos a tratar.
2. El lugar, día y hora de primera y, en su caso, segunda convocatoria.
3. La relación de propietarios que no estén al corriente en el pago.
4. La advertencia de que quedan privados del derecho de voto (art. 15.2).

Y una quinta cosa que no es de la ley sino de criterio: **lo que el sistema no sabe no
se inventa**. Sin lugar señalado deja el hueco a la vista; sin orden del día lo dice en
vez de emitir una convocatoria vacía que no cumpliría.
"""

import sys
import unittest
from io import BytesIO
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
from web import server  # noqa: E402

COMUNIDAD = {
    "nombre": "C. P Urbanización Barceló Bl4",
    "direccion": "Avenida Europa 108, Málaga",
    "cif": "H29123456",
}
ORDEN_DEL_DIA = [
    {"orden": 1, "titulo": "Lectura y aprobación del acta anterior", "descripcion": ""},
    {"orden": 2, "titulo": "Aprobación de cuentas del ejercicio 2025",
     "descripcion": "Estado de ingresos y gastos y fondo de reserva."},
]
MOROSOS = [
    {"piso": "3 B", "nombre": "ANTONIO ASENSIO RODRIGUEZ", "recibos": 4, "deuda": 248.0},
    {"piso": "9 C", "nombre": "SABRINA VERGARA SANZ", "recibos": 2, "deuda": 124.0},
]


def texto_de(junta=None, acuerdos=None, morosos=None, comunidad=None):
    from pypdf import PdfReader

    base = {"id": "j1", "fecha": "2026-09-18", "tipo": "ordinaria",
            "hora": "18:00", "lugar": "Portal del edificio", "hora_segunda": ""}
    pdf = server.build_convocatoria_junta_pdf(
        dict(base, **(junta or {})),
        COMUNIDAD if comunidad is None else comunidad,
        ORDEN_DEL_DIA if acuerdos is None else acuerdos,
        MOROSOS if morosos is None else morosos,
        workspace={}, company={"nombre": "Fincas Velazquez"},
    )
    return "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)


class LoQueExigeElArticulo16Tests(unittest.TestCase):
    def test_lleva_los_asuntos_a_tratar(self):
        texto = texto_de()
        self.assertIn("Orden del día", texto)
        self.assertIn("Lectura y aprobación del acta anterior", texto)
        self.assertIn("Aprobación de cuentas del ejercicio 2025", texto)

    def test_lleva_lugar_dia_y_las_dos_horas(self):
        texto = texto_de()
        self.assertIn("Portal del edificio", texto)
        self.assertIn("18 de septiembre de 2026", texto)
        self.assertIn("18:00", texto)
        self.assertIn("18:30", texto)

    def test_las_horas_no_se_pierden_en_las_tarjetas(self):
        """Con la fecha entera dentro, el motor recortaba la tarjeta por ancho y se
        comía la hora — el dato que la ley obliga a poner. Va también en texto."""
        self.assertIn("Hora: 18:00 en primera convocatoria", texto_de())

    def test_lleva_la_relacion_de_quien_no_esta_al_corriente(self):
        texto = texto_de()
        self.assertIn("Propietarios no al corriente de pago", texto)
        self.assertIn("ANTONIO ASENSIO RODRIGUEZ", texto)
        self.assertIn("SABRINA VERGARA SANZ", texto)
        self.assertIn("372,00 €", texto)   # la suma de las dos deudas

    def test_advierte_de_la_privacion_del_voto_citando_el_articulo(self):
        texto = texto_de()
        self.assertIn("NO tendrán derecho de voto", texto)
        self.assertIn("15.2", texto)
        # Las tres salidas que da la ley para recuperar el voto.
        for salida in ("pagado", "impugnado", "consignado"):
            with self.subTest(salida=salida):
                self.assertIn(salida, texto)


class LaSegundaConvocatoriaTests(unittest.TestCase):
    def test_sin_hora_se_calcula_la_media_hora_de_la_ley(self):
        self.assertEqual(server.FINCAS_MINUTOS_SEGUNDA_CONVOCATORIA, 30)
        self.assertIn("18:30", texto_de())

    def test_si_se_indica_otra_hora_manda_esa(self):
        texto = texto_de({"hora": "19:30", "hora_segunda": "20:15"})
        self.assertIn("20:15", texto)
        self.assertNotIn("20:00", texto)

    def test_sin_hora_ninguna_no_se_inventa_una_segunda(self):
        texto = texto_de({"hora": "", "hora_segunda": ""})
        self.assertIn("sin segunda convocatoria señalada", texto)
        self.assertIn("No se ha señalado segunda convocatoria", texto)


class LoQueNoSeSabeNoSeInventaTests(unittest.TestCase):
    def test_sin_lugar_deja_el_hueco_a_la_vista(self):
        texto = texto_de({"lugar": ""})
        self.assertIn("sin señalar en el sistema", texto)

    def test_sin_orden_del_dia_lo_dice_y_avisa_de_que_no_cumple(self):
        """Una convocatoria sin asuntos a tratar no cumple el art. 16.2. Mejor que se
        vea antes de enviarla que después."""
        texto = texto_de(acuerdos=[])
        self.assertIn("No hay puntos registrados", texto)
        self.assertIn("16.2", texto)

    def test_sin_morosos_no_se_calla_la_seccion(self):
        """Que no haya deuda es una afirmación, no un silencio."""
        texto = texto_de(morosos=[])
        self.assertIn("Propietarios no al corriente de pago", texto)
        self.assertIn("no consta deuda vencida", texto)

    def test_la_ordinaria_recuerda_la_antelacion_minima(self):
        self.assertEqual(server.FINCAS_DIAS_ANTELACION_ORDINARIA, 6)
        self.assertIn("6 días de antelación", texto_de())

    def test_la_extraordinaria_no_inventa_un_plazo(self):
        """El art. 16.3 solo fija plazo para la ordinaria; la extraordinaria va «con la
        antelación posible»."""
        self.assertNotIn("días de antelación", texto_de({"tipo": "extraordinaria"}))


class ElDocumentoSeSirveYSeDescargaTests(unittest.TestCase):
    def test_hay_endpoint_y_pide_pertenencia(self):
        i = SERVER.index('if path == "/api/workspace_fincas_convocatoria":')
        cuerpo = SERVER[i: SERVER.index("\n        if path ==", i + 10)]
        self.assertIn("enforce_workspace_membership", cuerpo)
        self.assertIn("build_convocatoria_junta_pdf", cuerpo)
        self.assertLess(cuerpo.index("enforce_workspace_membership"),
                        cuerpo.index("build_convocatoria_junta_pdf"))

    def test_saca_el_orden_del_dia_y_la_morosidad_de_la_base(self):
        i = SERVER.index('if path == "/api/workspace_fincas_convocatoria":')
        cuerpo = SERVER[i: SERVER.index("\n        if path ==", i + 10)]
        self.assertIn("workspace_fincas_junta_acuerdos", cuerpo)
        self.assertIn("fetch_workspace_fincas_morosidad", cuerpo)

    def test_hay_boton_en_la_pestaña_de_juntas(self):
        self.assertIn("data-junta-convocatoria", APP)
        i = APP.index("[data-junta-convocatoria]")
        self.assertIn("/api/workspace_fincas_convocatoria", APP[i: i + 500])

    def test_la_junta_guarda_hora_y_lugar(self):
        """Sin estas columnas el lugar y la hora había que ponerlos a mano fuera."""
        for columna in ("hora", "lugar", "hora_segunda"):
            with self.subTest(columna=columna):
                self.assertIn(
                    f'ensure_column(conn, "workspace_fincas_juntas", "{columna}"', SERVER
                )

    def test_el_endpoint_viejo_sigue_siendo_solo_un_interruptor(self):
        """`workspace_fincas_junta_convocatoria` marca si la junta es en segunda. El que
        genera el documento es otro; que no vuelvan a confundirse."""
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_junta_convocatoria":')
        cuerpo = SERVER[i: i + 1500]
        self.assertIn("segunda_convocatoria = ?", cuerpo)
        self.assertNotIn("build_convocatoria_junta_pdf", cuerpo)


if __name__ == "__main__":
    unittest.main()
