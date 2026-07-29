"""Regresión de dinero: los KPIs de /api/seguros_recibos_summary no deben truncarse.

Hallazgo verificado en vivo (2026-07-29): `pendiente_liquidacion_comision` y
`pendiente_impago_prima` se calculaban recorriendo las listas que alimentan el
listado, limitadas a 80 y 120 filas. Con más recibos que el límite, el importe
mostrado sub-reportaba dinero silenciosamente (85 recibos -> se ocultaban 5
recibos y 50,35 EUR de comisión pendiente de liquidar).

Ahora los KPIs se agregan en SQL sobre todas las filas del filtro, mientras los
listados siguen acotados para la UI.
"""

import json
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

from web import server as S

NOW = "2026-07-29 10:00:00"
PASSWORD = "Secreto123!"

# Por encima de los límites de listado (80 y 120) para que el truncamiento se note.
RECIBOS_COBRADOS = 85
COMISION_UNITARIA = 10.07
RECIBOS_IMPAGADOS = 130
PRIMA_UNITARIA = 200.50


class SegurosRecibosSummaryMoneyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db_path = Path(cls.tmp.name) / "recibos.sqlite"
        S.ensure_tables(db_path)
        cls.conn = S.open_sqlite_conn(str(db_path), with_row_factory=True)
        cls._seed()

        S.Handler.db_path = str(db_path)
        S.Handler.ocr_db_path = str(Path(cls.tmp.name) / "ocr.sqlite")
        cls.httpd = S.ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.cookie = cls._login()
        cls.summary = cls._get_summary()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.conn.close()
        cls.tmp.cleanup()

    @classmethod
    def _cols(cls, table):
        return [row[1] for row in cls.conn.execute(f"pragma table_info({table})")]

    @classmethod
    def _insert(cls, table, data):
        usable = {k: v for k, v in data.items() if k in cls._cols(table)}
        cls.conn.execute(
            f"INSERT INTO {table} ({','.join(usable)}) VALUES ({','.join('?' * len(usable))})",
            list(usable.values()),
        )

    @classmethod
    def _seed(cls):
        cls._insert("empresas", {"id": "empA", "nombre": "Empresa A SL", "activo": 1,
                                 "created_at": NOW, "updated_at": NOW})
        cls._insert("workspaces", {"id": "wsA", "nombre": "WS A", "slug": "wsa",
                                   "estado": "Activo", "plan": "Enterprise",
                                   "created_at": NOW, "updated_at": NOW})
        cls._insert("workspace_empresas", {"id": "weA", "workspace_id": "wsA",
                                           "empresa_id": "empA", "created_at": NOW,
                                           "updated_at": NOW})
        cls._insert("usuarios", {"id": "userA", "nombre": "Ana", "usuario": "ana",
                                 "email": "ana@a.test", "rol": "Miembro", "servicio": "Seguros",
                                 "activo": 1, "password_hash": S.hash_password(PASSWORD),
                                 "created_at": NOW, "updated_at": NOW})
        cls._insert("workspace_miembros", {"id": "wmA", "workspace_id": "wsA",
                                           "usuario_id": "userA", "rol": "Miembro",
                                           "created_at": NOW, "updated_at": NOW})
        cls._insert("clientes", {"id": "cli", "empresa_id": "empA", "nombre": "Cliente",
                                 "created_at": NOW, "updated_at": NOW})
        cls._insert("seguros", {"id": "pol", "empresa_id": "empA", "cliente_id": "cli",
                                "tomador": "Tomador", "compania": "AXA", "ramo": "Hogar",
                                "poliza_numero": "P1", "prima_total": 121.0,
                                "estado": "En vigor", "estado_poliza": "activa",
                                "created_at": NOW, "updated_at": NOW})

        base = {"seguro_id": "pol", "empresa_id": "empA", "cliente_id": "cli",
                "poliza_numero": "P1", "compania": "AXA", "ramo": "Hogar",
                "fecha_emision": "2026-01-15", "created_at": NOW, "updated_at": NOW}
        # Cobrados con comisión y sin liquidar -> "pendiente de liquidación".
        for i in range(RECIBOS_COBRADOS):
            cls._insert("seguros_recibos", {**base, "id": f"cob{i:03d}",
                                            "referencia": f"COB{i:03d}",
                                            "fecha_cobro": "2026-02-01", "estado": "cobrado",
                                            "prima_total": 121.0,
                                            "comision": COMISION_UNITARIA,
                                            "importe_liquidacion": 0})
        # Pendientes con vencimiento pasado y sin cobro -> "impagados".
        for i in range(RECIBOS_IMPAGADOS):
            cls._insert("seguros_recibos", {**base, "id": f"imp{i:03d}",
                                            "referencia": f"IMP{i:03d}",
                                            "fecha_vencimiento": "2026-02-01",
                                            "estado": "pendiente",
                                            "prima_total": PRIMA_UNITARIA, "comision": 5.0})
        cls.conn.commit()

    @classmethod
    def _login(cls):
        request = urllib.request.Request(
            cls.base + "/api/login",
            data=json.dumps({"usuario": "ana", "password": PASSWORD}).encode(),
            headers={"Content-Type": "application/json", "Origin": cls.base},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return (response.headers.get("Set-Cookie") or "").split(";")[0]

    @classmethod
    def _get_summary(cls):
        url = cls.base + "/api/seguros_recibos_summary?" + urllib.parse.urlencode({"empresa_id": "empA"})
        request = urllib.request.Request(url, headers={"Cookie": cls.cookie})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())

    # ---------- KPIs exactos (no truncados por el LIMIT del listado) ----------

    def test_comision_pendiente_de_liquidar_cuenta_todos_los_recibos(self):
        # 85 recibos x 10,07 EUR = 855,95 EUR (antes reportaba 80 x 10,07 = 805,60).
        kpis = self.summary["kpis"]
        self.assertEqual(kpis["pendiente_liquidacion_count"], RECIBOS_COBRADOS)
        self.assertAlmostEqual(kpis["pendiente_liquidacion_comision"],
                               round(RECIBOS_COBRADOS * COMISION_UNITARIA, 2), places=2)

    def test_prima_impagada_cuenta_todos_los_recibos(self):
        # 130 recibos x 200,50 EUR = 26.065,00 EUR (antes reportaba 120 x 200,50 = 24.060,00).
        kpis = self.summary["kpis"]
        self.assertEqual(kpis["pendiente_impago_count"], RECIBOS_IMPAGADOS)
        self.assertAlmostEqual(kpis["pendiente_impago_prima"],
                               round(RECIBOS_IMPAGADOS * PRIMA_UNITARIA, 2), places=2)

    def test_kpi_cuadra_con_el_agregado_sql_de_totales(self):
        """El total global de comisión debe salir de la misma fuente que el detalle."""
        total_comision = self.conn.execute(
            "SELECT SUM(COALESCE(comision, 0)) FROM seguros_recibos WHERE estado = 'cobrado'"
        ).fetchone()[0]
        self.assertAlmostEqual(self.summary["kpis"]["pendiente_liquidacion_comision"],
                               round(float(total_comision), 2), places=2)

    # ---------- los listados siguen acotados para la UI ----------

    def test_los_listados_siguen_limitados(self):
        self.assertEqual(len(self.summary["pendientes_liquidacion"]), 80)
        self.assertEqual(len(self.summary["pendientes_impago"]), 120)

    def test_la_muestra_de_conciliacion_declara_su_alcance(self):
        """La conciliación esperado/real recorre un máximo de filas: debe declararlo."""
        kpis = self.summary["kpis"]
        self.assertIn("comision_muestra_filas", kpis)
        self.assertIn("comision_muestra_truncada", kpis)
        # 215 recibos en total, por debajo del tope de 800 -> no truncada.
        self.assertFalse(kpis["comision_muestra_truncada"])


if __name__ == "__main__":
    unittest.main()
