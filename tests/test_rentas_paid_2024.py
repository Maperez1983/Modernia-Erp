import unittest

from web.server import sanitize_renta_entry


class RentasPaid2024Tests(unittest.TestCase):
    def test_renta_2024_is_forced_paid(self):
        entry = {
            "id": "renta-2024-foo",
            "ejercicio": "2024",
            "estado_presentacion": "Presentada",
            "cobrada": 0,
            "forma_cobro": "",
            "resultado_declaracion": 0,
        }
        sanitized = sanitize_renta_entry(entry)
        self.assertEqual(sanitized.get("cobrada"), 1)


if __name__ == "__main__":
    unittest.main()

