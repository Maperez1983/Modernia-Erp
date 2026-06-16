import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from scripts import summarize_audit_with_ollama


class SummarizeAuditWithOllamaTests(unittest.TestCase):
    def test_http_404_generates_degraded_summary_without_failing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "audit.json"
            report_path.write_text(json.dumps({"status": "failed", "steps": []}), encoding="utf-8")
            old_base = os.environ.get("OLLAMA_BASE_URL")
            os.environ["OLLAMA_BASE_URL"] = "http://ollama.internal:11434"
            try:
                with patch("scripts.summarize_audit_with_ollama.shutil.which", return_value="/usr/bin/ollama"):
                    with patch(
                        "scripts.summarize_audit_with_ollama.urlopen",
                        side_effect=HTTPError(
                            url="http://ollama.internal:11434/api/generate",
                            code=404,
                            msg="Not Found",
                            hdrs=None,
                            fp=None,
                        ),
                    ):
                        with patch("sys.argv", ["summarize_audit_with_ollama.py", str(report_path)]):
                            result = summarize_audit_with_ollama.main()
                self.assertEqual(result, 0)
                summary_path = report_path.with_suffix(".ollama.md")
                self.assertTrue(summary_path.exists())
                self.assertIn("HTTP 404", summary_path.read_text(encoding="utf-8"))
            finally:
                if old_base is None:
                    os.environ.pop("OLLAMA_BASE_URL", None)
                else:
                    os.environ["OLLAMA_BASE_URL"] = old_base


if __name__ == "__main__":
    unittest.main()
