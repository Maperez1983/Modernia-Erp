# Modernia CRM System Knowledge

Generated: 2026-06-17T19:55:53+00:00
Commit: c831f933d3d957120791cb62fca360b07c295963

Memoria estable para que Ollama relacione fallos de produccion con el modulo, endpoint, frontend, test y expectativa funcional correspondiente.

## Operational Memory

- Expected behaviors: docs/expected_behaviors.json
- Incidents: docs/incidents.jsonl
- Repair playbooks: docs/repair_playbooks.json
- Security invariants: docs/security_invariants.json

## Modules

### agenda

- API endpoints: 1
- Tests: tests/test_acciones_service_scope.py, tests/test_agenda_frontend_regressions.py
- Expectations:
  - Los usuarios de un workspace deben ver sus citas nuevas y antiguas si pertenecen al workspace.
  - El comportamiento de lectura de agenda debe ser equivalente entre admin y no admin dentro del mismo workspace permitido.
  - Al crear o editar citas no se deben heredar cliente, tipo de cita, responsable, fechas ni campos de una cita anterior.
  - Los filtros de agenda deben acotarse por workspace/servicio, no por estado modal residual del frontend.

### usuarios_permisos

- API endpoints: 2
- Tests: tests/test_api_usuarios_scoping.py, tests/test_privilege_refresh.py, tests/test_usuarios_uniqueness.py, tests/test_workspace_membership_autojoin.py
- Expectations:
  - Un usuario no privilegiado solo puede ver datos de workspaces donde es miembro.
  - Un admin puede auditar usuarios por workspace, pero no debe mezclar tenants sin workspace_id.
  - Las diferencias de permisos deben producir 401/403 controlados, nunca 5xx.

### workspaces

- API endpoints: 46
- Tests: tests/test_workspace_presupuestos_insert_placeholders.py, tests/test_workspace_scope_empresa_ids.py
- Expectations:
  - Toda consulta operativa debe resolver workspace_id de forma explicita o desde la sesion.
  - Los endpoints compartidos deben mantener aislamiento entre workspaces.

### core

- API endpoints: 46
- Tests: tests/test_admin_force_reset_password_invite.py, tests/test_admin_user_lookup.py, tests/test_aon_diario_to_miconversor.py, tests/test_auth_invites_table_does_not_close_conn.py, tests/test_auth_security.py, tests/test_cliente_ficha.py, tests/test_fiscal_venta_pdf.py, tests/test_fiscal_venta_presets.py, tests/test_frontend_smoke.py, tests/test_iivtnu_hacienda_excel2022_catalog.py, tests/test_iivtnu_malaga_proxies.py, tests/test_iivtnu_max_coefs.py
- Expectations:
  - Si una card del home es visible para el usuario, debe abrir una vista real o tener href funcional.
  - No puede existir una card CRM visible pero inerte por guards frontend inconsistentes con el render.

### inmobiliaria

- API endpoints: 27
- Tests: tests/test_inmobiliaria_archivar_pendientes.py, tests/test_inmobiliaria_crm_smoke.py, tests/test_inmobiliaria_e2e_playwright.py, tests/test_inmobiliaria_encargo_close.py, tests/test_inmobiliaria_workflow_docs.py
- Expectations:
  - La informacion de inmuebles, demandas, visitas, compraventas y matching debe estar filtrada por workspace.
  - Las vistas de no admin deben devolver datos permitidos, no listas vacias por error de scoping.

### seguros

- API endpoints: 26
- Tests: tests/test_ocr_smoke_seguros_upload.py, tests/test_seguros_activation.py, tests/test_seguros_contabilidad.py, tests/test_seguros_contabilidad_sync.py, tests/test_seguros_e2e_playwright.py, tests/test_seguros_kpis_vencen_30_ddmmyyyy.py, tests/test_seguros_ocr_parse.py, tests/test_seguros_renovaciones_queue_dedup.py
- Expectations:
  - Los endpoints de seguros deben devolver datos o 403 controlado si el usuario no tiene servicio.
  - Los KPIs no deben romper por falta de datos; si falta empresa_id debe responder 400 claro.

### gestoria

- API endpoints: 21
- Tests: tests/test_factura_ocr.py, tests/test_gapp_facturas_excel.py, tests/test_gestoria_import_backend.py, tests/test_gestoria_renta_cards_regression.py, tests/test_ocr_smoke_renta_upload.py, tests/test_renta_ocr_nif_detection.py, tests/test_renta_pdf_fields.py, tests/test_rentas_import.py, tests/test_rentas_ocr_normalization.py, tests/test_rentas_paid_2024.py
- Expectations:
  - Los endpoints de gestoria deben respetar permisos de servicio y workspace.
  - La importacion y consulta documental no debe cruzar clientes entre workspaces.

### financiacion

- API endpoints: 12
- Tests: tests/test_fin_liquidacion_excel_parity.py, tests/test_fin_liquidacion_fuzz.py, tests/test_fin_workflow.py, tests/test_hipotecas_delete.py
- Expectations:
  - Las alertas/KPIs financieros deben responder con datos o errores 400/403 controlados.

### fincas

- API endpoints: 2
- Tests: tests/test_fincas_bank_extract_import.py, tests/test_fincas_budget_edit_modal_regression.py, tests/test_fincas_budget_pdf_cover_layout_regression.py, tests/test_fincas_budget_pdf_map_render_regression.py, tests/test_fincas_budget_pdf_table_alignment_regression.py, tests/test_fincas_comunidad_ficha_tabs_regression.py
- Expectations:
  - Las comunidades, incidencias, proveedores y documentos deben acotarse por workspace.

### rrhh

- API endpoints: 25
- Tests: tests/test_nomina_pdf_fields_empresa_aportacion.py, tests/test_registro_horario_sweep_timezone.py, tests/test_rrhh_nominas_import_dedupe.py, tests/test_rrhh_nominas_split_pdf.py, tests/test_rrhh_personal_workspace_scoping.py
- Expectations:
  - El registro horario y personal deben estar acotados por usuario/workspace.

## Diagnostic Rules

### Una card del home se muestra pero al pulsarla no navega a ningun CRM.
- Module: core
- Look at:
  - web/app.js renderCompanyCards y appendServiceCard
  - web/app.js coreCards.addEventListener(click)
  - web/app.js userCanAccessService / hasAdminWideAccess
  - scripts/frontend_home_access_audit.py
  - tests/test_frontend_smoke.py
  - tests/test_agenda_frontend_regressions.py

### Un usuario no admin no ve citas o ve menos que admin en el mismo workspace.
- Module: agenda
- Look at:
  - scripts/prod_system_matrix_audit.py endpoint agenda_inmobiliaria
  - web/server.py /api/acciones
  - fetch_api_usuarios y enforce_workspace_membership
  - web/app.js estado modal/filtros de agenda
  - tests/test_agenda_frontend_regressions.py
  - tests/test_api_usuarios_scoping.py

### Despues de editar/crear una cita se heredan cliente, tipo o responsable.
- Module: agenda
- Look at:
  - web/app.js apertura/reset del modal de agenda
  - web/app.js serializacion del formulario de cita
  - tests/test_agenda_frontend_regressions.py

### Aparecen 500/timeout en endpoints de produccion.
- Module: core
- Look at:
  - output_tail del paso fallido
  - endpoint exacto en web/server.py
  - tests relacionados por nombre de modulo
  - schema.sql si el error menciona columna/tabla

### Un endpoint responde 403 a no admin.
- Module: usuarios_permisos
- Look at:
  - servicio/rol del usuario en /api/login
  - workspace_user_inventory
  - controles has_service_access/enforce_workspace_membership
- Note: Puede ser correcto si el usuario no tiene ese servicio; no debe considerarse caida si es esperado.

## Recent Incidents

### INC-AGENDA-SQLITE-POSTGRES-MIX
- Symptom: Usuarios admin y no admin dejaron de ver citas historicas en agenda inmobiliaria.
- Root cause: La web de produccion estaba conectada a SQLite mientras la agenda historica correcta residia en Postgres; coexistian syncs legacy a SQLite con despliegue operacional en Postgres.
- Fix commit: 3c669aa

### INC-AUTH-DRIFT-SHARED-PASSWORDS
- Symptom: Usuarios que podian entrar el dia anterior dejaron de autenticar tras la unificacion de backend.
- Root cause: En Postgres habia hashes divergentes entre usuarios de pruebas; la politica de contrasena compartida no estaba auditada y el admin lookup estaba roto por NameError.
- Fix commit: 350d26f

### INC-HOME-CARD-INERT
- Symptom: Al pulsar cards del home de CRM no se abria ningun modulo.
- Root cause: Guards frontend incoherentes con la visibilidad de las cards y routing legado hacia explorador de empresa en lugar de workspace CRM.
- Fix commit: 27d534e

### INC-GESTORIA-CLIENT-SEARCH-AGGREGATES
- Symptom: Las busquedas de clientes en gestoria devolvian agregados o columnas inconsistentes y degradaban la localizacion del cliente correcto.
- Root cause: La consulta de listado y agregados de clientes de gestoria no priorizaba coincidencias exactas y mezclaba campos agregados en la vista.
- Fix commit: 7f6ecf0

### INC-AUTH-NO-MEMBERSHIP-WARNINGS
- Symptom: Usuarios activos podian autenticar pero no tenian memberships asociadas a ningun workspace.
- Root cause: Existian cuentas operativas sin vinculacion tenant, lo que genera accesos parciales y diagnósticos confusos.
- Fix commit: cbf0a13

### INC-HOME-ADMIN-ROUTING-MISMATCH
- Symptom: Usuarios administradores veian cards o workspaces pero el enrutado real no abria el CRM correcto o les llevaba a un flujo legacy.
- Root cause: El criterio de acceso admin amplio no estaba alineado entre render de home, click handlers y routing tenant.
- Fix commit: 24a9568
