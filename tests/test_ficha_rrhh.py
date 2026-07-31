"""La ficha de RRHH vivía en dos tablas con los mismos conceptos duplicados.

`workspace_registro_personal` guarda identidad y jornada; `workspace_rrhh_profile`
guardaba además `tipo_contrato`, `fecha_inicio`, `fecha_fin` y `notas`, que ya
existían en la primera como `tipo_contrato`, `fecha_alta`, `fecha_baja` y `notas`.
Dos sitios donde editar lo mismo.

Medido en producción el 2026-07-31: de 21 fichas activas, el perfil estaba vacío
en TODAS (0 con puesto, departamento, centro, contrato o fechas) mientras la ficha
de personal sí tenía datos (contrato 11, fecha de alta 13, NIF 11, email 19). No
discrepaban solo porque un lado estaba sin usar; al rellenarlo habría dos verdades.

El aviso de contrato vencido dependía de `profile.fecha_fin`: se conserva, pero
leyendo `fecha_baja` de la ficha de personal, que es donde vive el contrato.
"""

import sqlite3
import unittest
from pathlib import Path

from web import server

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

SCHEMA = """
CREATE TABLE empresas (id TEXT PRIMARY KEY, nombre TEXT, nif TEXT, activo INTEGER DEFAULT 1);
CREATE TABLE workspaces (id TEXT PRIMARY KEY, nombre TEXT, slug TEXT, estado TEXT);
CREATE TABLE workspace_empresas (id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT, rol TEXT);
CREATE TABLE workspace_companies (workspace_id TEXT, legacy_empresa_id TEXT, activo INTEGER DEFAULT 1, nombre TEXT);
CREATE TABLE workspace_registro_personal (id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT, nombre TEXT,
  nif TEXT, fecha_alta TEXT, activo INTEGER DEFAULT 1, horas_pactadas_dia REAL);
CREATE TABLE workspace_rrhh_profile (id TEXT PRIMARY KEY, workspace_id TEXT, persona_id TEXT, puesto TEXT,
  departamento TEXT, centro_trabajo TEXT, vacaciones_dias_anuales REAL);
CREATE TABLE clientes (id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT, nombre TEXT);
CREATE TABLE clientes_empresas (id TEXT PRIMARY KEY, cliente_id TEXT, empresa_id TEXT, workspace_id TEXT, servicio TEXT);
"""
WS = "ws"


def _conn(*, nif="B1", alta="2024-01-01", perfil=True, vacaciones=22, puesto="Gestor", depto="Admin"):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.execute("INSERT INTO workspaces VALUES (?, 'W', 'w', 'Activo')", (WS,))
    c.execute("INSERT INTO empresas VALUES ('e1', 'E', 'B1', 1)")
    c.execute("INSERT INTO workspace_empresas VALUES ('l', ?, 'e1', 'operativa')", (WS,))
    c.execute("INSERT INTO workspace_registro_personal VALUES ('p1', ?, 'e1', 'Ana', ?, ?, 1, 8)", (WS, nif, alta))
    if perfil:
        c.execute("INSERT INTO workspace_rrhh_profile VALUES ('f1', ?, 'p1', ?, ?, 'Sede', ?)",
                  (WS, puesto, depto, vacaciones))
    c.commit()
    return c


def _claves(c):
    return {a["clave"] for a in server.fetch_workspace_setup_status(c, WS)}


class AvisosDeFichaIncompletaTests(unittest.TestCase):
    def test_ficha_completa_no_avisa_de_personal(self):
        c = _conn()
        self.assertEqual(_claves(c) & {"personal_sin_nif", "personal_sin_fecha_alta",
                                       "personal_sin_vacaciones", "personal_sin_puesto"}, set())
        c.close()

    def test_sin_nif(self):
        c = _conn(nif="")
        self.assertIn("personal_sin_nif", _claves(c))
        c.close()

    def test_sin_fecha_de_alta(self):
        c = _conn(alta="")
        self.assertIn("personal_sin_fecha_alta", _claves(c))
        c.close()

    def test_sin_dias_de_vacaciones_definidos(self):
        """22 por defecto está bien; que nadie lo haya confirmado, no."""
        c = _conn(perfil=False)
        self.assertIn("personal_sin_vacaciones", _claves(c))
        c.close()

    def test_con_vacaciones_puestas_no_avisa(self):
        c = _conn(vacaciones=25)
        self.assertNotIn("personal_sin_vacaciones", _claves(c))
        c.close()

    def test_con_departamento_puesto_no_avisa(self):
        c = _conn(puesto="")
        self.assertNotIn("personal_sin_puesto", _claves(c))
        c.close()

    def test_puesto_vacio_avisa_en_severidad_baja(self):
        # Es informativo: sirve para decidir si esos campos se usan o se quitan.
        # Basta con que ambos estén vacíos: si hay departamento, no avisa.
        c = _conn(puesto="", depto="")
        avisos = {a["clave"]: a for a in server.fetch_workspace_setup_status(c, WS)}
        self.assertIn("personal_sin_puesto", avisos)
        self.assertEqual(avisos["personal_sin_puesto"]["severidad"], "baja")
        c.close()

    def test_las_bajas_no_cuentan(self):
        c = _conn(nif="")
        c.execute("UPDATE workspace_registro_personal SET activo = 0")
        c.commit()
        self.assertNotIn("personal_sin_nif", _claves(c))
        c.close()


class SinCamposDuplicadosTests(unittest.TestCase):
    def _bloque_perfil(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_rrhh_profile":')
        return SERVER[i: SERVER.index("elif parsed.path ==", i + 100)]

    def test_el_perfil_ya_no_escribe_contrato_ni_fechas(self):
        b = self._bloque_perfil()
        for campo in ("tipo_contrato", "fecha_inicio", "fecha_fin"):
            with self.subTest(campo=campo):
                self.assertNotIn(f'payload.get("{campo}")', b,
                                 f"el perfil vuelve a escribir {campo}, duplicando la ficha de personal")

    def test_el_perfil_conserva_lo_suyo(self):
        b = self._bloque_perfil()
        for campo in ("puesto", "departamento", "centro_trabajo", "vacaciones_dias_anuales"):
            self.assertIn(campo, b)

    def test_el_formulario_no_pide_los_duplicados(self):
        i = APP.index('id="workspaceRrhhProfileForm"')
        form = APP[i: APP.index("Guardar ficha RRHH", i)]
        for campo in ('name="tipo_contrato"', 'name="fecha_inicio"', 'name="fecha_fin"', 'name="notas"'):
            with self.subTest(campo=campo):
                self.assertNotIn(campo, form)

    def test_el_aviso_de_contrato_vencido_sobrevive(self):
        """Estaba atado a profile.fecha_fin: al unificar, casi me lo llevo por delante."""
        i = APP.index('id="workspaceRrhhProfileForm"')
        form = APP[i: APP.index("Guardar ficha RRHH", i)]
        self.assertIn("Contrato vencido", form)
        self.assertIn("selectedEmployee?.fecha_baja", form)


if __name__ == "__main__":
    unittest.main()
