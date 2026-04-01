# Biblioteca legal (para “volcar” legislación)

## Objetivo

La **Biblioteca legal** permite guardar (en base de datos) el texto extraído de:

- BOE/BOJA/boletines oficiales (HTML/PDF)
- Jurisprudencia (si hay URL accesible y permitida)
- Otros dominios oficiales permitidos por Copilot web

…para que el **Copilot legal** tenga más recursos sin tener que pegar la URL cada vez.

## Cómo se guarda (UI)

En CRM → Legal → **Consulta web (tiempo real)**:

1. Pega una URL oficial.
2. (Opcional) añade una pregunta.
3. Marca **“Guardar esta URL en la biblioteca legal (área/tema actuales)”**.

El sistema almacenará el texto extraído asociado al **área** y **tema** seleccionados en el copilot legal.

## Endpoints

- `GET /api/legal_library_documents?area=rrhh&topic_key=vacaciones_convenio&limit=20`
- `POST /api/legal_library_import` con `{ area, topic_key, url, title? }`

## Importante (escalabilidad)

No es recomendable “volcar todo el BOE” completo: es enorme y no aporta.
La estrategia recomendada es:

- guardar **solo** leyes/convenios/jurisprudencia que afectan a procesos y plantillas del CRM,
- y usar el Radar legal como detector de novedades para decidir qué se importa.

