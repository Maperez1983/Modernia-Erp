# pip-audit

`pip-audit` analiza las dependencias Python instaladas o declaradas en `requirements.txt` y las compara con bases de datos públicas de vulnerabilidades.

## Qué revisa

- Paquetes directos declarados en `requirements.txt`.
- Dependencias transitivas resueltas a partir de esos paquetes.
- IDs de vulnerabilidades como `PYSEC-*`, `CVE-*` y `GHSA-*` cuando existen.

## Ejecución local

```bash
python -m pip_audit -r requirements.txt
python -m pip_audit -r requirements.txt -f json -o pip-audit-report.json
```

## Cómo interpretar los resultados

- Si `pip-audit` devuelve salida y código de error, existe al menos una vulnerabilidad conocida.
- La salida muestra el paquete afectado, la versión instalada y las versiones corregidas.
- El JSON se usa para revisión manual y como artifact en CI.
- `pip-audit` no clasifica el problema como `HIGH/MEDIUM/LOW`; esa severidad debe valorarse junto con el contexto del proyecto.

## Actualización Segura

1. Actualiza la dependencia mínima necesaria en `requirements.txt`.
2. Reinstala dependencias.
3. Ejecuta `python -m pytest`, `ruff check .`, `bandit -r web -c bandit.yaml --severity-level high --confidence-level high` y `python -m pip_audit -r requirements.txt`.
4. Verifica que no haya regresiones funcionales.

## Excepciones

- No se ignoran vulnerabilidades por ID salvo que exista una justificación documentada.
- Si una versión corregida no es compatible con el proyecto, se deja constancia en este documento con el riesgo y la mitigación.
- A día de hoy no hay excepciones permanentes registradas.

## Diferencia Con Bandit

- `pip-audit` evalúa dependencias de terceros instaladas.
- `Bandit` revisa el código fuente del proyecto.
- Ambos se complementan: uno protege la cadena de suministro, el otro el código propio.

## Frecuencia Recomendada

- En CI, en cada `push` y `pull_request`.
- Localmente, antes de publicar cambios en dependencias.
- Como revisión manual adicional cuando se actualice cualquier paquete de producción.
