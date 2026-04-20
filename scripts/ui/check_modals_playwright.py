import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="UI sanity checks with Playwright.")
    parser.add_argument(
        "--fixture",
        default=str(Path(__file__).with_name("modal_overlay_fixture.html")),
        help="Path to fixture HTML file.",
    )
    parser.add_argument(
        "--out",
        default=str(Path(os.environ.get("TMPDIR", "/tmp")) / "crm_ui_checks"),
        help="Output directory for screenshots/logs.",
    )
    args = parser.parse_args()

    fixture_path = Path(args.fixture).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright  # type: ignore

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"file://{fixture_path}", wait_until="load")
        page.wait_for_timeout(200)

        payload = page.evaluate(
            """
            () => {
              const modal = document.querySelector('#crmCaptacionModal');
              const card = modal && modal.querySelector('.crm-insert-card');
              const tableHead = document.querySelector('th');
              const modalStyle = modal ? getComputedStyle(modal) : null;
              const headStyle = tableHead ? getComputedStyle(tableHead) : null;
              const rect = card ? card.getBoundingClientRect() : null;
              const x = rect ? rect.left + rect.width / 2 : 0;
              const y = rect ? rect.top + 20 : 0;
              const topEl = rect ? document.elementFromPoint(x, y) : null;
              const contains = Boolean(card && topEl && card.contains(topEl));
              return {
                modalExists: Boolean(modal),
                modalZ: modalStyle ? modalStyle.zIndex : null,
                thZ: headStyle ? headStyle.zIndex : null,
                cardRect: rect ? {left: rect.left, top: rect.top, width: rect.width, height: rect.height} : null,
                elementFromPoint: topEl ? {tag: topEl.tagName, id: topEl.id, class: topEl.className} : null,
                cardContainsPoint: contains
              };
            }
            """
        )

        screenshot_path = out_dir / "modal_overlay.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        (out_dir / "modal_overlay.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        browser.close()

    if not payload.get("modalExists"):
        raise SystemExit("Fixture did not render modal.")
    if not payload.get("cardContainsPoint"):
        raise SystemExit(f"Modal card is not on top at center point: {payload}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

