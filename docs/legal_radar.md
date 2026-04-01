# Radar legal (BOE/BOJA/Jurisprudencia)

## Qué es y cómo se comporta

El **Radar legal** es un escáner de fuentes (RSS/Atom) que:

1. Descarga las entradas de las fuentes configuradas en `docs/legal_radar_sources.json`.
2. Clasifica cada entrada por **área** (`rrhh`, `gestoria`, `inmobiliaria`, etc.) y por **tema** (`topic_key`) usando reglas de palabras clave.
3. Guarda/actualiza los resultados en la tabla `legal_radar_items` con estado inicial **Pendiente**.
4. En la UI (CRM → Legal → *Radar legal*), puedes marcar una alerta como **Revisado** o **Aplicado**.

El escaneo puede ejecutarse:

- **Manual**: botón “Escanear fuentes oficiales” en la sección *Radar legal*.
- **Automático** (recomendado en Render): proceso background si activas variables de entorno.

## Aviso en Home (alerta)

En el Home aparece una alerta cuando hay alertas **pendientes** en el área **RRHH**:

- Texto: “Radar legal RRHH: N alertas pendientes.”
- Botón “Abrir radar” → abre CRM y te lleva a la pestaña **Legal** con el área `rrhh`.

## Activar escaneo automático (Render)

Variables recomendadas:

- `LEGAL_RADAR_AUTO_SCAN_ENABLED=true`
- `LEGAL_RADAR_AUTO_SCAN_INTERVAL_SECONDS=3600` (cada hora; mínimo 300)
- `LEGAL_RADAR_AUTO_SCAN_ON_START=true` (hace un scan al arrancar)

Puedes ver el estado con `GET /api/legal_radar_auto_status`.

## Volcar (importar) actualizaciones a la biblioteca legal

El Radar detecta novedades (y las lista en la **Cola de revisión**), pero además puedes **volcar** el texto completo
de la URL oficial a la **Biblioteca legal** para que el Copilot tenga más recursos por tema.

### Volcado manual

- Desde la UI: en “Escanear fuentes oficiales” puedes activar el volcado en el payload (`import_library`).
- Por API: `POST /api/legal_radar_import` con `{ "area": "rrhh", "limit": 3 }`.

### Volcado automático (Render)

Variables:

- `LEGAL_RADAR_AUTO_IMPORT_ENABLED=true`
- `LEGAL_RADAR_AUTO_IMPORT_LIMIT=3`

Se ejecuta en el mismo loop del Radar automático y guarda textos en `legal_library_documents`.

## Resumen significativo (Copilot)

Puedes pedir al Copilot un **resumen accionable** de las novedades pendientes:

- UI: botón **“Resumen novedades”** en *Radar legal*.
- API: `POST /api/legal_radar_digest` con `{ "area": "rrhh", "estado": "pendiente", "limit": 12, "include_text": 1 }`.

Si no hay `OPENAI_API_KEY`, el sistema devuelve un **resumen básico** (sin IA) basado en metadatos del radar
y en el texto importado a la biblioteca si existe.

Recomendación:

- activa el volcado a biblioteca (`LEGAL_RADAR_AUTO_IMPORT_ENABLED=true`) para que el resumen sea más fiable
  (usa el texto extraído de las URLs oficiales cuando exista).

## Conector de jurisprudencia (RSS/Atom)

El Radar soporta fuentes RSS/Atom además de BOE/BOJA. Para jurisprudencia:

- En `docs/legal_radar_sources.json` hay una fuente plantilla: `jurisprudencia_rrhh_laboral`.
- Está desactivada por defecto y se activa **por entorno**.

Variables:

- `LEGAL_RADAR_JURIS_ENABLED=true`
- `LEGAL_RADAR_JURIS_RSS_URLS` con una o varias URLs RSS/Atom (separadas por coma/espacio).

Ejemplo:

```
LEGAL_RADAR_JURIS_ENABLED=true
LEGAL_RADAR_JURIS_RSS_URLS=https://.../rss.xml,https://.../atom.xml
```

Notas:

- El conector **solo** consume RSS/Atom. Si una web de jurisprudencia no ofrece feed, necesitaríamos un scraper específico (no recomendado sin un endpoint oficial/estable).
- Las reglas de clasificación están en esa fuente (keywords + `topic_key`) y se pueden ajustar en `docs/legal_radar_sources.json`.
