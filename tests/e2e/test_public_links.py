from __future__ import annotations


def test_public_links_invalid_and_valid_token(page, e2e_app):
    e2e_app.goto(page, "/?activar_token=invalid-token")
    page.locator("#authActivateOverlay").wait_for(state="visible")
    page.wait_for_function(
        """
        () => {
          const status = document.getElementById('authActivateStatus');
          return Boolean(status && /Invitación inválida|Invitación no válida|No se pudo validar la invitación|caducado/i.test(status.textContent || ''));
        }
        """,
        timeout=15_000,
    )
    assert e2e_app.session_user(page) is None
    assert page.locator("#authActivateStatus").text_content() is not None
    assert not any(cookie["name"] == "crm_session" for cookie in page.context.cookies())

    e2e_app.goto(page, f"/?activar_token={e2e_app.data.invite_token}")
    page.locator("#authActivateOverlay").wait_for(state="visible")
    page.wait_for_function(
        """
        () => {
          const intro = document.getElementById('authActivateIntro');
          return Boolean(intro && /Invitado E2E|e2e_invited@example\\.test/i.test(intro.textContent || ''));
        }
        """,
        timeout=15_000,
    )
    assert e2e_app.session_user(page) is None
    assert e2e_app.data.invite_token in page.url
