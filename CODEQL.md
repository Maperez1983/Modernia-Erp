# CodeQL

CodeQL es el analizador estático de GitHub para seguridad y calidad. No ejecuta la aplicación ni los tests: construye un grafo semántico del código y busca patrones de riesgo, flujos de datos peligrosos y combinaciones de API conocidas.

## Qué analiza

- Rutas de datos desde entradas controladas por usuario hasta sinks sensibles.
- Uso inseguro de APIs, validaciones ausentes y patrones de codificación propensos a vulnerabilidades.
- Consultas de seguridad mantenidas por GitHub para los lenguajes configurados.

## Diferencia Con Bandit Y pip-audit

- `CodeQL` analiza el código fuente con contexto semántico y seguimiento de flujo de datos.
- `Bandit` revisa el código Python con reglas más directas y centradas en patrones concretos.
- `pip-audit` no analiza el código: revisa dependencias Python publicadas y compara versiones con vulnerabilidades conocidas.

Los tres son complementarios:

- `CodeQL` cubre análisis profundo de seguridad en Python y JavaScript.
- `Bandit` cubre heurísticas rápidas sobre el código Python propio.
- `pip-audit` cubre la cadena de suministro de dependencias Python.

## Lenguajes Analizados

- `python`
- `javascript-typescript`

No se añaden consultas personalizadas ni auto-fix. Se mantienen las consultas recomendadas por GitHub.

## Cuándo Se Ejecuta

- `push` a `main`
- `pull_request` hacia `main`
- programación semanal los martes a las `06:00 UTC`

Ese horario cae por la mañana en `Europe/Madrid` durante todo el año.

## Dónde Ver Los Resultados

- En `Security` > `Code scanning alerts`.
- En la ejecución del workflow `CodeQL` dentro de `Actions`.
- En cada pull request, si la protección de ramas expone el check de code scanning, como un estado de revisión más.

## Cómo Revisar Una Alerta

1. Abre la alerta en `Security` > `Code scanning alerts`.
2. Revisa el título, severidad, precisión y archivo afectado.
3. Sigue el trazado de la alerta para ver origen, propagación y sink.
4. Comprueba si el flujo es realmente alcanzable con datos no confiables.
5. Verifica si hay sanitización, validación, escaping o restricciones de contexto que invaliden el hallazgo.

## Cómo Distinguir Un Falso Positivo De Una Vulnerabilidad Real

- Es falso positivo si el origen no es controlable por un atacante.
- Es falso positivo si el sink no es alcanzable en la práctica.
- Es falso positivo si la validación o sanitización bloquea la explotación antes del punto sensible.
- Es más probable que sea real si la entrada viene de usuario, red, cabeceras, cookies, rutas o parámetros y llega sin control a una operación sensible.

Si hay duda, se debe asumir riesgo hasta demostrar lo contrario con código, trazas o una reproducción fiable.

## Política Para Cerrar Alertas

- Solo cerrar una alerta cuando el problema esté corregido, el hallazgo sea un falso positivo demostrado o exista una aceptación explícita del riesgo.
- Si se cierra como `false positive`, debe quedar claro por qué no es explotable.
- Si se cierra como `won't fix`, debe existir una justificación técnica y una mitigación compensatoria si procede.
- No se deben cerrar alertas por comodidad ni para limpiar el panel sin revisión.

## Por Qué No Se Debe Ignorar Una Alerta Sin Justificación

- Ignorar sin explicación oculta riesgo real y rompe la trazabilidad de seguridad.
- Una alerta sin revisión puede volver a aparecer en cambios futuros o en otra ruta de ejecución.
- La justificación ayuda a distinguir deuda aceptada de un problema pendiente.

## Pull Requests Bloqueadas Por CodeQL

Si una pull request queda bloqueada por el check de CodeQL:

1. Abre la pestaña `Checks` de la PR.
2. Localiza el job `CodeQL` y la alerta concreta.
3. Corrige el código si la ruta es explotable.
4. Si es falso positivo, cierra la alerta con la razón adecuada y documenta el motivo.
5. Reejecuta el workflow o espera al siguiente run para confirmar que el bloqueo desaparece.

## Limitaciones Del Análisis JavaScript Sin Tests E2E

- CodeQL no ejecuta la interfaz en navegador real.
- No ve rutas que solo aparecen tras interacción de usuario, eventos del DOM o estados asincrónicos complejos.
- No valida comportamientos que dependan de respuestas reales del backend, latencias, redirecciones o almacenamiento del navegador.
- El código embebido en HTML y otras rutas muy dinámicas puede quedar menos cubierto que el JavaScript modular.
- Sin tests E2E, una parte importante del comportamiento de la UI sigue sin ejercitarse, así que CodeQL debe tratarse como una capa de seguridad, no como validación funcional completa.
