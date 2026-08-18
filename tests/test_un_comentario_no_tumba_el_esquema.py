"""Un punto y coma dentro de un comentario tumbó el CRM.

`apply_schema_file` troceaba el fichero con `script.split(";")`. Un comentario
`--` que llevara un punto y coma partía la sentencia por la mitad y Postgres
contestaba «syntax error at end of input» señalando la línea del comentario.

Pasó de verdad. El comentario que explicaba la columna `cliente_id` de la tabla
`gestoria` decía «536 resuelven a un cliente único por nombre y empresa; 10
nombres no existen», y ese punto y coma cortó el `CREATE TABLE`. El esquema dejó
de aplicarse, el hilo de arranque entró en bucle, se comió el pool de conexiones
y el CRM estuvo horas contestando «DB no disponible».

Dos cosas tenían que fallar a la vez, y las dos están arregladas: que un
comentario pueda partir una sentencia, y que un arranque fallido se quede con la
conexión (`test_arranque_no_se_come_el_pool`).
"""

import unittest

from web.schema_support import _trocea_por_sentencias


class UnComentarioNoParteUnaSentenciaTests(unittest.TestCase):
    def test_el_caso_que_tumbo_produccion(self):
        script = (
            "CREATE TABLE IF NOT EXISTS gestoria (\n"
            "  id TEXT PRIMARY KEY,\n"
            "  -- 536 resuelven a un cliente único por nombre y empresa; 10 no existen\n"
            "  cliente_id TEXT\n"
            ");\n"
        )
        s = [x.strip() for x in _trocea_por_sentencias(script) if x.strip()]
        self.assertEqual(len(s), 1, f"la sentencia se ha partido en {len(s)}")
        self.assertTrue(s[0].startswith("CREATE TABLE"))
        self.assertIn("cliente_id TEXT", s[0])

    def test_las_sentencias_de_verdad_sí_se_separan(self):
        s = [x.strip() for x in _trocea_por_sentencias(
            "CREATE TABLE a (id TEXT);\nCREATE TABLE b (id TEXT);\n") if x.strip()]
        self.assertEqual(len(s), 2)

    def test_ni_un_punto_y_coma_entre_comillas(self):
        s = [x.strip() for x in _trocea_por_sentencias(
            "INSERT INTO t (v) VALUES ('uno; dos');\nSELECT 1;\n") if x.strip()]
        self.assertEqual(len(s), 2)
        self.assertIn("'uno; dos'", s[0])

    def test_el_comentario_acaba_con_la_linea(self):
        """Lo que va detrás del salto vuelve a contar."""
        s = [x.strip() for x in _trocea_por_sentencias(
            "-- comentario con ; dentro\nCREATE TABLE a (id TEXT);\n") if x.strip()]
        self.assertEqual(len(s), 1)
        self.assertIn("CREATE TABLE a", s[0])


class ElEsquemaDeVerdadTests(unittest.TestCase):
    def test_ningun_comentario_de_schema_sql_lleva_punto_y_coma(self):
        """Aunque el troceador ya lo aguante, no hay razón para escribirlos así."""
        import pathlib
        raiz = pathlib.Path(__file__).resolve().parents[1]
        malos = [(n, l.strip()) for n, l in enumerate(
            (raiz / "schema.sql").read_text(encoding="utf-8").split("\n"), 1)
            if l.strip().startswith("--") and ";" in l]
        self.assertEqual(malos, [], f"comentarios con punto y coma: {malos}")

    def test_el_esquema_entero_se_aplica_sin_partirse(self):
        import pathlib, tempfile, os
        os.environ["DATABASE_URL"] = ""
        from web import server as S
        with tempfile.TemporaryDirectory() as tmp:
            db = pathlib.Path(tmp) / "e.sqlite"
            S.ensure_tables(db)
            conn = S.open_sqlite_conn(str(db), with_row_factory=True)
            cols = {r[1] for r in conn.execute("pragma table_info(gestoria)")}
            self.assertIn("cliente_id", cols)
            self.assertIn("cliente", cols)
            conn.close()


if __name__ == "__main__":
    unittest.main()
