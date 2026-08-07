"""El censo de propietarios se puede llenar de verdad.

Al auditar el CRM de fincas el 2026-08-07, siete de sus ocho tablas estaban vacías en
producción. La que más pesa es `workspace_fincas_vecinos`: **cero filas**. Sin censo no
hay recibos, ni derramas, ni quórums, ni certificado de deuda; todo lo demás del módulo
descansa sobre él.

La pantalla existía. El problema era que solo dejaba dar de alta **de uno en uno**, y en
la comunidad más grande del workspace hay 177 viviendas y 373 plazas de garaje: nadie va
a teclear eso a mano. Por eso llevaba meses vacía.

Lo que se añade:

- **Pegar la lista entera** desde Excel. Se reconocen las columnas por su título y, si no
  hay título, se asume el orden con el que la gente escribe estas listas. Los pisos que ya
  existen se actualizan en vez de duplicarse: el propietario cambia, el piso no.
- **La suma de coeficientes a la vista.** Es el dato que decide si el censo sirve: si no
  da 100 %, cualquier reparto de derrama y cualquier votación por cuota van a salir mal, y
  más vale verlo aquí que descubrirlo repartiendo una obra.
- **Borrar**, que tampoco se podía.
"""

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
from web import server  # noqa: E402


class LeerUnCensoPegadoTests(unittest.TestCase):
    def test_pegado_de_excel_con_cabecera(self):
        filas = server.parse_censo_vecinos(
            "Piso\tPropietario\tNIF\tCoeficiente\n"
            "1A\tJuan Pérez\t12345678Z\t2,50\n"
            "1B\tAna Ruiz\t87654321X\t2,50"
        )
        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0]["nombre"], "Juan Pérez")
        self.assertEqual(filas[0]["piso"], "1A")
        self.assertEqual(filas[0]["coeficiente"], 2.5)

    def test_sin_cabecera_se_asume_el_orden_natural(self):
        filas = server.parse_censo_vecinos("1A\tJuan Pérez\t12345678Z\t2,50")
        self.assertEqual(filas[0]["piso"], "1A")
        self.assertEqual(filas[0]["nombre"], "Juan Pérez")

    def test_las_columnas_pueden_venir_en_cualquier_orden(self):
        filas = server.parse_censo_vecinos(
            "Nombre\tTeléfono\tPiso\tEmail\tCoef\nRosa Vega\t600111222\t3C\tr@x.es\t1,8"
        )
        self.assertEqual(filas[0]["piso"], "3C")
        self.assertEqual(filas[0]["telefono"], "600111222")
        self.assertEqual(filas[0]["coeficiente"], 1.8)

    def test_una_columna_titulada_solo_con_el_simbolo_de_porcentaje(self):
        """`normalize_lookup_text` se come los símbolos y «%» llegaba vacía."""
        filas = server.parse_censo_vecinos("Piso\tNombre\t%\nBajo A\tPepa Mora\t4.75 %")
        self.assertEqual(filas[0]["coeficiente"], 4.75)

    def test_admite_punto_y_coma(self):
        filas = server.parse_censo_vecinos("Piso;Nombre;Coeficiente\n2A;Luis Gil;3,10")
        self.assertEqual(filas[0]["nombre"], "Luis Gil")
        self.assertEqual(filas[0]["coeficiente"], 3.1)

    def test_una_coma_dentro_del_nombre_no_parte_la_fila(self):
        """«Pérez, Juan» es un apellido y un nombre, no dos columnas."""
        filas = server.parse_censo_vecinos("Piso\tNombre\n1A\tPérez, Juan")
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["nombre"], "Pérez, Juan")

    def test_las_filas_en_blanco_se_ignoran(self):
        filas = server.parse_censo_vecinos("Piso\tNombre\n\n1A\tJuan\n\n\n1B\tAna\n")
        self.assertEqual(len(filas), 2)

    def test_sin_texto_no_devuelve_nada(self):
        self.assertEqual(server.parse_censo_vecinos(""), [])
        self.assertEqual(server.parse_censo_vecinos(None), [])


class LosCoeficientesSeLeenBienTests(unittest.TestCase):
    def test_criterio_espanol(self):
        self.assertEqual(server.parse_coeficiente("2,50"), 2.5)
        self.assertEqual(server.parse_coeficiente("1.234,56"), 1234.56)

    def test_criterio_ingles_cuando_no_hay_coma(self):
        self.assertEqual(server.parse_coeficiente("4.75"), 4.75)

    def test_el_simbolo_de_porcentaje_no_estorba(self):
        self.assertEqual(server.parse_coeficiente("4,75 %"), 4.75)

    def test_lo_que_no_se_entiende_se_deja_vacio(self):
        """Un coeficiente inventado descuadra la comunidad entera."""
        self.assertIsNone(server.parse_coeficiente("abc"))
        self.assertIsNone(server.parse_coeficiente(""))
        self.assertIsNone(server.parse_coeficiente(None))


class LaSumaDeCoeficientesSeVeTests(unittest.TestCase):
    def test_existe_el_resumen(self):
        self.assertIn("def fetch_workspace_fincas_censo_resumen(", SERVER)

    def test_dice_si_cuadra_a_cien(self):
        i = SERVER.index("def fetch_workspace_fincas_censo_resumen")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn('"cuadra": abs(suma - 100.0) < 0.01', cuerpo)

    def test_cuenta_los_que_no_tienen_coeficiente(self):
        i = SERVER.index("def fetch_workspace_fincas_censo_resumen")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("sin_coeficiente", cuerpo)

    def test_el_get_lo_devuelve_siempre(self):
        """La pantalla lo necesita en cada carga, no en una llamada aparte."""
        i = SERVER.index('if path == "/api/workspace_fincas_vecinos"')
        self.assertIn('datos["resumen"] = fetch_workspace_fincas_censo_resumen', SERVER[i: i + 1400])

    def test_la_pantalla_avisa_cuando_no_cuadra(self):
        self.assertIn("no 100 %", APP)
        self.assertIn("censo-aviso", APP)

    def test_la_pantalla_compara_con_las_viviendas_declaradas(self):
        self.assertIn("viviendas_declaradas", APP)


class LaCargaMasivaEstaBienGuardadaTests(unittest.TestCase):
    def _manejador(self, ruta):
        i = SERVER.index(f'elif parsed.path == "{ruta}"')
        return SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]

    def test_las_dos_rutas_estan_dadas_de_alta(self):
        """Se busca dentro de la lista blanca entera, no en una ventana de caracteres:
        la primera versión miraba los 300 siguientes y se cayó sola al añadir rutas
        de juntas en medio, sin que nada estuviera roto."""
        i = SERVER.index("_POST_ALLOWED_PATHS") if "_POST_ALLOWED_PATHS" in SERVER else SERVER.index(
            '"/api/workspace_fincas_comunidades",'
        )
        lista = SERVER[i: SERVER.index("}", i) if "}" in SERVER[i: i + 20000] else i + 20000]
        for ruta in ("/api/workspace_fincas_vecinos_import", "/api/workspace_fincas_vecino_delete"):
            with self.subTest(ruta=ruta):
                self.assertIn(f'"{ruta}",', lista)

    def test_importar_exige_pertenencia_con_escritura(self):
        self.assertIn(
            "enforce_workspace_membership(conn, session, workspace_id, write=True)",
            self._manejador("/api/workspace_fincas_vecinos_import"),
        )

    def test_borrar_exige_pertenencia_con_escritura(self):
        cuerpo = self._manejador("/api/workspace_fincas_vecino_delete")
        self.assertIn("enforce_workspace_membership(conn, session, workspace_id, write=True)", cuerpo)
        self.assertLess(cuerpo.index("enforce_workspace_membership"), cuerpo.index("DELETE FROM"))

    def test_el_borrado_del_censo_solo_ocurre_si_se_pide(self):
        """Reemplazar borra: no puede pasar por accidente al importar."""
        cuerpo = self._manejador("/api/workspace_fincas_vecinos_import")
        i = cuerpo.index("DELETE FROM workspace_fincas_vecinos")
        self.assertIn('payload.get("reemplazar")', cuerpo[:i])

    def test_reimportar_no_duplica_los_pisos(self):
        cuerpo = self._manejador("/api/workspace_fincas_vecinos_import")
        self.assertIn("existentes", cuerpo)
        self.assertIn("UPDATE workspace_fincas_vecinos", cuerpo)

    def test_la_pantalla_pide_confirmacion_antes_de_reemplazar(self):
        self.assertIn("Se borrará el censo actual", APP)


if __name__ == "__main__":
    unittest.main()
