"""El presupuesto deja de salir apelotonado, y lo firma la marca del logo.

Al mirar un presupuesto real generado (C.P. Rocío Jurado 18, tres páginas) se veían
cinco cosas, todas de las que se notan al abrirlo:

- **La carta era un muro.** Ocho párrafos pegados uno debajo de otro, sin un hueco
  entre ellos: no se distinguía dónde acababa cada idea.
- **Los encabezados de sección se pegaban** al bloque anterior, así que «Datos de la
  comunidad» parecía continuación de la línea de arriba.
- **«Cierre económico» se quedó solo al pie de la página 2** y sus tres cifras se
  fueron a la 3, que quedó casi en blanco. La tabla de partidas, además, se partía:
  dos filas en una página y la tercera en la siguiente.
- **El subtítulo de la banda se recortaba a 58 caracteres a ciegas**, así que ponía
  «… Comunidad de Propietarios R…» aunque sobrara la mitad del ancho.
- **La cifra final iba igual que el IVA**, en cuerpo 8,5, cuando es el número que se
  lee en la junta.

Y una decisión que no es de forma: el documento lleva el logo de Fincas Velázquez
para todos los presupuestos de fincas, pero el nombre que salía bajo la banda era el
de la sociedad emisora. Poner «Inmovere Fincas» junto al logo de Velázquez confunde
a quien lo recibe. Ahora se lee la marca, y la sociedad y su CIF siguen apareciendo
—bajo la banda y en el pie—, que es lo que identifica con quién se contrata cuando
el presupuesto se acepta y pasa a ser contrato.
"""

import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
MOTOR = (RAIZ / "web" / "branded_pdf_vector.py").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))

try:
    from pypdf import PdfReader

    from web import server
    from web import branded_pdf_vector as motor

    LISTO = True
except Exception:  # pragma: no cover
    LISTO = False


WORKSPACE = {"nombre": "Modernia", "primary_color": "#3C6E71"}
EMPRESA = {"nombre": "Inmovere Fincas", "razon_social": "Inmovere Fincas", "nif": "B26798231"}
CLIENTE = {"nombre": "C.P. Rocío Jurado 18", "nif": "", "telefono": "", "email": ""}

CARTA = "\n".join(f"Párrafo número {n} de la carta, con su idea propia." for n in range(1, 9))

LINEAS = [
    {"categoria": "Edificio", "concepto": "Por vivienda (5,00 €/unidad)", "cantidad": 92,
     "unidad": "vivienda", "precio_unitario": 5, "total_linea": 460},
    {"categoria": "Edificio", "concepto": "Por trastero (1,00 €/unidad)", "cantidad": 95,
     "unidad": "trastero", "precio_unitario": 1, "total_linea": 95},
    {"categoria": "Edificio", "concepto": "Por aparcamiento (1,00 €/unidad)", "cantidad": 115,
     "unidad": "plaza", "precio_unitario": 1, "total_linea": 115},
]


def presupuesto(**extra):
    calc = {
        "num_vecinos": 92, "num_trasteros": 95, "num_aparcamientos": 115,
        "comunidad_denominacion": "Comunidad de Propietarios Rocío Jurado 18",
        "carta_presentacion": CARTA, "colegiado_numero": "3079",
    }
    calc.update(extra.pop("calc", {}))
    base = {
        "id": "x", "servicio": "fincas",
        "titulo": "Administración de comunidad · Comunidad de Propietarios Rocío Jurado 18",
        "fecha": "2026-08-07", "subtotal": 670.0, "impuestos": 140.7, "total": 810.7,
        "calculo_json": json.dumps(calc),
    }
    base.update(extra)
    return base


def genera(**extra):
    """Sin salir a la red: el mapa tiene sus propios tests."""
    with mock.patch.object(server, "fetch_geocode_coordinates", return_value=None), \
         mock.patch.object(server, "build_mapa_estatico", return_value=None):
        pdf = server.build_workspace_budget_pdf(
            presupuesto(**extra), WORKSPACE, EMPRESA, CLIENTE, LINEAS)
    lector = PdfReader(BytesIO(pdf))
    return pdf, lector, "\n".join((p.extract_text() or "") for p in lector.pages)


@unittest.skipUnless(LISTO, "hace falta web.server y pypdf")
class LaMarcaEsLaDelLogoTests(unittest.TestCase):
    def test_se_lee_fincas_velazquez_aunque_emita_inmovere(self):
        _pdf, _l, texto = genera()
        self.assertIn("Fincas Velázquez", texto)

    def test_la_sociedad_y_el_cif_no_desaparecen(self):
        """Un presupuesto aceptado es un contrato: hay que saber con quién."""
        _pdf, _l, texto = genera()
        self.assertIn("Inmovere Fincas", texto)
        self.assertIn("B26798231", texto)

    def test_el_pie_nombra_la_marca_y_entre_parentesis_la_sociedad(self):
        _pdf, _l, texto = genera()
        self.assertIn("emitido por Fincas Velázquez (Inmovere Fincas", texto)

    def test_si_marca_y_sociedad_coinciden_no_se_repite(self):
        misma = {"nombre": "Fincas Velázquez", "razon_social": "Fincas Velázquez", "nif": "B72661374"}
        with mock.patch.object(server, "fetch_geocode_coordinates", return_value=None), \
             mock.patch.object(server, "build_mapa_estatico", return_value=None):
            pdf = server.build_workspace_budget_pdf(presupuesto(), WORKSPACE, misma, CLIENTE, LINEAS)
        texto = "\n".join((p.extract_text() or "") for p in PdfReader(BytesIO(pdf)).pages)
        self.assertNotIn("Fincas Velázquez · Fincas Velázquez", texto)
        self.assertNotIn("(Fincas Velázquez ·", texto)

    def test_fuera_de_fincas_manda_la_razon_social(self):
        """La marca es de administración de fincas, no de todo el CRM."""
        _pdf, _l, texto = genera(servicio="gestoria")
        self.assertNotIn("Fincas Velázquez", texto)
        self.assertIn("Inmovere Fincas", texto)

    def test_la_carta_tambien_firma_con_la_marca(self):
        i = SERVER.index('"empresa": FINCAS_NOMBRE_COMERCIAL')
        self.assertGreater(i, 0)


@unittest.skipUnless(LISTO, "hace falta web.server y pypdf")
class ElSubtituloCabeEnteroTests(unittest.TestCase):
    def test_ya_no_se_recorta_a_ciegas(self):
        """71 caracteres caben de sobra al lado de «PRESUPUESTO»."""
        _pdf, _l, texto = genera()
        self.assertIn("Comunidad de Propietarios Rocío Jurado 18", texto)
        self.assertNotIn("Comunidad de Propietarios R…", texto)

    def test_uno_larguisimo_se_recorta_pero_no_se_solapa(self):
        largo = "Administración de comunidad · " + ("Nombre larguísimo de comunidad " * 8)
        _pdf, _l, texto = genera(titulo=largo)
        self.assertIn("…", texto)

    def test_el_motor_mide_en_vez_de_contar_caracteres(self):
        self.assertIn("def _encoge_para_caber(", MOTOR)
        i = MOTOR.index("def cabecera(c, pagina)")
        self.assertIn("_encoge_para_caber", MOTOR[i: i + 2000])

    def test_encoger_respeta_un_cuerpo_minimo(self):
        from reportlab.pdfgen import canvas as rl_canvas

        c = rl_canvas.Canvas(BytesIO())
        _texto, cuerpo = motor._encoge_para_caber(c, "x" * 400, motor.PDF_FONT_REGULAR, 9, 100, minimo=6.8)
        self.assertGreaterEqual(cuerpo, 6.8)


@unittest.skipUnless(LISTO, "hace falta web.server y pypdf")
class NadaSeQuedaPartidoTests(unittest.TestCase):
    def test_una_tabla_pequena_no_se_parte_en_dos_paginas(self):
        """Tres filas y un total: o entran enteras, o pasan a la página siguiente."""
        _pdf, lector, _t = genera()
        paginas = [(p.extract_text() or "") for p in lector.pages]
        con_partidas = [i for i, t in enumerate(paginas) if "Por trastero" in t]
        self.assertEqual(len(con_partidas), 1, "las partidas aparecen en más de una página")
        pagina = paginas[con_partidas[0]]
        for concepto in ("Por vivienda", "Por trastero", "Por aparcamiento", "Total"):
            with self.subTest(concepto=concepto):
                self.assertIn(concepto, pagina)

    def test_un_encabezado_no_se_queda_solo_al_pie(self):
        _pdf, lector, _t = genera()
        for n, pagina in enumerate(lector.pages, 1):
            texto = (pagina.extract_text() or "").strip()
            if not texto:
                continue
            with self.subTest(pagina=n):
                # Si la última línea con contenido es un encabezado conocido, se quedó huérfano.
                ultima = [l for l in texto.split("\n") if l.strip()][-1].strip()
                self.assertNotIn(ultima, {"Cierre económico", "Administración mensual", "Servicios incluidos"})

    def test_el_motor_estima_la_altura_de_los_bloques(self):
        self.assertIn("def _alto_estimado(", MOTOR)
        i = MOTOR.index("if encabezado:")
        self.assertIn("_alto_estimado(cuerpo)", MOTOR[i: i + 1200])

    def test_la_estimacion_de_una_tabla_crece_con_las_filas(self):
        una = motor._alto_estimado({"kind": "table", "rows": [["a"]]})
        cinco = motor._alto_estimado({"kind": "table", "rows": [["a"]] * 5})
        self.assertGreater(cinco, una)

    def test_sin_filas_no_estima(self):
        self.assertIsNone(motor._alto_estimado({"kind": "table", "rows": []}))

    def test_una_lista_de_texto_no_se_estima(self):
        """Se parte sin problema, y reservarle sitio dejaría páginas a medias."""
        self.assertIsNone(motor._alto_estimado(["uno", "dos"]))

    def test_la_reserva_nunca_pasa_de_una_pagina(self):
        """Si no, un bloque enorme provocaría saltos de página infinitos."""
        i = MOTOR.index("if encabezado:")
        self.assertIn("_alto_util_pagina()", MOTOR[i: i + 1200])


@unittest.skipUnless(LISTO, "hace falta web.server y pypdf")
class ElDocumentoRespiraTests(unittest.TestCase):
    def test_los_parrafos_de_la_carta_llevan_hueco(self):
        i = SERVER.index('carta = limpio(calc.get("carta_presentacion"))')
        self.assertIn('"espaciado": 7', SERVER[i: i + 700])

    def test_hay_aire_antes_de_cada_encabezado(self):
        self.assertIn("ESPACIO_ANTES_SECCION", MOTOR)
        i = MOTOR.index("if encabezado:")
        self.assertIn("lienzo.y -= ESPACIO_ANTES_SECCION", MOTOR[i: i + 1200])

    def test_al_abrir_pagina_no_se_separa_de_mas(self):
        """La cabecera ya deja su hueco; sumar otro dejaría el título flotando."""
        i = MOTOR.index("if encabezado:")
        self.assertIn("if not lienzo.recien_abierta():", MOTOR[i: i + 1200])

    def test_las_listas_separan_sus_elementos(self):
        self.assertIn("ESPACIO_ENTRE_ITEMS", MOTOR)
        self.assertIn("def _lista(", MOTOR)

    def test_la_carta_ocupa_mas_alto_que_antes(self):
        """Con ocho párrafos, el hueco entre ellos tiene que notarse."""
        con = motor.ESPACIO_ENTRE_ITEMS
        self.assertGreater(con, 0)

    def test_la_cifra_final_se_destaca(self):
        i = MOTOR.index("def _cascada(")
        cuerpo = MOTOR[i: MOTOR.index("\ndef ", i + 10)]
        self.assertIn("destacado = _es_destacado(paso)", cuerpo)
        self.assertIn("11.0 if destacado else 8.5", cuerpo)

    def test_la_raya_del_encabezado_no_corta_las_letras(self):
        """Iba justo a la altura de la base del texto, así que partía por la mitad
        el trazo que baja: «Carta de presentación» salía con la «p» cortada."""
        from reportlab.pdfbase import pdfmetrics

        cara = pdfmetrics.getFont(motor.PDF_FONT_BOLD).face
        # `descent` viene en milésimas de em y es negativo.
        descendente = abs(cara.descent) / 1000.0 * 11.5
        self.assertGreater(
            motor.REGLA_BAJO_ENCABEZADO, descendente,
            "la raya vuelve a pasar por encima de la «p»",
        )

    def test_la_raya_se_dibuja_bajo_la_base_del_texto(self):
        i = MOTOR.index("if encabezado:")
        cuerpo = MOTOR[i: i + 1600]
        self.assertIn("base_texto = lienzo.y + 4", cuerpo)
        self.assertIn("regla = base_texto - REGLA_BAJO_ENCABEZADO", cuerpo)

    def test_el_hueco_bajo_la_raya_se_mide_desde_la_raya(self):
        """Si se restara desde la base del texto, el contenido se le pegaría."""
        i = MOTOR.index("if encabezado:")
        self.assertIn("lienzo.y = regla - ESPACIO_TRAS_ENCABEZADO", MOTOR[i: i + 1600])

    def test_la_cifra_final_lleva_una_linea_encima(self):
        i = MOTOR.index("def _cascada(")
        cuerpo = MOTOR[i: MOTOR.index("\ndef ", i + 10)]
        self.assertIn("lienzo.c.line(MARGEN_X + 8", cuerpo)


@unittest.skipUnless(LISTO, "hace falta web.server y pypdf")
class LoQueNoSeDebeHaberRotoTests(unittest.TestCase):
    def test_sigue_siendo_texto_de_verdad(self):
        _pdf, lector, _t = genera()
        for n, pagina in enumerate(lector.pages, 1):
            with self.subTest(pagina=n):
                self.assertTrue(list((pagina.get("/Resources", {}) or {}).get("/Font") or {}))

    def test_sigue_diciendo_que_la_cuota_es_mensual(self):
        _pdf, _l, texto = genera()
        self.assertIn("CUOTA MENSUAL", texto.upper())

    def test_las_cifras_son_las_que_son(self):
        _pdf, _l, texto = genera()
        for cifra in ("670,00", "140,70", "810,70"):
            with self.subTest(cifra=cifra):
                self.assertIn(cifra, texto)

    def test_no_se_come_paginas_de_mas(self):
        _pdf, lector, _t = genera()
        self.assertLessEqual(len(lector.pages), 4)


if __name__ == "__main__":
    unittest.main()


class LosServiciosComplementariosVanAparteTests(unittest.TestCase):
    """Lo que hace el grupo además de administrar la finca.

    El usuario pidió que salieran en el presupuesto la asesoría fiscal, las rentas,
    las herencias, los seguros… Van en **su propia lista**, no en «Servicios
    incluidos»: esa lista define lo que compra la cuota mensual, y meter ahí la
    declaración de la renta sería comprometerse a hacer las 92 de la comunidad por
    los mismos 810,70 € al mes.
    """

    APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

    def test_estan_los_que_pidio(self):
        for servicio in ("Asesoría fiscal, contable y laboral",
                         "Elaboración de declaraciones de la renta",
                         "Gestión de herencias",
                         "Transferencias de vehículos",
                         "Asesoría jurídica",
                         "Análisis de inversiones",
                         "Intermediación inmobiliaria y financiera"):
            with self.subTest(servicio=servicio):
                self.assertIn(servicio, self.APP)

    def test_no_se_mezclan_con_los_incluidos(self):
        i = self.APP.index("const FINCAS_SERVICIOS_DEFAULT")
        incluidos = self.APP[i: self.APP.index("];", i)]
        self.assertNotIn("herencias", incluidos)
        self.assertNotIn("renta", incluidos)

    def test_se_leen_por_separado(self):
        self.assertIn("data-servicio-grupo", self.APP)
        self.assertIn("const readFincasServiciosGrupo", self.APP)
        i = self.APP.index("const readFincasServiciosIncluidos")
        self.assertIn(':not([data-servicio-grupo])', self.APP[i: i + 260])

    def test_viajan_en_el_presupuesto(self):
        self.assertIn("servicios_grupo: serviciosGrupo", self.APP)
        self.assertIn('calculo["servicios_grupo"]', SERVER)

    @unittest.skipUnless(LISTO, "hace falta web.server y pypdf")
    def test_el_pdf_los_pinta_en_su_bloque(self):
        _pdf, _l, texto = genera(calc={"servicios_incluidos": ["Gestión de incidencias"],
                                       "servicios_grupo": ["Gestión de herencias"]})
        self.assertIn("Servicios complementarios", texto)
        self.assertIn("Gestión de herencias", texto)

    @unittest.skipUnless(LISTO, "hace falta web.server y pypdf")
    def test_la_cuota_deja_claro_que_compra(self):
        _pdf, _l, texto = genera(calc={"servicios_incluidos": ["Gestión de incidencias"]})
        self.assertIn("Servicios incluidos en la cuota", texto)

    @unittest.skipUnless(LISTO, "hace falta web.server y pypdf")
    def test_se_advierte_de_que_van_con_presupuesto_aparte(self):
        _pdf, _l, texto = genera(calc={"servicios_grupo": ["Gestión de herencias"]})
        self.assertIn("presupuesto aparte", texto)

    @unittest.skipUnless(LISTO, "hace falta web.server y pypdf")
    def test_sin_complementarios_no_sale_el_bloque(self):
        _pdf, _l, texto = genera(calc={"servicios_grupo": []})
        self.assertNotIn("Servicios complementarios", texto)


@unittest.skipUnless(LISTO, "hace falta web.server y pypdf")
class ElPrecioPactadoMandaTests(unittest.TestCase):
    """El PDF imprimía la tarifa, no lo acordado.

    Cuando se negocia un precio distinto del que sale de la tarifa, el presupuesto
    guarda el pactado en `subtotal` pero las partidas siguen siendo las de tarifa. El
    PDF sumaba las partidas e ignoraba el pactado, así que **el documento que se le
    manda al presidente decía otra cifra que la acordada**:

    - C.P ASTREA 3: 140 € pactados, el PDF imprimía 222,64 €/mes.
    - La comunidad de 177 viviendas: 1.210 € pactados contra 1.523,39 € impresos.

    Los dos son presupuestos reales de producción. Ahora manda lo pactado y la
    diferencia sale como una línea más: disimularla cuadrando los números por dentro
    dejaría un desglose que no suma lo que dice.
    """

    def genera_con(self, subtotal, impuestos, total, lineas):
        budget = {"id": "x", "servicio": "fincas", "titulo": "Prueba", "fecha": "2026-08-08",
                  "subtotal": subtotal, "impuestos": impuestos, "total": total,
                  "calculo_json": json.dumps({"num_vecinos": 28})}
        with mock.patch.object(server, "fetch_geocode_coordinates", return_value=None), \
             mock.patch.object(server, "build_mapa_estatico", return_value=None), \
             mock.patch.object(server, "build_vista_aerea", return_value=None):
            pdf = server.build_workspace_budget_pdf(budget, WORKSPACE, EMPRESA, CLIENTE, lineas)
        return "\n".join((p.extract_text() or "") for p in PdfReader(BytesIO(pdf)).pages)

    TARIFA = [
        {"categoria": "Edificio", "concepto": "Viviendas", "cantidad": 28,
         "unidad": "vivienda", "precio_unitario": 5, "total_linea": 140},
        {"categoria": "Edificio", "concepto": "Aparcamientos", "cantidad": 44,
         "unidad": "plaza", "precio_unitario": 1, "total_linea": 44},
    ]

    def test_el_caso_real_de_astrea(self):
        texto = self.genera_con(140.0, 29.4, 169.4, self.TARIFA)
        self.assertIn("169,40", texto)
        self.assertNotIn("222,64", texto)

    def test_la_rebaja_se_enseña_no_se_disimula(self):
        texto = self.genera_con(140.0, 29.4, 169.4, self.TARIFA)
        self.assertIn("Ajuste comercial acordado", texto)
        self.assertIn("-44,00", texto)

    def test_un_suplemento_tambien_sale(self):
        texto = self.genera_con(200.0, 42.0, 242.0, self.TARIFA)
        self.assertIn("Suplemento acordado", texto)
        self.assertIn("242,00", texto)

    def test_sin_negociacion_no_aparece_ninguna_linea(self):
        """Lo normal es que coincidan: no hay que ensuciar el desglose."""
        texto = self.genera_con(184.0, 38.64, 222.64, self.TARIFA)
        self.assertNotIn("Ajuste comercial", texto)
        self.assertNotIn("Suplemento acordado", texto)
        self.assertIn("222,64", texto)

    def test_lo_puntual_no_se_confunde_con_una_rebaja(self):
        """El subtotal lleva dentro los trabajos de una sola vez: restarlos mal
        haría aparecer un «ajuste» que nadie ha pactado."""
        lineas = self.TARIFA + [{"categoria": "Servicios puntuales", "concepto": "Alta",
                                 "cantidad": 1, "unidad": "servicio",
                                 "precio_unitario": 350, "total_linea": 350}]
        texto = self.genera_con(534.0, 112.14, 646.14, lineas)
        self.assertNotIn("Ajuste comercial", texto)
        self.assertIn("222,64", texto)

    def test_un_subtotal_que_no_incluye_lo_puntual_no_inventa_un_descuento(self):
        """Casi siempre el subtotal lleva dentro los trabajos de una sola vez, pero
        no siempre. Restarlos a ciegas hacía aparecer un «ajuste» de -350 € que
        nadie había pactado: lo cazó un test que ya existía."""
        lineas = self.TARIFA + [{"categoria": "Servicios puntuales", "concepto": "Alta",
                                 "cantidad": 1, "unidad": "servicio",
                                 "precio_unitario": 350, "total_linea": 350}]
        texto = self.genera_con(184.0, 38.64, 222.64, lineas)
        self.assertNotIn("Ajuste comercial", texto)
        self.assertNotIn("-350,00", texto)
        self.assertIn("222,64", texto)

    def test_no_se_pinta_una_cuota_negativa(self):
        """Si las cifras guardadas no tienen sentido, mejor la tarifa que un
        importe en negativo en un documento que va al cliente."""
        lineas = self.TARIFA + [{"categoria": "Servicios puntuales", "concepto": "Alta",
                                 "cantidad": 1, "unidad": "servicio",
                                 "precio_unitario": 900, "total_linea": 900}]
        texto = self.genera_con(500.0, 105.0, 605.0, lineas)
        self.assertNotIn("-400", texto)

    def test_sin_subtotal_guardado_manda_la_tarifa(self):
        texto = self.genera_con(0, 0, 0, self.TARIFA)
        self.assertIn("184,00", texto)
