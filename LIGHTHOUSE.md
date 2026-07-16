# Lighthouse CI

Lighthouse CI mide la salud del frontend público desde un navegador real y guarda resultados reproducibles en local y en GitHub Actions.
En este repositorio se usa sobre el shell de login público de la SPA, sin Render y sin credenciales reales.

## Qué mide

- `performance`
- `accessibility`
- `best-practices`
- `seo`

Lighthouse 12.1.0 ya no expone un bloque PWA separado. En este proyecto la parte PWA se valida con el propio shell, el service worker, el manifiesto y tests de regresión de assets.

## Lighthouse vs ESLint vs Playwright

- `ESLint` detecta errores estáticos en JavaScript antes de ejecutar el navegador.
- `Playwright` valida flujos reales de usuario, sesión, routing y errores del DOM.
- `Lighthouse CI` mide la experiencia del shell real en navegador: rendimiento, accesibilidad, SEO y buenas prácticas.

Las tres herramientas se complementan. Ninguna sustituye a las otras.

## Páginas auditadas

- `/?swcleared=1`

Ese URL apunta al shell público estable del login y evita el redireccionamiento inicial que usa la app para limpiar cachés de service worker.

## Instalación

Instala las dependencias de desarrollo del proyecto:

```bash
npm ci
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

`CHROME_PATH` debe apuntar a un Chrome o Chromium ejecutable. En macOS se usa por defecto Chrome de aplicación si existe; en CI se resuelve desde la instalación de Chromium.

## Cómo ejecutar

Ejecuta la validación completa:

```bash
npm run lighthouse
```

Comandos separados:

```bash
npm run lighthouse:collect
npm run lighthouse:assert
npm run lighthouse:local
```

`lighthouse:collect` y `lighthouse:assert` usan la misma configuración, pero el comando `lighthouse`/`lighthouse:local` resuelve un puerto libre y crea una base SQLite temporal antes de lanzar LHCI.
Si quieres fijar la ruta de resultados, define `LHCI_TMPDIR` antes de ejecutar el comando.

## Cómo interpretar las categorías

- `performance`: tiempo de carga y coste de ejecución del shell.
- `accessibility`: etiquetas, navegación y nombres accesibles.
- `best-practices`: consola, recursos, compatibilidad y prácticas seguras.
- `seo`: metadatos y señales básicas de indexación.

## Métricas principales

- `FCP` `First Contentful Paint`: cuándo aparece el primer contenido visible.
- `LCP` `Largest Contentful Paint`: cuándo aparece el contenido principal.
- `TBT` `Total Blocking Time`: cuánto bloquea JavaScript el hilo principal.
- `CLS` `Cumulative Layout Shift`: cuánto se desplaza la interfaz mientras carga.
- `Speed Index`: rapidez con la que el contenido se visualiza.

## Umbrales actuales

Los umbrales están fijados para bloquear regresiones reales, no para perseguir un 100% artificial.

- `performance`: mínimo `0.30`
- `accessibility`: mínimo `1.00`
- `best-practices`: mínimo `0.95`
- `seo`: mínimo `0.90`
- `errors-in-console`: mínimo `1.00`
- `meta-description`: mínimo `1.00`
- `redirects`: mínimo `1.00`

Audits con nivel `warn` inicial:

- `bootup-time`
- `cumulative-layout-shift`
- `dom-size`
- `first-contentful-paint`
- `interactive`
- `largest-contentful-paint`
- `max-potential-fid`
- `offscreen-images`
- `render-blocking-resources`
- `server-response-time`
- `speed-index`
- `total-byte-weight`
- `unminified-css`
- `unminified-javascript`
- `unsized-images`
- `unused-css-rules`
- `unused-javascript`
- `uses-text-compression`
- `valid-source-maps`
- `bf-cache`

Estos avisos señalan deuda técnica y pueden endurecerse poco a poco cuando la base del frontend mejore.

## Cómo abrir los informes

- Los resultados locales se escriben en `${LHCI_TMPDIR}/lighthouse-results`.
- Si no defines `LHCI_TMPDIR`, el helper imprime la ruta temporal en consola.
- El workflow de GitHub Actions publica un artifact llamado `lighthouse-results`.
- Dentro del directorio aparecen HTML, JSON y `manifest.json` con el resumen de runs.

## Cómo revisar un fallo

1. Abre el HTML generado en `${LHCI_TMPDIR}/lighthouse-results`.
   Si usaste el helper local sin fijar `LHCI_TMPDIR`, abre el directorio que imprimió en consola.
2. Revisa la categoría o audit que haya fallado.
3. Mira si el problema viene de un 404, de consola, de metadatos o de peso de assets.
4. Comprueba si el fallo es una regresión real o una limitación aceptada del shell local.

## Accesibilidad

Cuando Lighthouse marque un problema de accesibilidad:

- añade `label` visibles a inputs;
- usa `alt` útil en imágenes decorativas o funcionales;
- da nombre accesible a botones e iconos;
- evita contrastes pobres;
- conserva el orden lógico de tabulación.

## Política de `eslint-disable` equivalente

No existe un `disable` en Lighthouse, pero sí una política de umbrales:

- no bajar un umbral para ocultar un problema real;
- si el problema es conocido y no accionable, documentarlo explícitamente;
- preferir un warning temporal antes que un fallo silencioso;
- no eliminar un audit solo por ruido.

## Limitaciones actuales

- Lighthouse 12.1.0 no expone una categoría PWA separada.
- La pantalla auditada es el login público, así que parte del coste medido depende de carga inicial y assets públicos.
- Tipografías y recursos externos pueden variar según red y caché.
- El shell sigue teniendo CSS y JavaScript históricos grandes; esos avisos se dejan como warning por ahora.

## Política del proyecto

- No se usan datos reales.
- No se usa Render.
- No se suben resultados a servicios externos.
- No se rebajan umbrales para esconder deuda técnica.
- Si una regresión rompe Lighthouse, se corrige el problema o se documenta la limitación.

## Siguientes mejoras recomendadas

1. Reducir el peso del shell público.
2. Seguir endureciendo `performance` y `best-practices` cuando el baseline mejore.
3. Reforzar cobertura de accesibilidad en el login y en los módulos con más DOM.
4. Revisar si conviene añadir una pantalla pública más pequeña para auditorías de rendimiento.
