from __future__ import annotations

import json


BASELINE_INITIAL_NODES = 8210
BASELINE_POST_LOGIN_NODES = 9332
INITIAL_NODE_TARGET = int(BASELINE_INITIAL_NODES * 0.75)
POST_LOGIN_NODE_TARGET = int(BASELINE_POST_LOGIN_NODES * 0.85)

GROUP_SELECTORS = {
    "gestoria": [
        "#gestoriaDashboardSection",
        "#gestoriaCrmSection",
        "#gestoriaDocsSection",
        "#gestoriaAgendaSection",
        "#gestoriaFactSection",
        "#gestoriaContaSection",
    ],
    "seguros": [
        "#segurosCrmSection",
    ],
    "fin": [
        "#hipotecaSection",
        "#finSimSection",
    ],
}


def _snapshot(page):
    return page.evaluate(
        """
        () => {
          const groups = {
            gestoria: [
              "#gestoriaDashboardSection",
              "#gestoriaCrmSection",
              "#gestoriaDocsSection",
              "#gestoriaAgendaSection",
              "#gestoriaFactSection",
              "#gestoriaContaSection",
            ],
            seguros: ["#segurosCrmSection"],
            fin: ["#hipotecaSection", "#finSimSection"],
          };
          const counts = {};
          const connected = {};
          for (const [name, selectors] of Object.entries(groups)) {
            counts[name] = {};
            connected[name] = {};
            for (const selector of selectors) {
              counts[name][selector] = document.querySelectorAll(selector).length;
              connected[name][selector] = Boolean(document.querySelector(selector));
            }
          }
          return {
            total: document.getElementsByTagName("*").length,
            counts,
            connected,
            authPending: Boolean(document.body && document.body.classList.contains("auth-pending")),
            appLoaded: window.__APP_JS_LOADED === true,
          };
        }
        """
    )


def _assert_snapshot(snapshot, *, total_target: int, expected_counts: dict[str, int], label: str) -> None:
    assert snapshot["total"] <= total_target, json.dumps(
        {
            "label": label,
            "total": snapshot["total"],
            "target": total_target,
            "counts": snapshot["counts"],
            "connected": snapshot["connected"],
        },
        ensure_ascii=False,
        indent=2,
    )
    for group_name, expected_count in expected_counts.items():
        for selector, count in snapshot["counts"][group_name].items():
            assert count == expected_count, json.dumps(
                {
                    "label": label,
                    "group": group_name,
                    "selector": selector,
                    "expected": expected_count,
                    "actual": count,
                    "total": snapshot["total"],
                    "counts": snapshot["counts"],
                },
                ensure_ascii=False,
                indent=2,
            )


def _open_group(page, e2e_app, group_name: str) -> None:
    page.evaluate(
        """
        (group) => {
          window.__CRMDeferredSections?.sync?.(group);
        }
        """,
        group_name,
    )
    try:
        page.wait_for_function(
            """
            (selectors) => selectors.every((selector) => document.querySelectorAll(selector).length === 1)
            """,
            arg=GROUP_SELECTORS[group_name],
            timeout=30_000,
        )
    except Exception as exc:
        raise AssertionError(
            json.dumps(
                {
                    "group": group_name,
                    "url": page.url,
                    "snapshot": _snapshot(page),
                },
                ensure_ascii=False,
                indent=2,
            )
        ) from exc


def test_deferred_dom_blocks_reduce_initial_dom_and_mount_on_demand(page, e2e_app):
    e2e_app.goto(page, "/")
    page.locator("#authLoginOverlay").wait_for(state="visible")

    initial = _snapshot(page)
    assert initial["authPending"] is True
    assert initial["appLoaded"] is False
    _assert_snapshot(
        initial,
        total_target=INITIAL_NODE_TARGET,
        expected_counts={name: 0 for name in GROUP_SELECTORS},
        label="initial",
    )

    e2e_app.login(page, e2e_app.data.admin_username, e2e_app.data.admin_password)
    page.wait_for_function(
        """
        () => window.location.search.includes("holding=1") && window.location.search.includes("mode=platform")
        """,
        timeout=30_000,
    )
    page.wait_for_function("() => window.__APP_JS_LOADED === true", timeout=30_000)

    post_login = _snapshot(page)
    assert post_login["appLoaded"] is True
    _assert_snapshot(
        post_login,
        total_target=POST_LOGIN_NODE_TARGET,
        expected_counts={name: 0 for name in GROUP_SELECTORS},
        label="post_login",
    )

    _open_group(page, e2e_app, "gestoria")
    gestoria = _snapshot(page)
    _assert_snapshot(
        gestoria,
        total_target=post_login["total"] + 5000,
        expected_counts={
            "gestoria": 1,
            "seguros": 0,
            "fin": 0,
        },
        label="gestoria",
    )

    _open_group(page, e2e_app, "seguros")
    seguros = _snapshot(page)
    _assert_snapshot(
        seguros,
        total_target=gestoria["total"] + 5000,
        expected_counts={
            "gestoria": 0,
            "seguros": 1,
            "fin": 0,
        },
        label="seguros",
    )

    _open_group(page, e2e_app, "fin")
    fin = _snapshot(page)
    _assert_snapshot(
        fin,
        total_target=seguros["total"] + 5000,
        expected_counts={
            "gestoria": 0,
            "seguros": 0,
            "fin": 1,
        },
        label="fin",
    )

    _open_group(page, e2e_app, "gestoria")
    gestoria_again = _snapshot(page)
    _assert_snapshot(
        gestoria_again,
        total_target=fin["total"] + 5000,
        expected_counts={
            "gestoria": 1,
            "seguros": 0,
            "fin": 0,
        },
        label="gestoria_again",
    )


def test_deferred_controls_keep_working_after_lazy_mount(page, e2e_app):
    def _stub_lazy_mount_api(route):
        url = route.request.url
        if "api/acciones" in url and ("servicio=gestoria" in url or "servicio=seguros" in url):
            route.fulfill(status=200, content_type="application/json", body='{"rows":[]}')
            return
        if "api/seguros_recibos_summary" in url:
            route.fulfill(status=200, content_type="application/json", body='{"rows":[],"summary":{}}')
            return
        if "api/seguros_recibos" in url or "api/seguros_siniestros" in url:
            route.fulfill(status=200, content_type="application/json", body='{"rows":[]}')
            return
        if "api/clientes_list" in url and "servicio=seguros" in url:
            route.fulfill(status=200, content_type="application/json", body='{"rows":[]}')
            return
        route.continue_()

    page.route("**/api/**", _stub_lazy_mount_api)
    e2e_app.login(page, e2e_app.data.admin_username, e2e_app.data.admin_password)
    page.wait_for_url("**/*holding=1*mode=platform*", timeout=30_000)
    page.wait_for_function("() => window.__APP_JS_LOADED === true", timeout=30_000)

    page.evaluate("document.getElementById('gestoriaDashTab')?.click()")
    page.locator("#gestoriaDashboardTabs").wait_for(state="visible")
    page.locator("#gestoriaDashboardTabs [data-gestoria-dashboard-view='servicios']").click()
    page.locator("#gestoriaDashboardPaneServicios").wait_for(state="visible")
    page.locator("#gestoriaDashboardTabs [data-gestoria-dashboard-view='general']").click()
    page.locator("#gestoriaDashboardPaneGeneral").wait_for(state="visible")

    page.evaluate("document.getElementById('fincasCrmTab')?.click()")
    page.locator("#gestoriaCrmSearch").wait_for(state="visible")
    page.locator("#gestoriaCrmTipo").select_option(label="Gestión administrativa")
    page.wait_for_function(
        """
        () => Array.from(document.querySelectorAll('#gestoriaCrmSubtipo option')).some((option) =>
          String(option.textContent || '').includes('Gestiones Administrativas')
        )
        """,
        timeout=30_000,
    )
    page.locator("#gestoriaCrmViews [data-gestoria-view='alta']").click()
    page.locator("#gestoriaCrmViewAlta").wait_for(state="visible")
    page.locator("#gestoriaCrmViews [data-gestoria-view='crm']").click()
    page.locator("#gestoriaCrmViewCrm").wait_for(state="visible")

    page.evaluate("document.getElementById('segurosCrmTab')?.click()")
    page.locator("#segurosTabs").wait_for(state="visible")
    page.locator("#segurosTabs [data-seguros-tab='contabilidad']").click()
    page.locator("#segurosContabilidadForm").wait_for(state="visible")
    page.wait_for_function(
        """
        () => document.querySelectorAll('#segurosCadenciaResponsable option').length > 1
        """,
        timeout=30_000,
    )

    page.evaluate("document.getElementById('finCrmTab')?.click()")
    page.locator("#hipotecaSection").wait_for(state="visible")
    assert page.locator("#hipotecaSection").is_visible()
    assert page.locator("#finSimSection").is_hidden()
    page.evaluate("document.getElementById('finSimTab')?.click()")
    page.locator("#finSimSection").wait_for(state="visible")
    assert page.locator("#finSimSection").is_visible()
    assert page.locator("#hipotecaSection").is_hidden()
