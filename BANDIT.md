# Bandit

Bandit analiza el código Python buscando patrones de riesgo de seguridad:

- uso inseguro de `subprocess`;
- `eval` / `exec`;
- SQL construido con f-strings o concatenación;
- importaciones y APIs criptográficas débiles;
- llamadas HTTP o parsing de XML potencialmente peligrosos;
- `assert` y otras rutas defensivas que no deberían quedar en producción.

## Ejecución local

```bash
bandit -r web -c bandit.yaml
```

Para generar el informe JSON que usa CI:

```bash
bandit -r web -c bandit.yaml --severity-level high --confidence-level high -f json -o bandit-report.json
```

## Interpretación

- `HIGH` se trata como bloqueo en CI.
- `MEDIUM` y `LOW` se revisan manualmente y, si no son vulnerabilidades reales, se documentan como riesgo aceptado.
- `HIGH confidence` indica que Bandit está bastante seguro de su regla.
- `LOW confidence` suele requerir revisión manual antes de actuar.

## Política Del Proyecto

- No se usa `# nosec` para esconder problemas de forma genérica.
- Solo se permite cuando la línea es segura por construcción y la justificación cabe en un comentario breve.
- Si un hallazgo es un falso positivo recurrente, se documenta como riesgo aceptado y se revisa junto al cambio funcional que lo origina.

## Revisión De Nuevos Hallazgos

1. Ejecuta Bandit localmente y revisa el archivo `bandit-report.json`.
2. Prioriza `HIGH` y `MEDIUM` con `HIGH confidence`.
3. Corrige el código si el dato o la ruta es realmente controlable desde fuera.
4. Si la alerta es estructural y no hay entrada no confiable, documenta el riesgo con una justificación breve.
5. Mantén el workflow de GitHub Actions para que cualquier nuevo `MEDIUM` o `HIGH` bloquee el pipeline.

## Umbral Actual

El workflow de CI ejecuta Bandit con umbral `high/high`. Eso deja pasar el ruido actual de severidad media y baja, pero bloquea regresiones de severidad alta.
