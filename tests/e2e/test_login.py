from __future__ import annotations


def test_login_success(page, e2e_app):
    e2e_app.login(page, e2e_app.data.admin_username, e2e_app.data.admin_password)
    page.wait_for_url("**/*holding=1*mode=platform*", timeout=30_000)
    page.locator("#holdingSection").wait_for(state="visible")

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
