import json
import sqlite3
import unittest
from pathlib import Path

from web.server import _irpf_ganancia_simulate, _iivtnu_simulate, build_fiscal_venta_report_pdf, ensure_iivtnu_schema


PRESETS_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "supuestos" / "fiscal_venta_presets.json"
)


class FiscalVentaPresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = PRESETS_PATH.read_text(encoding="utf-8")
        cls.data = json.loads(raw)
        cls.presets = list(cls.data.get("presets") or [])
        cls.conn = sqlite3.connect(":memory:")
        cls.conn.row_factory = sqlite3.Row
        ensure_iivtnu_schema(cls.conn)
        cls.conn.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.conn.close()
        except Exception:
            pass

    def test_presets_schema(self):
        self.assertEqual(self.data.get("schema"), "modernia.fiscal_venta_presets.v1")
        self.assertGreaterEqual(len(self.presets), 10)

    def test_presets_smoke_simulate(self):
        for preset in self.presets:
            preset_id = str(preset.get("id") or "").strip() or "<sin id>"
            with self.subTest(preset_id=preset_id):
                irpf_payload = preset.get("irpf") or {}
                iivtnu_payload = preset.get("iivtnu") or {}
                self.assertIsInstance(irpf_payload, dict)
                self.assertIsInstance(iivtnu_payload, dict)

                irpf_out = _irpf_ganancia_simulate(irpf_payload)
                self.assertTrue(irpf_out.get("ok"), msg=f"IRPF/IRNR no ok en {preset_id}")

                iivtnu_out = _iivtnu_simulate(self.conn, iivtnu_payload)
                self.assertTrue(iivtnu_out.get("ok"), msg=f"IIVTNU no ok en {preset_id}")

                expect = preset.get("expect") or {}
                expect_irpf = expect.get("irpf") or {}
                expect_iivtnu = expect.get("iivtnu") or {}

                if isinstance(expect_irpf, dict) and expect_irpf:
                    for key, expected in expect_irpf.items():
                        actual = (irpf_out.get("result") or {}).get(key)
                        if isinstance(expected, (int, float)):
                            self.assertAlmostEqual(float(actual), float(expected), places=2, msg=f"{preset_id}:{key}")
                        else:
                            self.assertEqual(actual, expected, msg=f"{preset_id}:{key}")

                if isinstance(expect_iivtnu, dict) and expect_iivtnu:
                    for key, expected in expect_iivtnu.items():
                        actual = (iivtnu_out.get("result") or {}).get(key)
                        if isinstance(expected, (int, float)):
                            self.assertAlmostEqual(float(actual), float(expected), places=2, msg=f"{preset_id}:{key}")
                        else:
                            self.assertEqual(actual, expected, msg=f"{preset_id}:{key}")

    def test_can_build_fiscal_venta_pdf_from_preset(self):
        preset = next((p for p in self.presets if p.get("id") == "venta_irpf_tramo_30pct_2025"), None)
        self.assertIsNotNone(preset)
        irpf_payload = preset.get("irpf") or {}
        iivtnu_payload = preset.get("iivtnu") or {}
        wizard = preset.get("wizard") or {}

        irpf_out = _irpf_ganancia_simulate(irpf_payload)
        iivtnu_out = _iivtnu_simulate(self.conn, iivtnu_payload)

        payload = {
            "brand_logo_url": "/assets/grupo_modernia_logo.png",
            "empresa_nombre": "Grupo Modernia",
            "referencia": str(wizard.get("referencia") or ""),
            "ccaa": str(wizard.get("ccaa") or "AN"),
            "pv_territorio": str(wizard.get("pv_territorio") or ""),
            "irpf_payload": irpf_payload,
            "irpf_result": irpf_out,
            "iivtnu_payload": iivtnu_payload,
            "iivtnu_result": iivtnu_out,
        }
        pdf_bytes = build_fiscal_venta_report_pdf(payload, irpf_out, iivtnu_out)
        self.assertIsInstance(pdf_bytes, (bytes, bytearray))
        self.assertTrue(bytes(pdf_bytes).startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 1500)


if __name__ == "__main__":
    unittest.main()

