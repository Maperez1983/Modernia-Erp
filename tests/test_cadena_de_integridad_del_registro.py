"""La cadena del registro horario decía «rota» sobre datos intactos.

Comprobado contra producción el 10-08-2026: `verify_workspace_registro_audit_chain`
daba cadena rota en los tres workspaces, y sin embargo **las 240 líneas firmadas
cuadraban todas contra su propio `prev_hash`**. No había manipulación ninguna.

Fallaba la verificación, por dos motivos:

1. Recorría con `ORDER BY created_at ASC` esperando reproducir el encadenamiento.
   Al escribir se buscaba la anterior con `created_at DESC`, y `created_at` es texto
   con tres formatos mezclados —ISO con T, `YYYY-MM-DD HH:MM:SS` y el literal `now`—,
   que no ordenan igual. Quedaron 15 líneas diciendo ser la primera de la cadena.
2. Metía en el mismo recorrido las 426 líneas anteriores a que la cadena existiera,
   que no tienen hash. Se rompía en la primera.

Una alarma que salta siempre no vigila nada, y en algo con valor legal eso es peor
que no tenerla. Ahora se comprueba lo que la cadena prueba de verdad —que el hash de
cada línea cuadre con su contenido, y que nadie apunte a una línea que ya no está—
sin depender de ningún orden por fecha, y la punta se busca por los enlaces.

Este fichero cubre lo que fallaba y, sobre todo, que se siga detectando lo que hay
que detectar: tocar una línea y borrar una de en medio.
"""

import hashlib
import json
import os
import sqlite3
import unittest

os.environ.setdefault("DATABASE_URL", "")

from web import server as S  # noqa: E402
from web.server import (  # noqa: E402
    log_workspace_registro_audit,
    verify_workspace_registro_audit_chain,
    workspace_registro_audit_chain_payload,
)

WS = "ws-1"

ESQUEMA = """
CREATE TABLE workspace_registro_audit (
  id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT, persona_id TEXT,
  entity_type TEXT, entity_id TEXT, action TEXT, actor_user_id TEXT, actor_nombre TEXT,
  before_json TEXT, after_json TEXT, created_at TEXT, prev_hash TEXT, integrity_hash TEXT
);
"""


class BaseCadena(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(ESQUEMA)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _linea(self, i, cuando):
        log_workspace_registro_audit(
            self.conn, WS, persona_id="p1", entity_type="fichaje", entity_id=f"f{i}",
            action="checkin", actor={"user_id": "u1", "usuario": "admin"},
            before=None, after={"x": i}, now=cuando)
        self.conn.commit()

    def _sin_firmar(self, i, cuando):
        """Una línea como las que había antes de que existiera la cadena."""
        self.conn.execute(
            "INSERT INTO workspace_registro_audit (id, workspace_id, entity_id, created_at) VALUES (?,?,?,?)",
            (f"vieja{i}", WS, f"v{i}", cuando))
        self.conn.commit()

    def _verifica(self):
        return verify_workspace_registro_audit_chain(self.conn, WS)


class LoQueFallabaTests(BaseCadena):
    def test_con_las_fechas_desordenadas_la_cadena_sigue_valiendo(self):
        """El caso de producción: el orden por fecha no es el orden de escritura."""
        for i, cuando in enumerate(("2026-07-29T10:05:00", "2026-07-29 10:01:00", "now"), 1):
            self._linea(i, cuando)
        r = self._verifica()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["checked"], 3)

    def test_las_lineas_anteriores_a_la_cadena_no_son_un_error(self):
        """426 líneas de producción no tienen hash: son de antes, no manipulación."""
        for i in range(4):
            self._sin_firmar(i, "2026-01-01 08:00:00")
        for i in range(1, 4):
            self._linea(i, f"2026-07-29 10:0{i}:00")
        r = self._verifica()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["sin_firmar"], 4)
        self.assertEqual(r["checked"], 3)
        self.assertEqual(r["total"], 7)

    def test_una_linea_sin_firmar_por_medio_no_parte_la_cadena(self):
        """Era lo que hacía empezar de cero: la «anterior» salía sin hash."""
        self._linea(1, "2026-07-29 10:01:00")
        self._sin_firmar(9, "2026-07-29 23:59:00")   # más nueva por fecha, sin hash
        self._linea(2, "2026-07-29 10:02:00")
        r = self._verifica()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["segmentos"], 1, "la cadena se ha partido en dos")

    def test_la_punta_no_depende_de_la_fecha(self):
        """Se escribe una línea con fecha anterior a la última: debe encadenar igual."""
        self._linea(1, "2026-07-29 10:05:00")
        self._linea(2, "2026-07-29 09:00:00")
        filas = self.conn.execute(
            "SELECT id, prev_hash, integrity_hash FROM workspace_registro_audit ORDER BY created_at").fetchall()
        enlaces = {f["id"]: f["prev_hash"] for f in filas}
        self.assertEqual(sum(1 for v in enlaces.values() if not v), 1,
                         "sólo una línea puede decir que es la primera")
        self.assertTrue(self._verifica()["ok"])


class LoQueTieneQueSeguirDetectandoTests(BaseCadena):
    def setUp(self):
        super().setUp()
        for i in range(1, 4):
            self._linea(i, f"2026-07-29 10:0{i}:00")

    def test_tocar_el_contenido_de_una_linea(self):
        self.conn.execute(
            "UPDATE workspace_registro_audit SET after_json = ? WHERE entity_id = 'f2'", ('{"x": 999}',))
        self.conn.commit()
        r = self._verifica()
        self.assertFalse(r["ok"])
        self.assertEqual(len(r["manipuladas"]), 1)
        self.assertIsNotNone(r["broken_at"])

    def test_cambiar_la_fecha_de_una_linea(self):
        """`created_at` entra en el hash: por eso no se pueden «reparar» esas fechas."""
        self.conn.execute(
            "UPDATE workspace_registro_audit SET created_at = ? WHERE entity_id = 'f2'", ("2020-01-01 00:00:00",))
        self.conn.commit()
        self.assertFalse(self._verifica()["ok"])

    def test_cambiar_quien_lo_hizo(self):
        self.conn.execute(
            "UPDATE workspace_registro_audit SET actor_user_id = 'otro' WHERE entity_id = 'f2'")
        self.conn.commit()
        self.assertFalse(self._verifica()["ok"])

    def test_borrar_una_linea_de_en_medio(self):
        self.conn.execute("DELETE FROM workspace_registro_audit WHERE entity_id = 'f2'")
        self.conn.commit()
        r = self._verifica()
        self.assertFalse(r["ok"])
        self.assertEqual(len(r["huecos"]), 1, "la siguiente apunta a una línea que ya no existe")

    def test_recolocar_el_hash_para_disimular_un_borrado_tampoco_cuela(self):
        """Borrar f2 y hacer que f3 apunte a f1 deja el hash de f3 sin cuadrar."""
        h1 = self.conn.execute(
            "SELECT integrity_hash FROM workspace_registro_audit WHERE entity_id='f1'").fetchone()[0]
        self.conn.execute("DELETE FROM workspace_registro_audit WHERE entity_id = 'f2'")
        self.conn.execute("UPDATE workspace_registro_audit SET prev_hash = ? WHERE entity_id = 'f3'", (h1,))
        self.conn.commit()
        self.assertFalse(self._verifica()["ok"])

    def test_una_cadena_intacta_no_da_falsa_alarma(self):
        r = self._verifica()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["manipuladas"], [])
        self.assertEqual(r["huecos"], [])


class UnSoloTextoFirmadoTests(BaseCadena):
    """Escritura y verificación armaban el texto por separado: dos listas de doce
    campos que había que mantener iguales a mano. En una cadena de integridad, eso es
    lo único que no puede desincronizarse."""

    def test_el_hash_guardado_sale_de_la_funcion_compartida(self):
        self._linea(1, "2026-07-29 10:01:00")
        f = self.conn.execute("SELECT * FROM workspace_registro_audit").fetchone()
        payload = workspace_registro_audit_chain_payload(WS, f, f["prev_hash"])
        self.assertEqual(hashlib.sha256(payload.encode()).hexdigest(), f["integrity_hash"])

    def test_el_escritor_ya_no_arma_el_texto_por_su_cuenta(self):
        import pathlib
        fuente = (pathlib.Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        i = fuente.index("def log_workspace_registro_audit")
        bloque = fuente[i:i + 6000]
        self.assertIn("workspace_registro_audit_chain_payload(", bloque)


class SePuedeVerificarDesdeLaAplicacionTests(unittest.TestCase):
    """La cadena existía desde hacía tiempo, pero la función que la comprueba sólo la
    llamaban los tests: desde la aplicación no había forma de verificar nada."""

    def test_hay_endpoint(self):
        import pathlib
        fuente = (pathlib.Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn('path == "/api/workspace_registro_audit_verify"', fuente)

    def test_pide_permiso_de_gestion_del_workspace(self):
        import pathlib
        fuente = (pathlib.Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        i = fuente.index('path == "/api/workspace_registro_audit_verify"')
        bloque = fuente[i:i + 1200]
        self.assertIn("workspace_actor_can_manage_workspace", bloque)
        self.assertIn("status=403", bloque)


if __name__ == "__main__":
    unittest.main()
