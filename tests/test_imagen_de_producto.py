"""Lo que ve el cliente: el correo de firma, el anuncio del portal y el acceso.

El CRM tenía la cadena rota justo donde la ve alguien de fuera. Los PDF se generan
vectoriales, con IBM Plex y cabecera de marca; pero el correo que llega antes que el
PDF eran cuatro `<p>` y un enlace azul del navegador, sin logo ni nombre de la
agencia. Y el anuncio publicado en el portal Verifika2 hablaba de «información
contrastada desde el CRM inmobiliario» y ofrecía «seguimiento con trazabilidad»:
palabras que le importan a quien contrata el software y a nadie más.

Se arreglan tres cosas y se atan aquí:

*   **El correo de firma** lleva la marca de la agencia que lo manda, un botón de
    verdad y el aviso de a quién avisar si no esperabas la solicitud. Escrito con
    tablas y estilos en línea a propósito: Outlook ignora hojas de estilo, `flex` y
    `grid`, y lo que aguanta en todos los clientes es esto.
*   **El código OTP deja de viajar en el mismo correo que el enlace** cuando hay SMS
    o WhatsApp configurado. Los dos factores en el mismo mensaje son un solo factor:
    si el buzón se compromete o alguien reenvía el correo, van juntos.
*   **El anuncio habla del inmueble**, con tildes, y sin colar la etapa del
    expediente. Salía publicado un «estado encargo» que no significa nada para quien
    busca casa.

De paso apareció un fallo que llevaba ahí desde el principio: `op_label` comparaba
la salida de `normalize_lookup_text` —que devuelve MAYÚSCULAS— contra minúsculas, así
que **todos** los anuncios se generaban como venta, también los alquileres.
"""

import os
import re
import unittest
from pathlib import Path

os.environ["DATABASE_URL"] = ""

from web import server as S  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
INDEX = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
CSS = (RAIZ / "web" / "styles.css").read_text(encoding="utf-8")


class ElCorreoDeFirmaLlevaLaMarcaTests(unittest.TestCase):
    def correo(self, **kwargs):
        base = dict(agencia="Estudio Velazquez 2012 SL", logo="", firmante="María Ruiz",
                    documento="Hoja de encargo", enlace="https://crm.verifika2.com/#firma_inmo=t")
        base.update(kwargs)
        return S.correo_de_firma_html(**base)

    def test_dice_de_quien_es(self):
        """Quien firma tiene que reconocer al remitente antes de pinchar nada."""
        self.assertIn("Estudio Velazquez 2012 SL", self.correo())

    def test_usa_el_logo_de_la_agencia_si_lo_hay(self):
        html = self.correo(logo="https://crm.verifika2.com/uploads/logo.png")
        self.assertIn('<img src="https://crm.verifika2.com/uploads/logo.png"', html)

    def test_sin_logo_pone_el_nombre_y_no_un_hueco(self):
        self.assertNotIn("<img", self.correo(logo=""))

    def test_el_enlace_tambien_va_en_texto(self):
        """Si el botón no tira —correo en texto plano, cliente raro—, queda la URL."""
        html = self.correo()
        self.assertEqual(html.count("https://crm.verifika2.com/#firma_inmo=t"), 2)

    def test_esta_escrito_para_clientes_de_correo(self):
        html = self.correo()
        self.assertIn("<table", html)
        for prohibido in ("display:flex", "display:grid", "<style"):
            self.assertNotIn(prohibido, html, f"{prohibido} no sobrevive a Outlook")

    def test_escapa_lo_que_viene_de_la_base(self):
        html = self.correo(firmante='<script>alert(1)</script>', documento='a"b')
        self.assertNotIn("<script>", html)

    def test_dice_que_hacer_si_no_lo_esperabas(self):
        self.assertIn("Si no esperabas esta solicitud", self.correo())


class ElOtpNoViajaConElEnlaceTests(unittest.TestCase):
    def setUp(self):
        self._previo = {
            k: os.environ.get(k)
            for k in ("SIGNATURE_SMS_WEBHOOK_URL", "SIGNATURE_WHATSAPP_WEBHOOK_URL")
        }
        for k in self._previo:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._previo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_sin_otro_canal_no_hay_canal_aparte(self):
        self.assertFalse(S.hay_canal_aparte_para_el_otp())

    def test_con_sms_si_lo_hay(self):
        os.environ["SIGNATURE_SMS_WEBHOOK_URL"] = "https://sms.example/webhook"
        self.assertTrue(S.hay_canal_aparte_para_el_otp())

    def test_con_whatsapp_tambien(self):
        os.environ["SIGNATURE_WHATSAPP_WEBHOOK_URL"] = "https://wa.example/webhook"
        self.assertTrue(S.hay_canal_aparte_para_el_otp())

    def test_el_correo_puede_llevar_el_codigo_si_no_hay_otra_via(self):
        """Sin SMS, quitarlo del correo dejaría la firma imposible de completar."""
        html = S.correo_de_firma_html(
            agencia="A", logo="", firmante="B", documento="C", enlace="https://x/", otp="482913")
        self.assertIn("482913", html)


class ElAnuncioHablaDelInmuebleTests(unittest.TestCase):
    PISO = {"tipo_inmueble": "Piso", "subtipologia": "ÁTICO", "zona": "Centro",
            "poblacion": "Málaga", "m2": 92, "habitaciones": 3, "banos": 2,
            "estado": "Encargo", "estado_inmueble": "Reformado"}

    def copy(self, **extra):
        datos = dict(self.PISO)
        datos.update(extra)
        return S.build_inmueble_anuncio_copy(datos)

    def test_no_habla_del_crm(self):
        texto = " ".join(str(v) for v in self.copy(tipo_operacion="venta").values()).lower()
        for jerga in ("crm", "trazabilidad", "verifika2 presenta", "información contrastada"):
            self.assertNotIn(jerga, texto, f"«{jerga}» no le dice nada a quien busca casa")

    def test_no_publica_la_etapa_del_expediente(self):
        """«Encargo» es vocabulario interno: salía publicado un «estado encargo»."""
        texto = " ".join(str(v) for v in self.copy(tipo_operacion="venta").values()).lower()
        self.assertNotIn("encargo", texto)

    def test_conserva_el_estado_de_conservacion(self):
        texto = " ".join(str(v) for v in self.copy(tipo_operacion="venta").values()).lower()
        self.assertIn("reformado", texto)

    def test_un_alquiler_no_se_anuncia_como_venta(self):
        """El fallo de fondo: la comparación era contra minúsculas y nunca acertaba."""
        for operacion in ("alquiler", "ALQUILER", "Arrendamiento", "renta"):
            with self.subTest(operacion=operacion):
                larga = self.copy(tipo_operacion=operacion)["descripcion_larga"]
                self.assertTrue(larga.startswith("Se alquila"), larga[:60])

    def test_una_venta_sigue_siendo_una_venta(self):
        for operacion in ("venta", "VENTA", "", "compraventa"):
            with self.subTest(operacion=operacion):
                larga = self.copy(tipo_operacion=operacion)["descripcion_larga"]
                self.assertTrue(larga.startswith("Se vende"), larga[:60])

    def test_lleva_las_tildes(self):
        c = self.copy(tipo_operacion="venta")
        texto = " ".join(str(v) for v in c.values())
        self.assertIn("m²", texto)
        self.assertIn("baños", texto)
        for sin_tilde in ("operacion", "informacion", "banos", " mas "):
            self.assertNotIn(sin_tilde, texto.lower())

    def test_la_ubicacion_no_repite_la_preposicion(self):
        """Salía «en San Andrés en Málaga»."""
        self.assertNotIn(" en Centro en Málaga", self.copy(tipo_operacion="venta")["titulo_anuncio"])

    def test_el_tipo_va_delante_del_subtipo(self):
        """«ÁTICO Piso» se lee como un error de plantilla."""
        self.assertTrue(self.copy(tipo_operacion="venta")["titulo_anuncio"].startswith("Piso ático"))


class LaPantallaDeAccesoTests(unittest.TestCase):
    def test_no_hay_insignias_de_marketing(self):
        """Publicidad dirigida a quien ya compró el producto y sólo quiere entrar.

        Se mira el marcado, no el texto: el comentario que explica por qué se
        quitaron menciona las insignias, y buscar la frase suelta lo daría por malo.
        """
        bloque = INDEX[INDEX.index('id="authLoginOverlay"'):][:2600]
        sin_comentarios = re.sub(r"<!--.*?-->", "", bloque, flags=re.S)
        self.assertNotIn("auth-brand-badge", sin_comentarios)

    def test_la_recuperacion_se_ve_sin_tener_que_fallar_antes(self):
        self.assertIn('id="authForgotLink"', INDEX)
        self.assertIn("¿Has olvidado la contraseña?", INDEX)

    def test_la_recuperacion_reutiliza_el_camino_que_ya_habia(self):
        """Duplicar la llamada sería tener dos flujos que se separan con el tiempo."""
        i = INDEX.index('const forgot = document.getElementById("authForgotLink")')
        bloque = INDEX[i:i + 700]
        self.assertIn("showRecoveryButton(login)", bloque)
        self.assertNotIn("auth_request_access_recovery", bloque)

    def test_pide_el_usuario_antes_de_intentar_recuperar(self):
        i = INDEX.index('const forgot = document.getElementById("authForgotLink")')
        self.assertIn("Escribe tu usuario o email", INDEX[i:i + 700])

    def test_el_boton_de_entrar_pesa_como_los_campos(self):
        i = CSS.index(".auth-login-actions {")
        bloque = CSS[i:i + 900]
        self.assertIn("flex-direction: column", bloque)
        self.assertIn("width: 100%", bloque)


class ElDominioPublicoSeVeTests(unittest.TestCase):
    def test_build_info_dice_de_donde_salen_los_enlaces(self):
        servidor = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
        i = servidor.index('"build_tag": "workspace_boot_v1"')
        bloque = servidor[i - 1200:i + 1200]
        self.assertIn('"public_base_url"', bloque)
        self.assertIn('"public_base_url_configurada"', bloque)


if __name__ == "__main__":
    unittest.main()
