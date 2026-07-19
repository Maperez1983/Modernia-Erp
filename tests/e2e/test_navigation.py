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


def test_workspace_company_switcher_preserves_selected_company(page, e2e_app):
    e2e_app.login(page, e2e_app.data.admin_username, e2e_app.data.admin_password)
    page.wait_for_url("**/*holding=1*mode=platform*", timeout=30_000)
    page.locator("#authLoginOverlay").wait_for(state="hidden")

    workspace = e2e_app.data.workspace_id
    target_company = e2e_app.data.secondary_company_id
    target_company_name = e2e_app.data.secondary_company_name
    e2e_app.goto(
        page,
        f"/?holding=1&mode=platform&workspace={workspace}&workspace_company_id={target_company}&view=tenant",
    )
    page.locator("#workspaceTenantTabs [data-workspace-tenant-tab='empresas']").click()
    companies = page.locator("#workspaceCompanies")
    companies.wait_for(state="visible")
    chips = page.locator("#workspaceCompanies [data-workspace-company-chip]")
    assert chips.count() >= 2
    assert target_company_name in page.locator("#workspaceCompanies .workspace-company-name").all_text_contents()
    assert e2e_app.data.company_name in page.locator("#workspaceCompanies .workspace-company-name").all_text_contents()

    page.reload(wait_until="domcontentloaded")
    companies.wait_for(state="visible")
    chips = page.locator("#workspaceCompanies [data-workspace-company-chip]")
    assert chips.count() >= 2
    assert target_company_name in page.locator("#workspaceCompanies .workspace-company-name").all_text_contents()
