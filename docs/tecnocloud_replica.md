# Replica Tecnocloud (Tecnocasa) → Modernia CRM Inmobiliario

Este documento aterriza, a partir de:
- exports CSV (Actividades/Citas/Clientes/Informadores/Inmuebles/Pedidos/Noticias/Control zona),
- PDF de formación “Tecnocloud y Herramientas Operativas 2019”,

una réplica **práctica** de lo que aporta Tecnocloud/Lightning, adaptada a Modernia y sin “cosas de franquicia” que no aporten.

## 1) Qué ya tenemos en Modernia (estado actual)

- **Pipeline captaciones** (kanban + lista) con etapas: Noticia → Adquisición → Encargo → Reservado → Vendido (+ Cerrado negativo / Alquiler).
- **Ficha de inmueble** con checklist por etapa y generación de PDFs (visita/venta/alquiler) cuando procede.
- **Demandas** (compradores) + vista de **matching** con inventario.
- **Visitas** vinculadas a inmueble y demanda.
- **Acciones** (agenda/tareas) vinculadas a cliente/inmueble y con workflows en negociaciones.
- **Mapa/geo**: lat/lon en inmueble + geocodificación + preview.

## 2) Qué diferencia Tecnocloud (lo “core” del método operativo)

1) **Priorización diaria**: la prioridad de trabajo no la marca el “listado”, la marca la **recencia de contacto** + **ocupación** + **pedidos/informadores**.
2) **Disciplina de próxima acción**: “programa siempre la próxima llamada/actualización”.
3) **Noticia verificada vs no verificada**: si no hay verificación directa de intención de venta, se trata como “no verificada”.
4) **Búsquedas precargadas**: listados por criterios típicos (pisos vacíos, inquilinos, propietarios de viviendas alquiladas, etc.).
5) **Cruce oferta-demanda**: matching sistemático y accionable (no solo “ver coincidencias”).
6) **Movilidad**: zona en móvil (captura rápida de info, reposicionamiento, etc.).
7) **Marketing operativo**: alertas y campañas “ligeras” ligadas al flujo (ej. alertas email de búsqueda).

## 3) Qué replicamos en Modernia (por fases)

### Fase 1 (rápida, sin romper)
- `Noticia verificada` en captaciones.
- `Ocupado por` (y sincronización captación ↔ inmueble).
- **Búsquedas rápidas** en pipeline (quick filters).
- Mejorar “bloqueos operativos” para priorizar:
  - sin próxima acción,
  - noticias sin verificar,
  - sin contacto > 120 días.

### Fase 2 (si algún día se quiere, opcional)
- Panel de **priorización diaria** (sin concepto de “zona”) con prioridades:
  1) Ocupación / Ocupado por
  2) Estado de contacto (por días desde último contacto)
  3) Pedidos (demandas) con falta de seguimiento
  4) Informadores (contactos que alimentan captación)
- Acciones rápidas: “Programar recontacto”, “Registrar contacto directo”, “Marcar no molestar”.

### Fase 3 (matching + alertas)
- Score de matching oferta-demanda (peso por zona, precio, m², habitaciones, tipología).
- “Acciones sugeridas” desde matching (crear visita, crear llamada, crear propuesta).
- Alertas (in-app) por “nuevo match” y “pedido sin seguimiento”.

### Fase 4 (movilidad)
- Vista móvil optimizada de priorización + geolocalización **si aporta**:
  - mostrar inmuebles/propietarios/informadores cercanos
  - capturar notas/actividades y crear captaciones en 15s

### Fase 5 (colaboración)
- Feed interno tipo “Chatter” **solo si** se valida que lo usará el equipo.

## 4) Qué normalmente NO merece la pena replicar

- Intranet corporativa (si ya hay Drive/Notion/Teams).
- Materiales de marketing específicos (revista A4) si vuestro canal es distinto.
- Complejidad de franquicia (territorios rígidos / multi-oficina) si no la necesitáis aún.

## 5) Próximos pasos

1) Confirmar qué se excluye (por ejemplo: “Chatter”, “revista”, “franquicia”).
2) Ejecutar Fase 1 y validar con 2–3 comerciales en uso real.
3) Planificar Fase 2 (zona diaria) con un diseño UX claro (lista+mapa+acciones rápidas).
