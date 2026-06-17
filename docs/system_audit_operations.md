# System Audit Operations

## Artefactos persistentes

Cada ejecucion de `scripts/run_system_audit.py` deja:

- `reports/system_audit/system-audit-*.json`
- `reports/system_audit/system-audit-*.ollama.md`
- `reports/system_audit/system-audit-history.jsonl`
- `reports/system_audit/latest-system-audit.json`
- `reports/system_audit/latest-system-audit.html`

## Clasificacion de avisos

La matriz de produccion clasifica cada endpoint en:

- `ok`
- `not_applicable`
- `expected_permission_denied`
- `permission_review`
- `missing_empresa_id`
- `server_error`
- `failed_check`
- `review`

Solo los avisos con `action_required=true` deben tratarse como incidencia real.

## Alertas

El runner genera `alerts` a partir de:

- pasos fallidos o timeout,
- avisos accionables de la matriz de endpoints.
- deriva de accesos (`production_auth_drift`): backend incorrecto, `admin_user_lookup`
  roto o usuarios de pruebas que dejan de validar la contrasena compartida.
- reconciliacion de negocio (`system_business_reconciliation`): KPIs, dashboards y
  resúmenes que dejan de cuadrar con el detalle esperado.
- smoke por proceso (`production_process_smoke`): procesos críticos que dejan de
  quedar verdes aunque el módulo siga respondiendo.

El HTML `latest-system-audit.html` resume:

- estado global,
- run ID,
- alertas accionables,
- tendencia respecto a la ejecucion anterior,
- historial reciente,
- pasos y duracion.

La tendencia incluye:

- fallos repetidos,
- fallos nuevos,
- fallos recuperados,
- racha de ejecuciones fallidas,
- modulos con incidencias accionables repetidas o nuevas,
- cambios en la clasificacion de endpoints,
- variacion de avisos accionables.

## Hook local

Para instalar revision pre-push:

```bash
./scripts/install_git_hooks.sh
```

El hook ejecuta:

```bash
python3 scripts/ollama_diff_review.py --staged --fail-on-review --json
```

## Modelos separados

Variables soportadas:

- `OLLAMA_AUDIT_MODEL`
- `OLLAMA_AUTOFIX_MODEL`
- `OLLAMA_REVIEW_MODEL`
- `RUN_SYSTEM_AUDIT_AUTH_DRIFT=1`
- `CRM_EXPECTED_BACKEND=postgres`
- `CRM_AUDIT_SHARED_LOGIN_USERS=usuario1,usuario2,...`
- `CRM_AUDIT_SHARED_PASSWORD=Modernia2026`
- `RUN_SYSTEM_AUDIT_MODULE_SMOKE=1`
- `RUN_SYSTEM_AUDIT_VOLUME_THRESHOLDS_PATH=docs/module_volume_thresholds.json`
- `RUN_SYSTEM_AUDIT_MODULE_EXPECTATIONS_PATH=docs/module_smoke_expectations.json`
- `CRM_AUDIT_IDENTITY_POLICY_PATH=docs/audit_identity_policy.json`
- `RUN_SYSTEM_AUDIT_AUTO_QUARANTINE=1`
- `RUN_SYSTEM_AUDIT_BROWSER_MODULE_SMOKE=1`
- `RUN_SYSTEM_AUDIT_BUSINESS_RECONCILIATION=1`
- `RUN_SYSTEM_AUDIT_PROCESS_SMOKE=1`
- `RUN_SYSTEM_AUDIT_SUPERVISOR=1`
- `RUN_SYSTEM_AUDIT_SAFE_AUTOREMEDIATE=1`
- `RUN_SYSTEM_AUDIT_IMPROVEMENT_ADVISOR=1`
- `RUN_SYSTEM_AUDIT_AUTO_CLEAR_QUARANTINE=1`
- `RUN_SYSTEM_AUDIT_RECONCILIATION_PATH=docs/reconciliation_checks.json`
- `RENDER_WEB_SERVICE_ID=<render_web_service_id>`
- `RENDER_API_KEY=<render_api_key>`

Sincronizacion segura de configuracion Render:

```bash
python3 scripts/render_env_sync.py \
  --api-key "$RENDER_API_KEY" \
  --service-id "$RENDER_WEB_SERVICE_ID" \
  --set APP_EMERGENCY_MODE=off \
  --json
```

Este script primero lee las variables actuales y luego hace merge. Evita el error
de pisar toda la configuracion con un `PUT` parcial.

La cuarentena operativa publica:

- `APP_EMERGENCY_MODE=off|read_only|quarantine`
- `APP_EMERGENCY_SCOPE=<global|modulo|workspace>`
- `APP_EMERGENCY_REASON=<motivo>`
- `RUN_SYSTEM_AUDIT_AUTOFIX_PREPARE_BRANCH=1`
- `RUN_SYSTEM_AUDIT_AUTOFIX_MATERIALIZE_TEST=1`

Recomendacion:

- auditoria: modelo pequeno/rapido,
- autofix: modelo coder,
- review de diff: modelo coder o reasoning corto.

## CI de guardarrailes

Se ha anadido `.github/workflows/system-guardrails.yml` para que en cada `push` y `pull_request` se ejecute:

- regeneracion de `docs/system_knowledge.json`,
- tests de automatizacion Ollama,
- revision heuristica del diff (`ollama_diff_review.py --no-ollama`),
- render local del dashboard de auditoria.

En CI no se depende de Ollama; la revision usa solo heuristicas y memoria del sistema.

## Autofix mas autonomo

Si una auditoria falla y se activa:

- `RUN_SYSTEM_AUDIT_AUTOFIX=1`
- `RUN_SYSTEM_AUDIT_AUTOFIX_PREPARE_BRANCH=1`
- `RUN_SYSTEM_AUDIT_AUTOFIX_MATERIALIZE_TEST=1`

el agente puede:

- crear la rama `autofix/<run_id>` solo si el arbol git esta limpio,
- materializar un test base en la ruta sugerida solo si no existe todavia,
- seguir sin tocar produccion ni desplegar.

## Supervisor de negocio

Capas de conocimiento activas:

- `docs/process_catalog.json`
- `docs/business_rules.json`
- `docs/system_invariants.json`
- `docs/reconciliation_checks.json`
- `docs/canonical_scenarios.json`
- `docs/improvement_opportunities.jsonl`

Checks nuevos:

- `scripts/system_business_reconciliation.py`
- `scripts/prod_process_smoke.py`

Objetivo:

- detectar dashboards que calculan mal,
- detectar procesos críticos que aparentan cargar pero rompen la lógica,
- dar a Ollama contexto estructurado de proceso, regla, invariante y escenario canónico.

## Asesor de mejoras

El asesor:

- lee auditoría, tendencia, incidentes y memoria del sistema,
- propone mejoras priorizadas con evidencia,
- y las persiste en `docs/improvement_opportunities.jsonl`.

Script:

- `scripts/system_improvement_advisor.py`
