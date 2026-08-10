from __future__ import annotations


def test_login_success(page, e2e_app):
    e2e_app.login(page, e2e_app.data.admin_username, e2e_app.data.admin_password)
    page.wait_for_url("**/*holding=1*mode=platform*", timeout=30_000)
    page.locator("#holdingSection").wait_for(state="visible")
    page.wait_for_function("() => window.__APP_JS_LOADED === true", timeout=30_000)

    cookies = page.context.cookies()
    assert any(cookie["name"] == "crm_session" for cookie in cookies)

    user = e2e_app.session_user(page)
    assert user is not None
    assert user["usuario"] == e2e_app.data.admin_username
    assert user["is_superadmin"] is True
    assert "holding=1" in page.url
    assert "mode=platform" in page.url
    assert page.locator("#authLoginOverlay").is_hidden()
    assert page.locator("#authSessionPill").is_visible()

    scripts = page.evaluate(
        """
        () => Array.from(document.querySelectorAll('script[data-crm-dynamic="1"]')).map((script) => script.dataset.crmSrc || '')
        """
    )
    # Los `?v=` son los números de caché-busting: cambian en CADA despliegue, así
    # que fijarlos aquí convertía este test en un aviso de «has vuelto a desplegar»
    # en vez de en una comprobación. Se mira el fichero, no su versión.
    assert any(nombre.startswith("ui-foundation.js?v=") for nombre in scripts)
    assert any(nombre.startswith("app-routing.js?v=") for nombre in scripts)
    assert any(nombre.startswith("app_shared.js?v=") for nombre in scripts)
    assert "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" in scripts
    assert any(nombre.startswith("app.js?v=") for nombre in scripts)

    resources = page.evaluate(
        """
        () => Array.from(performance.getEntriesByType('resource')).map((entry) => entry.name)
        """
    )
    assert any("app.js?v=" in name for name in resources)
    assert any("ui-foundation.js?v=" in name for name in resources)
    assert any("app-routing.js?v=" in name for name in resources)
    assert any("app_shared.js?v=" in name for name in resources)
    assert any("leaflet.css" in name for name in resources)
    assert any("leaflet.js" in name for name in resources)


def test_login_failure(page, e2e_app):
    e2e_app.login(page, e2e_app.data.normal_username, "WrongPassword!23")
    page.wait_for_function(
        """
        () => {
          const status = document.getElementById('authLoginStatus');
          return Boolean(status && /incorrectos|No se pudo iniciar sesión/i.test(status.textContent || ''));
        }
        """,
        timeout=15_000,
    )

    assert page.locator("#authLoginOverlay").is_visible()
    assert e2e_app.session_user(page) is None
    assert not any(cookie["name"] == "crm_session" for cookie in page.context.cookies())
