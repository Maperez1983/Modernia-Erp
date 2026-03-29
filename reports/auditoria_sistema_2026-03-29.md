# Auditoría Completa del Sistema (Modernia ERP)

Fecha: 2026-03-29  
Repo: `Modernia-Erp` (workspace local)  
Entorno objetivo: Render (SQLite en `/var/data`, servidor Python + frontend estático)

## Alcance

Auditoría técnica completa (sin tocar datos de negocio):

- Backend: `web/server.py` (HTTPServer propio, endpoints REST, OCR, S3, Catastro, Portal, RRHH, etc.)
- Frontend: `web/index.html`, `web/app.js`, `web/styles.css` (SPA vanilla)
- Persistencia: `schema.sql`, SQLite (`data/*.sqlite`)
- Seguridad: auth/sesiones, exposición de ficheros, validación entrada/salida, aislamiento
- Fiabilidad: errores 502, resiliencia ante terceros (geocode/Catastro), manejo de fallos
- Rendimiento: SQLite, índices, caching, tamaño de payloads, queries frecuentes
- Mantenibilidad: deuda técnica, duplicación, modularidad, testabilidad
- UX/Operativa: flujos CRM y consistencia de UI (visión “producto vendible”)

## Inventario rápido

Tamaño aproximado del core:

- `web/server.py`: 35.871 líneas
- `web/app.js`: 38.819 líneas
- `web/index.html`: 6.810 líneas
- `web/styles.css`: 6.465 líneas
- `schema.sql`: 1.419 líneas

Esto confirma un patrón “monolito pragmático” (mucha funcionalidad en pocos ficheros). Funciona, pero la auditoría recomienda separar por dominios conforme crece.

## Hallazgos (priorizados)

### 1) Seguridad (CRÍTICO)

**1.1 Exposición de ficheros por path traversal y static serving permisivo**

- Problema: el servidor aceptaba rutas tipo `/../...` y podía intentar servir ficheros fuera del directorio `web/`.
- Impacto: potencial lectura de ficheros sensibles del contenedor si existiesen rutas accesibles (riesgo alto en SaaS).
- Acción aplicada: hardening de resolución de rutas y bloqueo de traversal; `X-Content-Type-Options: nosniff`.
- Commit: `5aedd06` (ya aplicado en `main`).

**1.2 `/uploads/` público**

- Problema: la documentación servida bajo `/uploads/...` estaba accesible sin sesión.
- Impacto: fuga de documentación interna si alguien comparte/filtra un enlace.
- Acción aplicada: ahora `/uploads/...` requiere sesión (cookie).
- Commit: `5aedd06`.

Notas:
- Si queréis enlaces públicos a clientes, hacedlo por S3 con URL prefirmadas o endpoints públicos con token (no por `/uploads` “plano”).

### 2) Seguridad (ALTO)

**2.1 Escalabilidad de sesión**

- Sesiones en memoria (`AUTH_SESSIONS`): con 2 instancias se rompen (usuario “sale”).
- Render suele usar 1 instancia, pero si se escala, hay riesgo real.
- Recomendación: almacenar sesiones en SQLite (tabla `sessions`) o usar JWT firmado (con rotación y revocación).

**2.2 Falta de rate limit / antifuerza bruta en `/api/login`**

- Riesgo: intentos repetidos contra credenciales.
- Recomendación: rate limit por IP/usuario + lockout temporal + logging de intentos.

**2.3 CORS “abierto” en `OPTIONS`**

- `Access-Control-Allow-Origin: *` + sin `Allow-Credentials`: no es crítico, pero es mejor endurecer:
  - limitar a mismo origen o a una lista (`APP_ALLOWED_ORIGINS`)
  - sólo exponer `OPTIONS` para endpoints que lo necesiten

### 3) Datos/BD (ALTO)

**3.1 Foreign keys no garantizadas**

- `schema.sql` define `FOREIGN KEY ...`, pero SQLite no las aplica si no se activa `PRAGMA foreign_keys=ON` por conexión.
- Recomendación: habilitar `PRAGMA foreign_keys=ON` en `open_sqlite_conn`.
- Nota: activarlo puede destapar inconsistencias existentes (lo correcto es detectarlas y limpiarlas).

**3.2 Falta de índices en tablas operativas**

- Solo se detectan algunos índices (principalmente importador y postal).
- Impacto: a medida que crecen `clientes`, `gestoria_docs`, `inmuebles`, `acciones`, `visitas`, etc., habrá degradación.
- Recomendación: índices mínimos por `empresa_id`, `cliente_id`, `inmueble_id`, `created_at`, `estado`, y combinados para búsquedas reales.

### 4) Fiabilidad/Resiliencia (ALTO)

**4.1 Dependencias externas (geocode/Catastro)**

- Hay timeouts, pero sigue existiendo riesgo de fallos intermitentes.
- Recomendación:
  - cache persistente de geocode (SQLite) por dirección normalizada
  - “circuit breaker” por proveedor (si falla mucho, no insistir durante X min)
  - métricas por proveedor

### 5) Mantenibilidad (ALTO)

**5.1 Monolito frontend/backend**

- `web/server.py` y `web/app.js` concentran demasiadas responsabilidades.
- Recomendación: refactor incremental por dominio, siguiendo `docs/gestoria_arquitectura.md`:
  - Backend: `modules/inmo.py`, `modules/gestoria_import.py`, `modules/seguros.py`, etc.
  - Frontend: `web/modules/inmo.js`, `web/modules/gestoria.js`, con un router ligero.
- Beneficio: cambios más rápidos y menos regresiones.

**5.2 Test runner y cobertura**

- En el entorno local actual no hay `pytest` instalado (no he podido ejecutar test suite aquí).
- Recomendación: añadir un `requirements-dev.txt` y CI mínimo (GitHub Actions) para ejecutar tests y lint.

### 6) UX/Operativa (MEDIA)

**6.1 Consistencia de formularios**

- Hay cards y grids con estilos y densidades dispares.
- Recomendación:
  - una sola “apariencia” de formulario por dominio (Datos, Actividad, Documentos)
  - reducir whitespace y dar prioridad a acciones principales (estado, agenda, documentos)

**6.2 Navegación a fichas**

- Problema observado en Render: “Abrir ficha” no abría o te devolvía al panel general.
- Acción aplicada: apertura sin recarga y deep-links robustos.
- Commit: `e3bf821`.

## Cambios ya aplicados relacionados con la auditoría

- `e3bf821`: CRM Inmobiliaria abre fichas sin depender de reload, fallback geocode en navegador y mejoras Catastro (incluye “PASAJE”).
- `5aedd06`: hardening de static serving, bloqueo traversal, `/uploads` protegido por sesión.

## Recomendaciones de roadmap (30-60 días)

1. Seguridad:
   - rate limit login + logging de intentos
   - sesiones persistentes o JWT
2. Datos/BD:
   - activar `PRAGMA foreign_keys=ON`
   - índices mínimos por tablas core
3. Fiabilidad:
   - cache geocode en SQLite
   - métricas y trazabilidad (request_id, proveedor, latencia)
4. Mantenibilidad:
   - dividir backend/frontend por dominios (refactor incremental)
   - CI mínimo con tests/lint

## Checklist de pruebas (end-to-end)

### CRM Inmobiliaria

- Crear Noticia, asignar propietario, validar que “Abrir ficha” abre la ficha.
- Introducir dirección y pulsar “Localizar”: mapa aparece o muestra error accionable.
- Catastro: “Buscar referencia” desde dirección, y “Ficha PDF” (si procede).
- Documentos: subir PDF, abrirlo, verificar que sigue accesible con sesión.
- Actividad: crear cita/acción, cerrar con resultado, comprobar cambio de estado.
- Pipeline: mover etapa (drag) y confirmar persistencia.
- Borrado inmueble: confirma borrado y que desaparece del catálogo.

### Gestoría (CRM + Importador + Contabilidad)

- Alta cliente gestoría y módulos (fiscal/laboral/contable/renta).
- Subir docs a `gestoria_docs` y comprobar que se ven en ficha.
- Importador: crear lote, subir documentos, OCR, resolver incidencias, aplicar a contabilidad, exportar Excel.
- Validar trazabilidad: eventos del lote/documento y estado coherente.

### Seguros

- Subir póliza, OCR, vinculación automática por NIF al cliente.
- Documento al repositorio del cliente (Seguros) y acceso al PDF.
- Cambio de estado de póliza y control de transiciones.

### Financiaciones

- Crear oportunidad por “necesita financiación” desde Inmobiliaria.
- Completar datos económicos y verificar que el asesor financiero los ve.
- Workflow de citas/tareas y checklists.

### Portal cliente (público)

- Acceso por `portal_token` a su vista pública.
- Upload de documento vía portal (si aplica) y que queda en inbox con trazabilidad.

### RRHH/Admin

- Crear usuario, asignar servicios, comprobar acceso.
- Reset/alta password por invitación y expiración del token.

