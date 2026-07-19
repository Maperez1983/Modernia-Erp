from __future__ import annotations


def test_public_shell_has_no_serious_accessibility_violations(page, e2e_app, axe_audit):
    e2e_app.goto(page, "/")
    axe_audit(page, label="public-shell")


def test_authenticated_shell_has_no_serious_accessibility_violations(page, e2e_app, axe_audit):
    e2e_app.login(page, e2e_app.data.admin_username, e2e_app.data.admin_password)
    e2e_app.goto(page, "/")
    axe_audit(page, label="authenticated-shell")
