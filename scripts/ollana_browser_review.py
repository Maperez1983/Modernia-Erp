#!/usr/bin/env python3
"""Browser review driven by the Ollana technical account."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlencode

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None


DEFAULT_BASE_URL = "https://crm.verifika2.com"
DEFAULT_TIMEOUT_MS = 45000
DEFAULT_SEARCH_PROVIDER = "bing"


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _route_for(workspace_id: str, module: str, page: str = "") -> str:
    params = {"holding": "1", "mode": "tenant", "workspace": workspace_id, "nosw": "1", "swcleared": "1"}
    if module == "inmo":
        params.update({"crm": "inmo"})
    elif module == "gestoria":
        params.update({"crm": "gestoria"})
    elif module == "seguros":
        params.update({"crm": "seguros"})
    elif module == "fin":
        params.update({"crm": "fin"})
    elif module == "rrhh":
        params.update({"view": "rrhh"})
    elif module == "fincas":
        params.update({"view": "fincas"})
    if page == "agenda":
        params.update({"crm": "inmo", "view": "agenda"})
    return f"/?{urlencode(params)}"


def _ui_snapshot(page) -> dict:
    js = """
    () => {
      const textLen = (sel) => {
        const el = document.querySelector(sel);
        return el ? String(el.innerText || el.textContent || '').trim().length : 0;
      };
      const count = (sel) => document.querySelectorAll(sel).length;
      const visible = (sel) => {
        const el = document.querySelector(sel);
        if (!el) return false;
        const style = window.getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden' && !el.classList.contains('hidden');
      };
      return {
        title: document.title || "",
        current_url: location.href,
        visible_sections: {
          crm: visible('#crmSection'),
          gestoria: visible('#gestoriaCrmSection'),
          seguros: visible('#segurosCrmSection'),
          fin: visible('#finDashboardSection') || visible('#finCrmSection'),
          rrhh: visible('[data-workspace-view="rrhh"]'),
          fincas: visible('[data-workspace-view="fincas"]'),
          agenda: visible('#agendaSection') || visible('#crmAgendaSection') || visible('.tc-agenda-shell'),
        },
        metrics: {
          agenda_events: count('.agenda-event, .agenda-day-row, .tc-agenda-event'),
          agenda_text_chars: textLen('#agendaSection') + textLen('.tc-agenda-shell'),
          crm_chars: textLen('#crmSection') + textLen('#gestoriaCrmSection') + textLen('#segurosCrmSection') + textLen('#finCrmSection'),
        },
      };
    }
    """
    return page.evaluate(js)


def _browser_web_search(page, query: str, provider: str = DEFAULT_SEARCH_PROVIDER) -> dict:
    text = " ".join(str(query or "").split()).strip()
    if not text:
        return {"ok": False, "status": "failed", "detail": "Consulta vacía"}
    provider_key = str(provider or DEFAULT_SEARCH_PROVIDER).strip().lower()
    if provider_key == "duckduckgo":
        url = f"https://html.duckduckgo.com/html/?{urlencode({'q': text, 'kl': 'es-es'})}"
        page.goto(url, wait_until="domcontentloaded")
        challenge = page.locator("text=Unfortunately, bots use DuckDuckGo too.")
        if challenge.count():
            return {"ok": False, "status": "warning", "detail": "DuckDuckGo ha devuelto un challenge anti-bot.", "provider": "duckduckgo"}
        selector = "a.result__a"
        page.wait_for_selector(selector, timeout=15000)
        cards = page.locator(selector)
        results = []
        total = min(cards.count(), 6)
        for index in range(total):
            link = cards.nth(index)
            href = str(link.get_attribute("href") or "").strip()
            title = " ".join((link.inner_text() or "").split()).strip()
            snippet = ""
            try:
                snippet = " ".join(
                    (link.locator("xpath=ancestor::*[contains(@class,'result')][1]").locator(".result__snippet").inner_text() or "").split()
                ).strip()
            except Exception:
                snippet = ""
            if href:
                results.append({"title": title or href, "url": href, "snippet": snippet})
        return {"ok": True, "status": "passed", "provider": "duckduckgo", "query": text, "results": results}

    # Default: Bing
    url = f"https://www.bing.com/search?{urlencode({'q': text, 'setlang': 'es'})}"
    page.goto(url, wait_until="domcontentloaded")
    # Consent or modal noise is not fatal; dismiss best-effort if present.
    for selector in ("#bnp_btn_accept", "button[aria-label='Aceptar']", "button:has-text('Aceptar')"):
        try:
            if page.locator(selector).count():
                page.locator(selector).first.click(timeout=1500)
                break
        except Exception:
            pass
    page.wait_for_selector("li.b_algo h2 a, #b_results .b_algo h2 a", timeout=20000)
    results = page.evaluate(
        """
        () => {
          const rows = [];
          document.querySelectorAll('li.b_algo').forEach((item) => {
            if (rows.length >= 6) return;
            const anchor = item.querySelector('h2 a');
            if (!anchor) return;
            const snippetNode = item.querySelector('.b_caption p') || item.querySelector('p');
            rows.push({
              title: String(anchor.innerText || anchor.textContent || '').trim(),
              url: String(anchor.href || '').trim(),
              snippet: String(snippetNode ? (snippetNode.innerText || snippetNode.textContent || '') : '').trim(),
            });
          });
          return rows;
        }
        """
    )
    if not results:
        return {"ok": False, "status": "warning", "detail": "No he encontrado resultados visibles en el buscador.", "provider": "bing", "query": text}
    return {"ok": True, "status": "passed", "provider": "bing", "query": text, "results": results}


def _login(page, base_url: str, user: str, password: str) -> dict:
    page.goto(f"{base_url}/?nosw=1&swcleared=1", wait_until="domcontentloaded")
    page.wait_for_selector("#authLoginUser", timeout=DEFAULT_TIMEOUT_MS)
    page.fill("#authLoginUser", user)
    page.fill("#authLoginPass", password)
    with page.expect_response(lambda r: r.url.endswith("/api/login")) as login_info:
        page.click('#authLoginForm button[type="submit"]')
    resp = login_info.value
    payload = resp.json()
    if not resp.ok or not payload.get("ok"):
        raise RuntimeError(f"login_failed http={resp.status} payload={payload}")
    page.wait_for_function("() => !document.body.classList.contains('auth-locked')", timeout=DEFAULT_TIMEOUT_MS)
    return payload


def _impersonate(page, login: str) -> dict:
    if not login:
        return {"ok": True, "skipped": True}
    js = """
    async (targetLogin) => {
      const resp = await fetch('/api/auth_impersonate_user', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ login: targetLogin, reason: 'Revisión de navegador Ollana' }),
      });
      const data = await resp.json().catch(() => ({}));
      return { ok: resp.ok && !!data.ok, status: resp.status, data };
    }
    """
    result = page.evaluate(js, login)
    if not result.get("ok"):
        raise RuntimeError(f"impersonation_failed {result}")
    page.reload(wait_until="domcontentloaded")
    return result


def run() -> dict:
    if sync_playwright is None:
        return {"ok": False, "status": "skipped", "detail": "Playwright no disponible"}
    base_url = _env("OLLANA_BROWSER_BASE_URL", _env("CRM_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
    login = _env("OLLANA_SYSTEM_LOGIN")
    password = os.environ.get("OLLANA_SYSTEM_PASSWORD") or ""
    if not login or not password:
        return {"ok": False, "status": "skipped", "detail": "Faltan credenciales técnicas de Ollana"}
    impersonate_login = _env("OLLANA_BROWSER_IMPERSONATE_LOGIN")
    route = _env("OLLANA_BROWSER_ROUTE")
    workspace_id = _env("OLLANA_BROWSER_WORKSPACE_ID")
    module = _env("OLLANA_BROWSER_MODULE")
    page_name = _env("OLLANA_BROWSER_PAGE")
    task = _env("OLLANA_BROWSER_TASK", "review").lower() or "review"
    search_query = _env("OLLANA_BROWSER_SEARCH_QUERY")
    search_provider = _env("OLLANA_BROWSER_SEARCH_PROVIDER", DEFAULT_SEARCH_PROVIDER)
    if not route and workspace_id:
        route = _route_for(workspace_id, module, page_name)

    console_errors = []
    page_errors = []
    failed_requests = []
    api_errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True, service_workers="block")
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: page_errors.append(str(err)))
        page.on("requestfailed", lambda req: failed_requests.append({"url": req.url, "failure": str(req.failure or "")[:300]}))
        page.on(
            "response",
            lambda resp: api_errors.append({"url": resp.url, "status": resp.status})
            if ("/api/" in resp.url and int(resp.status or 0) >= 400)
            else None,
        )
        try:
            login_data = _login(page, base_url, login, password)
            impersonation = _impersonate(page, impersonate_login)
            snapshot = {}
            search = {}
            if task == "web_search":
                search = _browser_web_search(page, search_query, search_provider)
            else:
                if route:
                    page.goto(f"{base_url}{route}", wait_until="domcontentloaded")
                snapshot = _ui_snapshot(page)
        finally:
            context.close()
            browser.close()
    status = "passed"
    if task == "web_search":
        status = str((search or {}).get("status") or "failed").strip() or "failed"
    elif page_errors or failed_requests or any(int(item.get("status") or 0) >= 500 for item in api_errors):
        status = "failed"
    elif console_errors or any(int(item.get("status") or 0) >= 400 for item in api_errors):
        status = "warning"
    return {
        "ok": status != "failed",
        "status": status,
        "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "base_url": base_url,
        "route": route,
        "task": task,
        "impersonated_login": impersonate_login,
        "login_user": (login_data.get("user") or {}).get("usuario"),
        "impersonation": impersonation,
        "snapshot": snapshot,
        "search": search,
        "console_errors": console_errors[:20],
        "page_errors": page_errors[:20],
        "failed_requests": failed_requests[:20],
        "api_errors": api_errors[:30],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run browser review using the Ollana technical account.")
    parser.add_argument("--json", action="store_true", help="Print JSON result.")
    args = parser.parse_args()
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))
    return 0 if result.get("status") in ("passed", "warning", "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
