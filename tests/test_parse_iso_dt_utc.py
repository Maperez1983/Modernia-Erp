import unittest
from datetime import timezone

from web.server import _parse_iso_dt_utc


class ParseIsoDtUtcTests(unittest.TestCase):
    def test_parse_zulu(self):
        dt = _parse_iso_dt_utc("2026-04-23T10:00:00Z")
        self.assertIsNotNone(dt)
        self.assertIsNotNone(dt.tzinfo)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_naive_assumes_utc(self):
        dt = _parse_iso_dt_utc("2026-04-23T10:00:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parse_date_only(self):
        dt = _parse_iso_dt_utc("2026-04-23")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)


if __name__ == "__main__":
    unittest.main()

