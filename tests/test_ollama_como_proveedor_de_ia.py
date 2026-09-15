"""El sistema puede usar un Ollama propio en vez de OpenAI para todo lo que hoy es "IA".

Todas las funciones de IA del CRM (OCR de pólizas, extracción financiera, plantillas de
contrato, resúmenes, el copilot web...) pasan por dos funciones centrales:
`call_openai` y `call_openai_content`. En vez de tocar cada uno de los ~39 sitios que las
llaman, el interruptor vive ahí: con `AI_PROVIDER=ollama` ambas delegan en
`call_ollama`/`call_ollama_content`, que hablan con `/api/chat` de un servidor Ollama.

Con `AI_PROVIDER` en su valor por defecto ("openai") el comportamiento no cambia en nada
-- eso es lo que prueba `NoCambiaNadaPorDefectoTests`.
"""

import base64
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("POSTGRES_URL", "")

from web import server as S  # noqa: E402


class _OllamaFalso(BaseHTTPRequestHandler):
    respuesta = {"message": {"content": '{"tomador": "PRUEBA"}'}}
    peticiones = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).peticiones.append({"path": self.path, "json": json.loads(body or b"{}")})
        payload = json.dumps(type(self).respuesta).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


class ElProveedorOllamaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), _OllamaFalso)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        self._prev = {
            "AI_PROVIDER": S.AI_PROVIDER,
            "OLLAMA_BASE_URL": S.OLLAMA_BASE_URL,
            "OLLAMA_MODEL": S.OLLAMA_MODEL,
            "OLLAMA_VISION_MODEL": S.OLLAMA_VISION_MODEL,
        }
        S.AI_PROVIDER = "ollama"
        S.OLLAMA_BASE_URL = f"http://127.0.0.1:{self.port}"
        S.OLLAMA_MODEL = "modelo-texto-de-prueba"
        S.OLLAMA_VISION_MODEL = "modelo-vision-de-prueba"
        _OllamaFalso.peticiones = []

    def tearDown(self):
        S.AI_PROVIDER = self._prev["AI_PROVIDER"]
        S.OLLAMA_BASE_URL = self._prev["OLLAMA_BASE_URL"]
        S.OLLAMA_MODEL = self._prev["OLLAMA_MODEL"]
        S.OLLAMA_VISION_MODEL = self._prev["OLLAMA_VISION_MODEL"]

    def test_openai_available_no_exige_api_key_de_openai(self):
        """Con Ollama activo no hace falta OPENAI_API_KEY para que las funciones IA respondan."""
        prev = os.environ.pop("OPENAI_API_KEY", None)
        try:
            self.assertTrue(S.openai_available())
        finally:
            if prev is not None:
                os.environ["OPENAI_API_KEY"] = prev

    def test_call_openai_va_a_ollama_no_a_internet(self):
        texto, err = S.call_openai("di algo", temperature=0.1, max_tokens=50)
        self.assertEqual(err, "")
        self.assertEqual(texto, '{"tomador": "PRUEBA"}')
        self.assertEqual(len(_OllamaFalso.peticiones), 1)
        peticion = _OllamaFalso.peticiones[0]
        self.assertEqual(peticion["path"], "/api/chat")
        self.assertEqual(peticion["json"]["model"], "modelo-texto-de-prueba")
        self.assertFalse(peticion["json"]["stream"])

    def test_call_openai_extract_seguro_tambien_pasa_por_ollama(self):
        """La función que usa el OCR de pólizas no sabe ni le importa qué proveedor hay detrás."""
        campos, err = S.call_openai_extract_seguro("Tomador: PRUEBA\nNIF: 12345678Z")
        self.assertEqual(err, "")
        self.assertIn("PRUEBA", campos.get("tomador", ""))
        self.assertEqual(len(_OllamaFalso.peticiones), 1)

    def test_las_imagenes_se_traducen_al_formato_de_ollama(self):
        """El bloque input_image (Responses API de OpenAI) debe llegar como base64 plano
        en `images`, y sin texto/imagen debe usarse el modelo de visión, no el de texto."""
        imagen_fake = base64.b64encode(b"contenido-png-falso").decode()
        contenido = [
            {"type": "input_text", "text": "extrae los datos"},
            {"type": "input_image", "image_url": f"data:image/png;base64,{imagen_fake}"},
        ]
        texto, err = S.call_openai_content(contenido, temperature=0.0, max_tokens=50)
        self.assertEqual(err, "")
        self.assertEqual(len(_OllamaFalso.peticiones), 1)
        mensaje_usuario = _OllamaFalso.peticiones[0]["json"]["messages"][-1]
        self.assertEqual(mensaje_usuario["content"], "extrae los datos")
        self.assertEqual(mensaje_usuario["images"], [imagen_fake])
        self.assertEqual(_OllamaFalso.peticiones[0]["json"]["model"], "modelo-vision-de-prueba")

    def test_si_ollama_esta_apagado_no_revienta_da_un_error_claro(self):
        S.OLLAMA_BASE_URL = "http://127.0.0.1:1"  # nada escuchando ahí
        texto, err = S.call_openai("di algo")
        self.assertEqual(texto, "")
        self.assertIn("Ollama error", err)


class NoCambiaNadaPorDefectoTests(unittest.TestCase):
    """Con AI_PROVIDER sin configurar (o en "openai"), el comportamiento de siempre no cambia."""

    def test_ai_provider_por_defecto_es_openai(self):
        self.assertEqual(S.AI_PROVIDER, "openai")

    def test_sin_api_key_de_openai_sigue_fallando_igual_que_antes(self):
        prev = os.environ.pop("OPENAI_API_KEY", None)
        try:
            self.assertFalse(S.openai_available())
            texto, err = S.call_openai("di algo")
            self.assertEqual(texto, "")
            self.assertIn("OPENAI_API_KEY no configurada", err)
        finally:
            if prev is not None:
                os.environ["OPENAI_API_KEY"] = prev


if __name__ == "__main__":
    unittest.main()
