import os
import base64
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image

from web.server import run_copilot_image_edit, UPLOADS


class CopilotImageEditTests(unittest.TestCase):
    def test_run_copilot_image_edit_local_ops(self):
        image = Image.new("RGB", (32, 32), (80, 120, 40))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        payload = {
            "file_base64": f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}",
            "filename": "test_ollana_editor.png",
            "plan": {"operations": [{"op": "autocontrast"}]},
        }

        result = run_copilot_image_edit(payload)

        self.assertTrue(result.get("ok"))
        url = str(result.get("url") or "").strip()
        self.assertTrue(url.startswith("/uploads/copilot_image_edits/"))
        output_path = UPLOADS / url.removeprefix("/uploads/")
        self.assertTrue(output_path.exists(), f"Archivo esperado no encontrado: {output_path}")
        self.assertEqual(int(result.get("size", {}).get("width")), 32)
        self.assertEqual(int(result.get("size", {}).get("height")), 32)
        try:
            output_path.unlink()
        except OSError:
            pass

    def test_run_copilot_image_edit_photo_cleanup(self):
        image = Image.new("RGB", (48, 32), (130, 130, 130))
        buffer = BytesIO()
        image.save(buffer, format="JPEG")
        payload = {
            "file_base64": f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}",
            "filename": "test_photo_cleanup.jpg",
            "plan": {"operations": [{"op": "photo_cleanup", "level": 1.1}]},
        }

        result = run_copilot_image_edit(payload)

        self.assertTrue(result.get("ok"))
        url = str(result.get("url") or "").strip()
        self.assertTrue(url.startswith("/uploads/copilot_image_edits/"))
        output_path = UPLOADS / url.removeprefix("/uploads/")
        self.assertTrue(output_path.exists(), f"Archivo esperado no encontrado: {output_path}")
        with Image.open(output_path) as out:
            self.assertEqual(out.size, (48, 32))
        try:
            output_path.unlink()
        except OSError:
            pass

    def test_run_copilot_image_edit_virtual_empty_room_heuristic(self):
        image = Image.new("RGB", (96, 72), (245, 245, 245))
        # Mancha sintética y objeto simulado para forzar una zona que deba eliminarse.
        for y in range(20, 55):
            for x in range(24, 72):
                if 18 <= y <= 33:
                    image.putpixel((x, y), (90, 70, 50))
                else:
                    image.putpixel((x, y), (160, 120, 90))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        payload = {
            "file_base64": f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}",
            "filename": "test_virtual_empty_room.png",
            "plan": {"operations": [{"op": "virtual_empty_room", "level": 1.15}]},
        }

        result = run_copilot_image_edit(payload)

        self.assertTrue(result.get("ok"))
        url = str(result.get("url") or "").strip()
        self.assertTrue(url.startswith("/uploads/copilot_image_edits/"))
        output_path = UPLOADS / url.removeprefix("/uploads/")
        self.assertTrue(output_path.exists(), f"Archivo esperado no encontrado: {output_path}")
        with Image.open(output_path) as out:
            self.assertEqual(out.size, (96, 72))
        try:
            output_path.unlink()
        except OSError:
            pass

    def test_run_copilot_image_edit_virtual_empty_room_reinforces_no_change(self):
        image = Image.new("RGB", (128, 96), (230, 220, 200))
        for y in range(20, 76):
            for x in range(36, 92):
                image.putpixel((x, y), (95, 90, 85))
        buf = BytesIO()
        image.save(buf, format="JPEG")
        original_data = buf.getvalue()
        payload = {
            "file_base64": f"data:image/jpeg;base64,{base64.b64encode(original_data).decode('ascii')}",
            "filename": "test_virtual_empty_room_reinforce.jpg",
            "plan": {"operations": [{"op": "virtual_empty_room", "level": 1.3}]},
        }

        with patch(
            "web.server._copilot_image_edit_call_openai",
            return_value=(original_data, ""),
        ):
            result = run_copilot_image_edit(payload)

        self.assertTrue(result.get("ok"))
        url = str(result.get("url") or "").strip()
        self.assertTrue(url.startswith("/uploads/copilot_image_edits/"))
        output_path = UPLOADS / url.removeprefix("/uploads/")
        self.assertTrue(output_path.exists(), f"Archivo esperado no encontrado: {output_path}")
        with Image.open(output_path) as out:
            self.assertEqual(out.size, image.size)
            out_data = list(out.getdata())
            original_data_pixels = list(image.getdata())
            self.assertNotEqual(out_data, original_data_pixels)
        try:
            output_path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    unittest.main()
