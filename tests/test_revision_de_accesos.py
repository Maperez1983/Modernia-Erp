"""La pestaña de Permisos enseñaba una segmentación que no existía.

Mostraba cinco perfiles graduados —Dirección 14 módulos, Operaciones 9, Comercial
7, Backoffice 8, RRHH 4— con la letra pequeña "vista informativa". Nada del
sistema usa esos perfiles: el acceso lo deciden el rol del usuario y los módulos
activos del workspace.

Medido en producción el 2026-07-31: los 6 usuarios activos eran `Administrador`,
o sea, ninguno tenía el acceso limitado a nada — nóminas, contabilidad y datos
personales incluidos. Quien mirara esa pantalla se quedaba tranquilo.

Ahora se enseña primero el estado real y la matriz queda marcada como referencia.
"""

import sqlite3
import unittest
from pathlib import Path

from web import server

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")

SCHEMA = """
CREATE TABLE workspace_miembros (id TEXT PRIMARY KEY, workspace_id TEXT, usuario_id TEXT, rol TEXT);
CREATE TABLE usuarios (id TEXT PRIMARY KEY, usuario TEXT, nombre TEXT, rol TEXT, servicio TEXT, activo INTEGER DEFAULT 1);
"""
WS = "ws1"


def _conn(usuarios):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    for i, (nombre, rol_ws, rol_u, servicio, activo) in enumerate(usuarios):
        uid = f"u{i}"
        if activo is not None:
            c.execute("INSERT INTO usuarios VALUES (?,?,?,?,?,?)", (uid, nombre.lower(), nombre, rol_u, servicio, activo))
        c.execute("INSERT INTO workspace_miembros VALUES (?,?,?,?)", (f"m{i}", WS, uid, rol_ws))
    c.commit()
    return c


class ReglaDeAccesoTests(unittest.TestCase):
    """La regla se sacó del handler para que informe y realidad no discrepen."""

    def test_administrador_ve_todo(self):
        self.assertIsNone(server.allowed_services_for("Administrador", ""))

    def test_servicio_administracion_tambien_abre_todo(self):
        # Atajo poco evidente: el servicio, no solo el rol, concede acceso total.
        self.assertIsNone(server.allowed_services_for("gestor", "Administración"))

    def test_un_servicio_concreto_limita(self):
        self.assertEqual(server.allowed_services_for("gestor", "Seguros"), {"seguros"})

    def test_financiaciones_e_hipotecas_van_juntas(self):
        self.assertEqual(server.allowed_services_for("gestor", "Financiaciones"), {"financiaciones", "hipotecas"})

    def test_sin_rol_ni_servicio_no_ve_nada(self):
        self.assertEqual(server.allowed_services_for("", ""), set())

    def test_el_handler_usa_la_misma_regla(self):
        i = SERVER.index("def _auth_allowed_services")
        bloque = SERVER[i : SERVER.index("def _service_from_tabla", i)]
        self.assertIn("allowed_services_for(", bloque)
        # Y ya no reimplementa la lista de roles por su cuenta.
        self.assertNotIn('"administrador", "admin", "direccion"', bloque)


class RevisionDeAccesosTests(unittest.TestCase):
    def test_avisa_cuando_todos_ven_todo(self):
        c = _conn([("Ana", "Owner", "Administrador", "", 1), ("Luis", "Miembro", "Administrador", "", 1)])
        r = server.fetch_workspace_access_review(c, WS)
        self.assertEqual(r["sin_restriccion_total"], 2)
        self.assertIn("todos_sin_restriccion", [a["clave"] for a in r["avisos"]])
        self.assertEqual([a["severidad"] for a in r["avisos"] if a["clave"] == "todos_sin_restriccion"], ["alta"])
        c.close()

    def test_no_avisa_si_hay_segmentacion_real(self):
        c = _conn([("Ana", "Owner", "Administrador", "", 1), ("Luis", "Miembro", "gestor", "Seguros", 1)])
        r = server.fetch_workspace_access_review(c, WS)
        claves = [a["clave"] for a in r["avisos"]]
        self.assertNotIn("todos_sin_restriccion", claves)
        self.assertIn("algunos_sin_restriccion", claves)
        c.close()

    def test_detecta_pertenencias_sin_cuenta(self):
        c = _conn([("Ana", "Owner", "Administrador", "", 1),
                   ("Fantasma", "Miembro", "", "", None),
                   ("Baja", "Miembro", "gestor", "Seguros", 0)])
        r = server.fetch_workspace_access_review(c, WS)
        self.assertEqual(len(r["huerfanos"]), 2)
        self.assertEqual({h["motivo"] for h in r["huerfanos"]}, {"cuenta inexistente", "cuenta desactivada"})
        # Y no cuentan como miembros activos.
        self.assertEqual(r["miembros_total"], 1)
        c.close()

    def test_dice_quien_puede_escribir(self):
        c = _conn([("Ana", "Owner", "gestor", "Seguros", 1), ("Luis", "Consultor", "gestor", "Seguros", 1)])
        r = server.fetch_workspace_access_review(c, WS)
        escriben = {m["nombre"]: m["escribe"] for m in r["miembros"]}
        self.assertTrue(escriben["Ana"])
        self.assertFalse(escriben["Luis"], "un rol no reconocido no debería poder escribir")
        c.close()

    def test_sin_workspace_no_devuelve_nada(self):
        c = _conn([("Ana", "Owner", "Administrador", "", 1)])
        self.assertEqual(server.fetch_workspace_access_review(c, ""), {})
        c.close()


class PantallaDeAccesosTests(unittest.TestCase):
    def test_el_estado_real_va_antes_que_la_recomendacion(self):
        i_real = INDEX.index('id="workspaceAccessReview"')
        i_matriz = INDEX.index('id="workspacePermissionMatrix"')
        self.assertLess(i_real, i_matriz, "la recomendación no puede encabezar la pantalla")

    def test_la_matriz_se_declara_como_referencia(self):
        i = APP.index("const renderWorkspacePermissionMatrix")
        bloque = APP[i : i + 2000]
        self.assertIn("referencia", bloque)
        self.assertIn("NO aplica", bloque)

    def test_el_endpoint_es_solo_para_gestores(self):
        i = SERVER.index('if path == "/api/workspace_access_review":')
        bloque = SERVER[i : SERVER.index("if path ==", i + 100)]
        self.assertIn("workspace_actor_can_manage_workspace", bloque)
        self.assertIn("status=403", bloque)


if __name__ == "__main__":
    unittest.main()
