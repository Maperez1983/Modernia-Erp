# Manual de Identidad Corporativa · Verifika²

Última actualización: 2026-04-04

## 1) Visión de marca

**Verifika²** es el software (CRM + futuro portal) para operar inmuebles **reales** y **verificados documentalmente**.

- Promesa: “si está en Verifika², existe y está validado”.
- Valores: rigor, transparencia, trazabilidad, estética sobria, claridad legal.
- Tono: profesional, directo, sin “hype”.

## 2) Arquitectura de marca

- **Marca del software**: Verifika² (interfaz, documentación, PDFs generados).
- **Empresas/Clientes** dentro del CRM: pueden llamarse “Grupo Modernia”, “Financiaciones Modernia”, etc. (son datos de negocio, no la marca del software).

## 3) Logotipo (wordmark) y símbolo (isotipo)

### 3.1 Versiones oficiales

**Wordmark (recomendado para cabeceras y portada)**
- Claro (vector trazado desde el logo original): `assets/verifika2/verifika2_wordmark_traced.svg`
- Oscuro (vector): `assets/verifika2/verifika2_wordmark_traced_dark.svg`
- Raster (fiel al original): `assets/verifika2/verifika2_wordmark_check_green.png`
- Raster (transparente): `assets/verifika2/verifika2_wordmark_check_green_transparent.png`

**Isotipo (check “V” Verifika²)**
- `assets/verifika2/verifika2_mark.svg`

### 3.2 Zona de seguridad (clear space)

Regla: deja un margen libre mínimo alrededor del logo equivalente a:
- **1× el grosor visual del check** del isotipo.

### 3.3 Tamaños mínimos

- Wordmark: no usar por debajo de **140 px** de ancho en digital.
- Isotipo: no usar por debajo de **20 px** de alto (para evitar pérdida de legibilidad).

### 3.4 Usos incorrectos (no hacer)

- No deformar (estirar/encoger en un eje).
- No cambiar tipografía del wordmark.
- No aplicar sombras duras o contornos.
- No usar el sello “Verificado” en inmuebles no verificados.

## 4) Paleta de color

### 4.1 Colores principales

- Navy (texto/UI): `#0B1D33`
- Navy 2 (fondos): `#0F2742`
- Verde check (verificación): `#22C55E`
- Oro (acento/sello): `#F2C14E`
- Oro deep: `#B9892B`
- Fondo claro: `#F5F7FB`

### 4.2 Neutros recomendados

- Línea / bordes: `#E2E8F0`
- Texto secundario: `#64748B`
- Blanco: `#FFFFFF`

### 4.3 Principios de uso

- **Navy**: estructura, navegación, tipografía principal.
- **Verde**: estados de “verificado / ok / completado”.
- **Oro**: hitos (cierres, notaría), “premium”, sellos.
- Evitar saturar: máximo **1 color acento** dominante por pantalla.

## 5) Tipografía

Familias (web):
- Titulares/branding: `Playfair Display`
- UI/labels/píldoras: `Space Grotesk`
- Texto y tablas: `Source Sans 3`

Reglas:
- Usar `Space Grotesk` para KPIs y números (mejor lectura).
- Evitar mayúsculas largas; preferir *Title Case* o frase corta.

## 6) Sistema gráfico

### 6.1 Iconografía

- Estilo: simple, sin exceso de detalle, compatible con tamaños pequeños.
- Para estados, priorizar: check (verde), warning (oro), error (rojo solo si es imprescindible).

### 6.2 Componentes UI

- Cards con bordes suaves y sombras ligeras.
- Badges/pills redondeadas, con contraste correcto (AA).
- Gráficos: fondo claro, series con Navy + acento (oro/verde/azul) y etiquetas legibles.

## 7) Sello “Verificado por Verifika²”

### 7.1 Reglas de uso (críticas)

Mostrar sello / isotipo **solo** cuando el inmueble esté verificado documentalmente.

En el CRM, la condición mínima de UI es:
- `noticia_verificada = 1` (en Captaciones/Noticia) y/o un estado documental equivalente.

### 7.2 Activos del sello

- Oro: `assets/verifika2/verifika2_badge_gold.svg`
- Plata: `assets/verifika2/verifika2_badge_silver.svg`
- Carbon: `assets/verifika2/verifika2_badge_carbon.svg`

### 7.3 Copy recomendado (tooltip)

- “Verificado: documentación revisada.”
- “Verificación: ok (Catastro / titularidad / nota simple / cargas / etc.).”

## 8) Fotografía y estilo visual (portal)

Guías:
- Imágenes reales, sin filtros agresivos.
- Priorizar claridad: buena exposición, líneas rectas, encuadres “honestos”.
- Evitar imágenes “stock” cuando el inmueble sea verificable.

## 9) Documentos generados (PDF)

Reglas:
- El encabezado debe mostrar Verifika² como software y, cuando aplique, **la empresa** como parte (intermediación/cliente).
- Evitar textos “CRM Modernia”; usar “CRM Verifika²”.

## 10) Entregables y repositorio de marca

- Todos los activos viven en `assets/verifika2/`.
- Resumen rápido de activos: `docs/verifika2_brand.md`.

## 11) Checklist rápido (para nuevas pantallas)

- ¿El logo es Verifika² (y no una empresa/cliente)?
- ¿Los acentos de color respetan la paleta?
- ¿Los sellos se muestran solo si está verificado?
- ¿El texto evita “hype” y es trazable/operativo?

