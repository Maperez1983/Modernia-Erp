# Auditoría técnica (CRM Verifika²) — 2026-04-06

## Resumen ejecutivo

- El mayor riesgo operativo observado era la **inestabilidad/intermitencia de Postgres** (pool saturado + bursts de PWA/iOS) y el **descentrado de iconos iOS** en PWA.
- El sistema ya incorpora buenas prácticas clave: **gzip + caché inmutable en assets versionados**, **/api/health con TTL**, y **bootstrap DB en background**.

## Cambios aplicados en esta iteración

### PWA / iOS

- Se regeneran iconos centrados en `web/icons/ios/v26/` y se alinean referencias:
  - `web/index.html` (apple-touch-icon + manifest + favicon)
  - `web/manifest.webmanifest` (icon-192/icon-512)
  - `web/sw.js` (precache shell)
  - `web/server.py` (compat/rewrites de `/icons/...` hacia la versión actual)
- Se actualiza `assets/verifika2/verifika2_app_icon.svg` y `assets/verifika2/verifika2_mark.svg` para que el **“²” vaya superpuesto** sobre la V-check (más distintivo de marca).

### Base de datos (Postgres)

- Se baja el **pool por defecto** a 8 (`APP_PG_POOL_MAX`, override por env) para planes pequeños (256MB) y evitar “tumbar” Postgres por exceso de conexiones.
- `/api/health` deja de abrir **conexiones extra** cuando el error es “pool saturado” (evita empeorar el problema en picos).
- Se eliminan SQLs con `strftime('%Y'...)` en rutas críticas y se sustituyen por `substr(...)` (más rápido y usable por índices en TEXT ISO).
- Se añade `perf_indexes_v2` (índices adicionales best-effort) para tablas que empezaron a pesar más con uso real.

## Hallazgos y recomendaciones (sin romper nada)

### Rendimiento

- `web/app.js` es grande (≈1.8MB). Ya se sirve con gzip; la mejora real a futuro sería **dividir carga** (lazy-load) por módulos/vistas.
- Mantener **versionado coherente** entre `sw.js`, `manifest.webmanifest` e inclusiones en `index.html` para evitar PWA “atascadas”.

### Postgres / estabilidad

- Recomendado en Render:
  - `APP_PG_POOL_MAX=8` (o 6 si el plan es muy pequeño y el tráfico bajo)
  - `APP_PG_STATEMENT_TIMEOUT_MS=45000` (ya hay default)
  - `APP_HEALTH_CACHE_SECONDS=3` (ya hay default)
- Si se observan caídas persistentes en horas punta: considerar **subir plan** o reducir concurrencia (pool/tareas background).

### Operación / mantenimiento

- Añadir un “runbook” de incidencias (qué mirar en `/api/build_info`, cómo identificar pool saturado, cómo validar iconos/PWA).

