"""Tres pólizas reales, subidas por el OCR, que el lector leía mal.

Cada una rompía por un motivo distinto — no es una única regresión, son tres huecos
del lector con documentos de formato distinto al que ya tenía parche:

**Zurich "Motor GO!" (auto)**: el ramo salía "Responsabilidad civil" en una póliza de
coche porque el patrón `Ramo\\s*[:\\-]?\\s*(...)` no exige palabra completa y hacía
match dentro de «Te lo repaRAMOs» (una garantía de asistencia), capturando la «s»
suelta que seguía — y esa «s» es alias de RC en `canonicalize_ramo`. El email y la
dirección salían los de la correduría («Datos de tu mediador», que va ANTES que
«Datos del titular» en el documento a doble columna) porque ninguno de los dos
patrones tenía forma de saltarse ese bloque. Y como el documento no dice "prima
neta"/"prima total" en ningún sitio (usa "Precio X € / 1er recibo Y € / Resto
recibos Z €"), el importe total y el de la última cuota se colaban como si fueran
neta y total.

**iptiQ/Gallen (impago de alquiler)**: el tomador salía vacío. La etiqueta del
documento es «Nombre/Razon Social:» — con barra, no con dos puntos — y aparece CUATRO
veces (mediador, tomador, asegurado vacío, beneficiario vacío); ningún patrón
reconocía esa forma.

**Santa Lucía "SegurComunidad"**: es una póliza de 70 páginas con un índice delante.
El número de póliza salía "BASESDELCONTRATO25" — texto de una entrada del ÍNDICE
("Artículo Preliminar - Bases del contrato ....... 25"), porque el patrón específico
de Santa Lucía Hogar no admite el punto de millares de "145.991" y por eso nunca
llegaba a machear, dejando en pie el número que había cogido antes un atajo genérico
de última instancia. Las fechas salían vacías/basura porque el patrón exige "DIA"
sin tilde y el documento, como todo documento real en español, la lleva ("DEL DÍA 4
de septiembre de 2026"). Y el CIF salía mal (o el de otra entidad del documento)
porque la etiqueta aquí es "C.I.F." con puntos, no "NIF" — encima el tomador se
guardaba con el CIF pegado detrás («...Barceló 4     C.I.F. H29446622»), y al
cortarlo, la limpieza general de tomadores (`limpia_tomador`) se comía también el
"4" del final: un número no tiene mayúsculas ni minúsculas, así que caía en la misma
regla pensada para restos de OCR como «up»/«oD»/«pl» — y una comunidad de
propietarios termina legítimamente en su número de portal.
"""

import os
import unittest

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("POSTGRES_URL", "")

from web.server import parse_poliza_text  # noqa: E402


class ZurichMotorGoTests(unittest.TestCase):
    TEXTO = """
PÓLIZA
Nº de póliza: 00000168401412
Vigencia (peninsular): desde el día 11/09/2026 a las 00:00 h hasta el día 10/09/2027 a las 24:00 h
Producto: Motor GO!
Tipo: A terceros ampliado
Duración: Anual renovable
Precio: 465,41 € Pago semestral / 1er recibo: 284,51 € / Resto recibos: 180,90 €

¿Qué estamos asegurando?                                           Datos de tu mediador
Marca, modelo y versión: Peugeot 308 Sportium 1.6 Hdi 92
Matrícula: 7566HCK                                                     Fincas Velazquez, S.L.U.
                                                                        Teléfono: 951 394 365
                                                                        E-mail: miguelangelperez@grupomodernia.es
                                                                        Dirección: Calle Ildefonso Marzo, 18, Loc, 29003,
                                                                        Malaga, Malaga

¿Quién es el titular de esta póliza?                               Datos del conductor
Datos del titular: Alejandro Jose Sanchez Celis
Dirección: Calle Misterio de Elche, 15, -                              Datos del 1er conductor: Alejandro Jose Sanchez Celis
C.P.: 28300                                                            NIF/CIF: 51.229.709-S
Población: Aranjuez
Provincia: Madrid
Teléfono: 684319782
E-mail: albatefy1@gmail.com

Garantías incluidas:
   • Asistencia en viaje 24h. Te lo reparamos en el lugar de la avería siempre que sea posible.
 Responsabilidad civil obligatoria
 Responsabilidad civil voluntaria                                   50.000.000 €
"""

    def test_el_ramo_es_auto_no_responsabilidad_civil(self):
        """"Ramo" también aparecía dentro de "repARAMOs" y se colaba como "RC"."""
        fields = parse_poliza_text(self.TEXTO)
        self.assertEqual(fields.get("ramo"), "Auto")

    def test_el_email_es_el_del_titular_no_el_del_mediador(self):
        fields = parse_poliza_text(self.TEXTO)
        self.assertEqual(fields.get("email"), "albatefy1@gmail.com")

    def test_el_telefono_es_el_del_titular_no_el_del_mediador(self):
        fields = parse_poliza_text(self.TEXTO)
        self.assertEqual(fields.get("telefono"), "684319782")

    def test_sin_prima_neta_ni_total_etiquetadas_no_se_inventa_una_neta(self):
        """"Precio/1er recibo/Resto recibos" no es neta+total: mejor un hueco."""
        fields = parse_poliza_text(self.TEXTO)
        self.assertEqual(fields.get("prima_neta"), "")
        self.assertEqual(fields.get("prima_total"), "465,41")


class GallenImpagoTests(unittest.TestCase):
    TEXTO = """
CONDICIONESPARTICULARES

Poliza N°: GAG13246

Mediador

Nombre/Razon Social: FINCAS VELAZQUEZ.SL

Tomador del Seguro/Asegurado

Nombre/Razon Social: VAZQUEZ CABRERA, DOLORES

DNI/CIF: 02693015-Z

Asegurado

Nombre/Razon Social:

DNI/CIF:

Beneficiario

Nombre/Razon Social:
"""

    def test_encuentra_el_tomador_con_la_etiqueta_con_barra(self):
        """"Nombre/Razon Social:" aparece 4 veces; ninguna es un ":" a secas."""
        fields = parse_poliza_text(self.TEXTO)
        self.assertEqual(fields.get("tomador"), "VAZQUEZ CABRERA, DOLORES")

    def test_no_confunde_con_las_otras_tres_apariciones_de_la_etiqueta(self):
        fields = parse_poliza_text(self.TEXTO)
        self.assertNotIn("FINCAS VELAZQUEZ", (fields.get("tomador") or "").upper())


class SantaLuciaSegurComunidadTests(unittest.TestCase):
    TEXTO = """
Seguro de Comunidades
ÍNDICE
CONDICIONES PARTICULARES
Artículo Preliminar - Bases del contrato ____________________________25
Artículo 1 - Definiciones ________________________________________25

CONDICIONES PARTICULARES DEL CONTRATO
ASEGURADOR: SANTA LUCÍA, S.A., Compañía de Seguros y Reaseguros
MEDIADOR: FINCAS VELAZQUEZ, S.L.
PÓLIZA NÚMERO      145.991
                   SEGURO SEGURCOMUNIDAD HOGAR
                     DATOS DEL TOMADOR DEL SEGURO
TOMADOR:               Comunidad de Propietarios Barceló 4     C.I.F. H29446622

                            DURACIÓN DEL SEGURO
DESDE LAS 00:00 HORAS DEL DÍA 4 de septiembre de 2026
HASTA LAS 00:00 HORAS DEL DÍA 4 de septiembre de 2027
       IMPORTE DE LA PRIMA DE LA PRIMERA ANUALIDAD EN EUROS
PRIMA TARIFA:                             1.971,97
PRIMA TOTAL:                              2.480,30
"""

    def test_el_numero_de_poliza_no_es_texto_del_indice(self):
        """El índice trae "Bases del contrato ....... 25"; el número real es 145.991."""
        fields = parse_poliza_text(self.TEXTO)
        self.assertNotIn("CONTRATO", (fields.get("poliza_numero") or "").upper())
        self.assertIn("145991", (fields.get("poliza_numero") or "").replace(".", ""))

    def test_la_fecha_de_efecto_se_lee_con_dia_acentuado(self):
        fields = parse_poliza_text(self.TEXTO)
        self.assertEqual(fields.get("fecha_efecto"), "04/09/2026")

    def test_la_fecha_de_vencimiento_se_lee_con_dia_acentuado(self):
        fields = parse_poliza_text(self.TEXTO)
        self.assertEqual(fields.get("fecha_vencimiento"), "04/09/2027")

    def test_el_cif_es_el_de_la_comunidad_no_otro_del_documento(self):
        """La etiqueta es "C.I.F." con puntos, no "NIF": ningún patrón la veía."""
        fields = parse_poliza_text(self.TEXTO)
        self.assertEqual(fields.get("dni"), "H29446622")
        self.assertEqual(fields.get("nif"), "H29446622")

    def test_el_tomador_no_lleva_el_cif_pegado(self):
        fields = parse_poliza_text(self.TEXTO)
        self.assertNotIn("H29446622", fields.get("tomador") or "")

    def test_el_tomador_conserva_el_numero_de_portal(self):
        """"4" al final es el portal del edificio, no un resto de OCR como "up"/"pl"."""
        fields = parse_poliza_text(self.TEXTO)
        self.assertEqual(fields.get("tomador"), "Comunidad de Propietarios Barceló 4")


if __name__ == "__main__":
    unittest.main()
