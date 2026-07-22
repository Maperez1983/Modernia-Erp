import shutil
import subprocess
import unittest
from pathlib import Path
from textwrap import dedent


ROOT = Path(__file__).resolve().parents[1]


def run_node_script(script: str) -> None:
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node no está disponible")
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)
    if result.returncode:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        raise subprocess.CalledProcessError(result.returncode, result.args, output=result.stdout, stderr=result.stderr)


class AuthBootstrapUiTests(unittest.TestCase):
    def test_app_auth_blocks_duplicate_login_and_recovery_requests(self):
        script = (
            dedent(
                """
                (async () => {
                const assert = require("assert");
                const fs = require("fs");
                const path = require("path");
                const { JSDOM } = require("jsdom");
                """
            )
            + dedent(
                """

            const root = process.cwd();
            const source = fs.readFileSync(path.join(root, "web", "app-auth.js"), "utf8");
            const dom = new JSDOM(`<!doctype html><html><body>
              <form id="authLoginForm" class="auth-login-form">
                <label>
                  Usuario / email
                  <input id="authLoginUser" />
                </label>
                <label>
                  Contraseña
                  <div class="auth-input-wrap">
                    <input id="authLoginPass" type="password" />
                    <button id="authLoginPassToggle" type="button"></button>
                  </div>
                </label>
                <div class="auth-login-actions">
                  <button type="submit">Entrar</button>
                  <span id="authLoginStatus"></span>
                </div>
              </form>
            </body></html>`, {
              url: "https://crm.example/",
              runScripts: "outside-only",
              pretendToBeVisual: true,
            });

            const { window } = dom;
            Object.assign(window, {
              AbortController,
              Blob,
              URL,
              URLSearchParams,
              setTimeout,
              clearTimeout,
            });

            const fetchCalls = [];
            const deferred = () => {
              let resolve;
              let reject;
              const promise = new Promise((nextResolve, nextReject) => {
                resolve = nextResolve;
                reject = nextReject;
              });
              return { promise, resolve, reject };
            };

            const login = deferred();
            const recovery = deferred();
            window.fetch = async (url) => {
              const target = String(url || "");
              fetchCalls.push(target);
              if (target === "/api/health") {
                return {
                  ok: true,
                  status: 200,
                  json: async () => ({}),
                  text: async () => "",
                };
              }
              if (target === "/api/login") {
                return login.promise;
              }
              if (target === "/api/auth_request_access_recovery") {
                return recovery.promise;
              }
              throw new Error(`unexpected fetch ${target}`);
            };

            window.eval(source);

            const deps = {
              state: { appInitialized: false },
              authLoginForm: window.document.getElementById("authLoginForm"),
              authLoginUser: window.document.getElementById("authLoginUser"),
              authLoginPass: window.document.getElementById("authLoginPass"),
              authLoginPassToggle: window.document.getElementById("authLoginPassToggle"),
              authLoginStatus: window.document.getElementById("authLoginStatus"),
              authRecoveryBtn: null,
              init: async () => {},
              hideAuthOverlay: () => {},
              showAuthOverlay: () => {},
              setAuthUi: () => {},
              navigate: () => {},
              api: async () => ({}),
            };

            deps.authLoginUser.value = "Mperez";
            deps.authLoginPass.value = "Chapapote10";
            const submitBtn = deps.authLoginForm.querySelector('button[type="submit"]');

            const firstLogin = window.CRMAppAuth.submitAuthLogin(deps);
            assert.strictEqual(submitBtn.disabled, true);
            window.CRMAppAuth.submitAuthLogin(deps);
            await new Promise((resolve) => setTimeout(resolve, 20));
            assert.strictEqual(fetchCalls.filter((url) => url === "/api/health").length, 1);
            assert.strictEqual(fetchCalls.filter((url) => url === "/api/login").length, 1);

            login.resolve({
              ok: false,
              status: 401,
              json: async () => ({
                error: "Usuario o contraseña incorrectos",
                recovery_available: true,
                recovery_login: "Mperez",
                recovery_message: "Puedes recuperar el acceso.",
              }),
            });
            await firstLogin;
            await new Promise((resolve) => setTimeout(resolve, 20));

            assert.strictEqual(submitBtn.disabled, false);
            assert.ok(deps.authRecoveryBtn);
            assert.strictEqual(deps.authRecoveryBtn.style.display, "");
            assert.strictEqual(deps.authRecoveryBtn.disabled, false);
            assert.strictEqual(deps.authRecoveryBtn.dataset.login, "Mperez");

            deps.authRecoveryBtn.dispatchEvent(new window.Event("click", { bubbles: true, cancelable: true }));
            deps.authRecoveryBtn.dispatchEvent(new window.Event("click", { bubbles: true, cancelable: true }));
            await new Promise((resolve) => setTimeout(resolve, 20));
            assert.strictEqual(fetchCalls.filter((url) => url === "/api/auth_request_access_recovery").length, 1);
            assert.strictEqual(deps.authRecoveryBtn.disabled, true);

            recovery.resolve({
              ok: true,
              status: 200,
              json: async () => ({
                ok: true,
                message: "Si la cuenta existe, hemos enviado un enlace para recuperar el acceso.",
                recovery_message: "Revisa tu correo para continuar.",
              }),
            });
            await new Promise((resolve) => setTimeout(resolve, 20));

            assert.strictEqual(deps.authRecoveryBtn.disabled, false);
            assert.match(
              deps.authLoginStatus.textContent,
              /Si la cuenta existe, hemos enviado un enlace para recuperar el acceso\\. Revisa tu correo para continuar\\./
            );
            })().catch((err) => {
              console.error(err);
              process.exit(1);
            });
            """
            )
        )
        run_node_script(script)

    def test_standalone_login_bootstrap_shows_recovery_and_blocks_repeat_submit(self):
        script = (
            dedent(
                """
                (async () => {
                const assert = require("assert");
                const fs = require("fs");
                const path = require("path");
                const { JSDOM } = require("jsdom");
                """
            )
            + dedent(
                """

            const root = process.cwd();
            const indexHtml = fs.readFileSync(path.join(root, "web", "index.html"), "utf8");
            const marker = "// Standalone auth bootstrap:";
            const start = indexHtml.indexOf(marker);
            if (start === -1) {
              throw new Error("standalone auth bootstrap not found");
            }
            const scriptOpen = indexHtml.lastIndexOf("<script", start);
            const scriptStart = indexHtml.indexOf(">", scriptOpen) + 1;
            const scriptEnd = indexHtml.indexOf("</script>", start);
            const source = indexHtml.slice(scriptStart, scriptEnd);

            const dom = new JSDOM(`<!doctype html><html><body class="auth-pending">
              <div id="authLoginOverlay" class="auth-login-overlay hidden">
                <div class="auth-login-card">
                  <form id="authLoginForm" class="auth-login-form">
                    <label>
                      Usuario / email
                      <input id="authLoginUser" />
                    </label>
                    <label>
                      Contraseña
                      <input id="authLoginPass" type="password" />
                    </label>
                    <div class="auth-login-actions">
                      <button type="submit">Entrar</button>
                      <span id="authLoginStatus"></span>
                    </div>
                  </form>
                </div>
              </div>
              <div id="authActivateOverlay" class="auth-login-overlay hidden"></div>
            </body></html>`, {
              url: "https://crm.example/",
              runScripts: "outside-only",
              pretendToBeVisual: true,
            });

            const { window } = dom;
            Object.assign(window, {
              AbortController,
              Blob,
              URL,
              URLSearchParams,
              setTimeout,
              clearTimeout,
            });
            window.__APP_JS_EXPECTED = true;
            window.__APP_JS_LOADED = false;

            const fetchCalls = [];
            const deferred = () => {
              let resolve;
              const promise = new Promise((nextResolve) => {
                resolve = nextResolve;
              });
              return { promise, resolve };
            };

            const login = deferred();
            const recovery = deferred();
            window.fetch = async (url) => {
              const target = String(url || "");
              fetchCalls.push(target);
              if (target === "/api/health" || target === "/health") {
                return {
                  ok: true,
                  status: 200,
                  json: async () => ({}),
                  text: async () => "",
                };
              }
              if (target === "/api/session_state") {
                return {
                  ok: false,
                  status: 401,
                  json: async () => ({ user: null }),
                  text: async () => "",
                };
              }
              if (target === "/api/login") {
                return login.promise;
              }
              if (target === "/api/auth_request_access_recovery") {
                return recovery.promise;
              }
              throw new Error(`unexpected fetch ${target}`);
            };

            window.eval(source);

            const loginForm = window.document.getElementById("authLoginForm");
            const loginUser = window.document.getElementById("authLoginUser");
            const loginPass = window.document.getElementById("authLoginPass");
            const loginStatus = window.document.getElementById("authLoginStatus");
            const submitBtn = loginForm.querySelector('button[type="submit"]');

            loginUser.value = "Mperez";
            loginPass.value = "Chapapote10";

            loginForm.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));
            assert.strictEqual(submitBtn.disabled, true);
            await new Promise((resolve) => setTimeout(resolve, 20));
            assert.strictEqual(fetchCalls.filter((url) => url === "/api/login").length, 1);

            login.resolve({
              ok: false,
              status: 401,
              json: async () => ({
                error: "Usuario o contraseña incorrectos",
                recovery_available: true,
                recovery_login: "Mperez",
                recovery_message: "Puedes recuperar el acceso.",
              }),
            });
            await new Promise((resolve) => setTimeout(resolve, 20));

            const recoveryBtn = window.__authRecoveryBtn;
            assert.ok(recoveryBtn);
            assert.strictEqual(recoveryBtn.style.display, "");
            assert.strictEqual(recoveryBtn.disabled, false);
            assert.strictEqual(recoveryBtn.dataset.login, "Mperez");

            recoveryBtn.dispatchEvent(new window.Event("click", { bubbles: true, cancelable: true }));
            recoveryBtn.dispatchEvent(new window.Event("click", { bubbles: true, cancelable: true }));
            await new Promise((resolve) => setTimeout(resolve, 20));
            assert.strictEqual(fetchCalls.filter((url) => url === "/api/auth_request_access_recovery").length, 1);
            assert.strictEqual(recoveryBtn.disabled, true);

            recovery.resolve({
              ok: true,
              status: 200,
              json: async () => ({
                ok: true,
                message: "Si la cuenta existe, hemos enviado un enlace para recuperar el acceso.",
                recovery_message: "Revisa tu correo para continuar.",
              }),
            });
            await new Promise((resolve) => setTimeout(resolve, 20));

            assert.strictEqual(recoveryBtn.disabled, false);
            assert.match(
              loginStatus.textContent,
              /Si la cuenta existe, hemos enviado un enlace para recuperar el acceso\\. Revisa tu correo para continuar\\./
            );
            assert.strictEqual(submitBtn.disabled, false);
            })().catch((err) => {
              console.error(err);
              process.exit(1);
            });
            """
            )
        )
        run_node_script(script)
