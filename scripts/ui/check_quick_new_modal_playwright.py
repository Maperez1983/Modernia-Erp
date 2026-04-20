import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Check CRM quick-new modal stacking (Playwright).")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765", help="Base URL of local server.")
    parser.add_argument("--user", default="MPerez", help="Login user.")
    parser.add_argument("--password", default="Password1234", help="Login password.")
    parser.add_argument(
        "--out",
        default=str(Path(os.environ.get("TMPDIR", "/tmp")) / "crm_ui_checks"),
        help="Output directory for screenshots/logs.",
    )
    args = parser.parse_args()

    base_url = str(args.base_url).rstrip("/")
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    payload: dict = {"base_url": base_url, "checks": {}}

    from playwright.sync_api import sync_playwright  # type: ignore

    def write_payload() -> None:
        (out_dir / "quick_new_modal.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def assert_card_on_top(page, modal_selector: str, card_selector: str = ".crm-insert-card") -> dict:
        data = page.evaluate(
            """
            ({ modalSel, cardSel }) => {
              const modal = document.querySelector(modalSel);
              const card = modal ? modal.querySelector(cardSel) : null;
              const rect = card ? card.getBoundingClientRect() : null;
              const x = rect ? rect.left + rect.width / 2 : 0;
              const y = rect ? rect.top + Math.min(30, rect.height / 2) : 0;
              const topEl = rect ? document.elementFromPoint(x, y) : null;
              const contains = Boolean(card && topEl && card.contains(topEl));
              const modalStyle = modal ? getComputedStyle(modal) : null;
              return {
                modalExists: Boolean(modal),
                modalHidden: Boolean(modal && modal.classList.contains('hidden')),
                modalZ: modalStyle ? modalStyle.zIndex : null,
                cardRect: rect ? {left: rect.left, top: rect.top, width: rect.width, height: rect.height} : null,
                elementFromPoint: topEl ? {tag: topEl.tagName, id: topEl.id, class: topEl.className} : null,
                cardContainsPoint: contains,
                bodyModalOpen: document.body.classList.contains('modal-open'),
              };
            }
            """,
            {"modalSel": modal_selector, "cardSel": card_selector},
        )
        if not data.get("modalExists") or data.get("modalHidden"):
            raise SystemExit(f"Modal not visible: {modal_selector} data={data}")
        if not data.get("cardContainsPoint"):
            raise SystemExit(f"Modal card is not on top: {modal_selector} data={data}")
        return data

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={"width": 1460, "height": 920}, service_workers="block")
            context.add_init_script("try{localStorage.clear();}catch(e){}")
            page = context.new_page()

            page.goto(f"{base_url}/?crm=inmo", wait_until="load")

            # Login if needed.
            login_overlay = page.locator("#authLoginOverlay")
            if login_overlay.count() and login_overlay.first.is_visible():
                page.fill("#authLoginUser", str(args.user))
                page.fill("#authLoginPass", str(args.password))
                page.click("#authLoginForm button[type=submit]")
                try:
                    page.wait_for_selector("#authLoginOverlay", state="hidden", timeout=25000)
                except Exception:
                    status = ""
                    try:
                        status = page.locator("#authLoginStatus").first.inner_text()
                    except Exception:
                        status = ""
                    page.screenshot(path=str(out_dir / "quick_new_login_failed.png"), full_page=True)
                    payload["error"] = f"login_failed: {status!r}"
                    write_payload()
                    raise SystemExit(f"Login overlay did not close. status={status!r}")

            # Ensure we are in a view with dense table/sticky headers (captaciones).
            cap_btn = page.locator('[data-crm-view="captaciones"]:visible')
            if cap_btn.count() > 0:
                cap_btn.first.click()
            page.wait_for_timeout(300)

            # Click "Nuevo" (top button preferred; sidebar quick-new may be hidden depending on viewport/state).
            top_new = page.locator("#crmTopNewBtn:visible")
            quick_new = page.locator("#crmQuickNewBtn:visible")
            if top_new.count() > 0:
                top_new.first.click()
            elif quick_new.count() > 0:
                quick_new.first.click()
            else:
                page.screenshot(path=str(out_dir / "quick_new_button_missing.png"), full_page=True)
                payload["error"] = "no_new_button_visible"
                write_payload()
                raise SystemExit("No 'Nuevo' button visible (#crmTopNewBtn / #crmQuickNewBtn).")

            page.wait_for_selector("#crmInsertModal:not(.hidden)", timeout=10000)
            payload["checks"]["crmInsertModal_on_top"] = assert_card_on_top(page, "#crmInsertModal")

            # Open "Inmueble" from the insert list -> should close insert modal and open captacion modal.
            page.locator('#crmInsertModal [data-crm-insert="captacion"]').first.click()
            page.wait_for_selector("#crmCaptacionModal:not(.hidden)", timeout=10000)
            payload["checks"]["crmCaptacionModal_on_top"] = assert_card_on_top(page, "#crmCaptacionModal")

            page.screenshot(path=str(out_dir / "quick_new_modal.png"), full_page=True)
            browser.close()
    except Exception as exc:
        payload["error"] = payload.get("error") or f"{type(exc).__name__}: {exc}"
        write_payload()
        raise

    write_payload()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

