# mypy

`mypy` aporta análisis estático de tipos para Python. No ejecuta código ni sustituye a los tests.

## Qué analiza

- Compatibilidad de tipos en firmas, retornos, variables locales y flujos de control.
- Imports y dependencias opcionales cuando el código las referencia.
- Errores de tipado que suelen anticipar bugs reales, como `None` no protegido, contenedores mal inferidos o ramas incompatibles.

## Diferencia con tests

- `mypy` comprueba si el código es coherente a nivel de tipos antes de ejecutarse.
- `pytest` comprueba comportamiento real con ejecución.
- Un módulo puede pasar `mypy` y aun así fallar funcionalmente, y al revés.

## Módulos incluidos

- `web/auth_security.py`
- `web/public_links.py`
- `web/security_utils.py`
- `web/ocr_service.py`
- `web/pdf_utils.py`
- `web/document_pdf.py`
- `web/hipotecas_pdf.py`
- `web/db_backend.py`
- `web/schema_support.py`
- `web/seguros_state.py`

## Módulos excluidos temporalmente

- `web/server.py`

`web/server.py` sigue siendo un monolito grande y arrastra demasiado contexto dinámico para esta fase. Se mantiene fuera del chequeo principal hasta que más lógica se extraiga a módulos pequeños y tipables.

## Cómo ejecutarlo

Desde la raíz del repositorio:

```bash
python -m mypy -p web.auth_security -p web.public_links -p web.security_utils -p web.ocr_service -p web.pdf_utils -p web.document_pdf -p web.hipotecas_pdf -p web.db_backend -p web.schema_support -p web.seguros_state
```

En CI se usa el mismo conjunto de módulos para garantizar que la cobertura no cambie sin revisión.

## Política sobre `Any`

- `Any` se reserva para límites realmente dinámicos: JSON heterogéneo, conexiones externas opcionales, cargas de terceros sin contrato estable.
- No se usa como comodín para evitar trabajo de tipado.
- Cuando `Any` aparece, debe quedar cerca del borde del sistema y no propagarse sin necesidad.

## Política sobre `type: ignore`

- Se evita por defecto.
- Si es imprescindible, debe llevar código de error específico, por ejemplo `# type: ignore[import-not-found]`.
- Solo debe usarse cuando exista una razón clara, como un fallback de importación en tiempo de ejecución o una limitación real de un stub externo.

## Cómo ampliar la cobertura

1. Añade tipos seguros al módulo nuevo o extraído.
2. Corrige los errores reales que aparezcan.
3. Incorpora el módulo al comando de CI y al bloque de configuración de `pyproject.toml`.
4. Vuelve a ejecutar `mypy` y `pytest`.

## Siguiente objetivo

Reducir la exclusión de `web/server.py` extrayendo piezas con más deuda histórica hacia módulos pequeños tipados, empezando por:

- autenticación y sesiones;
- acceso a base de datos y pooling;
- generación de PDFs;
- utilidades de payloads y normalización.

Cuando esa fragmentación avance, `web/server.py` podrá entrar gradualmente en el alcance de `mypy`.
