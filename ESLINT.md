# ESLint

ESLint analiza el JavaScript del frontend y del service worker para detectar errores estáticos antes de llegar al navegador o a CI.
En este proyecto se usa sobre JavaScript clásico en navegador, sin bundler ni framework, y no cambia el comportamiento funcional.

## Qué analiza

- Variables y nombres no definidos.
- Re-declaraciones y claves duplicadas.
- Código inalcanzable.
- Comparaciones y tipos dudosos.
- Asignaciones sospechosas.
- Variables no usadas y bloques innecesarios.
- Uso de `console` fuera de `warn` y `error`.

## ESLint vs `node --check`

- `node --check` solo valida sintaxis.
- ESLint además entiende el contexto del archivo, detecta globals, variables no usadas, ramas muertas y patrones que pueden ser bugs reales.
- Ambos son útiles: `node --check` protege la sintaxis y ESLint añade análisis semántico ligero.

## Archivos incluidos

- `web/app.js`
- `web/app-auth.js`
- `web/app-routing.js`
- `web/app_shared.js`
- `web/ui-foundation.js`
- `web/sw.js`

Los archivos de configuración JavaScript del proyecto usan la configuración de Node en `eslint.config.js`.

## Reglas activadas

Errores:

- `no-undef`
- `no-redeclare`
- `no-dupe-keys`
- `no-dupe-args`
- `no-unreachable`
- `no-constant-condition` con bucles permitidos
- `valid-typeof`
- `use-isnan`
- `no-self-assign`
- `no-import-assign`
- `no-ex-assign`
- `no-func-assign`

Warnings:

- `no-unused-vars`
- `no-useless-catch`
- `no-useless-escape`
- `eqeqeq`
- `curly`
- `no-console`

`console.warn` y `console.error` están permitidos. `console.log` sigue siendo deuda histórica y se deja como warning cuando aparece.

## Warnings aceptados temporalmente

- `no-unused-vars` en helpers y callbacks históricos.
- `eqeqeq` en zonas donde el código legacy usa comparaciones laxas.
- `curly` en bloques cortos ya consolidados.
- `no-console` en trazas y diagnósticos no críticos.

## Cómo ejecutar

Instalar dependencias JavaScript:

```bash
npm ci
```

Ejecutar el lint normal:

```bash
npm run lint:js
```

Ejecutar solo con warnings ocultos:

```bash
npm run lint:js:quiet
```

## Cómo corregir una alerta

1. Lee el error o warning y confirma si es un bug real, una global legítima o deuda técnica.
2. Corrige el código si el cambio no altera contratos ni IDs del frontend.
3. Si el uso es intencional y estable, documenta el global o la excepción en la configuración.
4. Evita `eslint-disable` salvo casos puntuales y justificados.

## Política sobre `eslint-disable`

- No se usan `eslint-disable` globales.
- No se usan `eslint-disable-file`.
- Si un caso puntual es inevitable, se añade una línea concreta con la regla exacta y un comentario breve de justificación.

## Política sobre globals de navegador

- Los scripts del frontend siguen cargándose como scripts globales.
- `globals.browser` y `globals.serviceworker` están declarados en la configuración para reflejar el entorno real.
- No se convierte el proyecto a módulos ES porque rompería el patrón actual de carga.

## Integración con pre-commit y CI

- `pre-commit` ejecuta ESLint solo sobre los archivos JavaScript del frontend que cambian.
- El hook usa `npx --no-install eslint` y no reinstala dependencias.
- Si `node_modules/` no existe, el hook falla rápido y la corrección es ejecutar `npm ci`.
- GitHub Actions ejecuta `npm ci` y luego `npm run lint:js` antes de `pytest`.

## Qué sigue requiriendo Playwright

ESLint no valida comportamiento real del navegador, sesiones, routing en vivo ni errores asíncronos del DOM.
Los flujos que siguen necesitando Playwright son:

- Login y sesión real.
- Navegación entre pantallas y deep links.
- Permisos de usuario normal y administrador.
- Enlaces públicos y tokens de acceso.
- Fallos de carga, `pageerror` y respuestas HTTP inesperadas.
