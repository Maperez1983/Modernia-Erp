from __future__ import annotations


def test_normal_user_cannot_access_admin_route(page, e2e_app):
    page.add_init_script(
        """
        (() => {
          const nativeSetTimeout = window.setTimeout.bind(window);
          window.__adminRetryTimers = [];
          window.setTimeout = function(fn, delay, ...args) {
            const label = typeof fn === "function" ? String(fn) : String(fn || "");
            if (label.includes("openAdmin")) {
              window.__adminRetryTimers.push({ delay: Number(delay) || 0, label });
            }
            return nativeSetTimeout(fn, delay, ...args);
          };
        })();
        """
    )
    e2e_app.login(page, e2e_app.data.normal_username, e2e_app.data.normal_password)
    page.wait_for_url("**/*", timeout=30_000)
    page.locator("#authLoginOverlay").wait_for(state="hidden")

    status, body = e2e_app.api_get(page, "/api/admin_user_lookup?login=e2e_user")
    assert status == 403
    assert body["error"] == "No autorizado"

    e2e_app.goto(page, "/?admin=1")
    page.wait_for_load_state("domcontentloaded")
    page.locator("#adminSection").wait_for(state="hidden")
    assert page.locator("#adminSection").is_hidden()
    page.wait_for_timeout(250)
    admin_retry_timers = page.evaluate(
        """
        () => (window.__adminRetryTimers || []).filter((item) => String(item.label || "").includes("openAdmin"))
        """
    )
    assert admin_retry_timers == []
    assert e2e_app.session_user(page)["usuario"] == e2e_app.data.normal_username


def test_admin_user_can_access_admin_route(page, e2e_app):
    e2e_app.login(page, e2e_app.data.admin_username, e2e_app.data.admin_password)
    page.wait_for_url("**/*holding=1*mode=platform*", timeout=30_000)
    page.locator("#holdingSection").wait_for(state="visible")

    e2e_app.goto(page, "/?admin=1")
    page.locator("#adminSection").wait_for(state="visible")
    assert page.locator("#adminSection").is_visible()

    status, body = e2e_app.api_get(page, "/api/admin_user_lookup?login=e2e_user")
    assert status == 200
    assert body["ok"] is True
    assert any(item["usuario"] == e2e_app.data.normal_username for item in body["items"])
