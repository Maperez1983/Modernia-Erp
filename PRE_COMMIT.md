# pre-commit

`pre-commit` ejecuta comprobaciones ligeras antes de cada commit para detectar errores mecánicos y fallos de lint o tipado sin esperar a CI.

## Hooks que se ejecutan

- `ruff` sobre los archivos Python staged.
- `mypy` sobre estos módulos:
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
- `trailing-whitespace`
- `end-of-file-fixer`
- `check-yaml`
- `check-json`
- `check-toml`
- `check-merge-conflict`
- `check-added-large-files`
- `detect-private-key`
- `mixed-line-ending`

## Hooks que no se ejecutan

- `Bandit`
- `pip-audit`
- `Coverage`
- `pytest`
- `Playwright`
- `CodeQL`

Esas comprobaciones siguen en CI porque son más pesadas y no aportan suficiente valor en un hook local antes de cada commit.

## Instalación

Primero instala las dependencias de desarrollo y activa el entorno virtual recomendado del proyecto.

```bash
python -m pip install -r requirements-dev.txt
pre-commit install
```

Si quieres precargar los hooks la primera vez:

```bash
pre-commit install --install-hooks
```

## Ejecución manual

Ejecuta todos los hooks sobre los archivos staged:

```bash
pre-commit run
```

Ejecuta todos los hooks sobre todo el repositorio:

```bash
pre-commit run --all-files
```

Ejecuta un hook concreto:

```bash
pre-commit run ruff --files web/app.js
pre-commit run mypy
```

## Ejecutar todos los archivos

`pre-commit run --all-files` es útil después de cambiar la configuración del propio hook o antes de un release. En commits normales, `pre-commit` solo revisa los archivos afectados.

## Saltar un hook

Forma excepcional y puntual:

```bash
SKIP=ruff git commit
```

Si necesitas saltarte varios:

```bash
SKIP=ruff,mypy git commit
```

`git commit --no-verify` salta todo el hook y solo debe usarse en una emergencia real.

## Política sobre `SKIP` y `--no-verify`

- `SKIP` es preferible cuando necesitas omitir una sola comprobación conocida.
- `--no-verify` debe reservarse para incidencias urgentes.
- Después de cualquiera de las dos excepciones, vuelve a ejecutar `pre-commit run --all-files` antes de integrar el cambio.

## Límites y rendimiento

- `ruff` usa el entorno activo del proyecto y solo recibe archivos Python staged.
- `mypy` usa el mismo entorno activo y no reinstala dependencias en cada commit.
- `check-added-large-files` usa un límite de `5000 KB`, suficiente para los assets actuales y bajo para capturar ficheros accidentales grandes.

## Actualizar versiones

1. Cambia las versiones en `.pre-commit-config.yaml` cuando sea necesario.
2. Ejecuta:

```bash
pre-commit autoupdate
pre-commit run --all-files
```

3. Revisa el diff generado y confirma que no aparezcan cambios inesperados.

## Nota operativa

Los hooks locales (`ruff` y `mypy`) asumen que `python` apunta al entorno virtual del proyecto. Lo normal es instalar `pre-commit` desde ese mismo entorno.
