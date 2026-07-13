# AGENTS.md

Guía operativa para trabajar en este repositorio.

## Arquitectura

- El backend principal vive en `web/server.py`.
- Es una aplicación Python con servidor HTTP propio (`ThreadingHTTPServer`) que:
  - sirve la SPA y los assets estáticos,
  - expone la API `/api/*`,
  - inicializa y migra el esquema de la base de datos,
  - gestiona autenticación, sesiones y permisos,
  - genera PDF/XLSX/otros documentos,
  - ejecuta tareas auxiliares como OCR, sincronizaciones y automatizaciones.
- El frontend es una SPA clásica sin framework externo:
  - `web/index.html` es el shell HTML,
  - `web/app.js` contiene el estado y la lógica principal de la interfaz,
  - `web/app-auth.js` gestiona login, activación de cuenta y recuperación,
  - `web/app-routing.js` resuelve el deep-linking por query string,
  - `web/ui-foundation.js` aporta utilidades de formularios, borradores y contexto visual,
  - `web/sw.js` implementa la caché PWA del shell y de los assets.
- `web/db_backend.py` selecciona SQLite o Postgres y aplica compatibilidad entre ambos.
- `web/schema_support.py` aplica scripts de esquema y columnas condicionales.
- `web/auth_security.py` centraliza el hashing y verificación de contraseñas.
- `web/seguros_state.py` normaliza estados de seguros y valida transiciones permitidas.
- `assets/` contiene logos, iconos, imágenes y recursos de marca usados por la UI y por generación documental.
- `tests/` contiene pruebas unitarias y una E2E de navegador.
- El repositorio no usa `pyproject.toml`; la instalación se hace con `pip` y archivos `requirements*.txt`.

## Módulos Principales

- `CRM 360` y capa de workspace/tenant: navegación, panel home, scoping por workspace y configuración multiempresa.
- `Gestoría`: contabilidad, facturas, asientos, modelos fiscales, libros y documentos.
- `Seguros`: pólizas, estados, OCR, renovaciones y contabilidad asociada.
- `Inmobiliaria`: inmuebles, captaciones, demandas, visitas, contratos y documentación.
- `Financiación / Hipotecas`: asesoramientos, workflow, comisiones, PDFs y exportaciones.
- `Fincas`: comunidades, vecinos, proveedores, incidencias y contabilidad de comunidades.
- `RRHH` y `Registro Horario`: personal, fichajes, ausencias, nóminas, productividad y exportaciones.
- `Facturación` y `Portal Cliente`: presupuestos, facturas, cobros, remesas y portal público/privado.
- `Legal Radar` y catálogos auxiliares: conocimiento legal y fuentes documentales.
- `S3 / uploads`: carga, presign, redirección y acceso controlado a ficheros.

## Instalación

1. Usa Python `3.11.11`, que es la versión declarada en `.python-version`.
2. Crea y activa un entorno virtual:

```bash
python -m venv .venv
source .venv/bin/activate
```

3. Instala dependencias de ejecución y desarrollo:

```bash
pip install -r requirements-dev.txt
```

4. Si vas a usar las rutas SQLite por defecto, crea el directorio `data/` o pasa una ruta alternativa con `--db` y `--ocr-db`.
5. Si vas a usar Postgres, define `DATABASE_URL` o `POSTGRES_URL` en el entorno o en `.env`.

## Ejecución

- Arranque habitual:

```bash
python -m web.server --host 0.0.0.0 --port 8000
```

- También funciona como script directo:

```bash
python web/server.py
```

- Parámetros útiles del servidor:
  - `--db`: ruta de la base de datos principal.
  - `--ocr-db`: ruta de la base OCR.
  - `--ocr-workers`: número de workers OCR.
  - `--host` y `--port`: host y puerto de escucha.
- El servidor carga `.env` automáticamente.
- La SPA usa assets versionados con `?v=...` y un service worker; si cambias nombres o bundles, sincroniza `index.html`, `web/sw.js` y las versiones cacheadas.

## Tests

- Ejecuta la suite completa con:

```bash
python -m pytest
```

- La prueba E2E del navegador está desactivada por defecto y requiere Chrome:

```bash
RUN_PLAYWRIGHT_E2E=1 python -m pytest tests/test_empresa_contabilidad_e2e.py
```

- La suite mezcla `unittest` con `pytest`; no conviertas los tests a otro estilo sin necesidad.
- Varias pruebas crean esquemas SQLite en memoria o inspeccionan texto fuente, así que evita refactors casuales en SQL, alias y nombres de helpers sin ajustar los tests.

## Convenciones De Código

- Python:
  - usa `snake_case` para funciones, variables y módulos,
  - usa clases solo cuando aporten estado o un contrato claro,
  - sigue el patrón de helpers verbales: `ensure_*`, `resolve_*`, `build_*`, `compute_*`, `sync_*`, `delete_*`, `collect_*`, `sanitize_*`,
  - conserva la compatibilidad SQLite/Postgres cuando toques SQL o bootstrap.
- JavaScript:
  - el frontend se organiza en IIFEs que publican APIs en `window` (`CRMAppAuth`, `CRMAppRouting`, `CRMUI`),
  - mantén ese patrón salvo que reestructures también el shell completo,
  - usa la lógica existente de `?v=...` para busting de caché.
- CSS:
  - conserva las variables de `:root`,
  - sigue el lenguaje visual existente basado en layout responsive, `clamp()` y clases semánticas,
  - evita introducir un sistema de estilos paralelo.
- Mantén los comentarios breves y funcionales, especialmente cuando expliquen compatibilidad legacy, cachés o rutas de seguridad.

## Reglas De Seguridad

- No hardcodees secretos, tokens, contraseñas ni credenciales de nube.
- Usa `.env` y variables de entorno para configuración sensible.
- No amplíes el allowlist de archivos estáticos ni la lógica de `safe_resolve_under()` sin necesidad real.
- Respeta la autenticación y el scoping por `workspace_id`, `workspace_company_id` y `empresa_id` en frontend y backend.
- Mantén las restricciones de sesión, rate limiting de login y cookies `HttpOnly` / `SameSite`.
- No desactives controles como `APP_SUPERADMIN_ENFORCE`, `APP_WORKSPACE_MEMBERSHIP_ENFORCE` o `APP_S3_SCOPE_ENFORCE` salvo que sea parte explícita del cambio.
- No registres URLs con tokens o passwords en claro; sanitiza parámetros sensibles antes de loguear.
- No sirvas HTML como cache `immutable`; el backend y el service worker ya están ajustados para evitar caches rotas.
- Si añades nuevas rutas de subida o descarga, valida siempre el acceso y el path bajo el directorio esperado.

## Flujo Git

- Trabaja sobre una rama temática y mantén cada cambio pequeño y enfocado.
- Antes de editar, revisa `git status` y el alcance del diff.
- No uses comandos destructivos ni reescritura de historia salvo petición explícita.
- Si cambias `web/index.html`, `web/sw.js` o assets cacheados, actualiza las referencias versionadas en conjunto.
- Antes de finalizar cualquier cambio debes ejecutar siempre `python -m pytest`.
- Si la suite falla, corrige el problema o documenta claramente el bloqueo antes de cerrar el trabajo.
