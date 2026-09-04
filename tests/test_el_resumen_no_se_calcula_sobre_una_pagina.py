"""Los importes del panel de recibos se sumaban sobre las 800 filas que caben.

Salió montando una comunidad con lo que va a haber cuando fincas se use de verdad: en
producción hay 318 vecinos en 14 comunidades y **cero recibos**, así que todo lo
auditado de fincas se ha probado con cuatro propietarios.

Con 1.200 recibos en la base y 120.000 € emitidos, el panel decía:

    recibos 800 · emitido 80.000 € · pendiente 80.000 €

Faltaban 40.000 € de deuda, y nada lo delataba. La lista tiene un tope de 800 filas
—razonable— pero el resumen se calculaba **sobre esas 800**, no sobre lo que hay. Una
lista cortada es incómoda; un importe cortado es un número mal en una pantalla de
contabilidad.

Hasta dónde llega hoy
---------------------
La pantalla no lo alcanza: el front siempre manda `periodo`, así que pide un mes y un
mes son 59 recibos en la comunidad más grande. Para que la lista se llene haría falta
una comunidad de más de 800 pisos, o pedir el histórico entero. O sea que **no hay
ninguna cifra mal en producción hoy** — esto quita la trampa antes de pisarla, no
repara un daño.

El arreglo
----------
El resumen sale de un agregado sobre todos los recibos que cumplen el filtro. El IBAN
no se puede validar en SQL —hay que comprobar el dígito de control— así que se trae esa
columna y se cuenta aparte. Y la respuesta dice `total` y `limite`, para que la pantalla
pueda avisar de que la lista está cortada aunque los importes no lo estén.

Si el agregado falla, se vuelve a las cifras de la página **marcadas como parciales**:
antes un número pequeño y honesto que uno grande y falso.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("POSTGRES_URL", "")

from web import server as S  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

IBAN = "ES2321000418400000000001"


def comunidad_con(caso, vecinos, meses, cobrados=0, devueltos=0):
    """Una comunidad con `vecinos` propietarios y `meses` de recibos emitidos."""
    tmp = tempfile.mkdtemp()
    caso.addCleanup(shutil.rmtree, tmp, True)
    ruta = Path(tmp) / "fincas.sqlite"
    conn = S.get_db(ruta)
    caso.addCleanup(conn.close)
    S.ensure_tables(str(ruta))
    for crear in (S.ensure_workspace_core_tables, S.ensure_workspace_product_tables):
        crear(conn)
    ahora = "2026-01-01T09:00:00"
    conn.execute("INSERT INTO empresas (id, nombre, activo, created_at, updated_at) "
                 "VALUES ('e1','Fincas',1,?,?)", (ahora, ahora))
    conn.execute("INSERT INTO workspaces (id, nombre, slug, created_at, updated_at) "
                 "VALUES ('w1','Fincas','fincas',?,?)", (ahora, ahora))
    conn.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, created_at, "
                 "updated_at) VALUES ('we1','w1','e1',?,?)", (ahora, ahora))
    conn.execute("INSERT INTO workspace_fincas_comunidades (id, workspace_id, empresa_id, "
                 "nombre, created_at, updated_at) VALUES ('c1','w1','e1','C.P. Prueba',?,?)",
                 (ahora, ahora))
    for i in range(vecinos):
        conn.execute(
            "INSERT INTO workspace_fincas_vecinos (id, workspace_id, comunidad_id, nombre, "
            "piso, coeficiente, iban, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (f"v{i}", "w1", "c1", f"Propietario {i:03d}", f"{i // 4 + 1}{'ABCD'[i % 4]}",
             round(100.0 / vecinos, 4), IBAN, ahora, ahora))
    n = 0
    for m in range(1, meses + 1):
        for i in range(vecinos):
            # Los primeros de la tanda se marcan cobrados o devueltos, para que el
            # desglose por estado no sea todo «Pendiente» y se note si se suma mal.
            if n < cobrados:
                estado = "Cobrado"
            elif n < cobrados + devueltos:
                estado = "Devuelto"
            else:
                estado = "Pendiente"
            conn.execute(
                "INSERT INTO workspace_fincas_recibos (id, workspace_id, comunidad_id, "
                "vecino_id, periodo, concepto, importe, coeficiente, estado, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"r{m}-{i}", "w1", "c1", f"v{i}", f"2026-{m:02d}",
                 f"Cuota 2026-{m:02d}", 100.0, round(100.0 / vecinos, 4), estado,
                 ahora, ahora))
            n += 1
    conn.commit()
    return conn


class LosImportesSonLosDeTodosTests(unittest.TestCase):
    def test_con_mas_recibos_que_el_tope_los_importes_siguen_siendo_los_de_todos(self):
        """El caso que salió: 1.200 recibos, 120.000 €, la pantalla decía 80.000."""
        conn = comunidad_con(self, vecinos=100, meses=12, cobrados=3, devueltos=2)
        r = S.fetch_workspace_fincas_recibos(conn, "w1", "c1")
        self.assertEqual(len(r["rows"]), 800, "el tope de la lista ha cambiado")
        self.assertEqual(r["resumen"]["recibos"], 1200)
        self.assertAlmostEqual(r["resumen"]["emitido"], 120000.0, places=2)
        self.assertAlmostEqual(r["resumen"]["cobrado"], 300.0, places=2)
        self.assertAlmostEqual(r["resumen"]["devuelto"], 200.0, places=2)
        self.assertAlmostEqual(r["resumen"]["pendiente"], 119500.0, places=2)

    def test_y_los_tres_estados_suman_lo_emitido(self):
        """Si un estado se cuela en el saco de otro, esto lo caza."""
        conn = comunidad_con(self, vecinos=100, meses=12, cobrados=3, devueltos=2)
        r = S.fetch_workspace_fincas_recibos(conn, "w1", "c1")["resumen"]
        self.assertAlmostEqual(r["cobrado"] + r["devuelto"] + r["pendiente"],
                               r["emitido"], places=2)

    def test_la_respuesta_dice_cuantos_hay_y_cuantos_caben(self):
        conn = comunidad_con(self, vecinos=100, meses=12)
        r = S.fetch_workspace_fincas_recibos(conn, "w1", "c1")
        self.assertEqual(r["total"], 1200)
        self.assertEqual(r["limite"], 800)
        self.assertLess(len(r["rows"]), r["total"])

    def test_cuando_caben_todos_no_cambia_nada(self):
        """El caso normal: una comunidad de 59 pisos y un mes."""
        conn = comunidad_con(self, vecinos=59, meses=1, cobrados=2)
        r = S.fetch_workspace_fincas_recibos(conn, "w1", "c1")
        self.assertEqual(len(r["rows"]), 59)
        self.assertEqual(r["total"], 59)
        self.assertAlmostEqual(r["resumen"]["emitido"], 5900.0, places=2)
        self.assertAlmostEqual(r["resumen"]["cobrado"], 200.0, places=2)

    def test_filtrando_por_mes_los_importes_son_los_de_ese_mes(self):
        """El resumen tiene que respetar el filtro, no sumar el histórico entero."""
        conn = comunidad_con(self, vecinos=100, meses=12)
        r = S.fetch_workspace_fincas_recibos(conn, "w1", "c1", periodo="2026-03")
        self.assertEqual(r["total"], 100)
        self.assertAlmostEqual(r["resumen"]["emitido"], 10000.0, places=2)

    def test_los_recibos_sin_cuenta_valida_se_cuentan_sobre_todos(self):
        """Es el aviso que evita que el banco tumbe la remesa entera."""
        conn = comunidad_con(self, vecinos=100, meses=12)
        # Uno de los que NO caben en la lista se queda sin IBAN.
        conn.execute("UPDATE workspace_fincas_vecinos SET iban = '' WHERE id = 'v99'")
        conn.commit()
        r = S.fetch_workspace_fincas_recibos(conn, "w1", "c1")
        self.assertEqual(r["resumen"]["sin_iban"], 12, "un recibo por mes")

    def test_una_comunidad_sin_recibos_no_revienta(self):
        conn = comunidad_con(self, vecinos=4, meses=0)
        r = S.fetch_workspace_fincas_recibos(conn, "w1", "c1")
        self.assertEqual(r["rows"], [])
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["resumen"]["emitido"], 0)


class LaPantallaAvisaDeLaListaCortadaTests(unittest.TestCase):
    def test_lo_dice_y_aclara_que_los_importes_no_lo_están(self):
        # Anclado en el aviso del IBAN, que es la línea de al lado: `data-recibos-resumen`
        # aparece antes en la plantilla vacía del panel.
        i = APP.index("tumba el fichero entero en el banco")
        cuerpo = APP[i:i + 700]
        self.assertIn("Se listan ${numberFormatter.format(filas.length)}", cuerpo)
        self.assertIn("Los importes de arriba sí son los de todos", cuerpo)

    def test_y_sólo_cuando_sobran(self):
        i = APP.index("tumba el fichero entero en el banco")
        cuerpo = APP[i:i + 700]
        self.assertIn("Number(data?.total || 0) > filas.length", cuerpo)


if __name__ == "__main__":
    unittest.main()
