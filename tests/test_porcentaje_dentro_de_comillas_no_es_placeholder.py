"""`segmentacion_trabajos` volvía `{}` en `/api/gestoria_dashboard`, y con ella
"Rentas" (y el resto de servicios) se veían a 0 en la pestaña Servicios del
dashboard de Gestoría, con datos reales delante (834 trabajos de categoría
"rentas" en producción). El log de errores de producción decía:

    ProgrammingError: the query has 10 placeholders but 7 parameters were passed

La consulta solo tiene 7 "?" (uno por empresa_id). Los otros tres venían de
tres patrones LIKE que por casualidad empiezan por "%t": `'%trafic%'`,
`'%transfer%'` y `'%tasaci%'`. psycopg3 solo admite `%s`, `%b` y `%t` como
placeholders reales; cualquier otro `%x` hay que escaparlo a `%%` o revienta.

`_escape_psycopg_pyformat_percents` debía hacer justo eso, pero no distinguía
si el `%` estaba dentro de una cadena SQL o no: dejaba sin escapar cualquier
`%s`/`%b`/`%t`, viniera de donde viniera. Un `%t` que solo era el principio de
un LIKE se colaba como si fuera un placeholder real, y psycopg contaba de más
en vez de fallar por token inválido —así que el error ni siquiera señalaba
esta función—.
"""

import unittest

from web.db_backend import _escape_psycopg_pyformat_percents, translate_sqlite_sql_to_postgres


class UnPorcentajeDentroDeComillasNoEsPlaceholderTests(unittest.TestCase):
    def test_el_like_que_tumbo_produccion(self):
        sql = (
            "SELECT SUM(CASE WHEN LOWER(t) LIKE '%trafic%' THEN 1 ELSE 0 END) AS a, "
            "SUM(CASE WHEN LOWER(t) LIKE '%transfer%' THEN 1 ELSE 0 END) AS b, "
            "SUM(CASE WHEN LOWER(t) LIKE '%tasaci%' THEN 1 ELSE 0 END) AS c "
            "FROM gestoria_trabajos WHERE empresa_id IN (?,?,?,?,?,?,?)"
        )
        out = _escape_psycopg_pyformat_percents(sql.replace("?", "%s"))
        # Los tres LIKE quedan con el "%" escapado a "%%": ya no son placeholders.
        self.assertEqual(out.count("%%trafic%%"), 1)
        self.assertEqual(out.count("%%transfer%%"), 1)
        self.assertEqual(out.count("%%tasaci%%"), 1)
        # Los 7 placeholders de empresa_id siguen siendo %s, ni uno más ni uno menos.
        self.assertEqual(out.count("%s"), 7)

    def test_via_translate_sqlite_sql_to_postgres_de_extremo_a_extremo(self):
        sql = "SELECT 1 FROM t WHERE LOWER(x) LIKE '%tasaci%' AND id IN (?, ?)"
        out = translate_sqlite_sql_to_postgres(sql)
        self.assertEqual(out.count("%s"), 2)
        self.assertIn("%%tasaci%%", out)

    def test_placeholder_real_fuera_de_comillas_sigue_intacto(self):
        out = _escape_psycopg_pyformat_percents("SELECT %s, %s FROM t")
        self.assertEqual(out, "SELECT %s, %s FROM t")

    def test_b_y_t_dentro_de_comillas_tambien_se_escapan(self):
        out = _escape_psycopg_pyformat_percents("SELECT '%bicho%', '%todo%'")
        self.assertEqual(out, "SELECT '%%bicho%%', '%%todo%%'")

    def test_comilla_doble_tambien_protege(self):
        out = _escape_psycopg_pyformat_percents('SELECT "%trafic%" FROM t')
        self.assertEqual(out, 'SELECT "%%trafic%%" FROM t')

    def test_porcentaje_ya_escapado_en_la_fuente_no_se_dobla(self):
        # Fuera de comillas, un "%%" que ya viniera escrito así (poco común, pero
        # legítimo) no debe convertirse en "%%%%".
        out = _escape_psycopg_pyformat_percents("SELECT '%%' AS lit")
        self.assertEqual(out, "SELECT '%%%%' AS lit")


if __name__ == "__main__":
    unittest.main()
