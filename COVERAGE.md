# Cobertura de tests

## Ejecutar cobertura

```bash
python -m pytest --cov=web --cov-report=term-missing --cov-report=html --cov-report=xml
```

Esto genera:

- resumen en terminal;
- `htmlcov/index.html`;
- `coverage.xml`.

## Abrir el informe HTML

En macOS:

```bash
open htmlcov/index.html
```

Alternativas:

```bash
xdg-open htmlcov/index.html
python -m webbrowser htmlcov/index.html
```

## Interpretar el informe

- `Stmts`: líneas ejecutables.
- `Miss`: líneas no ejecutadas por los tests.
- `Cover`: porcentaje de líneas cubiertas.
- `Branch` coverage: con `branch = true`, Coverage también contabiliza ramas condicionales.

## Umbral actual

El umbral inicial de CI está en `8.5%`.

Se eligió porque la cobertura total actual del paquete `web` con `branch = true` está en torno al `8.8%` y `web/server.py` domina la métrica por tamaño. El margen evita un bloqueo artificial mientras se siguen cerrando huecos reales.

## Cómo subirlo después

- Añade tests sobre rutas y ramas concretas de los módulos con menor cobertura.
- Recalcula la cobertura real con el mismo comando.
- Sube el umbral en pasos pequeños, por ejemplo `8.5 -> 9 -> 10`.

## JavaScript

`pytest-cov` no mide `web/app.js`, `web/app_shared.js` ni el resto de JavaScript.

Para validar JavaScript usa:

- `node --check web/app.js`
- `node --check web/app_shared.js`
- pruebas de navegador o herramientas E2E cuando haga falta comportamiento en runtime.
