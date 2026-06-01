#!/usr/bin/env python3
import os
import sys
import time

from playwright.sync_api import sync_playwright


def main():
    base_url = (os.environ.get("CRM_E2E_URL") or "https://crm.verifika2.com/?swcleared=1").strip()
    user = (os.environ.get("CRM_E2E_USER") or "").strip()
    password = os.environ.get("CRM_E2E_PASS") or ""
    if not user or not password:
        raise SystemExit("CRM_E2E_USER y CRM_E2E_PASS son requeridos")

    report = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.set_default_timeout(60000)
        page.set_default_navigation_timeout(120000)

        page.goto(base_url, wait_until="domcontentloaded")
        page.wait_for_selector("#authLoginUser", timeout=60000)
        page.fill("#authLoginUser", user)
        page.fill("#authLoginPass", password)
        with page.expect_response(lambda r: r.url.endswith("/api/login")) as login_info:
            page.click('#authLoginForm button[type="submit"]')
        login_resp = login_info.value
        login_data = login_resp.json()
        if not login_resp.ok or not login_data.get("ok"):
            raise SystemExit(f"Login fallido: HTTP {login_resp.status} {login_data}")
        report.append("login_ok")
        page.wait_for_function("() => !document.body.classList.contains('auth-locked')", timeout=60000)

        page.evaluate(
            """() => {
              try {
                const params = new URLSearchParams(window.location.search || '');
                params.set('crm', 'inmo');
                params.set('swcleared', '1');
                history.replaceState(null, '', '/?' + params.toString());
              } catch (e) {}
              try { if (typeof openCrmInmobiliario === 'function') openCrmInmobiliario(); } catch (e) {}
            }"""
        )
        page.wait_for_selector("#crmSection:not(.hidden)", timeout=60000)
        report.append("crm_inmo_visible")

        page.wait_for_selector('[data-crm-view="inmuebles"]', timeout=60000)
        page.evaluate(
            """() => {
              const btn = Array.from(document.querySelectorAll('[data-crm-view="inmuebles"]')).find((el) => !!el.offsetParent);
              if (btn) btn.click();
            }"""
        )
        time.sleep(1)
        inmueble_count = page.locator("#crmInmueblesTable tbody tr, #crmCaptacionesTable tbody tr").count()
        report.append(f"inmuebles_rows={inmueble_count}")

        page.evaluate(
            """() => {
              try { if (typeof setCrmWorkspaceView === 'function') setCrmWorkspaceView('agenda'); } catch (e) {}
              const btn = Array.from(document.querySelectorAll('[data-crm-view="agenda"]')).find((el) => !!el.offsetParent);
              if (btn) btn.click();
            }"""
        )
        try:
            page.wait_for_selector("#crmViewAgenda:not(.hidden)", timeout=20000)
            try:
                page.click('#crmAgendaViewSeg button[data-crm-agenda-view="list"]')
            except Exception:
                pass
            page.wait_for_selector("#crmAgendaTable", timeout=30000)
            agenda_text = page.locator("#crmAgendaTable").inner_text(timeout=30000)
            report.append(f"agenda_chars={len(agenda_text)}")
        except Exception as exc:
            focus_items = page.evaluate(
                """() => Array.from(document.querySelectorAll('[data-crm-view="agenda"], .crm-focus-link'))
                  .filter((el) => !!el.offsetParent)
                  .map((el) => (el.innerText || el.textContent || '').trim())
                  .filter(Boolean)
                  .slice(0, 12)"""
            )
            report.append(f"agenda_view_warning={type(exc).__name__}")
            report.append(f"agenda_visible_items={len(focus_items)}")

        diag = context.request.get(f"{base_url.split('?')[0].rstrip('/')}/api/inmueble_signature_config")
        if diag.ok:
            data = diag.json()
            report.append(
                "signature_config="
                + ",".join(
                    f"{key}:{'1' if value else '0'}"
                    for key, value in sorted((data.get("config") or {}).items())
                    if key in {"smtp", "sms_webhook", "whatsapp_webhook", "external_signature", "external_feed"}
                )
            )
        else:
            report.append(f"signature_config_http={diag.status}")

        context.close()
        browser.close()

    print("\n".join(report))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
