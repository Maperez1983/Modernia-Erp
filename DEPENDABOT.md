# Dependabot

Dependabot abre pull requests automáticas para actualizar dependencias declaradas en el repositorio.

## Ecosistemas Revisados

- `pip`: revisa `requirements.txt` y `requirements-dev.txt`.
- `github-actions`: revisa las acciones usadas por el workflow de CI.

## Cuándo Se Ejecuta

- Una vez por semana.
- `pip`: lunes a las `08:00` en `Europe/Madrid`.
- `github-actions`: lunes a las `08:30` en `Europe/Madrid`.

## Cómo Agrupa Actualizaciones

- Las actualizaciones compatibles `patch` y `minor` se agrupan para reducir ruido.
- Las actualizaciones `major` no se agrupan.
- Las majors se abren en pull requests separadas para revisar su impacto con más detalle.

## Política Sobre Majors

- Las majors se revisan por separado porque pueden introducir cambios incompatibles.
- No se fusionan automáticamente.
- Se revisan junto a los tests del proyecto y, si hace falta, con una comprobación manual del comportamiento afectado.

## Cómo Revisar Una Pull Request De Dependabot

1. Leer el resumen del cambio y confirmar qué paquete se actualiza.
2. Revisar si la actualización es `patch`, `minor` o `major`.
3. Ejecutar o revisar los checks de CI.
4. Confirmar que `pip-audit`, Ruff, Bandit, pytest y cobertura pasan.
5. Verificar que no hay regresiones funcionales ni cambios inesperados de bloqueo.

## Comprobaciones Antes De Fusionar

- `python -m pip_audit -r requirements.txt`
- `ruff check .`
- `bandit -r web -c bandit.yaml --severity-level high --confidence-level high`
- `python -m pytest`
- `python -m pytest --cov=web --cov-report=term-missing`

## Auto-merge

- No activar auto-merge hasta disponer de pruebas suficientes y confianza real en la actualización.
- La decisión debe seguir pasando por revisión humana, especialmente para majors.

## Pausar Temporalmente Una Dependencia

- Si una actualización rompe CI o introduce un conflicto temporal, se puede pausar de forma manual en `.github/dependabot.yml` con una entrada `ignore` temporal para ese paquete o rango de versiones.
- La pausa debe incluir motivo, fecha de revisión y criterio para retirarla.
- No debe usarse como solución permanente sin revisión.

## Dependabot Y pip-audit

- Dependabot propone actualizaciones de versiones.
- `pip-audit` detecta vulnerabilidades conocidas en las dependencias instaladas o declaradas.
- Dependabot ayuda a mantenerse al día; `pip-audit` ayuda a identificar riesgos de seguridad ya presentes.
- Son complementarios y deben seguir ejecutándose ambos.
