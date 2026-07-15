# Roadmap

Base de analisis: `web/server.py`, `web/app.js`, `web/app-auth.js`, `web/app-routing.js`, `web/db_backend.py`, `web/auth_security.py`, `web/seguros_state.py`, `tests/`, `.github/workflows/ci.yml`, `requirements.txt`, `requirements-dev.txt` y `pyproject.toml`.

## Leyenda

| Etiqueta | Significado |
| --- | --- |
| `Hecho` | Visible en el codigo o en los tests del repositorio. |
| `Inferencia` | Deducido por fallbacks, compatibilidad legacy o ausencias detectadas. |

## Funcionalidades actuales por modulo

- Hecho: `Plataforma y autenticacion`: login, activacion, recuperacion, sesion persistida en BD, `api/health`, `api/me`, logout y carga de `.env` sin dependencias extra.
- Hecho: `Core workspace / admin`: resolucion de rutas por query string, multi-workspace, scoping por `workspace_id`, `workspace_company_id` y `empresa_id`, invitaciones, alta/edicion de usuarios y gestion de companies/workspaces.
- Hecho: `CRM / agenda / clientes`: dashboard, busqueda global, agenda, deep-linking y fichas de cliente, con routing centralizado en frontend.
- Hecho: `Gestoria`: contabilidad, facturas, asientos, modelos, documentos, importacion y conciliacion, Renta, presupuestos, tareas y exportaciones PDF/XLSX.
- Hecho: `Seguros`: polizas, renovaciones, siniestros, campañas, referidos, checklist, extraccion OCR y normalizacion de estados con transiciones bloqueadas.
- Hecho: `Inmobiliaria`: captaciones, inmuebles, demandas, visitas, matching, proceso guiado, portal, firmas, Catastro, valoracion y generacion de PDFs.
- Hecho: `Financiacion / hipotecas`: estudios, sincronizacion contable automatica, firmas, borrados seguros, PDFs y exportaciones.
- Hecho: `Fincas`: comunidades, vecinos, proveedores, incidencias, contabilidad y documentos.
- Hecho: `RRHH / registro horario`: personal, turnos, fichajes, ausencias, nominas, productividad, kiosko y utilidades de onboarding.
- Hecho: `Facturacion / portal cliente`: presupuestos, facturas, cobros, remesas, series, portal, requerimientos y automatizaciones.
- Hecho: `Legal Radar / automatizaciones`: copilot legal, library import, scans, digest, DGT lookup y auto-import opcional.
- Hecho: `Infraestructura`: S3 presign/upload/multipart, worker OCR en background, sweep horario, auto-scan legal, service worker PWA y compatibilidad SQLite/Postgres.
- Hecho: `GitHub y Render`: la CI de GitHub Actions ejecuta `python -m pytest` y `ruff check .`; el servidor escucha en `0.0.0.0`, usa `PORT` y arranca el bind antes de bootstraps pesados para evitar 502/timeouts en Render.

## Funcionalidades parcialmente terminadas

- Hecho: la migracion `workspace_company_id_rollout_v1` esta marcada como Fase 4 y sigue manteniendo backfills retrocompatibles por `empresa_id`, `workspace_id` y `workspace_company_id`.
- Hecho: las fases `service_first_clientes_v1` y `service_first_inmo_v1` siguen ampliando el modelo workspace-first sin eliminar del todo la compatibilidad legacy.
- Hecho: `ensure_workspace_default_company()` existe como stub y no crea ni vincula nada.
- Hecho: la vista `CRM Financiaciones` legacy sigue en el HTML, pero el propio frontend indica que ya no se usa y que el flujo real vive en el panel principal.
- Hecho: el modulo de valoracion de inmueble puede caer en `pendiente de configurar en este entorno`.
- Hecho: los simuladores incrustados de inmueble muestran `Simuladores no disponibles en este despliegue` si el motor no esta presente.
- Hecho: el boton de seed del catalogo core de Gestoria esta en frontend para evitar despliegues rotos por endpoints inexistentes.
- Inferencia: el cutover completo a workspace-first todavia no esta cerrado, porque el codigo sigue resolviendo `empresa_id` legacy en muchos puntos para no romper instalaciones antiguas.

## Funcionalidades pendientes detectables en el codigo

- Hecho: este checkout no versiona los artefactos que el servidor espera cargar (`schema.sql`, `docs/legal_inmobiliaria.json`, `docs/legal_radar_sources.json`, `docs/convenios_catalog.json`, plantillas PDF en `web/templates/` y catalogos en `data/`).
- Hecho: no hay manifiesto de despliegue a Render ni workflow de deploy en GitHub Actions; en `.github/workflows/` solo existe CI.
- Hecho: varias rutas dependen de configuracion externa y devuelven error claro cuando falta: `openpyxl`, `OPENAI_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`, `DOCUMENTAI_PROCESSOR_ID`, `SMTP_*`, `IMAP_*` y `AWS_S3_BUCKET` / `S3_BUCKET`.
- Hecho: el propio codigo mantiene la funcion `ensure_workspace_default_company()` como compatibilidad retirada, lo que sugiere que ese flujo esta pendiente de eliminacion completa o de una definicion nueva.
- Inferencia: faltan cierres formales para los flujos legacy de la vista BDT/Financiaciones y para la sustitucion definitiva de `empresa_id` por el modelo `workspace_company_id`.
- Inferencia: el catalogo core de Gestoria deberia pasar de workaround de cliente a operacion backend estable, para no depender de un boton que compensa endpoints inexistentes.

## Deuda tecnica

- Hecho: `web/server.py` concentra routing HTTP, auth, bootstrap de BD, migraciones, PDFs, OCR, S3, email, legal radar y logica de negocio en un unico monolito grande.
- Hecho: `web/db_backend.py` traduce SQL entre SQLite y Postgres con muchas reglas de compatibilidad, reescrituras y fallbacks.
- Hecho: la estrategia de migracion usa muchos `try/except` best-effort y backfills repetidos; el estado final depende del contenido real de cada BD.
- Hecho: el frontend conserva muchas ramas de compatibilidad `legacy_empresa_id` / `empresa_id` / `workspace_company_id` para no romper despliegues antiguos.
- Hecho: `web/app.js` centraliza gran parte de la UI y de la logica de negocio en un solo archivo grande.
- Hecho: la sincronizacion entre `index.html`, `sw.js` y las versiones cacheadas sigue siendo manual.
- Hecho: los artefactos de esquema y catalogos esperados por el servidor no estan versionados en este checkout.
- Inferencia: si el producto sigue creciendo, el coste de mantenimiento y el tiempo de arranque seguiran subiendo hasta que la logica se parta por dominios.

## Riesgos de seguridad

- Hecho: el scoping puede relajarse o endurecerse segun variables como `APP_WORKSPACE_MEMBERSHIP_ENFORCE`, `APP_S3_SCOPE_ENFORCE`, `APP_SUPERADMIN_ENFORCE` y `APP_WORKSPACE_AUTO_LINK_COMPANIES`.
- Hecho: la seguridad de cookies y sesiones depende de `APP_SESSION_COOKIE_SECURE`, `APP_SESSION_COOKIE_DOMAIN` y de cabeceras de proxy bien configuradas.
- Hecho: hay integraciones con S3, OpenAI, Google Cloud, SMTP, IMAP y webhooks de mensajes; todas dependen de secretos de entorno.
- Hecho: existen rutas publicas de portal/firma y rutas de subida/descarga que deben seguir validadas por workspace y por permiso.
- Hecho: el modo `APP_S3_LOCAL_FALLBACK` y otras rutas de compatibilidad pueden ampliar superficie si se usan fuera de entornos controlados.
- Inferencia: mientras convivan tantos modos legacy y v2, el riesgo principal es una mala combinacion de variables de entorno o un backfill incompleto que abra datos de otro workspace.

## Carencias de testing

- Hecho: `tests/` contiene 5 ficheros; la cobertura actual esta muy concentrada en hipotecas, finanzas, una comprobacion de alcance SQL y una E2E opcional.
- Hecho: la E2E esta desactivada por defecto con `RUN_PLAYWRIGHT_E2E=1` y ademas requiere Chrome disponible.
- Hecho: varios tests se saltan si falta `openpyxl`, asi que una parte de los flujos de exportacion puede quedar sin ejercitar en entornos minimos.
- Hecho: no hay tests de frontend, service worker, despliegue en Render, S3, OCR externo, email, Google Vision / Document AI ni OpenAI.
- Hecho: tampoco hay una bateria especifica para las migraciones `workspace_company_id` / `service-first` ni para los backfills de compatibilidad.
- Inferencia: la zona mas fragile es el conjunto de rutas que siguen teniendo ramas `legacy` y `best-effort`, porque hoy dependen mas del estado de la BD que de una suite de regresion amplia.

## Mejoras de rendimiento

- Hecho: ya existen indices de rendimiento y bootstraps en background para evitar 502/timeouts en listados y en arranque.
- Inferencia: seguir indexando los hot paths de dashboard y listados reducira scans completos en tenants grandes.
- Inferencia: extraer consultas agregadas a caches o precomputos ayudaria a evitar recomputos repetidos en dashboards de Gestoria, Inmobiliaria y RRHH.
- Inferencia: partir `web/server.py` por dominios reducira coste de arranque, memoria y complejidad de despliegue.
- Inferencia: hacer lazy-load de OCR, AI y otros integradores externos solo cuando se usen recortaria coste de inicio y fallos de dependencia.
- Inferencia: limitar la logica global de `web/app.js` con carga diferida por modulo reduciria el peso inicial del cliente.

## Prioridades

| Nivel | Que deberia entrar |
| --- | --- |
| Alta | Inferencia: cerrar el cutover workspace-first sin perder compatibilidad de datos, versionar o validar los artefactos que faltan, y cubrir auth/health/PDF/migraciones con smoke tests fiables. |
| Media | Inferencia: partir el monolito por dominios, reforzar indices y caches, mover el workaround de Gestoria al backend y ampliar la E2E opcional. |
| Baja | Inferencia: limpiar vistas legacy retiradas, pulir simuladores/valoracion, y mejorar UI secundaria una vez que el nucleo este estable. |

## Quick wins

- Inferencia: añadir una comprobacion de arranque o de CI que falle pronto si faltan `schema.sql`, plantillas o catalogos esperados.
- Inferencia: sumar un smoke test de `api/health`, `api/me` y al menos un flujo de PDF representativo.
- Inferencia: ejecutar la E2E opcional de forma manual o programada en GitHub Actions cuando haya Chrome disponible.
- Inferencia: documentar en el propio roadmap que el seed del catalogo core de Gestoria es un parche temporal, no el flujo final.
- Inferencia: reducir duplicacion entre frontend y backend en la resolucion legacy de `empresa_id`.

## Tareas que no deben abordarse todavia

- Inferencia: no eliminar la compatibilidad `empresa_id` / `legacy_empresa_id` hasta que el inventario de datos y los backfills del modelo workspace-first esten validados.
- Inferencia: no forzar `APP_WORKSPACE_MEMBERSHIP_ENFORCE`, `APP_S3_SCOPE_ENFORCE` o `APP_SUPERADMIN_ENFORCE` en produccion sin una ventana de migracion y pruebas de acceso.
- Inferencia: no reescribir el frontend a otro framework ni partir el backend en servicios antes de tener regresion para auth, PDFs, OCR, S3 y scoping.
- Inferencia: no retirar los fallbacks de OpenAI, Google, SMTP, IMAP o S3 hasta tener runbooks y entornos de prueba equivalentes.
- Inferencia: no borrar las vistas legacy retiradas hasta confirmar que todos los flujos equivalentes estan cubiertos por el panel principal y por tests.

## Hoja de ruta de 90 dias

| Ventana | Objetivo | Entregables principales | Prioridad |
| --- | --- | --- | --- |
| D0-D30 | Estabilizacion | Validar o versionar los artefactos esperados por el servidor, cerrar smoke tests de auth y health, y comprobar que CI y Render arrancan con el mismo contrato. | Alta |
| D31-D60 | Cutover workspace-first | Reducir la duplicacion `empresa_id` / `workspace_company_id`, mover los workarounds de frontend al backend, y endurecer cookies, scoping y permisos con tests de regresion. | Alta |
| D61-D90 | Rendimiento y limpieza | Partir `web/server.py` por dominios, reforzar caches e indices en rutas calientes, ampliar la E2E opcional y retirar stubs o vistas legacy ya sustituidas. | Media |
