import importlib.util
import io
import json
import http.server
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[1]
LIGHTHOUSE_SCRIPT = (ROOT / "scripts" / "lighthouse-local.cjs").read_text(encoding="utf-8")
LIGHTHOUSE_WORKFLOW = (ROOT / ".github" / "workflows" / "lighthouse.yml").read_text(encoding="utf-8")


def extract_chunk(start_marker: str, end_marker: str) -> str:
    start = LIGHTHOUSE_SCRIPT.index(start_marker)
    end = LIGHTHOUSE_SCRIPT.index(end_marker, start)
    return LIGHTHOUSE_SCRIPT[start:end]


def run_node_script(script: str) -> None:
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node no está disponible")
    proc = subprocess.run([node, "-e", script], capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(
            "node -e falló\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )


class LighthouseLocalRunnerTests(unittest.TestCase):
    @staticmethod
    def _start_external_http_server():
        html_body = (
            b"<!doctype html><html lang=\"en\"><head>"
            b"<meta charset=\"utf-8\">"
            b"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            b"<meta name=\"description\" content=\"LHCI test page\">"
            b"<title>LHCI</title>"
            b"</head><body><main><h1>LHCI</h1><p>Sanitized integration page.</p>"
            b"<form><label for=\"name\">Name</label><input id=\"name\" type=\"text\" value=\"Test\"></form>"
            b"<button type=\"button\">Save</button></main></body></html>"
        )
        robots_body = b"User-agent: *\nAllow: /\n"

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _respond(self, status=200, content_type="text/html; charset=utf-8", body=b""):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD" and body:
                    self.wfile.write(body)

            def _send(self):
                if self.path.startswith("/robots.txt"):
                    self._respond(200, "text/plain; charset=utf-8", robots_body)
                    return
                self._respond(200, "text/html; charset=utf-8", html_body)

            def do_GET(self):
                self._send()

            def do_HEAD(self):
                self._send()

            def log_message(self, format, *args):
                return

        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        except PermissionError as exc:
            raise unittest.SkipTest(f"no se puede abrir un puerto local en este entorno: {exc}") from exc
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def test_lighthouse_workflow_uses_visible_tmpdir(self):
        assert "lhci-artifacts" in LIGHTHOUSE_WORKFLOW
        assert ".lhci" not in LIGHTHOUSE_WORKFLOW

    def test_lighthouse_workflow_keeps_measurement_cold_and_runs_diagnostics_after_failure(self):
        measured_block = LIGHTHOUSE_WORKFLOW.split("- name: Run Lighthouse CI", 1)[1].split(
            "- name: Upload Lighthouse artifacts",
            1,
        )[0]
        diagnostics_block = LIGHTHOUSE_WORKFLOW.split("- name: Run Lighthouse diagnostic matrix", 1)[1].split(
            "- name: Upload Lighthouse diagnostics",
            1,
        )[0]
        results_upload_block = LIGHTHOUSE_WORKFLOW.split("- name: Upload Lighthouse artifacts", 1)[1].split(
            "- name: Run Lighthouse diagnostic matrix",
            1,
        )[0]
        matrix_upload_block = LIGHTHOUSE_WORKFLOW.split("- name: Upload Lighthouse diagnostics", 1)[1]

        assert "LHCI_DIAGNOSTIC: 1" not in measured_block
        assert "LHCI_DIAGNOSTIC_MATRIX: 1" not in measured_block
        assert "if: failure()" in diagnostics_block
        assert "LHCI_DIAGNOSTIC_MATRIX: 1" in diagnostics_block
        assert "if: always()" in results_upload_block
        assert "${{ env.LHCI_TMPDIR }}/lighthouse-results" in results_upload_block
        assert "navigation-diagnostic.log" not in results_upload_block
        assert "if: always() && steps.lighthouse-ci.outcome == 'failure'" in matrix_upload_block
        assert "lighthouse-diagnostic-matrix.json" in matrix_upload_block
        assert "lighthouse-diagnostic-matrix.log" in matrix_upload_block
        assert "lighthouse-netlog-summary.json" in matrix_upload_block
        assert "lighthouse-netlog-summary.log" in matrix_upload_block
        assert "lighthouse-server.log" in matrix_upload_block
        assert "lighthouse-server-observations.jsonl" in matrix_upload_block
        assert "lighthouse-netlog-*.json" in matrix_upload_block
        assert "chrome-stderr*.log" in matrix_upload_block

    def test_browser_matrix_workflow_adds_linux_diagnostic_job_and_artifacts(self):
        assert "browser-matrix-diagnostic" in LIGHTHOUSE_WORKFLOW
        assert "browser-matrix-artifacts" in LIGHTHOUSE_WORKFLOW
        browser_job_block = LIGHTHOUSE_WORKFLOW.split("browser-matrix-diagnostic:", 1)[1]
        assert 'LHCI_BROWSER_MATRIX_DIAGNOSTIC: "1"' in browser_job_block
        assert "continue-on-error: true" in browser_job_block
        assert "if: always()" in browser_job_block
        assert "Upload Browser matrix diagnostics" in browser_job_block
        upload_block = browser_job_block.split("- name: Upload Browser matrix diagnostics", 1)[1]
        assert "browser-matrix-linux.json" in upload_block
        assert "browser-matrix-linux.log" in upload_block
        assert "browser-matrix-linux" in upload_block
        assert "lighthouse-server.log" in upload_block
        assert "lighthouse-server-observations.jsonl" in upload_block
        assert "if-no-files-found: error" in upload_block

    def test_fd_inheritance_workflow_adds_linux_diagnostic_job_and_artifacts(self):
        assert "fd-inheritance-diagnostic" in LIGHTHOUSE_WORKFLOW
        fd_job_block = LIGHTHOUSE_WORKFLOW.split("fd-inheritance-diagnostic:", 1)[1]
        assert 'LHCI_FD_INHERITANCE_DIAGNOSTIC: "1"' in fd_job_block
        assert 'LHCI_FD_INHERITANCE_SCRUB: "1"' in fd_job_block
        assert "continue-on-error: true" in fd_job_block
        assert "Run FD inheritance diagnostics" in fd_job_block
        assert 'set -o pipefail' in fd_job_block
        assert 'tee "$LHCI_TMPDIR/fd-inheritance-matrix.log"' in fd_job_block
        assert "if: always()" in fd_job_block
        upload_block = fd_job_block.split("- name: Upload FD inheritance diagnostics", 1)[1]
        assert "fd-inheritance-matrix.json" in upload_block
        assert "fd-inheritance-matrix.log" in upload_block
        assert "fd-inheritance-matrix" in upload_block
        assert "lighthouse-server.log" in upload_block
        assert "lighthouse-server-observations.jsonl" in upload_block
        assert "if-no-files-found: error" in upload_block

    def test_package_json_declares_puppeteer_core(self):
        package_json = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        assert "puppeteer-core" in package_json["devDependencies"]

    def test_shared_swcleared_normalization_forces_one_and_preserves_params_and_hash(self):
        script = dedent(
            """
            const assert = require("assert");
            const { ensureSwClearedUrl } = require("./scripts/lighthouse-url.cjs");

            const cases = [
              [
                "http://example.test/",
                41765,
                "http://example.test/?swcleared=1",
              ],
              [
                "http://example.test/?swcleared=0",
                41765,
                "http://example.test/?swcleared=1",
              ],
              [
                "https://example.test/path?foo=1#frag",
                41765,
                "https://example.test/path?foo=1&swcleared=1#frag",
              ],
              [
                "https://example.test/path?foo=1&swcleared=0#frag",
                41765,
                "https://example.test/path?foo=1&swcleared=1#frag",
              ],
              [
                "https://user:pass@example.test/path?token=abc",
                41765,
                "https://user:pass@example.test/path?token=abc&swcleared=1",
              ],
              [
                "https://user@example.test/path?password=abc#frag",
                41765,
                "https://user@example.test/path?password=abc&swcleared=1#frag",
              ],
            ];

            for (const [input, port, expected] of cases) {
              assert.strictEqual(ensureSwClearedUrl(input, port), expected);
            }

            process.env.LHCI_BASE_URL = "https://example.test/path?foo=1&swcleared=0#frag";
            process.env.LHCI_PORT = "41765";
            delete require.cache[require.resolve("./lighthouserc.cjs")];
            const lighthouseRc = require("./lighthouserc.cjs");
            assert.strictEqual(
              lighthouseRc.ci.collect.url[0],
              "https://example.test/path?foo=1&swcleared=1#frag"
            );
            """
        )
        run_node_script(script)

    def test_diagnostic_sanitizer_redacts_userinfo_sensitive_values_and_logs(self):
        chunk = extract_chunk("const DIAGNOSTIC_REDACTED_VALUE", "function describeRedirectChain")
        script = (
            dedent(
                """
                const assert = require("assert");
                const source = 'const { StringDecoder } = require("node:string_decoder");\\n' + __SOURCE__;
                const factory = new Function(source + "\\nreturn { sanitizeDiagnosticText, sanitizeDiagnosticUrl, sanitizeDiagnosticValue };");
                const api = factory();

                assert.strictEqual(
                  api.sanitizeDiagnosticUrl("https://user:pass@example.test/path?token=abc"),
                  "https://example.test/path?token=REDACTED"
                );
                assert.strictEqual(
                  api.sanitizeDiagnosticUrl("https://user@example.test/path?password=abc&signature=def#sig=ghi"),
                  "https://example.test/path?password=REDACTED&signature=REDACTED#sig=REDACTED"
                );
                assert.strictEqual(
                  api.sanitizeDiagnosticUrl("https://user:pass@example.test/path?key=abc&passwd=def&auth=ghi&authorization=jkl#state=mno"),
                  "https://example.test/path?key=REDACTED&passwd=REDACTED&auth=REDACTED&authorization=REDACTED#state=REDACTED"
                );
                assert.strictEqual(
                  api.sanitizeDiagnosticUrl("https://example.test/?session_token=abc&session-token=abc&sessionToken=abc&oauth_token=abc&oauth-token=abc&oauthToken=abc&bearer_token=abc&bearer-token=abc&bearerToken=abc&swcleared=1"),
                  "https://example.test/?session_token=REDACTED&session-token=REDACTED&sessionToken=REDACTED&oauth_token=REDACTED&oauth-token=REDACTED&oauthToken=REDACTED&bearer_token=REDACTED&bearer-token=REDACTED&bearerToken=REDACTED&swcleared=1"
                );
                assert.strictEqual(
                  api.sanitizeDiagnosticText("Authorization: Bearer abc Cookie: session=1 https://example.test/?secret=xyz"),
                  "Authorization: REDACTED"
                );

                const payload = api.sanitizeDiagnosticValue({
                  url: "https://user:pass@example.test/?token=abc",
                  location: "https://user@example.test/redirect?api_key=secret",
                  frameUrl: "https://user@example.test/frame?signature=abc",
                  text: "https://user@example.test/?refresh_token=abc",
                  message: "Proxy-Authorization: Basic abc",
                  headers: {
                    Cookie: "session=abc",
                    Authorization: "Bearer xyz",
                  },
                  body: "raw body",
                  redirectChain: [{
                    url: "https://user:pass@example.test/?session=abc",
                    responseUrl: "https://user:pass@example.test/?code=abc",
                    location: "https://user:pass@example.test/?state=abc",
                  }],
                });

                assert.strictEqual(payload.url, "https://example.test/?token=REDACTED");
                assert.strictEqual(payload.location, "https://example.test/redirect?api_key=REDACTED");
                assert.strictEqual(payload.frameUrl, "https://example.test/frame?signature=REDACTED");
                assert.strictEqual(payload.text, "https://example.test/?refresh_token=REDACTED");
                assert.strictEqual(payload.message, "Proxy-Authorization: REDACTED");
                assert.strictEqual(payload.redirectChain[0].url, "https://example.test/?session=REDACTED");
                assert.strictEqual(payload.redirectChain[0].responseUrl, "https://example.test/?code=REDACTED");
                assert.strictEqual(payload.redirectChain[0].location, "https://example.test/?state=REDACTED");
                assert.ok(!Object.prototype.hasOwnProperty.call(payload, "headers"));
                assert.ok(!Object.prototype.hasOwnProperty.call(payload, "body"));

                const rawAuditUrl = "https://user:pass@example.test/path?token=abc&key=def&signature=ghi#state=jkl";
                const normalizedAuditUrl = "https://user:pass@example.test/path?token=abc&key=def&signature=ghi&swcleared=1#state=jkl";
                const startupLines = [
                  `Lighthouse temp dir: /tmp/lhci-test`,
                  `Lighthouse server log: /tmp/lhci-test/lighthouse-server.log`,
                  `[lighthouse] audit URL normalized: ${api.sanitizeDiagnosticUrl(rawAuditUrl)} -> ${api.sanitizeDiagnosticUrl(normalizedAuditUrl)}`,
                  `Lighthouse base URL: ${api.sanitizeDiagnosticUrl(normalizedAuditUrl)}`,
                ];
                const startupOutput = startupLines.join("\\n");
                assert.ok(!startupOutput.includes("user:pass@"));
                assert.ok(!startupOutput.includes("token=abc"));
                assert.ok(!startupOutput.includes("key=def"));
                assert.ok(!startupOutput.includes("signature=ghi"));
                assert.ok(!startupOutput.includes("Authorization"));
                assert.ok(startupOutput.includes("token=REDACTED"));
                assert.ok(startupOutput.includes("key=REDACTED"));
                assert.ok(startupOutput.includes("signature=REDACTED"));

                const urlCases = [
                  [
                    "https://user:pass@example.test/?authToken=abc",
                    "https://example.test/?authToken=REDACTED",
                  ],
                  [
                    "https://example.test/?sessionId=abc",
                    "https://example.test/?sessionId=REDACTED",
                  ],
                  [
                    "https://example.test/?csrfToken=abc",
                    "https://example.test/?csrfToken=REDACTED",
                  ],
                  [
                    "https://example.test/?xsrfToken=abc",
                    "https://example.test/?xsrfToken=REDACTED",
                  ],
                  [
                    "https://example.test/?clientId=abc&clientSecret=def",
                    "https://example.test/?clientId=REDACTED&clientSecret=REDACTED",
                  ],
                  [
                    "https://example.test/?signedUrl=abc",
                    "https://example.test/?signedUrl=REDACTED",
                  ],
                  [
                    "https://user:pass@example.test/?auth_token=abc&auth-token=def&authToken=ghi&session_id=jkl&session-id=mno&sessionId=pqr&foo=ok&swcleared=1#frag",
                    "https://example.test/?auth_token=REDACTED&auth-token=REDACTED&authToken=REDACTED&session_id=REDACTED&session-id=REDACTED&sessionId=REDACTED&foo=ok&swcleared=1#frag",
                  ],
                [
                  "https://example.test/?foo=bar&baz=qux&swcleared=1",
                  "https://example.test/?foo=bar&baz=qux&swcleared=1",
                ],
                [
                  "https://example.test/?session_token=abc",
                  "https://example.test/?session_token=REDACTED",
                ],
                [
                  "https://example.test/?session-token=abc",
                  "https://example.test/?session-token=REDACTED",
                ],
                [
                  "https://example.test/?sessionToken=abc",
                  "https://example.test/?sessionToken=REDACTED",
                ],
                [
                  "https://example.test/?oauth_token=abc",
                  "https://example.test/?oauth_token=REDACTED",
                ],
                [
                  "https://example.test/?oauth-token=abc",
                  "https://example.test/?oauth-token=REDACTED",
                ],
                [
                  "https://example.test/?oauthToken=abc",
                  "https://example.test/?oauthToken=REDACTED",
                ],
                [
                  "https://example.test/?bearer_token=abc",
                  "https://example.test/?bearer_token=REDACTED",
                ],
                [
                  "https://example.test/?bearer-token=abc",
                  "https://example.test/?bearer-token=REDACTED",
                ],
                [
                  "https://example.test/?bearerToken=abc",
                  "https://example.test/?bearerToken=REDACTED",
                ],
              ];

                for (const [input, expected] of urlCases) {
                  assert.strictEqual(api.sanitizeDiagnosticUrl(input), expected);
                }

                assert.strictEqual(api.sanitizeDiagnosticText("authToken=abc"), "authToken=REDACTED");
                assert.strictEqual(api.sanitizeDiagnosticText("sessionId=abc"), "sessionId=REDACTED");
                assert.strictEqual(api.sanitizeDiagnosticText("csrfToken=abc"), "csrfToken=REDACTED");
                assert.strictEqual(api.sanitizeDiagnosticText("session_token=abc"), "session_token=REDACTED");
                assert.strictEqual(api.sanitizeDiagnosticText("session-token=abc"), "session-token=REDACTED");
                assert.strictEqual(api.sanitizeDiagnosticText("sessionToken=abc"), "sessionToken=REDACTED");
                assert.strictEqual(api.sanitizeDiagnosticText("oauth_token=abc"), "oauth_token=REDACTED");
                assert.strictEqual(api.sanitizeDiagnosticText("oauth-token=abc"), "oauth-token=REDACTED");
                assert.strictEqual(api.sanitizeDiagnosticText("oauthToken=abc"), "oauthToken=REDACTED");
                assert.strictEqual(api.sanitizeDiagnosticText("bearer_token=abc"), "bearer_token=REDACTED");
                assert.strictEqual(api.sanitizeDiagnosticText("bearer-token=abc"), "bearer-token=REDACTED");
                assert.strictEqual(api.sanitizeDiagnosticText("bearerToken=abc"), "bearerToken=REDACTED");
                assert.strictEqual(api.sanitizeDiagnosticText("swcleared=1"), "swcleared=1");
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_server_log_tail_is_sanitized_before_console_output(self):
        chunk = extract_chunk("const DIAGNOSTIC_REDACTED_VALUE", "function describeRedirectChain")
        script = (
            dedent(
                """
                const assert = require("assert");
                const source = 'const { StringDecoder } = require("node:string_decoder");\\n' + __SOURCE__;
                const factory = new Function(source + "\\nreturn { sanitizeDiagnosticText };");
                const api = factory();

                const tail = [
                  "[ERROR] /ruta?token=abc",
                  "[ERROR] /callback?session_token=abc",
                  "[ERROR] https://user:pass@example.test/path?oauth_token=abc",
                  "[ERROR] Authorization: Bearer abc",
                  "[ERROR] Cookie: session=abc",
                  "[INFO] Linea normal sin secretos",
                ].join("\\n");

                const sanitized = api.sanitizeDiagnosticText(tail);

                assert.strictEqual(
                  sanitized,
                  [
                    "[ERROR] /ruta?token=REDACTED",
                    "[ERROR] /callback?session_token=REDACTED",
                    "[ERROR] https://example.test/path?oauth_token=REDACTED",
                    "[ERROR] Authorization: REDACTED",
                    "[ERROR] Cookie: REDACTED",
                    "[INFO] Linea normal sin secretos",
                  ].join("\\n")
                );
                assert.ok(!sanitized.includes("token=abc"));
                assert.ok(!sanitized.includes("session_token=abc"));
                assert.ok(!sanitized.includes("oauth_token=abc"));
                assert.ok(!sanitized.includes("user:pass@"));
                assert.ok(!sanitized.includes("Authorization: Bearer abc"));
                assert.ok(!sanitized.includes("Cookie: session=abc"));
                assert.ok(sanitized.includes("Linea normal sin secretos"));
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_server_log_stream_buffers_and_sanitizes_fragmented_chunks(self):
        chunk = extract_chunk("function tailText", "function describeStatus")
        script = (
            dedent(
                """
                const assert = require("assert");
                const source = 'const { StringDecoder } = require("node:string_decoder");\\n' + __SOURCE__;
                const factory = new Function(source + "\\nreturn { createSanitizedConsoleLineWriter };");
                const api = factory();

                const collect = (chunks, flushCount = 1, finish = true) => {
                  const writes = [];
                  const writer = api.createSanitizedConsoleLineWriter((text) => writes.push(text));
                  for (const chunk of chunks) {
                    writer.write(chunk);
                  }
                  for (let index = 0; index < flushCount; index += 1) {
                    writer.flush();
                  }
                  if (finish) {
                    writer.finish();
                  }
                  return writes;
                };

                assert.deepStrictEqual(collect(["sess", "ion_token=abc\\n"], 2), ["session_token=REDACTED\\n"]);
                assert.deepStrictEqual(collect(["Authoriza", "tion: Bearer abc\\n"]), ["Authorization: REDACTED\\n"]);
                assert.deepStrictEqual(
                  collect(["https://user:", "pass@example.test/path?oauth_", "token=abc\\n"]),
                  ["https://example.test/path?oauth_token=REDACTED\\n"]
                );
                assert.deepStrictEqual(collect(["Cookie: sess", "ion=abc\\n"]), ["Cookie: REDACTED\\n"]);
                assert.deepStrictEqual(collect(["Linea normal sin secretos\\n"]), ["Linea normal sin secretos\\n"]);
                assert.deepStrictEqual(collect(["alpha\\nbeta\\n"]), ["alpha\\n", "beta\\n"]);
                assert.deepStrictEqual(collect(["uno", "\\ndos", "\\ntercera sin salto"], 2), ["uno\\n", "dos\\n", "tercera sin salto"]);
                assert.deepStrictEqual(
                  collect([Buffer.from([0xc3]), Buffer.from([0xa9, 0x0a])]),
                  ["é\\n"]
                );
                assert.deepStrictEqual(
                  collect([Buffer.from([0xe2, 0x82]), Buffer.from([0xac, 0x0a])]),
                  ["€\\n"]
                );
                assert.deepStrictEqual(
                  collect([Buffer.from([0xe4]), Buffer.from([0xb8, 0xad, 0x0a])]),
                  ["中\\n"]
                );
                assert.deepStrictEqual(
                  collect([Buffer.from([0xf0, 0x9f]), Buffer.from([0x98, 0x80, 0x0a])]),
                  ["😀\\n"]
                );

                const mixedUtf8 = Buffer.from("Ejecución válida: José € 😀\\n", "utf8");
                assert.deepStrictEqual(
                  collect([mixedUtf8.slice(0, 4), mixedUtf8.slice(4, 13), mixedUtf8.slice(13)]),
                  ["Ejecución válida: José € 😀\\n"]
                );

                const secretUtf8 = Buffer.from("Usuario José token=secreto 😀\\n", "utf8");
                assert.deepStrictEqual(
                  collect([secretUtf8.slice(0, 9), secretUtf8.slice(9, 20), secretUtf8.slice(20)]),
                  ["Usuario José token=REDACTED 😀\\n"]
                );
                assert.deepStrictEqual(
                  collect([Buffer.from("Última línea sin salto", "utf8")], 0),
                  ["Última línea sin salto"]
                );

                const stdoutWrites = [];
                const stderrWrites = [];
                const stdoutWriter = api.createSanitizedConsoleLineWriter((text) => stdoutWrites.push(text));
                const stderrWriter = api.createSanitizedConsoleLineWriter((text) => stderrWrites.push(text));

                stdoutWriter.write("stdout-line-1\\n");
                stderrWriter.write("stderr-line-1\\n");
                stdoutWriter.write("sess");
                stderrWriter.write("Authoriza");
                stdoutWriter.write("ion_token=abc\\n");
                stderrWriter.write("tion: Bearer abc\\n");
                stdoutWriter.write("stdout final without newline");
                stderrWriter.write("stderr final without newline");
                stdoutWriter.flush();
                stdoutWriter.flush();
                stderrWriter.flush();
                stderrWriter.flush();
                stdoutWriter.finish();
                stdoutWriter.finish();
                stderrWriter.finish();
                stderrWriter.finish();

                assert.deepStrictEqual(stdoutWrites, [
                  "stdout-line-1\\n",
                  "session_token=REDACTED\\n",
                  "stdout final without newline",
                ]);
                assert.deepStrictEqual(stderrWrites, [
                  "stderr-line-1\\n",
                  "Authorization: REDACTED\\n",
                  "stderr final without newline",
                ]);
                assert.ok(!stdoutWrites.join("").includes("session_token=abc"));
                assert.ok(!stderrWrites.join("").includes("Bearer abc"));
                assert.ok(!stdoutWrites.join("").includes("user:pass@"));
                assert.ok(!stderrWrites.join("").includes("Cookie: session=abc"));
                assert.ok(stdoutWrites.includes("stdout-line-1\\n"));
                assert.ok(stderrWrites.includes("stderr-line-1\\n"));
                assert.ok(stdoutWrites.includes("stdout final without newline"));
                assert.ok(stderrWrites.includes("stderr final without newline"));
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_raw_log_capture_keeps_streams_independent_and_idempotent(self):
        chunk = extract_chunk("function removeStreamListener", "function runCommand")
        script = (
            dedent(
                """
                const assert = require("assert");
                const {EventEmitter} = require("events");
                const source = 'const { StringDecoder } = require("node:string_decoder");\\n' + __SOURCE__;
                const factory = new Function(source + "\\nreturn { attachRawLogCapture };");
                const api = factory();

                const makeStream = () => {
                  const stream = new EventEmitter();
                  stream.setEncoding = () => {};
                  return stream;
                };

                const stdout = makeStream();
                const stderr = makeStream();
                const child = { stdout, stderr };
                const logWrites = [];
                const events = [];
                let logEnded = 0;
                const logStream = {
                  write(chunk) {
                    if (logEnded) {
                      throw new Error("write after end");
                    }
                    logWrites.push(String(chunk));
                  },
                  end(callback) {
                    logEnded += 1;
                    events.push("log-end");
                    if (typeof callback === "function") {
                      callback();
                    }
                  },
                };

                const bridge = api.attachRawLogCapture(child, logStream);

                (async () => {
                  try {
                    stdout.emit("data", "stdout-1\\n");
                    stderr.emit("data", "stderr-1\\n");
                    assert.deepStrictEqual(logWrites, ["stdout-1\\n", "stderr-1\\n"]);
                    assert.strictEqual(bridge.isStdoutCapturing(), true);
                    assert.strictEqual(bridge.isStderrCapturing(), true);

                    stdout.emit("end");
                    assert.strictEqual(bridge.isStdoutCapturing(), false);
                    assert.strictEqual(bridge.isStderrCapturing(), true);
                    stderr.emit("data", "stderr-2\\n");
                    stderr.emit("end");
                    assert.deepStrictEqual(logWrites, ["stdout-1\\n", "stderr-1\\n", "stderr-2\\n"]);

                    bridge.stop();
                    bridge.stop();
                    const firstClose = bridge.closeLog();
                    const secondClose = bridge.closeLog();
                    stdout.emit("data", "late-stdout\\n");
                    stderr.emit("data", "late-stderr\\n");
                    stdout.emit("close");
                    stderr.emit("close");
                    await firstClose;
                    await secondClose;

                    assert.strictEqual(logEnded, 1);
                    assert.ok(bridge.isClosed());
                    assert.deepStrictEqual(logWrites, ["stdout-1\\n", "stderr-1\\n", "stderr-2\\n"]);
                    assert.ok(!logWrites.join("").includes("late-stdout"));
                    assert.ok(!logWrites.join("").includes("late-stderr"));
                    assert.ok(events.includes("log-end"));
                  } catch (error) {
                    console.error(error && error.stack ? error.stack : error);
                    process.exit(1);
                  }
                })().catch((error) => {
                  console.error(error && error.stack ? error.stack : error);
                  process.exit(1);
                });
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_console_stream_lifecycle_waits_for_end_close_and_timeout(self):
        chunk = extract_chunk("function tailText", "function runCommand")
        script = (
            dedent(
                """
                const assert = require("assert");
                const {EventEmitter} = require("events");
                const source = 'const { StringDecoder } = require("node:string_decoder");\\n' + __SOURCE__;
                const factory = new Function(
                  source + "\\nreturn { attachSanitizedConsoleStream, stopServer };"
                );
                const api = factory();

                const makeStream = () => {
                  const stream = new EventEmitter();
                  stream.setEncoding = () => {};
                  return stream;
                };

                const makeServer = (stdoutBridge, stderrBridge, events) => ({
                  child: {
                    exitCode: 0,
                    signalCode: null,
                    kill: () => events.push("kill"),
                  },
                  exited: Promise.resolve({code: 0, signal: null}),
                  consoleClosed: Promise.all([stdoutBridge.done, stderrBridge.done]),
                  forceConsoleClose: () => {
                    events.push("forceConsoleClose");
                    stdoutBridge.finish();
                    stderrBridge.finish();
                  },
                  closeLog: async () => {
                    events.push("closeLog");
                  },
                });

                const runScenario = async ({steps, consoleGraceMs = 20}) => {
                  const stdout = makeStream();
                  const stderr = makeStream();
                  const stdoutWrites = [];
                  const stderrWrites = [];
                  const events = [];
                  const stdoutBridge = api.attachSanitizedConsoleStream(stdout, (text) => stdoutWrites.push(text));
                  const stderrBridge = api.attachSanitizedConsoleStream(stderr, (text) => stderrWrites.push(text));
                  const server = makeServer(stdoutBridge, stderrBridge, events);
                  const stopPromise = api.stopServer(server, {consoleGraceMs});

                  for (const step of steps) {
                    const stream = step.stream === "stdout" ? stdout : stderr;
                    stream.emit(step.event, step.value);
                  }

                  await stopPromise;
                  return {stdoutWrites, stderrWrites, events, stdoutBridge, stderrBridge};
                };

                (async () => {
                  try {
                    const scenario1 = await runScenario({
                      steps: [
                        {stream: "stdout", event: "data", value: "sess"},
                        {stream: "stderr", event: "data", value: "Linea normal sin secretos\\n"},
                        {stream: "stdout", event: "data", value: "ion_token=abc\\n"},
                        {stream: "stdout", event: "end"},
                        {stream: "stdout", event: "close"},
                        {stream: "stderr", event: "end"},
                        {stream: "stderr", event: "close"},
                      ],
                    });
                    assert.deepStrictEqual(scenario1.stdoutWrites, ["session_token=REDACTED\\n"]);
                    assert.deepStrictEqual(scenario1.stderrWrites, ["Linea normal sin secretos\\n"]);
                    assert.ok(!scenario1.stdoutWrites.join("").includes("session_token=abc"));
                    assert.ok(!scenario1.stdoutWrites.join("").includes("user:pass@"));
                    assert.ok(!scenario1.stderrWrites.join("").includes("Authorization: Bearer abc"));
                    assert.ok(!scenario1.stderrWrites.join("").includes("Cookie: session=abc"));
                    assert.ok(scenario1.events.includes("closeLog"));

                    const scenario2 = await runScenario({
                      steps: [
                        {stream: "stdout", event: "data", value: "final without newline"},
                        {stream: "stderr", event: "data", value: "Cookie: sess"},
                        {stream: "stderr", event: "data", value: "ion=abc\\n"},
                        {stream: "stdout", event: "close"},
                        {stream: "stderr", event: "close"},
                      ],
                    });
                    assert.deepStrictEqual(scenario2.stdoutWrites, ["final without newline"]);
                    assert.deepStrictEqual(scenario2.stderrWrites, ["Cookie: REDACTED\\n"]);
                    scenario2.stdoutBridge.finish();
                    scenario2.stdoutBridge.finish();
                    scenario2.stderrBridge.finish();
                    scenario2.stderrBridge.finish();
                    assert.deepStrictEqual(scenario2.stdoutWrites, ["final without newline"]);
                    assert.deepStrictEqual(scenario2.stderrWrites, ["Cookie: REDACTED\\n"]);
                    assert.ok(scenario2.events.includes("closeLog"));

                    const scenario3 = await runScenario({
                      steps: [
                        {stream: "stdout", event: "data", value: "stdout-line-1\\n"},
                        {stream: "stdout", event: "end"},
                        {stream: "stdout", event: "close"},
                        {stream: "stderr", event: "data", value: "Authoriza"},
                        {stream: "stderr", event: "data", value: "tion: Bearer abc\\n"},
                        {stream: "stderr", event: "end"},
                        {stream: "stderr", event: "close"},
                      ],
                    });
                    assert.deepStrictEqual(scenario3.stdoutWrites, ["stdout-line-1\\n"]);
                    assert.deepStrictEqual(scenario3.stderrWrites, ["Authorization: REDACTED\\n"]);
                    assert.ok(!scenario3.stdoutWrites.join("").includes("Authorization: Bearer abc"));
                    assert.ok(!scenario3.stderrWrites.join("").includes("session_token=abc"));
                    assert.ok(scenario3.events.includes("closeLog"));

                    const scenario4 = await runScenario({
                      consoleGraceMs: 5,
                      steps: [
                        {stream: "stdout", event: "data", value: "sess"},
                        {stream: "stdout", event: "data", value: "ion_token=abc"},
                        {stream: "stderr", event: "data", value: "Authorization: Bearer abc"},
                      ],
                    });
                    assert.deepStrictEqual(scenario4.stdoutWrites, ["session_token=REDACTED"]);
                    assert.deepStrictEqual(scenario4.stderrWrites, ["Authorization: REDACTED"]);
                    assert.ok(scenario4.events.includes("forceConsoleClose"));
                    scenario4.stdoutBridge.finish();
                    scenario4.stderrBridge.finish();
                    assert.deepStrictEqual(scenario4.stdoutWrites, ["session_token=REDACTED"]);
                    assert.deepStrictEqual(scenario4.stderrWrites, ["Authorization: REDACTED"]);
                    assert.ok(!scenario4.stdoutWrites.join("").includes("session_token=abc"));
                    assert.ok(!scenario4.stderrWrites.join("").includes("Authorization: Bearer abc"));
                  } finally {
                    // No-op: each scenario tears down its own listeners.
                  }
                })().catch((error) => {
                  console.error(error && error.stack ? error.stack : error);
                  process.exit(1);
                });
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_stop_server_timeout_disables_raw_log_capture_before_close(self):
        chunk = extract_chunk("function removeStreamListener", "function runCommand")
        script = (
            dedent(
                """
                const assert = require("assert");
                const {EventEmitter} = require("events");
                const source = 'const { StringDecoder } = require("node:string_decoder");\\n' + __SOURCE__;
                const factory = new Function(source + "\\nreturn { attachRawLogCapture, stopServer };");
                const api = factory();

                const makeStream = () => {
                  const stream = new EventEmitter();
                  stream.setEncoding = () => {};
                  return stream;
                };

                const stdout = makeStream();
                const stderr = makeStream();
                const child = {
                  stdout,
                  stderr,
                  exitCode: null,
                  signalCode: null,
                  kill(signal) {
                    this.exitCode = 0;
                    this.signalCode = signal || null;
                  },
                };

                const logWrites = [];
                let logEnded = 0;
                const events = [];
                const logStream = {
                  write(chunk) {
                    if (logEnded) {
                      throw new Error("write after end");
                    }
                    logWrites.push(String(chunk));
                  },
                  end(callback) {
                    logEnded += 1;
                    events.push("log-end");
                    if (typeof callback === "function") {
                      callback();
                    }
                  },
                };

                const bridge = api.attachRawLogCapture(child, logStream);
                let resolveConsoleClosed;
                const consoleClosed = new Promise((resolve) => {
                  resolveConsoleClosed = resolve;
                });
                const server = {
                  child,
                  exited: Promise.resolve({code: 0, signal: null}),
                  consoleClosed,
                  forceConsoleClose() {
                    events.push("forceConsoleClose");
                    bridge.stop();
                    resolveConsoleClosed("forced");
                  },
                  stopRawLogCapture() {
                    events.push("stopRawLogCapture");
                    bridge.stop();
                  },
                  closeLog() {
                    events.push("closeLog");
                    return bridge.closeLog();
                  },
                };

                (async () => {
                  try {
                    const stopPromise1 = api.stopServer(server, {consoleGraceMs: 500, graceMs: 500});
                    stdout.emit("data", "stdout-before-timeout\\n");
                    stderr.emit("data", "stderr-before-timeout\\n");
                    setTimeout(() => {
                      stdout.emit("data", "late-stdout\\n");
                      stderr.emit("data", "late-stderr\\n");
                      stdout.emit("close");
                      stderr.emit("close");
                    }, 650);
                    await stopPromise1;

                    const stopPromise2 = api.stopServer(server, {consoleGraceMs: 500, graceMs: 500});
                    await stopPromise2;

                    await bridge.closeLog();
                    await bridge.closeLog();

                    assert.deepStrictEqual(logWrites, [
                      "stdout-before-timeout\\n",
                      "stderr-before-timeout\\n",
                    ]);
                    assert.strictEqual(logEnded, 1);
                    assert.ok(bridge.isClosed());
                    assert.ok(events.includes("stopRawLogCapture"));
                    assert.ok(events.includes("forceConsoleClose"));
                    assert.ok(events.includes("log-end"));
                    assert.ok(!logWrites.join("").includes("late-stdout"));
                    assert.ok(!logWrites.join("").includes("late-stderr"));
                  } catch (error) {
                    console.error(error && error.stack ? error.stack : error);
                    process.exit(1);
                  }
                })().catch((error) => {
                  console.error(error && error.stack ? error.stack : error);
                  process.exit(1);
                });
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_run_command_captures_and_sanitizes_lhci_output(self):
        chunk = extract_chunk("function tailText", "(async () => {")
        script = (
            dedent(
                """
                const assert = require("assert");
                const source = 'const { StringDecoder } = require("node:string_decoder");\\n' + __SOURCE__;
                const factory = new Function(
                  "process",
                  "require",
                  "spawn",
                  source + "\\nreturn { runCommand };"
                );
                const api = factory(process, require, require("child_process").spawn);

                const childScript = [
                  'const mode = process.env.RUN_MODE;',
                  'process.stdout.write("Running Lighthouse 3 time(s) on\\\\n");',
                  'process.stdout.write("Run #1\\\\nRun #2\\\\n");',
                  'process.stdout.write("http://user:pass@localhost:64965/path?to");',
                  'process.stdout.write("ken=abc&swcleared=1#frag\\\\n");',
                  'process.stderr.write("Authorization: Bearer ");',
                  'process.stderr.write("abc\\\\n");',
                  'process.stderr.write("Cookie: sess");',
                  'process.stderr.write("ion=abc\\\\n");',
                  'process.stderr.write("http://user:pass@localhost:64965/path?oauth_");',
                  'process.stderr.write("token=abc\\\\n");',
                  'process.stdout.write("Final stdout line without newline");',
                  'process.stderr.write("Final stderr line without newline");',
                  'process.exitCode = mode === "failure" ? 7 : 0;',
                ].join("\\n");

                const captureRunCommand = async (runMode) => {
                  const stdoutWrites = [];
                  const stderrWrites = [];
                  const originalStdoutWrite = process.stdout.write;
                  const originalStderrWrite = process.stderr.write;
                  process.stdout.write = (chunk, encoding, callback) => {
                    stdoutWrites.push(String(chunk));
                    if (typeof callback === "function") callback();
                    return true;
                  };
                  process.stderr.write = (chunk, encoding, callback) => {
                    stderrWrites.push(String(chunk));
                    if (typeof callback === "function") callback();
                    return true;
                  };
                  try {
                    const result = await api.runCommand(
                      process.execPath,
                      ["-e", childScript],
                      {...process.env, RUN_MODE: runMode},
                      {captureOutput: true}
                    );
                    return {stdoutWrites, stderrWrites, result, error: null};
                  } catch (error) {
                    return {stdoutWrites, stderrWrites, result: null, error};
                  } finally {
                    process.stdout.write = originalStdoutWrite;
                    process.stderr.write = originalStderrWrite;
                  }
                };

                (async () => {
                  try {
                    const success = await captureRunCommand("success");
                    assert.deepStrictEqual(success.result, {code: 0, signal: null});
                    assert.strictEqual(success.error, null);
                    assert.deepStrictEqual(success.stdoutWrites, [
                      "Running Lighthouse 3 time(s) on\\n",
                      "Run #1\\n",
                      "Run #2\\n",
                      "http://localhost:64965/path?token=REDACTED&swcleared=1#frag\\n",
                      "Final stdout line without newline",
                    ]);
                    assert.deepStrictEqual(success.stderrWrites, [
                      "Authorization: REDACTED\\n",
                      "Cookie: REDACTED\\n",
                      "http://localhost:64965/path?oauth_token=REDACTED\\n",
                      "Final stderr line without newline",
                    ]);
                    assert.ok(!success.stdoutWrites.join("").includes("user:pass@"));
                    assert.ok(!success.stdoutWrites.join("").includes("token=abc"));
                    assert.ok(!success.stdoutWrites.join("").includes("session_token=abc"));
                    assert.ok(!success.stdoutWrites.join("").includes("oauth_token=abc"));
                    assert.ok(!success.stderrWrites.join("").includes("Authorization: Bearer abc"));
                    assert.ok(!success.stderrWrites.join("").includes("Cookie: session=abc"));
                    assert.ok(success.stdoutWrites.join("").includes("swcleared=1"));
                    assert.ok(success.stdoutWrites.join("").includes("Run #1"));
                    assert.ok(success.stdoutWrites.join("").includes("Run #2"));

                    const failure = await captureRunCommand("failure");
                    assert.strictEqual(failure.result, null);
                    assert.ok(failure.error);
                    assert.strictEqual(failure.error.code, 7);
                    assert.deepStrictEqual(failure.stdoutWrites, success.stdoutWrites);
                    assert.deepStrictEqual(failure.stderrWrites, success.stderrWrites);

                    await assert.rejects(
                      api.runCommand("__definitely_missing_command__", [], process.env, {captureOutput: true}),
                      (error) => Boolean(error && (error.code === "ENOENT" || String(error.message || "").includes("ENOENT")))
                    );
                  } catch (error) {
                    console.error(error && error.stack ? error.stack : error);
                    process.exit(1);
                  }
                })();
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_lighthouse_run_command_sanitizes_sensitive_external_base_url_output(self):
        node = shutil.which("node")
        npm = shutil.which("npm")
        if not node or not npm:
            raise unittest.SkipTest("node o npm no están disponibles")

        server, thread = self._start_external_http_server()
        temp_dir = tempfile.mkdtemp(prefix="lhci-runcommand-")
        try:
            port = server.server_address[1]
            env = os.environ.copy()
            env["LHCI_BASE_URL"] = f"http://user:pass@127.0.0.1:{port}/path?token=abc#frag"
            env["LHCI_TMPDIR"] = temp_dir
            proc = subprocess.run(
                [npm, "run", "lighthouse"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=240,
            )
            combined = f"{proc.stdout}{proc.stderr}"
            assert proc.returncode == 0, (
                "npm run lighthouse falló\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}"
            )
            assert "user:pass@" not in combined
            assert "token=abc" not in combined
            assert "session_token=abc" not in combined
            assert "oauth_token=abc" not in combined
            assert "Authorization: Bearer abc" not in combined
            assert "Cookie: session=abc" not in combined
            assert "http://127.0.0.1:" in combined
            assert "token=REDACTED" in combined
            assert "swcleared=1" in combined
            assert "Running Lighthouse 3 time(s) on" in combined
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_browser_diagnostic_records_events_with_mock_puppeteer_core(self):
        chunk = extract_chunk("const DIAGNOSTIC_REDACTED_VALUE", "function describeStatus")
        script = (
            dedent(
                """
                const assert = require("assert");
                const fs = require("fs");
                const os = require("os");
                const path = require("path");
                const Module = require("module");
                const {EventEmitter} = require("events");
                const source = 'const { StringDecoder } = require("node:string_decoder");\\n' + __SOURCE__;
                const factory = new Function(
                  "require",
                  "fs",
                  "path",
                  "Module",
                  "EventEmitter",
                  source + "\\nreturn { runBrowserDiagnostic, sanitizeDiagnosticValue };"
                );
                const api = factory(require, fs, path, Module, EventEmitter);

                const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "lhci-browser-diag-"));
                const logPath = path.join(tempDir, "navigation-diagnostic.log");
                fs.writeFileSync(logPath, "");
                const recorder = {
                  diagnosticPath: logPath,
                  record(event, data = {}) {
                    const entry = api.sanitizeDiagnosticValue({event, ...data});
                    fs.appendFileSync(logPath, `${JSON.stringify(entry)}\\n`);
                    return entry;
                  },
                };
                const originalLoad = Module._load;
                const originalSetTimeout = global.setTimeout;
                let launchCalls = 0;
                const navigationUrl = "https://user:pass@example.test/path?oauth_token=abc&session_token=abc";
                const finalUrl = "https://user:pass@example.test/path?oauth_token=abc&session_token=abc#frag";
                const mainFrame = {
                  url: () => finalUrl,
                  name: () => "",
                };
                const browser = new EventEmitter();
                const pageState = {
                  handlers: Object.create(null),
                  currentUrl: "about:blank",
                };
                const request = {
                  url: () => navigationUrl,
                  method: () => "GET",
                  resourceType: () => "document",
                  isNavigationRequest: () => true,
                  frame: () => ({url: () => "about:blank"}),
                  redirectChain: () => [],
                };
                const response = {
                  request: () => request,
                  headers: () => ({
                    "content-type": "text/html; charset=utf-8",
                    "content-length": "12",
                    location: navigationUrl,
                  }),
                  status: () => 200,
                  url: () => navigationUrl,
                  fromCache: () => false,
                };
                const page = {
                  on(event, handler) {
                    pageState.handlers[event] = handler;
                  },
                  mainFrame() {
                    return mainFrame;
                  },
                  url() {
                    return pageState.currentUrl;
                  },
                  goto: async (url, options) => {
                    assert.strictEqual(url, navigationUrl);
                    assert.deepStrictEqual(options, {waitUntil: "domcontentloaded", timeout: 30000});
                    pageState.handlers.request(request);
                    pageState.handlers.response(response);
                    pageState.handlers.console({
                      type: () => "warn",
                      text: () => "Authorization: Bearer abc Cookie: session=abc",
                    });
                    pageState.handlers.pageerror(new Error("pageerror token=abc"));
                    pageState.currentUrl = finalUrl;
                    pageState.handlers.framenavigated(mainFrame);
                    browser.emit("targetchanged", {
                      type: () => "page",
                      url: () => finalUrl,
                    });
                    return response;
                  },
                };

                browser.newPage = async () => page;
                browser.close = async () => {};

                Module._load = function(request, parent, isMain) {
                  if (request === "puppeteer-core") {
                    return {
                      launch: async (options) => {
                        launchCalls += 1;
                        assert.strictEqual(options.executablePath, "/fake/chrome");
                        assert.ok(options.args.includes("--no-sandbox"));
                        return browser;
                      },
                    };
                  }
                  return originalLoad.apply(this, arguments);
                };
                global.setTimeout = (fn) => {
                  fn();
                  return 0;
                };

                (async () => {
                  try {
                    const result = await api.runBrowserDiagnostic(navigationUrl, "/fake/chrome", tempDir, recorder);
                    assert.strictEqual(launchCalls, 1);
                    assert.strictEqual(
                      result.finalUrl,
                      "https://example.test/path?oauth_token=REDACTED&session_token=REDACTED#frag"
                    );
                    const log = fs.readFileSync(logPath, "utf8");
                    assert.ok(log.includes('"event":"browser-start"'));
                    assert.ok(log.includes('"event":"request"'));
                    assert.ok(log.includes('"event":"response"'));
                    assert.ok(log.includes('"event":"framenavigated"'));
                    assert.ok(log.includes('"event":"console"'));
                    assert.ok(log.includes('"event":"targetchanged"'));
                    assert.ok(!log.includes("oauth_token=abc"));
                    assert.ok(!log.includes("session_token=abc"));
                    assert.ok(!log.includes("user:pass@"));
                    assert.ok(!log.includes("Authorization: Bearer abc"));
                    assert.ok(!log.includes("Cookie: session=abc"));
                  } finally {
                    global.setTimeout = originalSetTimeout;
                    Module._load = originalLoad;
                  }
                })().catch((error) => {
                  console.error(error && error.stack ? error.stack : error);
                  process.exit(1);
                });
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_browser_diagnostic_warns_when_puppeteer_core_is_unavailable(self):
        chunk = extract_chunk("const DIAGNOSTIC_REDACTED_VALUE", "function describeStatus")
        script = (
            dedent(
                """
                const assert = require("assert");
                const fs = require("fs");
                const os = require("os");
                const path = require("path");
                const Module = require("module");
                const source = 'const { StringDecoder } = require("node:string_decoder");\\n' + __SOURCE__;
                const factory = new Function(
                  "require",
                  "fs",
                  "path",
                  "Module",
                  source + "\\nreturn { runBrowserDiagnostic, sanitizeDiagnosticValue };"
                );
                const api = factory(require, fs, path, Module);

                const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "lhci-browser-missing-"));
                const logPath = path.join(tempDir, "navigation-diagnostic.log");
                fs.writeFileSync(logPath, "");
                const recorder = {
                  diagnosticPath: logPath,
                  record(event, data = {}) {
                    const entry = api.sanitizeDiagnosticValue({event, ...data});
                    fs.appendFileSync(logPath, `${JSON.stringify(entry)}\\n`);
                    return entry;
                  },
                };
                const originalLoad = Module._load;
                const originalWarn = console.warn;
                const warnings = [];
                Module._load = function(request, parent, isMain) {
                  if (request === "puppeteer-core") {
                    throw new Error("Cannot find module 'puppeteer-core'");
                  }
                  return originalLoad.apply(this, arguments);
                };
                console.warn = (...args) => {
                  warnings.push(args.join(" "));
                };

                (async () => {
                  try {
                    const result = await api.runBrowserDiagnostic("https://example.test/", "/fake/chrome", tempDir, recorder);
                    assert.strictEqual(result, null);
                    const log = fs.readFileSync(logPath, "utf8");
                    assert.ok(log.includes('"event":"browser-warning"'));
                    assert.ok(log.includes('"phase":"require"'));
                    assert.ok(warnings.some((line) => line.includes("puppeteer-core no disponible")));
                  } finally {
                    console.warn = originalWarn;
                    Module._load = originalLoad;
                  }
                })().catch((error) => {
                  console.error(error && error.stack ? error.stack : error);
                  process.exit(1);
                });
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_diagnostic_matrix_mode_is_disabled_by_default_and_builds_four_cases(self):
        chunk = extract_chunk("const DIAGNOSTIC_REDACTED_VALUE", "function describeStatus")
        script = (
            dedent(
                """
                const assert = require("assert");
                const source = [
                  'function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }',
                  'function readDiagnosticFileText(filePath) { try { return String(fs.readFileSync(filePath, "utf8") || ""); } catch { return ""; } }',
                  'const { StringDecoder } = require("node:string_decoder");',
                  'const { ensureSwClearedUrl } = require("./scripts/lighthouse-url.cjs");',
                  __SOURCE__,
                ].join("\\n");
                const factory = new Function(source + "\\nreturn { isTruthyEnvFlag, isDiagnosticMatrixEnabled, buildDiagnosticMatrixCases };");
                const api = factory();
                const originalEnv = process.env.LHCI_DIAGNOSTIC_MATRIX;

                try {
                  delete process.env.LHCI_DIAGNOSTIC_MATRIX;
                  assert.strictEqual(api.isTruthyEnvFlag(process.env.LHCI_DIAGNOSTIC_MATRIX), false);
                  assert.strictEqual(api.isDiagnosticMatrixEnabled(), false);
                  process.env.LHCI_DIAGNOSTIC_MATRIX = "1";
                  assert.strictEqual(api.isDiagnosticMatrixEnabled(), true);

                  const cases = api.buildDiagnosticMatrixCases("http://user:pass@example.test/path?foo=1&swcleared=1#frag");
                  assert.deepStrictEqual(cases.map((item) => item.id), ["A", "B", "C", "D"]);
                  assert.strictEqual(cases[0].url, "http://user:pass@example.test/path?foo=1#frag");
                  assert.strictEqual(cases[1].url, "http://user:pass@example.test/path?foo=1&swcleared=1#frag");
                  assert.strictEqual(cases[2].url, "http://user:pass@example.test/kiosk");
                  assert.strictEqual(cases[3].url, "http://user:pass@example.test/kiosk?swcleared=1");
                } finally {
                  if (originalEnv === undefined) {
                    delete process.env.LHCI_DIAGNOSTIC_MATRIX;
                  } else {
                    process.env.LHCI_DIAGNOSTIC_MATRIX = originalEnv;
                  }
                }
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_diagnostic_matrix_runs_all_cases_and_writes_artifacts_with_independent_profiles(self):
        chunk = extract_chunk("const DIAGNOSTIC_REDACTED_VALUE", "function describeStatus")
        script = (
            dedent(
                """
                const assert = require("assert");
                const fs = require("fs");
                const os = require("os");
                const path = require("path");
                const Module = require("module");
                const {EventEmitter} = require("events");
                let spawnSync = require("child_process").spawnSync;
                const source = [
                  'function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }',
                  'function readDiagnosticFileText(filePath) { try { return String(fs.readFileSync(filePath, "utf8") || ""); } catch { return ""; } }',
                  'const { StringDecoder } = require("node:string_decoder");',
                  'const { ensureSwClearedUrl } = require("./scripts/lighthouse-url.cjs");',
                  __SOURCE__,
                ].join("\\n");
                const factory = new Function(
                  "require",
                  "fs",
                  "path",
                  "Module",
                  "EventEmitter",
                  "process",
                  "console",
                  "setTimeout",
                  source + "\\nreturn { runDiagnosticMatrix, buildDiagnosticMatrixCases };"
                );
                const api = factory(require, fs, path, Module, EventEmitter, process, console, setTimeout);

                const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "lhci-matrix-"));
                const launchCalls = [];
                const lighthouseCalls = [];
                const originalLoad = Module._load;
                const originalSetTimeout = global.setTimeout;
                const originalSpawnSync = spawnSync;
                const originalEnv = process.env.LHCI_DIAGNOSTIC_MATRIX;
                process.env.LHCI_DIAGNOSTIC_MATRIX = "1";

                const makeRequest = (url, failed = false) => ({
                  url: () => url,
                  method: () => "GET",
                  resourceType: () => "document",
                  isNavigationRequest: () => true,
                  frame: () => ({url: () => "about:blank"}),
                  redirectChain: () => [],
                  failure: () => (failed ? {errorText: "net::ERR_ABORTED"} : {}),
                });
                const makeResponse = (url) => ({
                  request: () => makeRequest(url),
                  headers: () => ({
                    "content-type": "text/html; charset=utf-8",
                    "content-length": "12",
                  }),
                  status: () => 200,
                  url: () => url,
                  fromCache: () => false,
                });
                const makeBrowser = (launchOptions) => {
                  const browser = new EventEmitter();
                  const page = new EventEmitter();
                  let currentUrl = "about:blank";
                  page.url = () => currentUrl;
                  page.mainFrame = () => ({url: () => currentUrl, name: () => ""});
                  page.goto = async (url) => {
                    currentUrl = url;
                    page.emit("request", makeRequest(url, launchOptions.userDataDir.includes("/B/")));
                    page.emit("domcontentloaded");
                    if (launchOptions.userDataDir.includes("/B/")) {
                      page.emit("requestfailed", makeRequest(url, true));
                      throw new Error("net::ERR_ABORTED");
                    }
                    page.emit("response", makeResponse(url));
                    page.emit("framenavigated", {url: () => url, name: () => ""});
                    page.emit("console", {type: () => "warn", text: () => "Authorization: Bearer abc Cookie: session=abc"});
                    page.emit("pageerror", new Error("pageerror token=abc"));
                    page.emit("load");
                    return makeResponse(url);
                  };
                  browser.process = () => ({pid: launchCalls.length + 4100});
                  browser.wsEndpoint = () => `ws://127.0.0.1:${launchCalls.length + 6100}/devtools/browser/test`;
                  browser.version = async () => "HeadlessChrome/143.0.0.0";
                  browser.newPage = async () => page;
                  browser.close = async () => {
                    page.emit("close");
                    browser.emit("disconnected");
                  };
                  return browser;
                };
                const mockLighthouse = async (url, flags, config) => {
                  lighthouseCalls.push({url, flags, config});
                  if (url.includes("/kiosk") && !url.includes("swcleared=1")) {
                    return {
                      lhr: {
                        userAgent: "HeadlessChrome/143.0.0.0",
                        requestedUrl: url,
                        finalUrl: url,
                        finalDisplayedUrl: url,
                        runtimeError: {
                          code: "FAILED_DOCUMENT_REQUEST",
                          message: "net::ERR_ABORTED",
                        },
                      },
                    };
                  }
                  return {
                    lhr: {
                      userAgent: "HeadlessChrome/143.0.0.0",
                      requestedUrl: url,
                      finalUrl: url,
                      finalDisplayedUrl: url,
                      runtimeError: null,
                    },
                  };
                };

                Module._load = function(request, parent, isMain) {
                  if (request === "puppeteer-core") {
                    return {
                      launch: async (options) => {
                        launchCalls.push({kind: "puppeteer", options});
                        return makeBrowser(options);
                      },
                    };
                  }
                  if (request === "chrome-launcher") {
                    return {
                      launch: async (options) => {
                        launchCalls.push({kind: "chrome-launcher", options});
                        return {
                          pid: launchCalls.length + 5100,
                          port: 9330 + launchCalls.length,
                          kill: async () => {
                            launchCalls.push({kind: "kill", options});
                          },
                        };
                      },
                    };
                  }
                  if (request === "lighthouse") {
                    return {
                      default: mockLighthouse,
                      defaultConfig: {},
                    };
                  }
                  return originalLoad.apply(this, arguments);
                };
                spawnSync = (command, args) => {
                  if (command === "curl") {
                    const target = String(args[args.length - 1] || "");
                    const noProxy = args.includes("--noproxy");
                    const stderr = noProxy
                      ? "* Connected to example.test (127.0.0.1) port 7777 (#0)"
                      : "* Connected to proxy.example (127.0.0.1) port 8080 (#0)";
                    const stdout = `\n200`;
                    return {
                      stdout,
                      stderr,
                      status: 0,
                      signal: null,
                      error: null,
                    };
                  }
                  return originalSpawnSync(command, args);
                };
                global.setTimeout = (fn) => {
                  fn();
                  return 0;
                };

                (async () => {
                  try {
                    const matrix = await api.runDiagnosticMatrix({
                      auditUrl: "http://user:pass@example.test/path?foo=1&swcleared=1#frag",
                      tempDir,
                      chromePath: "/fake/chrome",
                    });

                    assert.strictEqual(matrix.exitCode, 1);
                    assert.strictEqual(matrix.cases.length, 4);
                    assert.ok(matrix.auditUrl.includes("swcleared=1"));
                    assert.ok(!matrix.auditUrl.includes("user:pass@"));
                    assert.ok(matrix.cases[0].directNavigation.exitCode === 0);
                    assert.ok(matrix.cases[1].directNavigation.exitCode === 1);
                    assert.ok(matrix.cases[2].lighthouse.exitCode === 1);
                    assert.ok(matrix.cases[3].lighthouse.exitCode === 0);
                    assert.ok(matrix.environment.platform);
                    assert.ok(matrix.environment.arch);
                    assert.ok(matrix.environment.nodeVersion);
                    assert.strictEqual(matrix.probes.length, 4);
                    assert.ok(matrix.netLogSummary.jsonPath.includes("lighthouse-netlog-summary.json"));
                    assert.ok(matrix.netLogSummary.logPath.includes("lighthouse-netlog-summary.log"));

                    const directProfiles = launchCalls
                      .filter((entry) => entry.kind === "puppeteer")
                      .filter((entry) => String(entry.options.userDataDir || "").includes("direct-profile"))
                      .map((entry) => entry.options.userDataDir);
                    const lighthouseProfiles = launchCalls
                      .filter((entry) => entry.kind === "puppeteer")
                      .filter((entry) => String(entry.options.userDataDir || "").includes("lighthouse-profile"))
                      .map((entry) => entry.options.userDataDir);
                    assert.strictEqual(directProfiles.length, 4);
                    assert.strictEqual(lighthouseProfiles.length, 4);
                    assert.strictEqual(new Set(directProfiles).size, 4);
                    assert.strictEqual(new Set(lighthouseProfiles).size, 4);
                    const directLaunches = launchCalls.filter((entry) => entry.kind === "puppeteer" && String(entry.options.userDataDir || "").includes("direct-profile"));
                    const lighthouseLaunches = launchCalls.filter((entry) => entry.kind === "puppeteer" && String(entry.options.userDataDir || "").includes("lighthouse-profile"));
                    assert.ok(directLaunches.every((entry) => entry.options.args.some((arg) => String(arg).startsWith("--log-net-log="))));
                    assert.ok(directLaunches.every((entry) => entry.options.args.includes("--net-log-capture-mode=Everything")));
                    assert.ok(lighthouseLaunches.every((entry) => entry.options.args.some((arg) => String(arg).startsWith("--log-net-log="))));
                    assert.ok(lighthouseLaunches.every((entry) => entry.options.args.includes("--net-log-capture-mode=Everything")));

                    const jsonPath = path.join(tempDir, "lighthouse-diagnostic-matrix.json");
                    const logPath = path.join(tempDir, "lighthouse-diagnostic-matrix.log");
                    assert.ok(fs.existsSync(jsonPath));
                    assert.ok(fs.existsSync(logPath));
                    const jsonText = fs.readFileSync(jsonPath, "utf8");
                    const logText = fs.readFileSync(logPath, "utf8");
                    assert.ok(jsonText.includes('"id": "A"'));
                    assert.ok(jsonText.includes('"id": "B"'));
                    assert.ok(jsonText.includes('"id": "C"'));
                    assert.ok(jsonText.includes('"id": "D"'));
                    assert.ok(logText.includes("case-A-direct-request"));
                    assert.ok(logText.includes("case-B-direct-requestfailed"));
                    assert.ok(logText.includes("case-C-lighthouse-lighthouse-summary"));
                    assert.ok(logText.includes("case-D-lighthouse-lighthouse-summary"));
                    assert.ok(logText.includes("case-A-direct-lighthouse-error") || logText.includes("case-A-direct-browser-start"));
                    assert.ok(jsonText.includes('"environment"'));
                    assert.ok(jsonText.includes('"probes"'));
                    assert.ok(jsonText.includes('"serverObservations"'));
                    assert.ok(jsonText.includes('"directNetLogPath"'));
                    assert.ok(jsonText.includes('"lighthouseNetLogPath"'));
                    assert.ok(!jsonText.includes("user:pass@"));
                    assert.ok(!jsonText.includes("token=abc"));
                    assert.ok(!logText.includes("user:pass@"));
                    assert.ok(!logText.includes("token=abc"));
                    assert.ok(logText.includes("domcontentloaded"));
                    assert.ok(logText.includes("load"));
                  } finally {
                    Module._load = originalLoad;
                    global.setTimeout = originalSetTimeout;
                    spawnSync = originalSpawnSync;
                    if (originalEnv === undefined) {
                      delete process.env.LHCI_DIAGNOSTIC_MATRIX;
                    } else {
                      process.env.LHCI_DIAGNOSTIC_MATRIX = originalEnv;
                    }
                  }
                })().catch((error) => {
                  console.error(error && error.stack ? error.stack : error);
                  process.exit(1);
                });
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_browser_matrix_mode_is_disabled_by_default_and_builds_four_variants(self):
        chunk = extract_chunk("const DIAGNOSTIC_REDACTED_VALUE", "function describeStatus")
        script = (
            dedent(
                """
                const assert = require("assert");
                const source = [
                  'const { StringDecoder } = require("node:string_decoder");',
                  'const { ensureSwClearedUrl } = require("./scripts/lighthouse-url.cjs");',
                  __SOURCE__,
                ].join("\\n");
                const factory = new Function(
                  source + "\\nreturn { isBrowserMatrixDiagnosticEnabled, buildBrowserMatrixVariants };"
                );
                const api = factory();
                const originalEnv = process.env.LHCI_BROWSER_MATRIX_DIAGNOSTIC;

                try {
                  delete process.env.LHCI_BROWSER_MATRIX_DIAGNOSTIC;
                  assert.strictEqual(api.isBrowserMatrixDiagnosticEnabled(), false);
                  process.env.LHCI_BROWSER_MATRIX_DIAGNOSTIC = "1";
                  assert.strictEqual(api.isBrowserMatrixDiagnosticEnabled(), true);

                  const variants = api.buildBrowserMatrixVariants("/tmp/current-chrome", {
                    LHCI_BROWSER_MATRIX_V2_PATH: "/tmp/google-chrome-stable",
                    LHCI_BROWSER_MATRIX_V3_PATH: "/tmp/chromium-previous",
                    LHCI_BROWSER_MATRIX_V4_PATH: "/tmp/chrome-beta",
                  });

                  assert.deepStrictEqual(variants.map((variant) => variant.id), ["V1", "V2", "V3", "V4"]);
                  assert.strictEqual(variants[0].executablePath, "/tmp/current-chrome");
                  assert.strictEqual(variants[1].executablePath, "/tmp/google-chrome-stable");
                  assert.strictEqual(variants[2].executablePath, "/tmp/chromium-previous");
                  assert.strictEqual(variants[3].executablePath, "/tmp/chrome-beta");
                  assert.strictEqual(variants[0].captureStrace, true);
                  assert.strictEqual(variants[1].captureStrace, true);
                  assert.strictEqual(variants[2].captureStrace, false);
                  assert.strictEqual(variants[3].captureStrace, false);
                } finally {
                  if (originalEnv === undefined) {
                    delete process.env.LHCI_BROWSER_MATRIX_DIAGNOSTIC;
                  } else {
                    process.env.LHCI_BROWSER_MATRIX_DIAGNOSTIC = originalEnv;
                  }
                }
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_fd_inheritance_mode_is_disabled_by_default_and_builds_five_variants(self):
        chunk = extract_chunk("function isTruthyEnvFlag", "function buildBrowserMatrixVariants")
        script = (
            dedent(
                """
                const assert = require("assert");
                const source = [
                  'const { StringDecoder } = require("node:string_decoder");',
                  'const { ensureSwClearedUrl } = require("./scripts/lighthouse-url.cjs");',
                  'const sanitizeDiagnosticText = (value) => String(value || "").trim();',
                  __SOURCE__,
                ].join("\\n");
                const factory = new Function(
                  source + "\\nreturn { isFdInheritanceDiagnosticEnabled, buildFdInheritanceMatrixVariants, buildFdInheritanceMatrixArtifacts };"
                );
                const api = factory();
                const originalEnv = process.env.LHCI_FD_INHERITANCE_DIAGNOSTIC;

                try {
                  delete process.env.LHCI_FD_INHERITANCE_DIAGNOSTIC;
                  assert.strictEqual(api.isFdInheritanceDiagnosticEnabled(), false);
                  process.env.LHCI_FD_INHERITANCE_DIAGNOSTIC = "1";
                  assert.strictEqual(api.isFdInheritanceDiagnosticEnabled(), true);

                  const variants = api.buildFdInheritanceMatrixVariants("/tmp/current-chrome");
                  assert.deepStrictEqual(variants.map((variant) => variant.id), ["F1", "F2", "F3", "F4", "F5"]);
                  assert.strictEqual(variants[0].launcherKind, "direct");
                  assert.strictEqual(variants[1].stdioMode, "ignore");
                  assert.strictEqual(variants[2].stdioMode, "inherit");
                  assert.strictEqual(variants[3].launcherKind, "auxiliary");
                  assert.strictEqual(variants[4].launcherTransport, "python");
                  assert.strictEqual(variants[4].closeInheritedPipeFds, true);
                  assert.strictEqual(variants[0].executablePath, "/tmp/current-chrome");
                  assert.strictEqual(variants[4].executablePath, "/tmp/current-chrome");

                  const artifacts = api.buildFdInheritanceMatrixArtifacts("/tmp/fd-temp", "F5");
                  assert.ok(artifacts.caseDir.endsWith("/fd-inheritance-matrix/F5"));
                  assert.ok(artifacts.resultPath.endsWith("/fd-inheritance-matrix/F5/result.json"));
                  assert.ok(artifacts.parentFdsBeforePath.endsWith("/fd-inheritance-matrix/F5/parent-fds-before.json"));
                  assert.ok(artifacts.launcherStderrPath.endsWith("/fd-inheritance-matrix/F5/launcher-stderr.log"));
                } finally {
                  if (originalEnv === undefined) {
                    delete process.env.LHCI_FD_INHERITANCE_DIAGNOSTIC;
                  } else {
                    process.env.LHCI_FD_INHERITANCE_DIAGNOSTIC = originalEnv;
                  }
                }
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_fd_inheritance_launch_flags_include_headless_and_remote_debugging_port(self):
        chunk = extract_chunk("function getDiagnosticChromeFlags()", "function isTruthyEnvFlag")
        script = (
            dedent(
                """
                const assert = require("assert");
                const source = [
                  __SOURCE__,
                ].join("\\n");
                const factory = new Function(
                  source + "\\nreturn { getDiagnosticChromeFlags, buildChromeLaunchFlags };"
                );
                const api = factory();
                const flags = api.buildChromeLaunchFlags(["--foo=bar", ""]);

                assert.ok(Array.isArray(flags));
                assert.ok(flags.includes("--no-sandbox"));
                assert.ok(flags.includes("--headless=new"));
                assert.ok(flags.includes("--remote-debugging-port=0"));
                assert.ok(flags.includes("--foo=bar"));
                assert.ok(!flags.includes(""));
                assert.strictEqual(flags[flags.length - 1], "--foo=bar");
                assert.deepStrictEqual(api.buildChromeLaunchFlags([]).slice(-2), [
                  "--headless=new",
                  "--remote-debugging-port=0",
                ]);
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_python_fd_inheritance_launcher_uses_close_fds_and_empty_pass_fds(self):
        launcher_path = ROOT / "scripts" / "chrome_clean_launcher.py"
        spec = importlib.util.spec_from_file_location("chrome_clean_launcher", launcher_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        popen_calls = []
        snapshots = iter(
            [
                {"pid": 111, "available": True, "count": 1, "entries": [{"fd": 142, "target": "pipe:[1]"}]},
                {"pid": 111, "available": True, "count": 1, "entries": [{"fd": 145, "target": "pipe:[2]"}]},
                {"pid": 4321, "available": True, "count": 2, "entries": [{"fd": 142, "target": "pipe:[3]"}, {"fd": 145, "target": "pipe:[4]"}]},
                {"pid": 111, "available": True, "count": 1, "entries": [{"fd": 142, "target": "pipe:[1]"}]},
                {"pid": 4321, "available": True, "count": 2, "entries": [{"fd": 142, "target": "pipe:[3]"}, {"fd": 145, "target": "pipe:[4]"}]},
            ]
        )

        class FakeProc:
            def __init__(self):
                self.pid = 4321
                self.stdout = io.StringIO("chrome stdout line\n")
                self.stderr = io.StringIO("Authorization: Bearer abc\nChrome stderr line\n")
                self._returncode = None

            def poll(self):
                return self._returncode

            def wait(self, timeout=None):
                self._returncode = 0
                return 0

            def terminate(self):
                return None

            def kill(self):
                return None

        fake_proc = FakeProc()

        class FakeSubprocess:
            DEVNULL = subprocess.DEVNULL
            PIPE = subprocess.PIPE
            TimeoutExpired = subprocess.TimeoutExpired

            @staticmethod
            def Popen(*args, **kwargs):
                popen_calls.append({"args": args, "kwargs": kwargs})
                return fake_proc

        def capture_fd_listing(_pid):
            return next(snapshots)

        with mock.patch.object(
            module,
            "wait_for_devtools_active_port",
            return_value={
                "filePath": "/tmp/profile/DevToolsActivePort",
                "port": 9222,
                "wsPath": "/devtools/browser/test",
                "wsEndpoint": "ws://127.0.0.1:9222/devtools/browser/test",
            },
        ):
            state = module.launch_chrome_process(
                {
                    "chromePath": "/fake/chrome",
                    "profileDir": "/tmp/profile",
                    "launchFlags": ["--headless=new", "--remote-debugging-port=0"],
                    "devtoolsTimeoutMs": 5000,
                },
                subprocess_module=FakeSubprocess,
                capture_fd_listing_fn=capture_fd_listing,
            )
            complete = module.wait_for_chrome_exit(
                state,
                timeout_ms=5000,
                capture_fd_listing_fn=capture_fd_listing,
            )

        assert len(popen_calls) == 1
        call = popen_calls[0]["kwargs"]
        assert call["close_fds"] is True
        assert call["pass_fds"] == ()
        assert call["stdin"] is subprocess.DEVNULL
        assert call["stdout"] is subprocess.PIPE
        assert call["stderr"] is subprocess.PIPE
        assert call["text"] is True
        assert state["launch_info"]["browserWSEndpoint"] == "ws://127.0.0.1:9222/devtools/browser/test"
        assert state["launch_info"]["chromePid"] == 4321
        assert state["launch_info"]["chromeFdsBeforeLaunch"]["entries"][0]["fd"] == 142
        assert state["launch_info"]["chromeFdsBeforeLaunch"]["entries"][1]["fd"] == 145
        assert complete["chromeExitCode"] == 0
        assert complete["chromeExitSignal"] is None
        assert "Chrome stderr line" in complete["chromeStderrText"]

    def test_python_fd_inheritance_scrub_closes_extra_descriptors_and_preserves_stdio(self):
        launcher_path = ROOT / "scripts" / "chrome_clean_launcher.py"
        spec = importlib.util.spec_from_file_location("chrome_clean_launcher", launcher_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        closed = []
        snapshots = iter(
            [
                {
                    "pid": 111,
                    "available": True,
                    "count": 6,
                    "entries": [
                        {"fd": 0, "target": "pipe:[0]", "fdinfo": {"inode": 0, "flags": "00", "raw": "", "error": ""}},
                        {"fd": 1, "target": "pipe:[1]", "fdinfo": {"inode": 1, "flags": "01", "raw": "", "error": ""}},
                        {"fd": 2, "target": "pipe:[2]", "fdinfo": {"inode": 2, "flags": "02", "raw": "", "error": ""}},
                        {"fd": 3, "target": "pipe:[3]", "fdinfo": {"inode": 3, "flags": "03", "raw": "", "error": ""}},
                        {"fd": 7, "target": "pipe:[7]", "fdinfo": {"inode": 7, "flags": "07", "raw": "", "error": ""}},
                        {"fd": 9, "target": "pipe:[9]", "fdinfo": {"inode": 9, "flags": "09", "raw": "", "error": ""}},
                    ],
                },
                {
                    "pid": 111,
                    "available": True,
                    "count": 3,
                    "entries": [
                        {"fd": 0, "target": "pipe:[0]", "fdinfo": {"inode": 0, "flags": "00", "raw": "", "error": ""}},
                        {"fd": 1, "target": "pipe:[1]", "fdinfo": {"inode": 1, "flags": "01", "raw": "", "error": ""}},
                        {"fd": 2, "target": "pipe:[2]", "fdinfo": {"inode": 2, "flags": "02", "raw": "", "error": ""}},
                    ],
                },
                {
                    "pid": 111,
                    "available": True,
                    "count": 3,
                    "entries": [
                        {"fd": 0, "target": "pipe:[0]", "fdinfo": {"inode": 0, "flags": "00", "raw": "", "error": ""}},
                        {"fd": 1, "target": "pipe:[1]", "fdinfo": {"inode": 1, "flags": "01", "raw": "", "error": ""}},
                        {"fd": 2, "target": "pipe:[2]", "fdinfo": {"inode": 2, "flags": "02", "raw": "", "error": ""}},
                    ],
                },
            ]
        )

        class FakeOs:
            @staticmethod
            def close(fd):
                closed.append(fd)
                if fd == 9:
                    raise OSError(9, "Bad file descriptor")

        result = module.scrub_inherited_fd_descriptors(
            allow_list=[0, 1, 2],
            capture_fd_listing_fn=lambda pid: next(snapshots),
            process_impl=FakeOs(),
        )

        assert closed == [3, 7, 9]
        assert [entry["fd"] for entry in result["before"]["entries"]] == [0, 1, 2, 3, 7, 9]
        assert [entry["fd"] for entry in result["after"]["entries"]] == [0, 1, 2]
        assert [entry["fd"] for entry in result["closed"] if entry.get("closed")] == [3, 7]
        assert any(entry["fd"] == 9 and entry.get("ignored") for entry in result["closed"])

    def test_python_fd_inheritance_launcher_waits_for_devtools_http_ready(self):
        launcher_path = ROOT / "scripts" / "chrome_clean_launcher.py"
        spec = importlib.util.spec_from_file_location("chrome_clean_launcher", launcher_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        class FakeProc:
            def poll(self):
                return None

        http_attempts = {"count": 0}
        ws_attempts = {"count": 0}

        def fake_urlopen(url, timeout=1):
            http_attempts["count"] += 1

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            if http_attempts["count"] < 3:
                raise module.urllib_error.URLError("connection refused")
            assert url == "http://127.0.0.1:9222/json/version"
            assert timeout == 1
            return FakeResponse()

        class FakeSocket:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def sendall(self, data):
                self.sent = data

            def settimeout(self, timeout):
                self.timeout = timeout

            def recv(self, size):
                return b"HTTP/1.1 101 Switching Protocols\r\nSec-WebSocket-Accept: test\r\n\r\n"

        def fake_create_connection(address, timeout=1):
            ws_attempts["count"] += 1
            if ws_attempts["count"] < 3:
                raise OSError("connection refused")
            assert address == ("127.0.0.1", 9222)
            assert timeout == 1
            return FakeSocket()

        with mock.patch.object(module, "read_devtools_active_port", return_value={
            "filePath": "/tmp/profile/DevToolsActivePort",
            "port": 9222,
            "wsPath": "/devtools/browser/test",
            "wsEndpoint": "ws://127.0.0.1:9222/devtools/browser/test",
        }), mock.patch.object(module.urllib_request, "urlopen", side_effect=fake_urlopen), mock.patch.object(
            module.socket,
            "create_connection",
            side_effect=fake_create_connection,
        ), mock.patch.object(
            module.time, "sleep", return_value=None
        ), mock.patch.object(
            module.time,
            "monotonic",
            side_effect=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
        ):
            devtools = module.wait_for_devtools_active_port("/tmp/profile", FakeProc(), timeout_ms=1000)

        assert devtools["port"] == 9222
        assert http_attempts["count"] >= 3
        assert ws_attempts["count"] >= 2

    def test_python_fd_inheritance_launcher_emits_launch_info_before_close_command(self):
        launcher_path = ROOT / "scripts" / "chrome_clean_launcher.py"
        spec = importlib.util.spec_from_file_location("chrome_clean_launcher", launcher_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        stdout_stream = io.StringIO()
        stdin_stream = io.StringIO('{"command":"close"}\n')

        class DummyThread:
            def join(self, timeout=None):
                return None

        class FakeProc:
            def __init__(self):
                self.pid = 4321
                self._returncode = None
                self.terminated = False

            def poll(self):
                return self._returncode

            def wait(self, timeout=None):
                self._returncode = 0
                return 0

            def terminate(self):
                self.terminated = True
                assert 'launch_info' in stdout_stream.getvalue()

            def kill(self):
                self._returncode = -9

        fake_proc = FakeProc()
        launch_calls = []
        complete_calls = []

        def fake_launch_chrome_process(config, subprocess_module=None, capture_fd_listing_fn=None):
            launch_calls.append(config)
            return {
                "proc": fake_proc,
                "stdout_chunks": [],
                "stderr_chunks": [],
                "stdout_thread": DummyThread(),
                "stderr_thread": DummyThread(),
                "launch_info": {
                    "phase": "launch",
                    "pythonPid": 111,
                    "chromePid": fake_proc.pid,
                    "chromePath": "/fake/chrome",
                    "browserWSEndpoint": "ws://127.0.0.1:9222/devtools/browser/test",
                    "devtoolsPort": 9222,
                    "devtoolsPath": "/devtools/browser/test",
                    "profileDir": "/tmp/profile",
                    "devtoolsActivePort": {
                        "filePath": "/tmp/profile/DevToolsActivePort",
                        "port": 9222,
                        "wsPath": "/devtools/browser/test",
                        "wsEndpoint": "ws://127.0.0.1:9222/devtools/browser/test",
                    },
                    "chromeFdsBeforeLaunch": {"available": True, "entries": []},
                },
                "python_pid": 111,
                "chrome_pid": fake_proc.pid,
                "python_fds_before": {"available": True, "entries": []},
                "python_fds_after": {"available": True, "entries": []},
                "chrome_fds_before": {"available": True, "entries": []},
                "config": config,
            }

        def fake_wait_for_chrome_exit(state, timeout_ms=None, grace_ms=5000, capture_fd_listing_fn=None):
            complete_calls.append(
                {
                    "terminated": fake_proc.terminated,
                    "stdout": stdout_stream.getvalue(),
                }
            )
            return {
                "phase": "complete",
                "pythonPid": state["python_pid"],
                "chromePid": fake_proc.pid,
                "chromeExitCode": 0,
                "chromeExitSignal": None,
                "chromeTimedOut": False,
                "pythonFdsAfterExit": {"available": True, "entries": []},
                "chromeFdsAfterExit": {"available": True, "entries": []},
                "chromeStdoutText": "",
                "chromeStderrText": "",
            }

        with mock.patch.object(module, "launch_chrome_process", side_effect=fake_launch_chrome_process), mock.patch.object(
            module, "wait_for_chrome_exit", side_effect=fake_wait_for_chrome_exit
        ):
            launch_info, complete_info = module.run_launcher(
                {
                    "completionTimeoutMs": 1000,
                    "completionGraceMs": 1000,
                },
                stdin_stream=stdin_stream,
                stdout_stream=stdout_stream,
                started_at=0.0,
            )

        emitted_lines = [json.loads(line) for line in stdout_stream.getvalue().splitlines() if line.strip()]
        assert emitted_lines[0]["phase"] == "launch_info"
        assert emitted_lines[1]["phase"] == "complete_info"
        assert emitted_lines[0]["chromePid"] == 4321
        assert emitted_lines[0]["browserWSEndpoint"] == "ws://127.0.0.1:9222/devtools/browser/test"
        assert emitted_lines[0]["devtoolsPort"] == 9222
        assert emitted_lines[0]["devtoolsPath"] == "/devtools/browser/test"
        assert emitted_lines[0]["profileDir"] == "/tmp/profile"
        assert launch_info["phase"] == "launch_info"
        assert complete_info["phase"] == "complete_info"
        assert fake_proc.terminated is True
        assert launch_calls
        assert complete_calls and complete_calls[0]["terminated"] is True
        assert 'launch_info' in complete_calls[0]["stdout"]

    def test_chrome_clean_launcher_closes_only_inherited_pipe_fds(self):
        script = dedent(
            """
            const assert = require("assert");
            const fs = require("fs");
            const path = require("path");
            const launcher = require("./scripts/chrome-clean-launcher.cjs");

            const original = {
              existsSync: fs.existsSync,
              readdirSync: fs.readdirSync,
              readlinkSync: fs.readlinkSync,
              closeSync: fs.closeSync,
            };
            const closeCalls = [];

            try {
              fs.existsSync = (target) => (target === "/proc" ? true : original.existsSync(target));
              fs.readdirSync = (dir) => (dir.endsWith("/fd") ? ["0", "1", "2", "142", "145", "300"] : original.readdirSync(dir));
              fs.readlinkSync = (filePath) => {
                const fdName = path.basename(filePath);
                if (fdName === "142" || fdName === "145") {
                  return "pipe:[123]";
                }
                if (fdName === "300") {
                  return "eventpoll:[456]";
                }
                return "pipe:[0]";
              };
              fs.closeSync = (fd) => {
                closeCalls.push(fd);
              };

              const result = launcher.closeInheritedPipeDescriptors({
                fsImpl: fs,
                processImpl: {
                  pid: 999,
                  platform: "linux",
                },
              });
              assert.deepStrictEqual(closeCalls, [142, 145]);
              assert.strictEqual(result.closed.length, 2);
              assert.ok(result.closed.every((entry) => entry.reason === "inherited pipe from parent"));
              assert.ok(result.before.available);
              assert.ok(result.after.available);
            } finally {
              fs.existsSync = original.existsSync;
              fs.readdirSync = original.readdirSync;
              fs.readlinkSync = original.readlinkSync;
              fs.closeSync = original.closeSync;
            }
            """
        )
        run_node_script(script)

    def test_chrome_clean_launcher_runs_navigation_with_shell_false_and_sanitizes_stderr(self):
        script = dedent(
            """
            const assert = require("assert");
            const fs = require("fs");
            const os = require("os");
            const path = require("path");
            const {EventEmitter} = require("events");
            const launcher = require("./scripts/chrome-clean-launcher.cjs");

            (async () => {
              const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "lhci-fd-launcher-"));
              const caseDir = path.join(tempDir, "case");
              const profileDir = path.join(caseDir, "profile");
              fs.mkdirSync(caseDir, {recursive: true});
              fs.mkdirSync(profileDir, {recursive: true});

              const spawnCalls = [];
              let chromeChild = null;
              const page = new EventEmitter();
              page.url = () => "about:blank";
              page.mainFrame = () => ({url: () => "about:blank", name: () => ""});
              page.goto = async (url) => {
                page.emit("request", {
                  url: () => url,
                  method: () => "GET",
                  resourceType: () => "document",
                  isNavigationRequest: () => true,
                  failure: () => null,
                });
                page.emit("response", {
                  url: () => url,
                  status: () => 200,
                  fromCache: () => false,
                });
                page.emit("framenavigated", {url: () => url});
                page.emit("domcontentloaded");
                page.emit("console", {type: () => "warn", text: () => "console token=abc"});
                page.emit("pageerror", new Error("pageerror oauth_token=abc"));
                page.emit("load");
                return {
                  status: () => 200,
                  url: () => url,
                };
              };

              const browser = {
                version: async () => "Chrome/143.0.7499.4",
                newPage: async () => page,
                close: async () => {
                  chromeChild.emit("exit", 0, null);
                  chromeChild.emit("close", 0, null);
                },
              };

              const spawn = (chromePath, args, options) => {
                spawnCalls.push({chromePath, args, options});
                chromeChild = new EventEmitter();
                chromeChild.pid = 4321;
                chromeChild.exitCode = null;
                chromeChild.signalCode = null;
                chromeChild.stdout = new EventEmitter();
                chromeChild.stdout.setEncoding = () => {};
                chromeChild.stderr = new EventEmitter();
                chromeChild.stderr.setEncoding = () => {};
                setImmediate(() => {
                  fs.writeFileSync(
                    path.join(profileDir, "DevToolsActivePort"),
                    "9222\\n/devtools/browser/test\\n",
                    "utf8"
                  );
                  chromeChild.stderr.emit(
                    "data",
                    "Authorization: Bearer abc\\n"
                  );
                  chromeChild.stderr.emit("data", "Bearer abc\\n");
                  chromeChild.stderr.emit("data", "Cookie: session=abc\\n");
                  chromeChild.stderr.emit(
                    "data",
                    "https://user:pass@example.test/path?oauth_token=abc\\n"
                  );
                });
                return chromeChild;
              };

              const result = await launcher.runChromeFdInheritanceCase(
                {
                  variantId: "F1",
                  label: "main-pipes",
                  launcherKind: "direct",
                  stdioMode: "pipe",
                  closeInheritedPipeFds: false,
                  auditUrl: "http://127.0.0.1:12345/path?foo=1&swcleared=1",
                  chromePath: "/fake/chrome",
                  tempDir,
                  caseDir,
                  profileDir,
                  extraFlags: ["--foo=bar"],
                  navigationTimeoutMs: 3000,
                  devtoolsTimeoutMs: 3000,
                  closeTimeoutMs: 3000,
                },
                {
                  spawn,
                  puppeteer: {
                    connect: async ({browserWSEndpoint}) => {
                      assert.ok(browserWSEndpoint.includes("ws://127.0.0.1:9222/devtools/browser/test"));
                      return browser;
                    },
                  },
                  process: {
                    pid: 999,
                    env: process.env,
                    cwd: () => process.cwd(),
                    stderr: {write: () => {}},
                    stdout: {write: () => {}},
                  },
                }
              );

              assert.strictEqual(spawnCalls.length, 1);
              assert.strictEqual(spawnCalls[0].options.shell, false);
              assert.deepStrictEqual(spawnCalls[0].options.stdio, ["ignore", "pipe", "pipe"]);
              assert.ok(spawnCalls[0].args.includes("--remote-debugging-port=0"));
              assert.ok(spawnCalls[0].args.some((arg) => String(arg).includes(`--user-data-dir=${profileDir}`)));
              assert.strictEqual(result.exitCode, 0);
              assert.ok(result.navigation.responseSeen);
              assert.ok(result.navigation.loadSeen);
              assert.ok(result.navigation.frameNavigatedSeen);
              assert.ok(result.navigation.events.some((entry) => entry.event === "pageerror" && !String(entry.message || "").includes("oauth_token=abc")));
              assert.ok(!result.chromeStderrText.includes("user:pass@"));
              assert.ok(!result.chromeStderrText.includes("oauth_token=abc"));
              assert.ok(!result.chromeStderrText.includes("Authorization: Bearer abc"));
              assert.ok(result.chromeStderrText.includes("Authorization: REDACTED"));
              assert.ok(result.chromeStderrText.includes("Bearer REDACTED"));
              assert.ok(result.chromeStderrText.includes("Cookie: REDACTED"));
              assert.ok(result.chromeStderrText.includes("https://example.test/path?oauth_token=REDACTED"));
              assert.strictEqual(result.navigation.helperPid, 999);
            })().catch((error) => {
              console.error(error && error.stack ? error.stack : error);
              process.exit(1);
            });
            """
        )
        run_node_script(script)

    def test_fd_inheritance_python_launcher_sends_close_after_connect(self):
        chunk = extract_chunk("function sleep(ms)", "function describeStatus(")
        script = (
            dedent(
                """
                const assert = require("assert");
                const {EventEmitter} = require("events");
                const source = [
                  'const { StringDecoder } = require("node:string_decoder");',
                  'const { captureProcFdListing: captureChromeCleanFdListing } = require("./scripts/chrome-clean-launcher.cjs");',
                  __SOURCE__,
                ].join("\\n");
                const factory = new Function(
                  "require",
                  "fs",
                  "path",
                  "os",
                  "spawn",
                  "spawnSync",
                  "process",
                  "console",
                  "setTimeout",
                  "clearTimeout",
                  "clearInterval",
                  "JSON",
                  "Object",
                  "Array",
                  "String",
                  "Number",
                  "Boolean",
                  source + "\\nreturn { runChromeFdInheritanceCaseViaPythonLauncher };"
                );
                const api = factory(
                  require,
                  require("fs"),
                  require("path"),
                  require("os"),
                  () => {},
                  require("child_process").spawnSync,
                  process,
                  console,
                  setTimeout,
                  clearTimeout,
                  clearInterval,
                  JSON,
                  Object,
                  Array,
                  String,
                  Number,
                  Boolean
                );
                let connectCalled = false;
                let closeCommandSeen = false;
                let helperClosed = false;
                const spawnCalls = [];
                const stdoutLines = [];
                const stderrLines = [];

                const helperProcess = new EventEmitter();
                helperProcess.pid = 54321;
                helperProcess.exitCode = null;
                helperProcess.signalCode = null;
                helperProcess.stdout = new EventEmitter();
                helperProcess.stdout.on = helperProcess.stdout.addListener.bind(helperProcess.stdout);
                helperProcess.stdout.once = helperProcess.stdout.once.bind(helperProcess.stdout);
                helperProcess.stderr = new EventEmitter();
                helperProcess.stderr.on = helperProcess.stderr.addListener.bind(helperProcess.stderr);
                helperProcess.stderr.once = helperProcess.stderr.once.bind(helperProcess.stderr);
                helperProcess.stdin = {
                  write(chunk) {
                    const text = String(chunk);
                    stdoutLines.push(text);
                    if (text.includes('\"command\":\"close\"')) {
                      closeCommandSeen = true;
                      setImmediate(() => {
                        helperProcess.stdout.emit('data', JSON.stringify({
                          phase: 'complete_info',
                          pythonPid: 101,
                          chromePid: 54321,
                          chromeExitCode: 0,
                          chromeExitSignal: null,
                          chromeTimedOut: false,
                          chromeStdoutText: '',
                          chromeStderrText: '',
                        }) + '\\n');
                        helperProcess.emit('close', 0, null);
                        helperClosed = true;
                      });
                    }
                    return true;
                  },
                  end() {},
                  destroyed: false,
                };

                setImmediate(() => {
                  helperProcess.stdout.emit('data', JSON.stringify({
                    phase: 'launch_info',
                    pythonPid: 101,
                    chromePid: 54321,
                    browserWSEndpoint: 'ws://127.0.0.1:9222/devtools/browser/test',
                    devtoolsPort: 9222,
                    devtoolsPath: '/devtools/browser/test',
                    profileDir: '/tmp/profile',
                  }) + '\\n');
                });

                const browser = {
                  version: async () => 'Chrome/143.0.7499.4',
                  newPage: async () => ({
                    on() {},
                    goto: async () => {
                      return {
                        status: () => 200,
                        url: () => 'http://127.0.0.1:12345/?swcleared=1',
                      };
                    },
                  }),
                  close: async () => {
                    assert.strictEqual(closeCommandSeen, false, 'close command must be sent after browser.close completes');
                  },
                };

                const spawn = (chromePath, args, options) => {
                  spawnCalls.push({chromePath, args, options});
                  return helperProcess;
                };

                (async () => {
                  const result = await api.runChromeFdInheritanceCaseViaPythonLauncher(
                    {
                      variantId: 'F5',
                      label: 'auxiliary-scrubbed',
                      launcherKind: 'auxiliary',
                      launcherTransport: 'python',
                      stdioMode: 'pipe',
                      closeInheritedPipeFds: true,
                      scrubInheritedFds: true,
                      auditUrl: 'http://127.0.0.1:12345/?swcleared=1',
                      chromePath: '/fake/chrome',
                      tempDir: '/tmp/fd-test',
                      caseDir: '/tmp/fd-test/case',
                      profileDir: '/tmp/fd-test/case/profile',
                      launchFlags: ['--headless=new', '--remote-debugging-port=0'],
                      navigationTimeoutMs: 3000,
                      devtoolsTimeoutMs: 3000,
                      closeTimeoutMs: 3000,
                    },
                    {
                      spawn,
                      puppeteer: {
                        connect: async ({browserWSEndpoint}) => {
                          connectCalled = true;
                          assert.ok(browserWSEndpoint.includes('ws://127.0.0.1:9222/devtools/browser/test'));
                          assert.strictEqual(closeCommandSeen, false, 'connect must happen before close command');
                          return browser;
                        },
                      },
                      process: {
                        pid: 999,
                        env: process.env,
                        cwd: () => process.cwd(),
                        stderr: {write: (text) => stderrLines.push(String(text))},
                        stdout: {write: () => {}},
                      },
                    }
                  );

                  assert.strictEqual(connectCalled, true);
                  assert.strictEqual(closeCommandSeen, true);
                  assert.strictEqual(helperClosed, true);
                  assert.strictEqual(spawnCalls.length, 1);
                  assert.ok(spawnCalls[0].args.includes('--scrub-inherited-fds'));
                  assert.deepStrictEqual(spawnCalls[0].options.stdio, ['pipe', 'pipe', 'pipe']);
                  assert.strictEqual(result.exitCode, 0);
                  assert.strictEqual(result.helperProcess.status, 0);
                })().catch((error) => {
                  console.error(error && error.stack ? error.stack : error);
                  process.exit(1);
                });
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_browser_matrix_runs_variants_and_writes_artifacts_with_independent_profiles(self):
        chunk = extract_chunk("const DIAGNOSTIC_REDACTED_VALUE", "function describeStatus")
        script = (
            dedent(
                """
                const assert = require("assert");
                const fs = require("fs");
                const os = require("os");
                const path = require("path");
                const Module = require("module");
                const {EventEmitter} = require("events");
                let spawnSync = require("child_process").spawnSync;
                const source = [
                  'function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }',
                  'function readDiagnosticFileText(filePath) { try { return String(fs.readFileSync(filePath, "utf8") || ""); } catch { return ""; } }',
                  'const { StringDecoder } = require("node:string_decoder");',
                  'const { ensureSwClearedUrl } = require("./scripts/lighthouse-url.cjs");',
                  __SOURCE__,
                ].join("\\n");
                const factory = new Function(
                  "require",
                  "fs",
                  "path",
                  "Module",
                  "EventEmitter",
                  "process",
                  "console",
                  "setTimeout",
                  "spawnSync",
                  source + "\\nreturn { runBrowserMatrixDiagnostic };"
                );
                const api = factory(require, fs, path, Module, EventEmitter, process, console, setTimeout, spawnSync);

                const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "lhci-browser-matrix-"));
                const launchCalls = [];
                const lighthouseCalls = [];
                const originalLoad = Module._load;
                const originalSetTimeout = global.setTimeout;
                const originalEnv = process.env.LHCI_BROWSER_MATRIX_DIAGNOSTIC;
                const originalV2Path = process.env.LHCI_BROWSER_MATRIX_V2_PATH;
                const originalV3Path = process.env.LHCI_BROWSER_MATRIX_V3_PATH;
                const originalV4Path = process.env.LHCI_BROWSER_MATRIX_V4_PATH;
                process.env.LHCI_BROWSER_MATRIX_DIAGNOSTIC = "1";
                process.env.LHCI_BROWSER_MATRIX_V2_PATH = "/fake/google-chrome-stable";
                process.env.LHCI_BROWSER_MATRIX_V3_PATH = "/fake/playwright-chromium-previous";
                process.env.LHCI_BROWSER_MATRIX_V4_PATH = "/fake/chrome-beta";

                let activeVariant = "";

                const makeRequest = (url, failed = false) => ({
                  url: () => url,
                  method: () => "GET",
                  resourceType: () => "document",
                  isNavigationRequest: () => true,
                  frame: () => ({url: () => "about:blank"}),
                  redirectChain: () => [],
                  failure: () => (failed ? {errorText: "net::ERR_ABORTED"} : {}),
                });

                const makeResponse = (url) => ({
                  request: () => makeRequest(url),
                  headers: () => ({
                    "content-type": "text/html; charset=utf-8",
                    "content-length": "12",
                  }),
                  status: () => 200,
                  url: () => url,
                  fromCache: () => false,
                });

                const makeBrowser = (launchOptions) => {
                  const browser = new EventEmitter();
                  const page = new EventEmitter();
                  let currentUrl = "about:blank";
                  page.url = () => currentUrl;
                  page.mainFrame = () => ({url: () => currentUrl, name: () => ""});
                  page.goto = async (url) => {
                    currentUrl = url;
                    page.emit("request", makeRequest(url, String(launchOptions.userDataDir || "").includes("V2")));
                    page.emit("domcontentloaded");
                    if (String(launchOptions.userDataDir || "").includes("V2")) {
                      page.emit("requestfailed", makeRequest(url, true));
                      throw new Error("net::ERR_ABORTED");
                    }
                    page.emit("response", makeResponse(url));
                    page.emit("framenavigated", {url: () => url, name: () => ""});
                    page.emit("console", {type: () => "warn", text: () => "Authorization: Bearer abc Cookie: session=abc"});
                    page.emit("pageerror", new Error("pageerror token=abc"));
                    page.emit("load");
                    return makeResponse(url);
                  };
                  browser.process = () => ({pid: launchCalls.length + 4100});
                  browser.wsEndpoint = () => `ws://127.0.0.1:${launchCalls.length + 6100}/devtools/browser/test`;
                  browser.version = async () => "Chrome/143.0.7499.4";
                  browser.newPage = async () => page;
                  browser.close = async () => {
                    page.emit("close");
                    browser.emit("disconnected");
                  };
                  return browser;
                };

                Module._load = function(request, parent, isMain) {
                  if (request === "puppeteer-core") {
                    return {
                      launch: async (options) => {
                        launchCalls.push({kind: "puppeteer", options});
                        activeVariant = String(options.userDataDir || "").match(/V[1-4]/)?.[0] || "";
                        return makeBrowser(options);
                      },
                    };
                  }
                  if (request === "lighthouse") {
                    return {
                      default: async (url, flags, config) => {
                        lighthouseCalls.push({url, flags, config, variant: activeVariant});
                        if (activeVariant === "V3") {
                          return {
                            lhr: {
                              userAgent: "Chrome/143.0.7499.4",
                              requestedUrl: url,
                              finalUrl: url,
                              finalDisplayedUrl: url,
                              runtimeError: {
                                code: "FAILED_DOCUMENT_REQUEST",
                                message: "net::ERR_ABORTED",
                              },
                            },
                          };
                        }
                        return {
                          lhr: {
                            userAgent: "Chrome/143.0.7499.4",
                            requestedUrl: url,
                            finalUrl: url,
                            finalDisplayedUrl: url,
                            runtimeError: null,
                          },
                        };
                      },
                      defaultConfig: {},
                    };
                  }
                  return originalLoad.apply(this, arguments);
                };
                global.setTimeout = (fn) => {
                  fn();
                  return 0;
                };

                (async () => {
                  try {
                    const matrix = await api.runBrowserMatrixDiagnostic({
                      auditUrl: "http://user:pass@example.test/path?foo=1&swcleared=1#frag",
                      tempDir,
                      chromePath: "/fake/current-chrome",
                    });

                    assert.strictEqual(matrix.exitCode, 1);
                    assert.strictEqual(matrix.cases.length, 4);
                    assert.strictEqual(matrix.variants.length, 4);
                    assert.ok(matrix.auditUrl.includes("swcleared=1"));
                    assert.ok(!matrix.auditUrl.includes("user:pass@"));
                    assert.strictEqual(matrix.cases[0].captureStrace, true);
                    assert.strictEqual(matrix.cases[1].captureStrace, true);
                    assert.strictEqual(matrix.cases[2].captureStrace, false);
                    assert.strictEqual(matrix.cases[3].captureStrace, false);
                    assert.ok(matrix.cases[0].directNavigation.exitCode === 0);
                    assert.ok(matrix.cases[1].directNavigation.exitCode === 1);
                    assert.ok(matrix.cases[2].lighthouse.exitCode === 1);
                    assert.ok(matrix.cases[3].lighthouse.exitCode === 0);
                    assert.ok(matrix.environment.platform);
                    assert.ok(matrix.environment.arch);
                    assert.ok(matrix.environment.nodeVersion);

                    assert.strictEqual(launchCalls.length, 8);
                    const launchPaths = launchCalls.map((entry) => entry.options.executablePath);
                    assert.ok(launchPaths.some((entry) => String(entry).includes("direct-launcher.cjs")));
                    assert.ok(launchPaths.some((entry) => String(entry).includes("lighthouse-launcher.cjs")));
                    assert.ok(launchCalls.every((entry) => entry.options.args.some((arg) => String(arg).startsWith("--log-net-log="))));

                    const directProfiles = launchCalls
                      .filter((entry) => entry.kind === "puppeteer")
                      .filter((entry) => String(entry.options.userDataDir || "").includes("direct-profile"))
                      .map((entry) => entry.options.userDataDir);
                    const lighthouseProfiles = launchCalls
                      .filter((entry) => entry.kind === "puppeteer")
                      .filter((entry) => String(entry.options.userDataDir || "").includes("lighthouse-profile"))
                      .map((entry) => entry.options.userDataDir);
                    assert.strictEqual(new Set(directProfiles).size, 4);
                    assert.strictEqual(new Set(lighthouseProfiles).size, 4);

                    const jsonPath = path.join(tempDir, "browser-matrix-linux.json");
                    const logPath = path.join(tempDir, "browser-matrix-linux.log");
                    assert.ok(fs.existsSync(jsonPath));
                    assert.ok(fs.existsSync(logPath));
                    const jsonText = fs.readFileSync(jsonPath, "utf8");
                    const logText = fs.readFileSync(logPath, "utf8");
                    assert.ok(jsonText.includes('"id": "V1"'));
                    assert.ok(jsonText.includes('"id": "V4"'));
                    assert.ok(jsonText.includes('"variants"'));
                    assert.ok(logText.includes("browser-matrix-case-start"));
                    assert.ok(logText.includes("browser-matrix-case-complete"));

                    for (const caseSummary of matrix.cases) {
                      assert.ok(fs.existsSync(caseSummary.artifacts.prelaunchSnapshotPath));
                      assert.ok(fs.existsSync(caseSummary.artifacts.directSnapshotPath));
                      assert.ok(fs.existsSync(caseSummary.artifacts.lighthouseSnapshotPath));
                      assert.ok(fs.existsSync(caseSummary.artifacts.straceSummaryPath));
                      assert.ok(caseSummary.prelaunchSnapshot);
                      assert.ok(caseSummary.directNavigation);
                      assert.ok(caseSummary.lighthouse);
                    }

                    const straceWrappers = [
                      path.join(tempDir, "browser-matrix-linux", "V1", "direct-launcher.cjs"),
                      path.join(tempDir, "browser-matrix-linux", "V1", "lighthouse-launcher.cjs"),
                      path.join(tempDir, "browser-matrix-linux", "V2", "direct-launcher.cjs"),
                      path.join(tempDir, "browser-matrix-linux", "V2", "lighthouse-launcher.cjs"),
                    ];
                    for (const filePath of straceWrappers) {
                      assert.ok(fs.existsSync(filePath));
                      assert.ok(fs.readFileSync(filePath, "utf8").includes("strace"));
                    }
                  } finally {
                    Module._load = originalLoad;
                    global.setTimeout = originalSetTimeout;
                    if (originalEnv === undefined) {
                      delete process.env.LHCI_BROWSER_MATRIX_DIAGNOSTIC;
                    } else {
                      process.env.LHCI_BROWSER_MATRIX_DIAGNOSTIC = originalEnv;
                    }
                    if (originalV2Path === undefined) {
                      delete process.env.LHCI_BROWSER_MATRIX_V2_PATH;
                    } else {
                      process.env.LHCI_BROWSER_MATRIX_V2_PATH = originalV2Path;
                    }
                    if (originalV3Path === undefined) {
                      delete process.env.LHCI_BROWSER_MATRIX_V3_PATH;
                    } else {
                      process.env.LHCI_BROWSER_MATRIX_V3_PATH = originalV3Path;
                    }
                    if (originalV4Path === undefined) {
                      delete process.env.LHCI_BROWSER_MATRIX_V4_PATH;
                    } else {
                      process.env.LHCI_BROWSER_MATRIX_V4_PATH = originalV4Path;
                    }
                  }
                })().catch((error) => {
                  console.error(error && error.stack ? error.stack : error);
                  process.exit(1);
                });
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
        )
        run_node_script(script)

    def test_bootstrap_skips_when_schema_recovery_is_unavailable(self):
        chunk = extract_chunk("function bootstrapSqliteSchema", "function tailText")
        script = dedent(
            f"""
            const assert = require("assert");
            const path = require("path");
            const source = {json.dumps(chunk)};
            const factory = new Function(
              "resolveSchemaSqlPath",
              "runPythonCode",
              "console",
              "path",
              source + "\\nreturn bootstrapSqliteSchema;"
            );
            const warnings = [];
            const calls = [];
            const bootstrapSqliteSchema = factory(
              () => null,
              (...args) => {{
                calls.push(args);
                return {{ status: 0, stdout: "", stderr: "" }};
              }},
              {{
                log: () => {{}},
                warn: (...args) => warnings.push(args.join(" ")),
              }},
              path
            );
            assert.doesNotThrow(() => bootstrapSqliteSchema("/tmp/lhci-test.sqlite", {{}}));
            assert.strictEqual(calls.length, 0);
            assert.ok(warnings.some((line) => line.includes("schema.sql")));
            assert.ok(warnings.some((line) => line.includes("git")));
            """
        )
        run_node_script(script)

    def test_external_probe_falls_back_to_get_when_head_returns_403(self):
        self._assert_probe_fallback(
            head_code=403,
            get_code=200,
            expected_method="GET",
        )

    def test_external_probe_falls_back_to_get_when_head_returns_404(self):
        self._assert_probe_fallback(
            head_code=404,
            get_code=302,
            expected_method="GET",
        )

    def _assert_probe_fallback(self, *, head_code: int, get_code: int, expected_method: str) -> None:
        chunk = extract_chunk("function describeStatus", "function spawnServer")
        script = (
            dedent(
                """
                const assert = require("assert");
                const source = 'const { StringDecoder } = require("node:string_decoder");\\n' + __SOURCE__;
                const calls = [];
                const factory = new Function(
                  "curlStatus",
                  source + "\\nreturn { describeStatus, isHeadUnsupported, isReachableHttpStatus, probeAuditUrlReachability };"
                );
                const api = factory((url, timeoutSeconds, options = {}) => {
                  calls.push(options.method || "GET");
                  if ((options.method || "GET") === "HEAD") {
                    return {
                      code: __HEAD_CODE__,
                      status: 0,
                      error: "",
                      stderr: "",
                    };
                  }
                  return {
                    code: __GET_CODE__,
                    status: 0,
                    error: "",
                    stderr: "",
                  };
                });
                const result = api.probeAuditUrlReachability("http://example.test/", 5);
                assert.deepStrictEqual(calls, ["HEAD", "GET"]);
                assert.strictEqual(result.method, "__EXPECTED_METHOD__");
                assert.strictEqual(result.headResult.code, __HEAD_CODE__);
                assert.strictEqual(result.result.code, __GET_CODE__);
                assert.strictEqual(result.fallbackUsed, true);
                assert.strictEqual(api.isReachableHttpStatus(result.result.code), true);
                """
            )
            .replace("__SOURCE__", json.dumps(chunk))
            .replace("__HEAD_CODE__", str(head_code))
            .replace("__GET_CODE__", str(get_code))
            .replace("__EXPECTED_METHOD__", expected_method)
        )
        run_node_script(script)


if __name__ == "__main__":
    unittest.main()
