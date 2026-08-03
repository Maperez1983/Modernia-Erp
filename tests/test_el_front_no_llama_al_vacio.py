"""Botones que llaman a un endpoint que no existe.

El tablero de demandas (CRM inmobiliaria) tiene dos botones de acción masiva,
"Aceptar" y "Descartar", que mueven de fase los pedidos seleccionados. Llamaban a
`/api/demandas_update`, que nunca se implementó: el servidor mantiene una lista
blanca de rutas POST y todo lo que no está en ella responde

    {"error": "Endpoint no valido"}  404

así que el botón enseñaba una alerta y no movía nada. No hay forma de verlo
leyendo el front —la llamada está perfectamente escrita— ni leyendo el servidor,
que simplemente no la menciona.

El primer test compara ambos lados y no depende de este caso concreto.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
FRONT = ["app.js", "index.html", "app-routing.js", "app-auth.js", "ui-foundation.js", "app_shared.js"]


def texto_del_front():
    return "\n".join((RAIZ / "web" / n).read_text(encoding="utf-8") for n in FRONT)


class NingunEndpointLlamadoSeQuedaSinRutaTests(unittest.TestCase):
    def test_todo_lo_que_pide_el_front_existe_en_el_servidor(self):
        front = texto_del_front()
        servidor = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

        # Solo rutas literales y completas: las que se construyen con plantilla
        # (`/api/x_${y}`) o se comparan con startsWith no se pueden resolver aquí.
        pedidos = set()
        for cita, ruta in re.findall(r'(["\'`])(/api/[a-z0-9_]+)\1', front):
            pedidos.add(ruta)
        # Descartar los que el propio front usa como prefijo.
        prefijos = set(re.findall(r'startsWith\(\s*["\'`](/api/[a-z0-9_]+)', front))
        pedidos -= prefijos

        servidas = set(re.findall(r'["\'](/api/[a-z0-9_]+)["\']', servidor))

        huerfanos = sorted(p for p in pedidos if p not in servidas)
        self.assertEqual(
            huerfanos,
            [],
            "el front llama a endpoints que el servidor no declara:\n  " + "\n  ".join(huerfanos),
        )


class ElTableroDeDemandasPuedeMoverDeFaseTests(unittest.TestCase):
    def setUp(self):
        self.servidor = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

    def test_la_ruta_esta_en_la_lista_blanca_de_post(self):
        i = self.servidor.index("if parsed.path not in (")
        bloque = self.servidor[i: self.servidor.index('json_response(self, {"error": "Endpoint no valido"}', i)]
        self.assertIn('"/api/demandas_update"', bloque)

    def test_tiene_manejador(self):
        self.assertIn('elif parsed.path == "/api/demandas_update":', self.servidor)

    def _manejador(self):
        i = self.servidor.index('elif parsed.path == "/api/demandas_update":')
        return self.servidor[i: self.servidor.index("\n        elif parsed.path ==", i + 10)]

    def test_exige_permiso_de_escritura_en_el_workspace(self):
        self.assertIn("enforce_workspace_membership(conn, session, ws_id, write=True)", self._manejador())

    def test_no_toca_demandas_de_otro_ambito(self):
        """Llegan ids del cliente: sin filtro de ámbito se podría mover lo ajeno."""
        manejador = self._manejador()
        self.assertIn('build_service_scope_filter(', manejador)
        # El UPDATE solo alcanza los ids que el ámbito ha confirmado.
        self.assertIn("UPDATE demandas SET", manejador)
        self.assertIn("marcas_ok", manejador)

    def test_sabe_a_que_servicio_pertenece(self):
        i = self.servidor.index("path_service = {")
        bloque = self.servidor[i: self.servidor.index("}", i)]
        self.assertIn('"/api/demandas_update": "inmobiliaria"', bloque)


if __name__ == "__main__":
    unittest.main()
