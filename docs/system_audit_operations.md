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

El HTML `latest-system-audit.html` resume:

- estado global,
- run ID,
- alertas accionables,
- pasos y duracion.

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

Recomendacion:

- auditoria: modelo pequeno/rapido,
- autofix: modelo coder,
- review de diff: modelo coder o reasoning corto.
