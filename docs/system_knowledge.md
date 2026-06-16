# Modernia CRM System Knowledge

Generated: 2026-06-16T12:39:40+00:00
Commit: cc0041524667d4eb5d212d6dfff96a1db9bfc1aa

Memoria estable para que Ollama relacione fallos de produccion con el modulo, endpoint, frontend, test y expectativa funcional correspondiente.

## Modules

### agenda

- API endpoints: 1
- Tests: tests/test_agenda_frontend_regressions.py
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
