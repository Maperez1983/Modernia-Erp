from __future__ import annotations


def test_initial_load(page, e2e_app):
    e2e_app.goto(page, "/")
    page.locator("#authLoginOverlay").wait_for(state="visible")

    assert "Verifika²" in page.title()
    assert page.locator("#authLoginForm").is_visible()
    assert page.locator("#authLoginUser").is_visible()
    assert page.locator("#authLoginPass").is_visible()

    scripts = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('script[src]')).map((script) => script.getAttribute('src') || '')
        """
    )
    shared_index = next(i for i, src in enumerate(scripts) if "app_shared.js" in src)
    app_index = next(i for i, src in enumerate(scripts) if "app.js" in src)
    auth_index = next(i for i, src in enumerate(scripts) if "app-auth.js" in src)
    routing_index = next(i for i, src in enumerate(scripts) if "app-routing.js" in src)

    assert auth_index < routing_index
    assert routing_index < shared_index
    assert shared_index < app_index
