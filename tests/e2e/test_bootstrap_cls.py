from __future__ import annotations

import json


CLS_OBSERVER_SCRIPT = r"""
(() => {
  const state = (window.__bootstrapCls = {
    shifts: [],
  });
  const toRect = (rect) => {
    if (!rect) return null;
    return {
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
    };
  };
  const describeNode = (node) => {
    if (!node) return null;
    const el = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
    if (!el) return null;
    const classes = String(el.className || "")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 4);
    let selector = el.tagName ? el.tagName.toLowerCase() : "node";
    if (el.id) {
      selector += `#${el.id}`;
    } else if (classes.length) {
      selector += `.${classes.join(".")}`;
    }
    return {
      selector,
      id: el.id || "",
      className: String(el.className || ""),
      text: String(el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 140),
      rect: toRect(el.getBoundingClientRect ? el.getBoundingClientRect() : null),
    };
  };
  try {
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.hadRecentInput) continue;
        state.shifts.push({
          value: entry.value,
          startTime: entry.startTime,
          sources: Array.from(entry.sources || []).map((source) => ({
            previousRect: toRect(source.previousRect),
            currentRect: toRect(source.currentRect),
            node: describeNode(source.node),
          })),
        });
      }
    });
    observer.observe({ type: "layout-shift", buffered: true });
  } catch (error) {
    state.error = String(error && error.message ? error.message : error);
  }
})();
"""

CLS_THRESHOLD = 0.10


def _format_shift(shift: dict) -> str:
    sources = []
    for source in shift.get("sources", [])[:4]:
      node = source.get("node") or {}
      sources.append(
        {
            "selector": node.get("selector"),
            "text": node.get("text"),
            "previousRect": source.get("previousRect"),
            "currentRect": source.get("currentRect"),
        }
      )
    return json.dumps(
        {
            "value": shift.get("value"),
            "startTime": shift.get("startTime"),
            "sources": sources,
        },
        ensure_ascii=False,
        indent=2,
    )


def test_bootstrap_cls_stays_within_threshold(page, e2e_app):
    page.add_init_script(CLS_OBSERVER_SCRIPT)
    e2e_app.goto(page, "/")
    page.locator("#authLoginOverlay").wait_for(state="visible")
    page.wait_for_function(
        """
        () => Boolean(document.body)
          && document.body.classList.contains('auth-pending')
          && document.body.classList.contains('auth-locked')
          && document.querySelector('#authLoginOverlay')
          && document.querySelector('#uiContextBar')
        """,
        timeout=15_000,
    )
    page.wait_for_function(
        """
        async () => {
          await document.fonts.ready;
          return true;
        }
        """,
        timeout=15_000,
    )
    page.wait_for_timeout(1000)

    assert page.locator("#authLoginOverlay").is_visible()
    assert page.locator("main").evaluate("el => getComputedStyle(el).visibility") == "hidden"
    assert page.locator("#uiContextBar").bounding_box() is not None
    assert page.locator("header").bounding_box() is not None
    assert page.locator(".app-footer").bounding_box() is not None

    cls_data = page.evaluate("window.__bootstrapCls || { shifts: [] }")
    assert "error" not in cls_data, f"PerformanceObserver failed: {cls_data.get('error')}"
    shifts = cls_data.get("shifts") or []
    total_cls = sum(float(shift.get("value") or 0.0) for shift in shifts)

    assert total_cls <= CLS_THRESHOLD, json.dumps(
        {
            "total_cls": total_cls,
            "threshold": CLS_THRESHOLD,
            "body_class": page.locator("body").evaluate("body => body.className"),
            "login_overlay_visible": page.locator("#authLoginOverlay").is_visible(),
            "main_visibility": page.locator("main").evaluate("el => getComputedStyle(el).visibility"),
            "top_shifts": [_format_shift(shift) for shift in sorted(shifts, key=lambda item: float(item.get("value") or 0.0), reverse=True)[:5]],
        },
        ensure_ascii=False,
        indent=2,
    )
