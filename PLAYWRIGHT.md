# Playwright

Playwright se usa aquí para pruebas end-to-end del frontend real de la SPA.
La suite arranca un servidor local efímero, usa SQLite temporal por test y abre Chromium en modo headless por defecto.

## Qué prueba

- Carga inicial de `index.html`.
- Orden de carga de los scripts principales.
- Login correcto e incorrecto.
- Acceso y bloqueo de rutas administrativas.
- Navegación entre módulos y mantenimiento del deep link tras recargar.
- Enlaces públicos de activación con token válido e inválido.

## Playwright vs tests unitarios

- Los tests unitarios validan helpers, regresiones y lógica aislada.
- Playwright valida el comportamiento real del navegador, el DOM, el routing, la sesión y los flujos de usuario.
- Esta suite no sustituye a los unit tests; los complementa.

## Instalación

Instala Chromium con el comando oficial:

```bash
python -m playwright install chromium
```

En CI se instala con dependencias del sistema:

```bash
python -m playwright install --with-deps chromium
```

La dependencia `playwright` vive en `requirements-dev.txt`, no en `requirements.txt`.

## Ejecución

Modo headless, que es el valor por defecto:

```bash
python -m pytest tests/e2e -v
```

Modo visible:

```bash
PLAYWRIGHT_HEADLESS=0 python -m pytest tests/e2e -v
```

Ejecutar una sola prueba:

```bash
python -m pytest tests/e2e/test_login.py -k success -v
```

## Servidor y datos

- Cada test arranca un servidor local en `127.0.0.1` sobre un puerto libre.
- La base de datos es SQLite temporal y aislada por test.
- Los usuarios, workspaces y tokens son ficticios.
- No se usa Render ni ningún secreto real.

## Dónde ver resultados

- Informe HTML: `playwright-report/index.html`
- Capturas: `screenshots/`
- Traces: `traces/`
- Logs sanitizados: `test-results/`

## Cómo revisar una alerta

1. Abre el HTML del informe.
2. Mira el test fallido y su URL saneada.
3. Revisa la captura asociada.
4. Abre el trace para ver la secuencia de navegación y red.
5. Compara el fallo con el texto esperado del UI o con el estado de la API.

## Falso positivo vs bug real

- Falso positivo: un fallo provocado por un selector demasiado estricto, un tiempo de espera corto o una dependencia externa stubbed.
- Bug real: `pageerror`, respuesta `500`, ruta principal con `404`, sesión que no se crea o un deep link que deja la pantalla en un estado inválido.

## Política de alertas

- No se ignoran fallos por defecto.
- Si el test falla, se guarda screenshot y trace.
- No se registran contraseñas reales, cookies ni tokens sensibles en los logs sanitizados.
- Los tokens y contraseñas de esta suite son ficticios y exclusivos de pruebas.

## Pull requests bloqueadas

- Si una PR queda bloqueada por Playwright, abre el informe generado en la ejecución de CI.
- Revisa el paso fallido, la captura y el trace.
- Corrige el bug o el test antes de reintentar.

## Añadir nuevos flujos

1. Crea un test en `tests/e2e/`.
2. Reutiliza la fixture `page` y el contenedor `e2e_app`.
3. Usa solo datos sintéticos.
4. Espera estados visibles del DOM, no solo respuestas HTTP.
5. Deja fallar ante `pageerror` o `500`.

## Limitaciones actuales

- Los recursos externos de tipografías y Leaflet se stubbean en la suite.
- No se graban vídeos por defecto para evitar capturar datos sensibles.
- La cobertura de navegación es todavía parcial respecto al producto completo.
- La suite no depende de servicios externos reales.

## Flujos pendientes recomendados

1. Flujo completo de alta y edición de entidades principales.
2. Subida/descarga de documentos con permisos.
3. OCR y validación de documentos.
4. Flujos de contabilidad más largos.
5. Casos de portal público adicionales.
