from __future__ import annotations


def test_navigation_between_modules_and_reload(page, e2e_app):
    e2e_app.login(page, e2e_app.data.normal_username, e2e_app.data.normal_password)
    page.wait_for_url("**/*", timeout=30_000)
    page.locator("#authLoginOverlay").wait_for(state="hidden")

    workspace = e2e_app.data.workspace_id
    e2e_app.goto(page, f"/?holding=1&mode=tenant&workspace={workspace}&view=rrhh")
    page.locator("#workspaceRrhhHub").wait_for(state="visible")
    assert page.locator("#workspaceRrhhHub").is_visible()
    assert page.get_by_role("heading", name="RRHH").is_visible()

    e2e_app.goto(page, f"/?holding=1&mode=tenant&workspace={workspace}&view=fincas")
    page.locator("#workspaceFincasTabs").wait_for(state="visible")
    assert page.locator("#workspaceFincasTabs").is_visible()
    assert page.get_by_role("heading", name="Módulo Fincas").is_visible()

    page.reload(wait_until="domcontentloaded")
    page.locator("#workspaceFincasTabs").wait_for(state="visible")
    assert "view=fincas" in page.url
    assert f"workspace={workspace}" in page.url
