# CRM Autofix Agent

El agente de autofix convierte una auditoria fallida en un plan de reparacion
accionable. Su modo actual es seguro: no modifica codigo, no despliega y no toca
produccion.

## Flujo actual

1. Lee un `system-audit-*.json` fallido.
2. Carga `docs/system_knowledge.json`.
3. Genera un plan heuristico con modulo, ficheros probables, tests y estrategia.
4. Pide a Ollama un plan estructurado si hay `OLLAMA_BASE_URL`.
5. Acepta la respuesta de Ollama solo si cumple el esquema esperado.
6. Escribe:
   - `autofix_plan.json`
   - `codex_repair_prompt.md`
7. Propone una regresion minima en `regression_test_outline`.

## Niveles de autonomia

- Nivel 1: diagnostico y plan.
- Nivel 2: ejecutar tests relacionados y proponer regresion minima. Estado actual.
- Nivel 3: preparar parche en rama local, sin push.
- Nivel 4: abrir PR automatico con tests verdes.
- Nivel 5: auto-merge/deploy solo para cambios triviales y acotados.

## Politica de seguridad

- Nunca modifica produccion.
- Nunca ejecuta operaciones destructivas.
- No acepta respuestas libres de Ollama como plan valido.
- No ejecuta tests E2E salvo `RUN_AUTOFIX_E2E=1`.
- No debe hacer push/deploy automatico sin una politica explicita por nivel.

## Uso

```bash
python3 scripts/system_autofix_agent.py reports/system_audit/system-audit-YYYY.json --json
```

Para ejecutar tests seguros relacionados:

```bash
python3 scripts/system_autofix_agent.py reports/system_audit/system-audit-YYYY.json --run-tests --json
```

Para integrarlo con el runner:

```bash
RUN_SYSTEM_AUDIT_AUTOFIX=1 python3 scripts/run_system_audit.py --skip-local --include-production-api --include-system-matrix --ollama --fail-fast
```

## Revision local antes de push

```bash
python3 scripts/ollama_diff_review.py --json
```

Para revisar solo lo staged y fallar si hay riesgos:

```bash
python3 scripts/ollama_diff_review.py --staged --fail-on-review --json
```
