from __future__ import annotations


def test_initial_load(page, e2e_app):
    e2e_app.goto(page, "/")
    page.locator("#authLoginOverlay").wait_for(state="visible")

    assert "Verifika²" in page.title()
    assert page.locator("#authLoginForm").is_visible()
    assert page.locator("#authLoginUser").is_visible()
    assert page.locator("#authLoginPass").is_visible()
    assert page.locator("main").evaluate("el => getComputedStyle(el).visibility") == "hidden"
    assert page.evaluate("window.__APP_JS_LOADED === true") is False
    assert page.evaluate("window.__APP_JS_EXPECTED === true") is False

    scripts = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('script[src]')).map((script) => script.getAttribute('src') || '')
        """
    )
    assert scripts == ["app-auth.js?v=16"]

    resources = page.evaluate(
        """
        () => Array.from(performance.getEntriesByType('resource')).map((entry) => entry.name)
        """
    )
    assert not any("app.js?v=790" in name for name in resources)
    assert not any("ui-foundation.js?v=5" in name for name in resources)
    assert not any("app-routing.js?v=13" in name for name in resources)
    assert not any("app_shared.js?v=1" in name for name in resources)
    assert not any("leaflet.css" in name for name in resources)
    assert not any("leaflet.js" in name for name in resources)
