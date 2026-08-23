# Auditoría de agosto de 2026

Registro de la campaña de auditoría completa del CRM. Está escrito para que dentro de
seis meses alguien pueda **repetirla, ampliarla y saber qué no se miró**.

Tres partes: los métodos que funcionaron y por qué, lo que se encontró, y lo que queda
abierto. Para las simulaciones de uso hay un documento aparte, `AUDITORIA_DE_USO.md`; la
revisión estática previa está en `TECHNICAL_AUDIT.md`.

---

## 1. Lo que aprendimos sobre cómo auditar esto

Vale más que la lista de fallos, porque es lo que sirve la próxima vez.

### Leer el código no basta, y engaña

Durante esta campaña **cada hallazgo real salió de ejecutar algo**: un endpoint, un
navegador de verdad, o la propia suite. Los barridos por patrones produjeron una decena
de falsos positivos que llegué a dar por buenos. Dos ejemplos que cuestan tiempo:

- «Los botones Buscar y Volver al panel están muertos»: los manejaba
  `ui-foundation.js`. Había buscado en `app.js` y en `index.html`, dos de **siete**
  ficheros de front.
- «Siete pruebas en rojo en main»: el árbol de trabajo no tenía `node_modules`, que está
  en `.gitignore`. El código estaba perfecto. Lo afirmé dos veces.

**Regla:** antes de afirmar un fallo, ejecutarlo. Y si el barrido es estático, comprobar
que reconoce lo que dice reconocer.

### Una simulación con datos inventados demuestra lo que tú has inventado

El caso más caro de la campaña, y salió al final. Al enganchar
`/api/portal_empresa_logo` lo probé con una empresa de mentira cuyo logotipo era
`/assets/sur.png`, un fichero que no existe. Dio 404, lo achaqué al fichero inventado
—correctamente— y di el endpoint por bueno.

No lo era. Dentro tenía un fallo que nunca se había ejecutado, porque hasta ese día la
ruta no era alcanzable: le pasaba a `_normalize_s3_key` la URI entera en vez de la clave,
así que la comprobación del prefijo quedaba en falso y **ningún logotipo de S3 llegaba a
servirse**. En producción todas las empresas con logotipo propio lo tienen en S3. El
resultado: el escaparate público pasó de enseñar el logotipo del grupo a enseñar un
hueco, y estuvo así hasta que lo miré en producción.

Dos reglas, las dos de lo mismo:

- **Los datos de la simulación tienen que existir.** Un 404 que se explica por tu propio
  dato de mentira no distingue «el dato no está» de «el código está roto». Poner un
  fichero real habría enseñado el fallo en el sitio, no en producción.
- **Al enganchar código que nunca se ha ejecutado, dar por hecho que está roto.** Llevaba
  escrito y sin usar; nadie lo había probado nunca. Que compile y que lea bien no es
  haberlo ejecutado.

Y una tercera, de después: **al publicar algo que cambia lo que se ve desde fuera,
mirarlo desde fuera.** Bastó un `curl` al escaparate público con el commit ya desplegado.
Ahí salieron los dos problemas de golpe: el logotipo roto y el nombre.

### Una prueba que nunca ha fallado no demuestra nada

El patrón más productivo de toda la campaña fue **auditar los guardarraíles**, no el
código. Dos pruebas que vigilaban exactamente la clase de fallo que buscábamos pasaban en
verde mientras el fallo estaba presente:

- `los_post_del_front_estan_dados_de_alta` no reconocía `apiPost`, el ayudante más usado
  después de `fetch`: **39 rutas sin vigilar**, y por ahí se colaron las tres rotas.
- `el_front_no_llama_al_vacio` exigía que la ruta terminara en la comilla de cierre, así
  que **162 de 444** llamadas —las que llevan parámetros— quedaban fuera.

**Regla:** a toda prueba de cobertura, dos preguntas. ¿Cuántas cosas mira de las que hay?
¿Falla si rompo lo que vigila? Verificarlo revirtiendo el arreglo.

### Los sitios donde el dato entra mal en silencio

Un 500 se ve. Lo que no se ve es un dato aceptado con «ok» y guardado mal. Tres de esa
familia en esta campaña: el importe en formato inglés, la fecha imposible y la morosidad
del mes en curso. Ninguno daba error.

**Regla:** para cada dato que entra, probar lo que teclea una persona de verdad —formatos
mezclados, copiar y pegar de un Excel, el 31 de febrero— y mirar qué quedó guardado.

### Simular uso, no buscar errores

Ver `AUDITORIA_DE_USO.md`. Los dos fallos que encontró devolvían `200 OK` en todas sus
llamadas: sólo aparecen si compruebas el resultado, no la respuesta.

---

## 2. Lo que se encontró

Veintidós cambios publicados. Ordenados por lo que le pasaba a quien lo sufría.

### Se perdían datos

| Qué pasaba | Dónde |
|---|---|
| Borrar a un propietario del censo dejaba **tres recibos sin dueño**, uno pendiente de 240 €. Contestaba «ok». | `505b0a5` |
| Borrar la captación de un piso vendido reventaba con un **500** por clave ajena; en Postgres además envenenaba el resto de la petición. | `64e6f85` |
| **«Generar checklist»** y **«Convertir en hipoteca»** decían «ok» y no guardaban nada: faltaba el `conn.commit()`. La conversión devolvía el id de una hipoteca inexistente. | *(en este documento)* |
| Un importe pegado en formato inglés (`1,234.56`) se guardaba como **1,23 €**. Estaba en tres analizadores distintos. | `40e1522` |
| Teclear **31/02** no daba error: guardaba el 3 de marzo. Con guiones o puntos, ni se traducía. | `85241ac` |

### El CRM decía algo que no era verdad

| Qué pasaba | Dónde |
|---|---|
| Cerrar una venta dejaba el piso como «Inmueble»: volvía al listado **indistinguible de uno disponible**. | *(en este documento)* |
| El día de emitir los recibos, **toda la comunidad salía morosa**. El certificado de deuda certificaba un importe que aún no se debía. | `4b0948b` |
| La supresión RGPD respondía «la ficha ya no identifica a nadie» cuando la misma persona seguía entera en otra tabla. | `32fe0f3` |

### Cosas que no se podían hacer

| Qué pasaba | Dónde |
|---|---|
| Tres botones contestaban «Endpoint no valido»: cerrar una compraventa, la preparación guiada del inmueble y reprocesar el OCR de una nómina. El manejador existía; faltaba darlo de alta en una lista. | `38962df` |
| Un comunero no tenía forma de ejercer el art. 17: no es un cliente, y la supresión no llegaba a su ficha. | `505b0a5` |

### El dato entraba mal y nadie avisaba

Cuatro cifras que el CRM aceptaba con un «ok». El criterio lo decidió el cliente:
**rechazar los negativos siempre** —porque el signo lo pone el tipo de apunte, no quien
teclea— y **pedir confirmación por encima de un tope** en vez de bloquear, porque una
derrama grande es legítima y un tope de negocio se acaba quedando corto.

| Qué pasaba | Cómo queda |
|---|---|
| Un **coeficiente del 250 %** entraba en la ficha del vecino. Es la parte que le toca de la finca (art. 5 LPH) y multiplica lo que se le cobra: dos veces y media el presupuesto entero. Un negativo le devolvía dinero cada mes. | 400 entre 0 y 100 |
| **Cuota mensual negativa** en el alta de la comunidad. | 400 |
| Un **gasto de -500 €** sumaba en vez de restar: el signo lo pone el tipo. | 400, y se indica que un abono se anota como ingreso |
| Un apunte de **un billón de euros**. | 409 con `requiere_confirmacion`; el front pregunta y reintenta |

### El escaparate llevaba la marca de otro

| Qué pasaba | Cómo queda |
|---|---|
| Todo lo publicado salía anunciado por **«Grupo Modernia»**, fuera de quien fuera. La consulta ya traía `e.nombre` y `e.logo_url` de la empresa dueña; el armador de la respuesta pública no los miraba. Hoy no se nota porque publica una sola agencia. | Cada piso sale con la marca y el logotipo de **su** agencia |
| `/api/portal_empresa_logo` estaba escrito y no era alcanzable desde ninguna ruta pública. | Dado de alta en la lista pública de GET, y sólo responde si esa empresa tiene algo publicado: no sirve para pasear el directorio de empresas desde fuera |
| Dentro de ese endpoint, **ningún logotipo de S3 se servía**: se le pasaba la URI entera a `_normalize_s3_key`, que espera la clave. Nunca se había notado porque la ruta no era alcanzable; en cuanto lo fue, dejó el escaparate sin logotipo. | Se trocea como en el generador de informes. Y si aun así no se puede servir, se enseña la marca de la casa: quien mira el anuncio no tiene la culpa |
| Al publicarlo, los seis anuncios pasaron a decir **«Estudio Velazquez 2012 SL»**: es la empresa dueña, correcto en la base y malo en un escaparate. | Un campo **nombre comercial** en la ficha de la empresa, editable. Vacío = «Grupo Modernia», que es lo que había siempre |

### Seguridad

| Qué pasaba | Dónde |
|---|---|
| El documento que se manda a firmar se servía con su tipo real: un `.html` se **ejecutaba en el navegador del cliente**, en el origen de la aplicación. La ruta `/uploads/` ya se protegía así; este endpoint se la saltaba. | `eea715f` |
| Un nombre de cliente con etiquetas se ejecutaba al abrir sus relaciones. Una de 235 interpolaciones. | `7c0aa3a` |
| El último administrador podía **echarse a sí mismo** y dejar el espacio sin nadie que lo gestionara. | `e0c943e` |

### Los guardarraíles

| Qué pasaba | Dónde |
|---|---|
| La prueba que vigila las rutas POST no miraba `apiPost`: 39 rutas sin cubrir. | `0280240` |
| Su hermana no miraba las llamadas con parámetros: 162 de 444. | `8613c18` |
| Una copia recién clonada daba siete pruebas en rojo por falta de `npm install`, con un volcado de pila que se leía como código roto. | `0e90487` |

---

## 3. Lo que se comprobó y estaba bien

Tan importante como lo anterior, para no repetir trabajo:

- **123 endpoints transversales**, con GET y POST: ningún 500.
- **Aislamiento entre espacios**: un miembro del espacio B llamando a los 123 con el
  `workspace_id` del espacio A no lee ni escribe nada. Con control de que la dueña
  legítima **sí** ve sus datos, para que el barrido no pase por vacío.
- **Escalada de privilegios**: un trabajador raso contra 28 endpoints destructivos, todo
  403. No consigue ascenderse.
- **Superficie anónima**: sólo responden `build_info`, `health` y `session_state`.
- **31 endpoints que generan documentos**: todos producen su PDF, XLSX, XML o CSV.
- **Los botones**: 636 en el HTML, ninguno huérfano; 100 pulsados de verdad en el
  navegador recorriendo el espacio y las 16 vistas del CRM, ninguno muerto.
- **Los portales públicos**: su JavaScript escapa todo con `esc()`.
- **19 paneles sobre una base vacía** —el primer día de un cliente— sin un `NaN` ni un
  `undefined`.
- **Registro horario**: el borrado de una ficha con fichajes protegidos desactiva en vez
  de borrar. Bien resuelto desde antes.
- **Sesión caducada**: superpone la capa de acceso sin recargar; no se pierde lo tecleado.
- **Los tres portales de cliente, de punta a punta**: consentimiento antes de enseñar
  nada, cada uno ve sólo lo suyo, token falso y token cruzado rechazados, enlace revocado
  con mensaje claro, y la visita pedida desde el portal llega a la agenda. Sin fallos.
- **Ciclo de una gestoría**: expediente con sus servicios, trabajo con plazo, modelos
  programados, apunte contable y panel. Sin fallos.
- **Ciclo de una póliza**: oferta, contratación con su PDF obligatorio, entrada en vigor,
  recibo, resumen, siniestro y renovación. Los importes cuadran de punta a punta y los
  dos controles del módulo explican qué hacer. Sin fallos.
- **Registro de jornada, ciclo completo**: fichar, regularizar un olvido con constancia en
  la auditoría, cerrar el mes —que impide fichar y regularizar, diciendo qué hacer—,
  desbloquear y exportar. Sin fallos.

---

## 4. Herramientas que quedan

```bash
python scripts/simula_ciclo_fincas.py          # mes completo de una comunidad
python scripts/simula_ciclo_inmobiliaria.py    # de la captación a la firma
python scripts/simula_ciclo_rrhh.py            # jornada y cierre de mes
python scripts/simula_ciclo_seguros.py         # de la oferta a la renovación
python scripts/simula_ciclo_financiaciones.py  # del estudio a la firma
python scripts/simula_ciclo_gestoria.py        # expediente, trabajos y modelos
python scripts/simula_portales.py              # los tres portales de cliente
python scripts/auditoria_endpoints_inmo.py     # barrido de los endpoints del módulo
```

Y en la suite, las pruebas nuevas que vigilan lo encontrado: búsquense por
`test_los_post_del_front_estan_dados_de_alta`, `test_el_front_no_llama_al_vacio`,
`test_ningun_campo_de_la_base_sin_escapar`, `test_importe_en_formato_ingles`,
`test_una_fecha_que_no_existe`, `test_documento_de_firma_no_se_ejecuta`,
`test_borrar_captacion_no_arrastra_el_cierre`, `test_una_venta_cerrada_figura_vendida`,
`test_supresion_rgpd`, `test_morosidad_y_certificado`,
`test_cifras_que_no_pueden_ser`, `test_el_anuncio_lleva_su_agencia`.

---

## 5. Lo que queda abierto

### Sin auditar

- **Los caminos que se salen de lo normal** en los seis módulos simulados: derramas,
  cambio de propietario a mitad de ejercicio, anulaciones, devoluciones parciales,
  alquileres, ausencias, nóminas, cambio de compañía y bajas de póliza.
- **Los portales de punta a punta**, como recorrido completo del cliente.
- **La interfaz**: las simulaciones comprueban la API y la base. Una pantalla puede
  enseñar mal un dato correcto.

### Decisiones pendientes del cliente

- Datos de fincas: coeficientes por cargar, referencia catastral de Sierra Bermeja 5,
  recuento de unidades de cinco comunidades, 39 correos truncados.
- El **500 de `/api/gestoria_docs`** (clave ajena), sin tocar por ser área de trabajo
  activa de otra sesión.

### Anotaciones menores

- Un parámetro que falta en `/api/captacion_convert` responde **403 «id requerido»** en
  vez de 400. No es visible para el usuario, pero despista al depurar.
- `/api/hipotecas_fichas_pdf` y `/api/hipotecas_listado_pdf` tienen manejador escrito y
  no los llama nadie: quedan deliberadamente fuera de la lista blanca, documentado en
  `tests/test_auditoria_modulos_restantes.py`.
