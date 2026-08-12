# Registro de actividades de tratamiento · portales de cliente

> **Borrador para revisión legal.** Lo ha preparado el equipo de desarrollo a partir
> de lo que el sistema hace realmente. **No lo presentes ante una inspección sin que
> lo revise vuestro asesor o el DPD.** Los huecos entre corchetes hay que rellenarlos.

Cubre sólo los dos tratamientos que habilitan los portales de cliente. El resto de
tratamientos de la agencia (nóminas, contabilidad, registro horario) van aparte.

## Responsable

| | |
|---|---|
| Razón social | [RAZÓN SOCIAL] |
| NIF | [NIF] |
| Domicilio | [DOMICILIO] |
| Contacto para derechos | [CORREO] |
| Delegado de Protección de Datos | [SI LO HAY] |

## Tratamiento 1 · Seguimiento de la venta por el propietario

**Finalidad.** Que el propietario que nos ha dado un encargo pueda seguir el estado
de su venta y comunicarse con su asesor.

**Base jurídica.** Ejecución del contrato de encargo (art. 6.1.b RGPD) para el
seguimiento; consentimiento (art. 6.1.a) para habilitar el acceso al portal y, por
separado, para comunicaciones comerciales.

**Categorías de interesados.** Propietarios con encargo de venta o alquiler.

**Categorías de datos.** Identificativos (nombre, NIF), de contacto (teléfono,
correo), datos del inmueble, documentación aportada, mensajes escritos en el portal
y decisiones sobre ofertas. **No se tratan categorías especiales.**

**Cesiones.** Ninguna. Los datos no salen de la agencia salvo obligación legal.

**Transferencias internacionales.** No. Alojamiento en [PROVEEDOR], región [UE].

**Plazo de conservación.** Mientras dure el encargo y después el plazo de
prescripción aplicable [CONCRETAR]. El acceso al portal se revoca automáticamente al
cerrarse la operación.

**Medidas de seguridad.** Acceso por enlace con token aleatorio de 256 bits del que
sólo se almacena su hash SHA-256; caducidad configurable (120 días por defecto);
revocación manual e inmediata; segundo factor por código de un solo uso cuando hay
canal de mensajería configurado; registro de cada entrada; consentimiento firmado y
conservado con encadenamiento de hashes que hace detectable cualquier modificación
posterior.

## Tratamiento 2 · Selección de inmuebles para el comprador

**Finalidad.** Enseñar al comprador los inmuebles seleccionados por su asesor,
concertar visitas y acompañar la operación.

**Base jurídica.** Medidas precontractuales a petición del interesado (art. 6.1.b) y
consentimiento (art. 6.1.a) para el acceso al portal y para comunicaciones
comerciales.

**Categorías de interesados.** Compradores e inquilinos potenciales.

**Categorías de datos.** Identificativos y de contacto, criterios de búsqueda
(zona, tipo, presupuesto), visitas, valoraciones sobre los inmuebles vistos y
documentación económica que el interesado decida aportar.

**Cesiones.** Al propietario del inmueble se le comunica el importe y las
condiciones de una oferta, **no la identidad del ofertante**, salvo que la operación
llegue a formalizarse.

**Plazo de conservación.** Mientras la búsqueda siga activa y después el plazo de
prescripción aplicable [CONCRETAR].

**Medidas de seguridad.** Las mismas del tratamiento 1.

## Qué NO sale por los portales

Está comprobado con pruebas automáticas, no sólo por criterio:

- Identidad, teléfono y datos de los compradores interesados.
- Honorarios y márgenes de la agencia.
- Notas internas del asesor. El comentario dirigido al cliente es un campo distinto,
  que se escribe a sabiendas de que lo va a leer.
- Identificadores internos de empresa, workspace o expediente.
- Documentos del expediente que no se hayan compartido uno a uno de forma expresa.

## Violaciones de seguridad

Si se detecta un acceso indebido: revocar los accesos afectados desde la ficha
(efecto inmediato), documentar el alcance con el registro de entradas, y valorar la
notificación a la AEPD en 72 horas y a los interesados si procede.
