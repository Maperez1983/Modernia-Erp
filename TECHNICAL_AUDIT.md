# Auditoría Técnica

Base de esta auditoría: revisión estática del código, inventario de tests y ejecución final de `python -m pytest`.

Resultado de validación: `35 passed, 1 skipped`.

## Resumen Ejecutivo

- El repositorio está operativo y la suite principal pasa, pero la arquitectura está muy concentrada.
- `web/server.py` y `web/app.js` son los dos puntos de mayor riesgo: ambos superan con holgura las 90k líneas y concentran autenticación, autorización, enrutado, renderizado y lógica de negocio.
- El riesgo más serio es de seguridad: la autorización de workspace depende de campos mutables como `rol` y `servicio`, y existe una cadena de refresco de sesión que puede convertir ese cambio en privilegios efectivos.
- El segundo riesgo importante es de aislamiento tenant: el backend puede autovincular todas las empresas activas a un workspace vacío en escenarios legacy, lo que puede mezclar datos entre workspaces o empresas.
- Hay riesgos medios adicionales por tokens en URL, renderizado frontend sin escape en varias listas, rate limiting de login solo en memoria, consultas pesadas y duplicación de helpers en OCR.
- No confirmé un bypass concreto en S3 ni un fallo específico en correo, pero ambas integraciones son sensibles y dependen mucho de configuración y credenciales.

## Hallazgos Por Severidad

### Crítica

- **C1. Posible escalada de privilegios mediante `servicio` mutable**
  - **Hecho comprobado:** `resolve_workspace_module_key_for_user_service()` devuelve vacío para valores como `direccion` y `administracion`, por lo que `validate_usuario_services_for_workspace()` no los bloquea; `workspace_session_is_privileged()` considera privilegiados `rol` o `servicio` con valores como `ADMINISTRADOR`, `ADMIN`, `DIRECCION`, `CONTROL` o `ADMINISTRACION`; `/api/usuarios_update` permite a un admin de workspace modificar `servicio`; `/api/me` refresca `rol` y `servicio` desde la base de datos y actualiza la sesión persistida.
  - **Inferencia de riesgo:** un usuario con permisos de administración en un workspace puede autoasignarse un `servicio` privilegiado y pasar a ser tratado como sesión privilegiada sin un control de transición explícito. Esto puede convertirse en una escalada efectiva de permisos globales o al menos de privilegios de workspace.
  - **Zona afectada:** `web/server.py:1680-1700`, `web/server.py:42982-43081`, `web/server.py:54546-54595`, `web/server.py:59709-59859`.
  - **Prioridad de corrección:** separar autorización real de la etiqueta de servicio, prohibir que un usuario no privilegiado cambie a servicios administrativos y hacer que la sesión privilegiada dependa solo de un flag explícito e inmutable.

### Alta

- **H1. Autovinculación de todas las empresas activas en workspaces vacíos**
  - **Hecho comprobado:** `WORKSPACE_AUTO_LINK_COMPANIES` está activado por defecto (`APP_WORKSPACE_AUTO_LINK_COMPANIES="1"` si no se cambia); `fetch_workspace_company_ids()` puede inferir vínculos, y si no hay ninguno, en ciertos workspaces legacy inserta todas las empresas activas en `workspace_empresas`.
  - **Inferencia de riesgo:** un workspace sin mapeo explícito puede terminar viendo o usando todas las empresas activas del sistema, lo que rompe el aislamiento tenant y puede contaminar datos entre clientes o áreas.
  - **Zona afectada:** `web/server.py:1179`, `web/server.py:39742-39927`.
  - **Prioridad de corrección:** desactivar el autolink por defecto, exigir vínculos explícitos y reservar cualquier backfill masivo para migraciones controladas.

- **H2. `APP_BASE_URL`/`Host` usados para generar enlaces sensibles**
  - **Hecho comprobado:** `_external_base_url()` usa primero variables de entorno, pero en fallback construye la URL pública a partir de `X-Forwarded-Host` o `Host`; esa base se usa para enlaces de invitación, reset y QR de kiosk.
  - **Inferencia de riesgo:** si un proxy no está estrictamente controlado o la petición llega con un `Host` no fiable, se pueden generar enlaces con tokens apuntando a un dominio incorrecto o controlado por un tercero.
  - **Zona afectada:** `web/server.py:54017-54029`, `web/server.py:59673`, `web/server.py:61612`, `web/server.py:79088`.
  - **Prioridad de corrección:** depender solo de una base pública explícita y validada, o de una allowlist de host/proxy confiable; nunca derivar enlaces con tokens de un `Host` no verificado.

### Media

- **M1. Rate limiting de login solo en memoria**
  - **Hecho comprobado:** `check_login_rate_limit()` y `register_login_attempt()` almacenan el estado en `_LOGIN_RATE_STATE`, que es un diccionario de proceso; no hay persistencia ni coordinación entre workers.
  - **Inferencia de riesgo:** un reinicio, un despliegue o una escala horizontal puede reiniciar el contador, debilitando la protección frente a fuerza bruta.
  - **Zona afectada:** `web/server.py:12697-12742`, `web/server.py:55729-55826`.
  - **Prioridad de corrección:** persistir la ventana de intentos en almacenamiento compartido o aplicar rate limiting en el borde.

- **M2. Tokens sensibles en query string**
  - **Hecho comprobado:** el frontend y el backend usan `activar_token`, `portal_token`, `firma_inmo` y `token` en la URL para activar cuentas, abrir portales, firmar documentos y abrir kioscos; `web/app-auth.js` los consume directamente desde `window.location.search`, y `web/app.js` los vuelve a generar en varios flujos.
  - **Inferencia de riesgo:** esos tokens quedan expuestos en historial, logs, copias de la URL y referers, lo que amplía el radio de fuga para enlaces que dan acceso a datos privados o flujos de firma.
  - **Zona afectada:** `web/app-auth.js:135-166`, `web/app-auth.js:320-349`, `web/app.js:14200`, `web/app.js:20013`, `web/app.js:29744`, `web/app.js:30445`, `web/app.js:30724-30734`, `web/server.py:59673`, `web/server.py:61612`, `web/server.py:72286`, `web/server.py:79088`.
  - **Prioridad de corrección:** sustituir tokens en URL por sesiones cortas server-side, POST con CSRF o enlaces de un solo uso que se invaliden al abrirse.

- **M3. Renderizado frontend con `innerHTML` sin escape en varias listas**
  - **Hecho comprobado:** `renderWorkspaceBillingList()`, `renderWorkspacePortalList()`, `renderWorkspacePortalRequestList()`, `renderWorkspaceSeriesList()`, `renderWorkspaceInboxList()` y `renderWorkspaceAutomationList()` interpolan campos del backend directamente en plantillas HTML; algunas URLs se insertan como `href` sin validación previa.
  - **Inferencia de riesgo:** si un nombre, nota, URL o descripción llega con contenido malicioso, puede ejecutarse script en el contexto del usuario que navega por el panel, especialmente en vistas de administrador o tenant.
  - **Zona afectada:** `web/app.js:19172-20115`.
  - **Prioridad de corrección:** escapar todos los valores no confiables, validar URL y preferir creación de nodos DOM en vez de plantillas HTML para datos externos.

- **M4. Monolitos y funciones excesivamente grandes**
  - **Hecho comprobado:** `web/server.py` tiene 93.092 líneas y `web/app.js` 90.337; dentro del backend destacan `Handler` con 39.376 líneas, `_do_POST` con 22.558 y `handle_api` con 15.404.
  - **Inferencia de riesgo:** el coste de revisión, el riesgo de regresión y la dificultad de aislar bugs aumenta de forma desproporcionada; cualquier cambio pequeño puede tocar ramas muy alejadas del comportamiento esperado.
  - **Zona afectada:** `web/server.py:53638-93013`, `web/app.js:1-90337`.
  - **Prioridad de corrección:** partir por dominios funcionales, mover rutas a módulos específicos y dividir el frontend por features o subsistemas.

- **M5. Consultas y barridos de datos potencialmente costosos**
  - **Hecho comprobado:** `fetch_workspace_gestoria_overview()`, `fetch_workspace_seguros_overview()`, `fetch_workspace_fin_overview()`, `fetch_workspace_document_hub()` y `workspace_time_sweep_loop()` realizan múltiples agregaciones, joins y recorridos completos; el sweep de horario itera todos los workspaces en cada ciclo.
  - **Inferencia de riesgo:** con crecimiento de volumen, estos endpoints pueden convertirse en cuellos de botella o disparar tiempos de respuesta altos, sobre todo en el boot de workspace y en tareas periódicas.
  - **Zona afectada:** `web/server.py:40163-40605`, `web/server.py:41448-41537`, `web/server.py:43519-43599`, `web/server.py:44573-44603`, `web/server.py:47885-48020`.
  - **Prioridad de corrección:** introducir caches o agregados materiales, índices específicos y evitar recorridos globales cuando el workspace activo ya está conocido.

- **M6. Duplicación y dispersión en la resolución de credenciales OCR**
  - **Hecho comprobado:** `ocr_image_external()` y `external_ocr_available()` contienen helpers duplicados para resolver credenciales (`_resolve_credentials_path`, `_env_first_line`, `_env_first_token`) y buscan `vision-sa.json` en varias rutas del árbol de trabajo.
  - **Inferencia de riesgo:** la lógica duplicada tiende a divergir y los fallbacks amplios facilitan que el runtime use credenciales inesperadas si el árbol contiene ficheros sensibles.
  - **Zona afectada:** `web/server.py:19161-19255`, `web/server.py:19255-19381`.
  - **Prioridad de corrección:** centralizar la resolución de credenciales en un único helper y limitarla a una ruta/configuración explícita.

- **M7. Carencias de testing en seguridad y aislamiento**
  - **Hecho comprobado:** solo existen cinco ficheros de test: hipotecas, un smoke E2E opcional, una aserción de scope en texto fuente y dos tests de workflow financiero. No hay tests dedicados a sesión, elevación de privilegios, `workspace_company_id`, S3, OCR, correo o escaping frontend.
  - **Inferencia de riesgo:** los fallos más delicados pueden introducirse sin cobertura automática, justo en las zonas que concentran autenticación, tenant isolation y salida HTML.
  - **Zona afectada:** `tests/`, y por extensión `web/server.py` y `web/app.js`.
  - **Prioridad de corrección:** añadir tests unitarios de permisos, tests de scope workspace/empresa, pruebas de sesión y tests de sanitización para renderizadores clave.

### Baja

- **L1. `Secure` en cookies de sesión es condicional**
  - **Hecho comprobado:** `_session_cookie_secure()` solo añade `Secure` si `APP_SESSION_COOKIE_SECURE` o las cabeceras proxy indican HTTPS; si no, la cookie se envía sin ese flag.
  - **Inferencia de riesgo:** si el entorno queda expuesto por HTTP o las cabeceras proxy están mal configuradas, la cookie puede viajar en claro. El código intenta evitar bucles de login, pero la seguridad depende de la infraestructura.
  - **Zona afectada:** `web/server.py:53892-53939`.
  - **Prioridad de corrección:** forzar `Secure` en producción y validar que el borde proxy siempre termina TLS antes de servir la app.

- **L2. Dependencias innecesarias o débilmente fijadas**
  - **Hecho comprobado:** `rembg>=2.0.61` aparece en `requirements.txt` y no encontré uso en `web/` ni en `tests/`; además, varias dependencias están fijadas solo por mínimo o sin versión exacta (`psycopg[binary]`, `cairosvg>=2.7.1`, `opencv-python-headless>=...`, `onnxruntime>=...`).
  - **Inferencia de riesgo:** aumenta la superficie de instalación y puede empeorar la reproducibilidad o el tiempo de aprovisionamiento sin aportar valor funcional.
  - **Zona afectada:** `requirements.txt`.
  - **Prioridad de corrección:** eliminar lo que no se use y fijar versiones donde la reproducibilidad importe más que la flexibilidad.

## Riesgos Por Área

- **Autenticación y sesiones:** el modelo funciona, pero la sesión se refresca desde DB y hereda `rol`/`servicio`; sin un separador de autorización inmutable, eso amplifica el hallazgo crítico.
- **Cookies:** la cookie de sesión es `HttpOnly` y `SameSite=Lax`, pero `Secure` depende del entorno.
- **S3:** vi endpoints de presign, upload y redirect, más un helper que valida visibilidad de claves; no confirmé un bypass concreto, pero el área es sensible por definición y merece pruebas específicas.
- **OCR:** hay fallbacks a `vision-sa.json` y a credenciales de Google Vision/Document AI; no vi un bug concreto de exfiltración, pero sí lógica duplicada y búsquedas de credenciales amplias.
- **Correo e IMAP:** `send_mail_smtp()` e `import_campaigns_from_mailbox()` usan credenciales de entorno o payload; no confirmé una vulnerabilidad específica, pero el manejo de secretos y el principio de menor privilegio deben revisarse.
- **Integraciones externas:** `_external_base_url()` y los flujos de tokens en URL son el punto más delicado de esa superficie.

## Deuda Técnica Y Duplicación

- El backend está dominado por un único `Handler` gigantesco y por dos métodos monolíticos (`_do_POST` y `handle_api`).
- El frontend repite el mismo patrón de listas y tarjetas en múltiples renderizadores (`billing`, `portal`, `portal requests`, `series`, `inbox`, `automation`), lo que complica sanitización y mantenimiento.
- La resolución de credenciales OCR está duplicada entre dos funciones distintas.
- La mezcla de lógica de negocio, seguridad, PDF, OCR, S3 y mail en `web/server.py` dificulta cualquier cambio con garantías.

## Propuesta De Corrección Priorizada

1. Romper primero la cadena crítica de privilegios: separar `rol`/`servicio` de la autorización real, impedir que un usuario no privilegiado se autoasigne servicios administrativos y revisar el refresco de sesión desde DB.
2. Desactivar la autovinculación masiva de empresas y exigir mapeos explícitos de workspace/empresa.
3. Eliminar tokens sensibles de las URLs públicas o convertirlos en identificadores de un solo uso con invalidación inmediata.
4. Corregir el renderizado frontend inseguro y validar todas las URLs que se insertan en `href`.
5. Repartir el backend y el frontend en módulos más pequeños para que las revisiones de seguridad y mantenimiento sean viables.
6. Sustituir el rate limiting de login en memoria por un mecanismo persistente o de borde.
7. Simplificar OCR, consolidar credenciales y limpiar dependencias no usadas.
8. Ampliar la suite de tests para cubrir exactamente los flujos que hoy concentran el riesgo.

## Acciones Inmediatas Sin Alterar Producción

- Añadir tests de regresión para:
  - escalada de privilegios vía `servicio`,
  - resolución de `workspace_id` / `empresa_id`,
  - refresco de sesión en `/api/me`,
  - renderizado seguro de las listas frontend más expuestas.
- Hacer un inventario de todos los usos de `innerHTML` y de todos los generadores de URL con tokens, para priorizar su saneamiento sin tocar comportamiento en producción.
- Revisar y documentar las variables de entorno críticas: `APP_BASE_URL`, `APP_SESSION_COOKIE_SECURE`, `APP_WORKSPACE_AUTO_LINK_COMPANIES`, `GOOGLE_APPLICATION_CREDENTIALS`, `AWS_*`, `SMTP_*`, `IMAP_*`.
- Confirmar si `rembg` tiene alguna dependencia indirecta real; si no, planificar su retirada de `requirements.txt`.
- Preparar un plan de refactor por dominios sin desplegarlo todavía: auth, workspace scope, frontend rendering, OCR/S3 y mail.
