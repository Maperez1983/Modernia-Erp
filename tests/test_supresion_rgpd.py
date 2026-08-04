"""El derecho de supresión no tenía forma de ejercerse.

Auditado el 2026-08-04: no había endpoint, ni botón, ni guion. Ni un solo
`DELETE FROM clientes` en las 96.000 líneas del servidor. Las tablas
`clientes_borrados_backup` y `clientes_empresas_borrados_backup` existían pero
nadie escribía en ellas: eran restos de limpiezas hechas a mano.

Un derecho que la aplicación no sabe cumplir es un incumplimiento, no una carencia
de producto.

La decisión de diseño
---------------------
Suprimir NO es borrar la fila. El art. 17.3 b) y e) del RGPD permite —y la Ley
General Tributaria obliga— conservar lo que sostiene una obligación legal:
facturas, asientos, pólizas. Borrar la ficha rompería esos registros, que además
hay que guardar. Lo que desaparece es la identidad: quien mire esas filas después
no puede saber de quién eran.

Las dos listas (lo que se borra y lo que se conserva) están en el servidor, en
constantes con nombre, para que un asesor pueda leerlas y corregirlas sin bucear
en el código.
"""

import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")


def manejador():
    i = SERVER.index('elif parsed.path == "/api/cliente_suprimir":')
    return SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]


class LaPoliticaEstaEscritaTests(unittest.TestCase):
    def test_hay_lista_de_lo_que_se_borra(self):
        self.assertIn("RGPD_TABLAS_A_BORRAR = (", SERVER)

    def test_hay_lista_de_lo_que_se_conserva_y_por_que(self):
        self.assertIn("RGPD_TABLAS_QUE_SE_CONSERVAN = (", SERVER)
        # Cada tabla conservada lleva el motivo al lado; si no, nadie sabe por qué está.
        i = SERVER.index("RGPD_TABLAS_QUE_SE_CONSERVAN = (")
        bloque = SERVER[i: SERVER.index("\n)", i)]
        self.assertIn('("gestoria_facturas", "facturas emitidas")', bloque)
        self.assertIn('("hipotecas", "operaciones y comisiones")', bloque)

    def test_la_facturacion_no_se_borra(self):
        """Borrarla incumpliría la obligación de conservación, que va aparte."""
        i = SERVER.index("RGPD_TABLAS_A_BORRAR = (")
        a_borrar = SERVER[i: SERVER.index(")\n", i)]
        for tabla in ("gestoria_facturas", "gestoria_asientos", "gestoria_contabilidad", "hipotecas", "seguros"):
            with self.subTest(tabla=tabla):
                self.assertNotIn(f'("{tabla}"', a_borrar)


class ElEndpointTests(unittest.TestCase):
    def test_existe_y_esta_en_la_lista_blanca(self):
        self.assertIn('elif parsed.path == "/api/cliente_suprimir":', SERVER)
        i = SERVER.index("if parsed.path not in (")
        blanca = SERVER[i: SERVER.index('json_response(self, {"error": "Endpoint no valido"}', i)]
        self.assertIn('"/api/cliente_suprimir"', blanca)

    def test_exige_escritura_en_el_workspace(self):
        self.assertIn("enforce_workspace_membership(conn, session, ws_id, write=True)", manejador())

    def test_no_lo_hace_cualquiera(self):
        """Suprimir no es una edición más: hace falta ser responsable del workspace."""
        self.assertIn("workspace_actor_is_privileged(conn, session)", manejador())

    def test_no_se_puede_suprimir_una_ficha_de_otro_workspace(self):
        cuerpo = manejador()
        self.assertIn('clientes_workspace_scope_sql(conn, ws_id, alias="c")', cuerpo)
        self.assertIn("Cliente no encontrado en este workspace", cuerpo)

    def test_la_ficha_deja_de_identificar_pero_no_se_borra(self):
        cuerpo = manejador()
        self.assertIn("UPDATE clientes SET", cuerpo)
        self.assertNotIn("DELETE FROM clientes ", cuerpo)
        self.assertIn("Cliente suprimido", cuerpo)

    def test_vacia_todas_las_columnas_identificativas(self):
        cuerpo = manejador()
        self.assertIn("RGPD_COLUMNAS_IDENTIFICATIVAS", cuerpo)
        i = SERVER.index("RGPD_COLUMNAS_IDENTIFICATIVAS = (")
        bloque = SERVER[i: SERVER.index(")\n", i)]
        for columna in ("nif", "telefono", "movil", "email", "direccion", "fecha_nacimiento"):
            with self.subTest(columna=columna):
                self.assertIn(f'"{columna}"', bloque)

    def test_queda_constancia_de_quien_y_cuando(self):
        """El registro de la supresión es lo que demuestra que se atendió."""
        cuerpo = manejador()
        self.assertIn('"supresion_rgpd"', cuerpo)
        self.assertIn("audit_event(", cuerpo)

    def test_devuelve_que_se_borro_y_que_se_conservo(self):
        """Quien atiende la solicitud tiene que poder contestar al interesado."""
        cuerpo = manejador()
        self.assertIn('"borrado": borrados', cuerpo)
        self.assertIn('"conservado": conservados', cuerpo)


class LaPantallaTests(unittest.TestCase):
    def test_hay_boton_en_la_ficha(self):
        self.assertIn('id="clienteSuprimirBtn"', HTML)

    def test_no_basta_con_aceptar_un_aviso(self):
        """Sin vuelta atrás: hay que escribir la palabra."""
        i = APP.index("clienteSuprimirBtn")
        bloque = APP[i:]
        self.assertIn('!== "SUPRIMIR"', bloque)

    def test_el_aviso_dice_lo_que_se_conserva(self):
        i = APP.index("clienteSuprimirBtn")
        bloque = APP[i: i + 2500]
        self.assertIn("Se conservan facturas", bloque)
        self.assertIn("no se puede deshacer", bloque)

    def test_pide_motivo(self):
        i = APP.index("clienteSuprimirBtn")
        self.assertIn("Motivo (queda registrado", APP[i:])


if __name__ == "__main__":
    unittest.main()
