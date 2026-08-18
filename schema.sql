PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS empresas (
  id TEXT PRIMARY KEY,
  nombre TEXT NOT NULL UNIQUE,
  activo INTEGER NOT NULL DEFAULT 1,
  logo_url TEXT,
  nif TEXT,
  direccion TEXT,
  sector TEXT,
  cnae TEXT,
  cnaes_json TEXT,
  convenio_key TEXT,
  convenio_nombre TEXT,
  vacaciones_modo TEXT NOT NULL DEFAULT 'habiles',
  vacaciones_dias_anuales REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS empresa_aliases (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  source TEXT NOT NULL,
  alias TEXT NOT NULL,
  alias_norm TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (source, alias_norm),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);
CREATE INDEX IF NOT EXISTS idx_empresa_aliases_empresa_id ON empresa_aliases (empresa_id);

CREATE TABLE IF NOT EXISTS workspaces (
  id TEXT PRIMARY KEY,
  nombre TEXT NOT NULL UNIQUE,
  slug TEXT NOT NULL UNIQUE,
  estado TEXT NOT NULL DEFAULT 'Activo',
  plan TEXT NOT NULL DEFAULT 'Enterprise',
  descripcion TEXT,
  logo_url TEXT,
  primary_color TEXT,
  accent_color TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_empresas (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  empresa_id TEXT NOT NULL,
  rol TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (workspace_id, empresa_id),
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS workspace_modulos (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  modulo_key TEXT NOT NULL,
  modulo_nombre TEXT NOT NULL,
  categoria TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0,
  config_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (workspace_id, modulo_key),
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE TABLE IF NOT EXISTS workspace_facturacion (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  empresa_id TEXT,
  cliente_id TEXT,
  servicio TEXT,
  origen_tipo TEXT,
  origen_id TEXT,
  serie TEXT,
  numero TEXT,
  fecha_emision TEXT,
  fecha_vencimiento TEXT,
  concepto TEXT,
  subtotal REAL,
  impuestos REAL,
  total REAL,
  estado TEXT,
  remesa_id TEXT,
  conciliacion_estado TEXT,
  cobrada INTEGER NOT NULL DEFAULT 0,
  fecha_cobro TEXT,
  forma_cobro TEXT,
  responsable TEXT,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS workspace_facturacion_series (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  empresa_id TEXT,
  servicio TEXT,
  serie TEXT NOT NULL,
  prefijo TEXT,
  siguiente_numero INTEGER NOT NULL DEFAULT 1,
  activa INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (workspace_id, empresa_id, serie),
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS workspace_documentos_inbox (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  empresa_id TEXT,
  cliente_id TEXT,
  suggested_cliente_id TEXT,
  servicio TEXT,
  nombre TEXT NOT NULL,
  tipo TEXT,
  clasificacion TEXT,
  canal_entrada TEXT,
  prioridad TEXT,
  estado TEXT NOT NULL DEFAULT 'Pendiente',
  doc_key TEXT,
  doc_url TEXT,
  origen_tipo TEXT,
  origen_id TEXT,
  ocr_job_id TEXT,
  ocr_status TEXT,
  ocr_error TEXT,
  ocr_method TEXT,
  factura_id TEXT,
  asiento_id TEXT,
  reviewed_at TEXT,
  reviewed_by TEXT,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id),
  FOREIGN KEY (suggested_cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS workspace_portal_clientes (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  cliente_id TEXT NOT NULL,
  email_acceso TEXT,
  estado TEXT NOT NULL DEFAULT 'Invitado',
  token TEXT,
  ultimo_acceso_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (workspace_id, cliente_id),
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS workspace_automatizaciones (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  nombre TEXT NOT NULL,
  trigger_key TEXT NOT NULL,
  modulo_key TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  action_summary TEXT,
  config_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE TABLE IF NOT EXISTS workspace_facturacion_cobros (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  factura_id TEXT NOT NULL,
  empresa_id TEXT,
  cliente_id TEXT,
  fecha_cobro TEXT,
  importe REAL NOT NULL DEFAULT 0,
  metodo TEXT,
  referencia TEXT,
  estado TEXT NOT NULL DEFAULT 'Aplicado',
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (factura_id) REFERENCES workspace_facturacion(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS workspace_facturacion_remesas (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  empresa_id TEXT,
  servicio TEXT,
  referencia TEXT NOT NULL,
  fecha_emision TEXT,
  fecha_cargo TEXT,
  estado TEXT NOT NULL DEFAULT 'Preparada',
  total REAL NOT NULL DEFAULT 0,
  facturas_total INTEGER NOT NULL DEFAULT 0,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS workspace_portal_requerimientos (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  portal_cliente_id TEXT NOT NULL,
  cliente_id TEXT,
  servicio TEXT,
  titulo TEXT NOT NULL,
  descripcion TEXT,
  clasificacion TEXT,
  prioridad TEXT,
  estado TEXT NOT NULL DEFAULT 'Pendiente',
  fecha_limite TEXT,
  completed_at TEXT,
  resolved_doc_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (portal_cliente_id) REFERENCES workspace_portal_clientes(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS workspace_registro_personal (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  empresa_id TEXT,
  usuario_id TEXT,
  kiosk_token TEXT,
  nombre TEXT NOT NULL,
  nif TEXT,
  email TEXT,
  telefono TEXT,
  tipo_jornada TEXT NOT NULL DEFAULT 'Completa',
  horas_pactadas_dia REAL,
  horas_pactadas_semana REAL,
  fecha_alta TEXT,
  fecha_baja TEXT,
  activo INTEGER NOT NULL DEFAULT 1,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);

CREATE TABLE IF NOT EXISTS workspace_registro_horario (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  empresa_id TEXT,
  persona_id TEXT,
  usuario_id TEXT,
  persona_nombre TEXT NOT NULL,
  tipo_jornada TEXT,
  horas_pactadas_dia REAL,
  fecha TEXT NOT NULL,
  hora_inicio TEXT NOT NULL,
  hora_fin TEXT,
  pausa_min INTEGER NOT NULL DEFAULT 0,
  minutos_trabajados INTEGER NOT NULL DEFAULT 0,
  metodo_registro TEXT,
  estado TEXT NOT NULL DEFAULT 'Abierto',
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (persona_id) REFERENCES workspace_registro_personal(id),
  FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
);

CREATE TABLE IF NOT EXISTS workspace_presupuestos (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  empresa_id TEXT,
  cliente_id TEXT,
  servicio TEXT,
  referencia_tipo TEXT,
  referencia_id TEXT,
  titulo TEXT NOT NULL,
  estado TEXT NOT NULL DEFAULT 'Borrador',
  fecha TEXT,
  fecha_seguimiento TEXT,
  motivo_estado TEXT,
  responsable TEXT,
  forma_pago TEXT,
  encargo_estado TEXT,
  fecha_encargo TEXT,
  observaciones TEXT,
  subtotal REAL,
  impuestos REAL,
  total REAL,
  calculo_json TEXT,
  seguimiento_accion_id TEXT,
  encargo_accion_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS workspace_presupuesto_lineas (
  id TEXT PRIMARY KEY,
  presupuesto_id TEXT NOT NULL,
  orden INTEGER NOT NULL DEFAULT 1,
  categoria TEXT,
  concepto TEXT NOT NULL,
  cantidad REAL NOT NULL DEFAULT 1,
  unidad TEXT,
  precio_unitario REAL NOT NULL DEFAULT 0,
  descuento_pct REAL NOT NULL DEFAULT 0,
  total_linea REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (presupuesto_id) REFERENCES workspace_presupuestos(id)
);

CREATE TABLE IF NOT EXISTS workspace_fincas_comunidades (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  empresa_id TEXT,
  nombre TEXT NOT NULL,
  cif TEXT,
  direccion TEXT,
  presidente TEXT,
  secretario TEXT,
  estado TEXT NOT NULL DEFAULT 'Activa',
  num_vecinos INTEGER,
  num_locales INTEGER,
  num_trasteros INTEGER,
  num_aparcamientos INTEGER,
  cuota_sugerida REAL,
  cuota_mensual REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS workspace_fincas_incidencias (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  comunidad_id TEXT NOT NULL,
  titulo TEXT NOT NULL,
  descripcion TEXT,
  prioridad TEXT,
  estado TEXT NOT NULL DEFAULT 'Abierta',
  proveedor TEXT,
  proveedor_id TEXT,
  responsable TEXT,
  fecha_apertura TEXT,
  fecha_cierre TEXT,
  coste_estimado REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (comunidad_id) REFERENCES workspace_fincas_comunidades(id)
);

CREATE TABLE IF NOT EXISTS workspace_fincas_proveedores (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  comunidad_id TEXT,
  empresa_id TEXT,
  nombre TEXT NOT NULL,
  tipo_servicio TEXT,
  telefono TEXT,
  email TEXT,
  estado TEXT NOT NULL DEFAULT 'Activo',
  tarifa_mensual REAL,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (comunidad_id) REFERENCES workspace_fincas_comunidades(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS workspace_fincas_juntas (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  comunidad_id TEXT NOT NULL,
  fecha TEXT NOT NULL,
  tipo TEXT,
  estado TEXT NOT NULL DEFAULT 'Planificada',
  orden_dia TEXT,
  acuerdos TEXT,
  proxima_fecha TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
  FOREIGN KEY (comunidad_id) REFERENCES workspace_fincas_comunidades(id)
);

CREATE TABLE IF NOT EXISTS clientes (
  id TEXT PRIMARY KEY,
  -- El tenant del cliente es el workspace. `empresa_id` es un dato de negocio, no
  -- el ámbito: durante un tiempo el scope se dedujo de él y de `clientes_empresas`,
  -- y los clientes sin ese vínculo desaparecían de todas las listas.
  workspace_id TEXT,
  empresa_id TEXT,
  nombre TEXT NOT NULL,
  tipo_persona TEXT,
  nif TEXT,
  telefono TEXT,
  movil TEXT,
  otro_telefono TEXT,
  email TEXT,
  fecha_nacimiento TEXT,
  direccion TEXT,
  direccion_numero TEXT,
  codigo_postal TEXT,
  localidad TEXT,
  poblacion TEXT,
  provincia TEXT,
  id_personal TEXT,
  captado_por_user_id TEXT,
  procedencia_canal TEXT,
  procedencia_detalle TEXT,
  procedencia_user_id TEXT,
  procedencia_cliente_id TEXT,
  cliente_generico_web INTEGER NOT NULL DEFAULT 0,
  tiene_pedido INTEGER NOT NULL DEFAULT 0,
  viabilidad TEXT,
  fecha_estudio TEXT,
  valor_maximo_piso REAL,
  perfil_kiron TEXT,
  estudio_vip INTEGER NOT NULL DEFAULT 0,
  tipo TEXT,
  perfil TEXT,
  estado TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS postal_catalogo (
  codigo_postal TEXT,
  poblacion TEXT,
  provincia TEXT
);

CREATE TABLE IF NOT EXISTS clientes_empresas (
  id TEXT PRIMARY KEY,
  cliente_id TEXT NOT NULL,
  empresa_id TEXT NOT NULL,
  servicio TEXT,
  captado_por_user_id TEXT,
  procedencia_canal TEXT,
  procedencia_cliente_id TEXT,
  estado TEXT,
  fecha_inicio TEXT,
  fecha_fin TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS movimientos (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  concepto TEXT NOT NULL,
  pisos_vendidos TEXT,
  comision REAL,
  asesor TEXT,
  anio INTEGER,
  mes TEXT,
  sl TEXT,
  tipo TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS seguros (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  cliente_id TEXT,
  mes_creacion TEXT,
  fecha_efecto TEXT,
  fecha_vencimiento TEXT,
  tomador TEXT,
  compania TEXT,
  ramo TEXT,
  poliza_numero TEXT,
  prima_neta REAL,
  prima_total REAL,
  comision REAL,
  porcentaje REAL,
  produccion TEXT,
  colaborador TEXT,
  estado TEXT,
  estado_renovacion TEXT,
  renovacion_fecha TEXT,
  nueva_poliza_ref TEXT,
  poliza_key TEXT,
  poliza_url TEXT,
  fecha_baja TEXT,
  motivo_baja TEXT,
  estado_poliza TEXT,
  poliza_origen_id TEXT,
  poliza_sustituta_id TEXT,
  version_grupo TEXT,
  tipo_vigencia TEXT,
  datos_ramo_json TEXT,
  matricula TEXT,
  direccion_riesgo TEXT,
  referencia_catastral TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

-- Reglas configurables de calidad del dato (Seguros).
-- Permite definir campos mínimos por compañía/ramo sin tocar código.
-- `compania_key` puede ir vacío para aplicar a cualquier compañía.
CREATE TABLE IF NOT EXISTS seguros_quality_rules (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  compania_key TEXT,
  ramo_key TEXT NOT NULL,
  field_key TEXT NOT NULL,
  field_label TEXT,
  severity TEXT DEFAULT 'warning',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);
CREATE INDEX IF NOT EXISTS idx_seguros_quality_rules_empresa
ON seguros_quality_rules (empresa_id, enabled);
CREATE INDEX IF NOT EXISTS idx_seguros_quality_rules_scope
ON seguros_quality_rules (empresa_id, compania_key, ramo_key, enabled);

CREATE TABLE IF NOT EXISTS gestoria (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  -- `cliente` es el nombre tal cual vino en la importación, y era el único
  -- vínculo: sin id no se puede cruzar con la ficha del cliente ni saber si dos
  -- expedientes son de la misma persona. De los 548 de producción, 536 resuelven
  -- a un cliente único por nombre y empresa. Diez nombres no existen en `clientes`
  -- y 2 comparten nombre, así que ésos se quedan sin vincular a propósito:
  -- adivinar cuál de los dos es sería peor que dejarlo en blanco.
  cliente TEXT,
  cliente_id TEXT,
  fecha TEXT,
  cuota TEXT,
  precio REAL,
  tipo TEXT,
  perfil TEXT,
  estado TEXT,
  fecha_baja TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS cliente_gestoria (
  id TEXT PRIMARY KEY,
  cliente_id TEXT UNIQUE,
  tipo_cliente TEXT,
  mod_fiscal INTEGER,
  mod_laboral INTEGER,
  mod_contable INTEGER,
  mod_renta INTEGER,
  mod_registro INTEGER,
  mod_trafico INTEGER,
  mod_puntuales INTEGER,
  renta_detalles TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS cliente_relaciones (
  id TEXT PRIMARY KEY,
  cliente_id TEXT NOT NULL,
  related_cliente_id TEXT NOT NULL,
  vinculo TEXT,
  notas TEXT,
  usar_en_renta INTEGER DEFAULT 0,
  usar_en_seguros INTEGER DEFAULT 0,
  usar_en_inmobiliaria INTEGER DEFAULT 0,
  declaracion_conjunta INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id),
  FOREIGN KEY (related_cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS gestoria_modelos (
  id TEXT PRIMARY KEY,
  cliente_id TEXT,
  modelo TEXT,
  periodicidad TEXT,
  proxima_fecha TEXT,
  responsable TEXT,
  estado TEXT,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS gestoria_trabajos (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  cliente_id TEXT,
  tipo_trabajo TEXT,
  tipo_categoria TEXT,
  estado TEXT,
  fecha_inicio TEXT,
  fecha_fin TEXT,
  sla_dias INTEGER,
  responsable TEXT,
  importe REAL,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS gestoria_trabajo_tipos (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  tipo_key TEXT NOT NULL,
  nombre TEXT NOT NULL,
  categoria TEXT,
  activo INTEGER NOT NULL DEFAULT 1,
  orden INTEGER,
  color TEXT,
  sla_dias INTEGER,
  iva_pct REAL,
  precio_base REAL,
  plantilla_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_gestoria_trabajo_tipos_empresa_key
  ON gestoria_trabajo_tipos (empresa_id, tipo_key);

CREATE TABLE IF NOT EXISTS gestoria_docs (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  cliente_id TEXT,
  referencia_tipo TEXT,
  referencia_id TEXT,
  nombre TEXT,
  tipo TEXT,
  fecha TEXT,
  estado TEXT,
  notas TEXT,
  doc_key TEXT,
  doc_url TEXT,
  calidad_ocr TEXT,
  campos_ocr TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS gestoria_contabilidad (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  cliente_id TEXT,
  hipoteca_id TEXT,
  seguro_id TEXT,
  poliza_numero TEXT,
  fecha TEXT,
  concepto TEXT,
  gestion TEXT,
  tipo TEXT,
  importe REAL,
  notas TEXT,
  cliente_ids_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

-- Índices para acelerar filtros por año/fecha (muy usado en dashboard y /api/years).
CREATE INDEX IF NOT EXISTS idx_gestoria_contabilidad_fecha ON gestoria_contabilidad (fecha);
CREATE INDEX IF NOT EXISTS idx_gestoria_contabilidad_year ON gestoria_contabilidad (substr(fecha, 1, 4));

CREATE TABLE IF NOT EXISTS hipotecas_contabilidad_excluidas (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  hipoteca_id TEXT NOT NULL,
  fecha TEXT NOT NULL,
  gestion TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (empresa_id, hipoteca_id, fecha, gestion)
);

CREATE TABLE IF NOT EXISTS gestoria_conta_config (
  id TEXT PRIMARY KEY,
  cliente_id TEXT UNIQUE,
  periodo TEXT,
  fecha_inicio TEXT,
  responsable TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS gestoria_conta_tasks (
  id TEXT PRIMARY KEY,
  cliente_id TEXT,
  periodo TEXT,
  tarea TEXT,
  estado TEXT,
  fecha_limite TEXT,
  responsable TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS gestoria_terceros (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  nif TEXT,
  nombre TEXT,
  tipo TEXT,
  cuenta_contable TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS gestoria_facturas (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  cliente_id TEXT,
  tercero_id TEXT,
  tipo TEXT,
  numero TEXT,
  fecha_emision TEXT,
  descripcion TEXT,
  base_imponible REAL,
  cuota_iva REAL,
  cuota_irpf REAL,
  total REAL,
  iva_pct REAL,
  estado_ocr TEXT,
  doc_key TEXT,
  raw_text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id),
  FOREIGN KEY (tercero_id) REFERENCES gestoria_terceros(id)
);

CREATE TABLE IF NOT EXISTS gestoria_asientos (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  cliente_id TEXT,
  factura_id TEXT,
  fecha TEXT,
  concepto TEXT,
  diario TEXT,
  referencia TEXT,
  total_debe REAL,
  total_haber REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id),
  FOREIGN KEY (factura_id) REFERENCES gestoria_facturas(id)
);

CREATE TABLE IF NOT EXISTS gestoria_asiento_lineas (
  id TEXT PRIMARY KEY,
  asiento_id TEXT,
  tercero_id TEXT,
  cuenta TEXT,
  descripcion TEXT,
  debe REAL,
  haber REAL,
  impuesto_tipo TEXT,
  impuesto_pct REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (asiento_id) REFERENCES gestoria_asientos(id),
  FOREIGN KEY (tercero_id) REFERENCES gestoria_terceros(id)
);

CREATE TABLE IF NOT EXISTS gestoria_import_lotes (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  cliente_id TEXT,
  origen TEXT,
  estado TEXT NOT NULL,
  periodo TEXT,
  carpeta_origen TEXT,
  template_path TEXT,
  total_documentos INTEGER NOT NULL DEFAULT 0,
  total_ok INTEGER NOT NULL DEFAULT 0,
  total_revisar INTEGER NOT NULL DEFAULT 0,
  total_duplicado INTEGER NOT NULL DEFAULT 0,
  total_error INTEGER NOT NULL DEFAULT 0,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS gestoria_import_documentos (
  id TEXT PRIMARY KEY,
  lote_id TEXT NOT NULL,
  empresa_id TEXT NOT NULL,
  cliente_id TEXT,
  factura_id TEXT,
  tercero_id TEXT,
  gestoria_doc_id TEXT,
  archivo_nombre TEXT NOT NULL,
  archivo_hash TEXT,
  doc_key TEXT,
  numero_detectado TEXT,
  fecha_detectada TEXT,
  tercero_detectado TEXT,
  nif_detectado TEXT,
  base_detectada REAL,
  cuota_iva_detectada REAL,
  total_detectado REAL,
  tipo_detectado TEXT,
  categoria_detectada TEXT,
  subcategoria_detectada TEXT,
  cuenta_sugerida TEXT,
  cuenta_tercero_sugerida TEXT,
  confianza_categoria REAL,
  confianza_extraccion REAL,
  estado_revision TEXT NOT NULL,
  motivos_revision TEXT,
  regla_aplicada TEXT,
  ocr_metodo TEXT,
  ocr_error TEXT,
  raw_text TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (lote_id) REFERENCES gestoria_import_lotes(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id),
  FOREIGN KEY (factura_id) REFERENCES gestoria_facturas(id),
  FOREIGN KEY (tercero_id) REFERENCES gestoria_terceros(id),
  FOREIGN KEY (gestoria_doc_id) REFERENCES gestoria_docs(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_gestoria_import_documentos_lote_archivo
ON gestoria_import_documentos (lote_id, archivo_nombre);

CREATE INDEX IF NOT EXISTS idx_gestoria_import_documentos_estado
ON gestoria_import_documentos (estado_revision);

CREATE INDEX IF NOT EXISTS idx_gestoria_import_documentos_hash
ON gestoria_import_documentos (archivo_hash);

CREATE TABLE IF NOT EXISTS gestoria_import_reglas (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  cliente_id TEXT,
  ambito TEXT NOT NULL,
  prioridad INTEGER NOT NULL DEFAULT 100,
  activo INTEGER NOT NULL DEFAULT 1,
  proveedor_match TEXT,
  proveedor_nif_match TEXT,
  texto_match TEXT,
  categoria_forzada TEXT,
  tercero_nombre_forzado TEXT,
  tercero_nif_forzado TEXT,
  cuenta_gasto_forzada TEXT,
  cuenta_tercero_forzada TEXT,
  iva_pct_forzado REAL,
  auto_ok INTEGER NOT NULL DEFAULT 0,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE INDEX IF NOT EXISTS idx_gestoria_import_reglas_scope
ON gestoria_import_reglas (empresa_id, cliente_id, activo, prioridad);

CREATE TABLE IF NOT EXISTS gestoria_import_eventos (
  id TEXT PRIMARY KEY,
  lote_id TEXT NOT NULL,
  documento_id TEXT,
  factura_id TEXT,
  tipo TEXT NOT NULL,
  detalle TEXT,
  payload_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (lote_id) REFERENCES gestoria_import_lotes(id),
  FOREIGN KEY (documento_id) REFERENCES gestoria_import_documentos(id),
  FOREIGN KEY (factura_id) REFERENCES gestoria_facturas(id)
);

CREATE INDEX IF NOT EXISTS idx_gestoria_import_eventos_lote
ON gestoria_import_eventos (lote_id, created_at);

CREATE TABLE IF NOT EXISTS cnae_catalogo (
  codigo TEXT PRIMARY KEY,
  descripcion TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS iae_catalogo (
  codigo TEXT PRIMARY KEY,
  descripcion TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auditoria (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  entidad TEXT,
  entidad_id TEXT,
  accion TEXT,
  usuario TEXT,
  detalles TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

-- Eventos de etapa (para métricas de embudo y conversión a lo largo del tiempo).
-- Nota: se alimenta desde el backend cuando se crea/actualiza una captación o se mueve de etapa.
CREATE TABLE IF NOT EXISTS crm_stage_events (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  captacion_id TEXT,
  inmueble_id TEXT,
  from_etapa TEXT,
  to_etapa TEXT NOT NULL,
  usuario TEXT,
  responsable TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE INDEX IF NOT EXISTS idx_crm_stage_events_empresa_created
ON crm_stage_events (empresa_id, created_at);

CREATE INDEX IF NOT EXISTS idx_crm_stage_events_empresa_responsable_created
ON crm_stage_events (empresa_id, responsable, created_at);

CREATE INDEX IF NOT EXISTS idx_crm_stage_events_empresa_to_etapa_created
ON crm_stage_events (empresa_id, to_etapa, created_at);

CREATE TABLE IF NOT EXISTS captaciones (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  inmueble_id TEXT,
  propietario TEXT,
  propietario_telefono TEXT,
  propietario_email TEXT,
  focalizacion TEXT,
  tipo_inmueble TEXT,
  subtipologia TEXT,
  direccion TEXT,
  direccion_numero TEXT,
  planta TEXT,
  puerta TEXT,
  interior TEXT,
  escalera TEXT,
  edificio TEXT,
  zona TEXT,
  localidad TEXT,
  m2 REAL,
  anio_construccion INTEGER,
  habitaciones INTEGER,
  banos INTEGER,
  precio_objetivo REAL,
  precio_encargo REAL,
  precio_valoracion REAL,
  precio_pedido_cliente REAL,
  fecha_valoracion TEXT,
  desviacion_pct REAL,
  urgencia TEXT,
  motivo TEXT,
  motivacion TEXT,
  necesidad_venta_alquiler TEXT,
  canal TEXT,
  tipo_procedencia TEXT,
  etapa TEXT,
  situacion_comercial TEXT,
  situacion_ocupacion TEXT,
  ocupado_por TEXT,
  noticia_verificada INTEGER NOT NULL DEFAULT 0,
  fecha_conversion TEXT,
  probabilidad REAL,
  proxima_accion TEXT,
  fecha_contacto TEXT,
  modalidad_ultimo_contacto TEXT,
  estado_contacto TEXT,
  no_molestar INTEGER NOT NULL DEFAULT 0,
  planificado INTEGER NOT NULL DEFAULT 0,
  fecha_planificacion TEXT,
  planificacion_encargo TEXT,
  fecha_ultima_renov_rebaja TEXT,
  prioridad_noticia TEXT,
  encargo_competencia INTEGER NOT NULL DEFAULT 0,
  asesor TEXT,
  responsable TEXT,
  codigo_postal TEXT,
  poblacion TEXT,
  provincia TEXT,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (inmueble_id) REFERENCES inmuebles(id)
);

CREATE TABLE IF NOT EXISTS inmuebles (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  referencia TEXT,
  titulo TEXT,
  tipo_operacion TEXT,
  direccion TEXT,
  direccion_numero TEXT,
  planta TEXT,
  puerta TEXT,
  interior TEXT,
  escalera TEXT,
  edificio TEXT,
  referencia_catastral TEXT,
  codigo_postal TEXT,
  localidad TEXT,
  poblacion TEXT,
  provincia TEXT,
  zona TEXT,
  focalizacion TEXT,
  tipo_inmueble TEXT,
  subtipologia TEXT,
  m2 REAL,
  anio_construccion INTEGER,
  anio_reforma INTEGER,
  habitaciones INTEGER,
  banos INTEGER,
  precio_objetivo REAL,
  precio_encargo REAL,
  precio_valoracion REAL,
  precio_pedido_cliente REAL,
  fecha_valoracion TEXT,
  desviacion_pct REAL,
  valor_referencia REAL,
  honorarios REAL,
  asesor TEXT,
  responsable TEXT,
  categoria TEXT,
  descripcion TEXT,
  situacion_ocupacion TEXT,
  ocupado_por TEXT,
  propietario_telefono TEXT,
  propietario_email TEXT,
  informador_id TEXT,
  informador_nombre TEXT,
  estado_inmueble TEXT,
  potencial_adquisicion TEXT,
  propietario_localizado INTEGER NOT NULL DEFAULT 0,
  fecha_primer_contacto TEXT,
  ultima_fecha_contacto TEXT,
  modalidad_ultimo_contacto TEXT,
  estado_contacto TEXT,
  no_molestar INTEGER NOT NULL DEFAULT 0,
  planificado INTEGER NOT NULL DEFAULT 0,
  fecha_planificacion TEXT,
  planificacion_encargo TEXT,
  fecha_ultima_renov_rebaja TEXT,
  con_inquilino INTEGER NOT NULL DEFAULT 0,
  estado TEXT,
  lat REAL,
  lon REAL,
  valoracion_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS inmueble_propietarios (
  id TEXT PRIMARY KEY,
  inmueble_id TEXT NOT NULL,
  cliente_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (inmueble_id) REFERENCES inmuebles(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS inmueble_servicios (
  id TEXT PRIMARY KEY,
  inmueble_id TEXT NOT NULL,
  servicio TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(inmueble_id, servicio),
  FOREIGN KEY (inmueble_id) REFERENCES inmuebles(id)
);

CREATE INDEX IF NOT EXISTS idx_inmueble_servicios_inmueble ON inmueble_servicios(inmueble_id);

CREATE TABLE IF NOT EXISTS inmueble_docs (
  id TEXT PRIMARY KEY,
  inmueble_id TEXT NOT NULL,
  nombre TEXT,
  url TEXT,
  tipo TEXT,
  estado TEXT NOT NULL DEFAULT 'Vigente',
  version INTEGER NOT NULL DEFAULT 1,
  plantilla_clave TEXT,
  origen_tipo TEXT,
  origen_id TEXT,
  payload_json TEXT,
  reviewed_at TEXT,
  reviewed_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (inmueble_id) REFERENCES inmuebles(id)
);

-- Histórico de cierres (evita borrar y permite recuperar).
CREATE TABLE IF NOT EXISTS inmueble_cierres (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  inmueble_id TEXT NOT NULL,
  tipo TEXT NOT NULL, -- Vendido | Alquiler | Cerrado negativamente
  fecha_cierre TEXT,
  importe_final REAL,
  honorarios REAL,
  numero_citas INTEGER,
  motivo_cierre TEXT,
  nuevo_propietario_id TEXT,
  nuevo_propietario_nombre TEXT,
  nuevo_propietario_nif TEXT,
  nuevo_propietario_telefono TEXT,
  nuevo_propietario_email TEXT,
  operacion_id TEXT,
  notas TEXT,
  usuario TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (inmueble_id) REFERENCES inmuebles(id)
);

CREATE INDEX IF NOT EXISTS idx_inmueble_cierres_inmueble
ON inmueble_cierres (inmueble_id, created_at);

CREATE TABLE IF NOT EXISTS operaciones_inmobiliarias (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  tipo_operacion TEXT NOT NULL,
  estado TEXT,
  origen TEXT,
  origen_inmueble TEXT,
  expediente_path TEXT,
  expediente_hash TEXT UNIQUE,
  anio INTEGER,
  mes TEXT,
  inmueble_id TEXT,
  direccion TEXT,
  referencia_catastral TEXT,
  propietario1_id TEXT,
  propietario1_nombre TEXT,
  propietario1_nif TEXT,
  propietario1_telefono TEXT,
  propietario1_email TEXT,
  propietario1_fecha_nacimiento TEXT,
  propietario2_id TEXT,
  propietario2_nombre TEXT,
  propietario2_nif TEXT,
  propietario2_telefono TEXT,
  propietario2_email TEXT,
  propietario2_fecha_nacimiento TEXT,
  contraparte1_id TEXT,
  contraparte2_id TEXT,
  contraparte_nombre TEXT,
  contraparte_nif TEXT,
  contraparte_telefono TEXT,
  contraparte_email TEXT,
  contraparte_fecha_nacimiento TEXT,
  fecha_encargo TEXT,
  fecha_propuesta TEXT,
  fecha_contrato TEXT,
  fecha_escritura TEXT,
  fecha_operacion TEXT,
  precio_encargo REAL,
  precio_propuesta REAL,
  precio_contrato REAL,
  precio_escritura REAL,
  precio_renta REAL,
  desviacion_euros REAL,
  desviacion_pct REAL,
  dias_hasta_venta INTEGER,
  num_visitas INTEGER,
  honorarios REAL,
  agente TEXT,
  responsable_gestion TEXT,
  oficina TEXT,
  doc_nota_encargo_path TEXT,
  doc_propuesta_path TEXT,
  doc_escritura_path TEXT,
  doc_nota_simple_path TEXT,
  doc_partes_visita_paths TEXT,
  estado_documental TEXT,
  calidad_ocr TEXT,
  notas TEXT,
  datos_extraidos_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (inmueble_id) REFERENCES inmuebles(id),
  FOREIGN KEY (propietario1_id) REFERENCES clientes(id),
  FOREIGN KEY (propietario2_id) REFERENCES clientes(id),
  FOREIGN KEY (contraparte1_id) REFERENCES clientes(id),
  FOREIGN KEY (contraparte2_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS inmueble_checklist (
  id TEXT PRIMARY KEY,
  inmueble_id TEXT NOT NULL,
  etapa TEXT,
  tarea TEXT,
  estado TEXT,
  responsable TEXT,
  fecha_limite TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (inmueble_id) REFERENCES inmuebles(id)
);

CREATE TABLE IF NOT EXISTS seguros_ofertas (
  id TEXT PRIMARY KEY,
  cliente_id TEXT,
  ramo TEXT,
  compania TEXT,
  propuesta TEXT,
  estado TEXT,
  motivo TEXT,
  fecha TEXT,
  responsable TEXT,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS seguros_preferencias (
  id TEXT PRIMARY KEY,
  cliente_id TEXT UNIQUE,
  prioridad_precio INTEGER DEFAULT 0,
  prioridad_compania INTEGER DEFAULT 0,
  prioridad_coberturas INTEGER DEFAULT 0,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS seguros_referidos (
  id TEXT PRIMARY KEY,
  cliente_id TEXT,
  referido_por TEXT,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS seguros_campanas (
  id TEXT PRIMARY KEY,
  compania TEXT,
  nombre TEXT,
  ramo TEXT,
  origen TEXT,
  fecha_inicio TEXT,
  fecha_fin TEXT,
  descripcion TEXT,
  url TEXT,
  adjunto_url TEXT,
  adjunto_nombre TEXT,
  precio_base REAL,
  comision_pct REAL,
  comision_fija REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seguros_campanas_mail_seen (
  id TEXT PRIMARY KEY,
  message_id TEXT UNIQUE,
  mailbox_uid TEXT,
  remitente TEXT,
  asunto TEXT,
  fecha_mail TEXT,
  campaign_id TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seguros_comisiones (
  id TEXT PRIMARY KEY,
  compania TEXT,
  ramo TEXT,
  porcentaje REAL,
  vigencia_desde TEXT,
  vigencia_hasta TEXT,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seguros_checklist (
  id TEXT PRIMARY KEY,
  poliza_id TEXT NOT NULL,
  tarea TEXT,
  estado TEXT,
  responsable TEXT,
  fecha_limite TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (poliza_id) REFERENCES seguros(id)
);

CREATE TABLE IF NOT EXISTS seguros_renovaciones (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  poliza_id TEXT,
  poliza_key TEXT NOT NULL,
  fecha_vencimiento TEXT NOT NULL,
  estado TEXT NOT NULL DEFAULT 'pendiente',
  responsable TEXT,
  proxima_accion_fecha TEXT,
  ultimo_contacto_fecha TEXT,
  notas TEXT,
  motivo_perdida TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (empresa_id, poliza_key, fecha_vencimiento),
  FOREIGN KEY (poliza_id) REFERENCES seguros(id)
);

CREATE TABLE IF NOT EXISTS seguros_eventos (
  id TEXT PRIMARY KEY,
  seguro_id TEXT,
  cliente_id TEXT,
  empresa_id TEXT,
  tipo TEXT,
  fecha TEXT,
  motivo TEXT,
  payload_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seguros_reclamaciones (
  id TEXT PRIMARY KEY,
  seguro_id TEXT,
  cliente_id TEXT,
  empresa_id TEXT,
  estado TEXT,
  canal TEXT,
  fecha_apertura TEXT,
  fecha_cierre TEXT,
  asunto TEXT,
  detalle TEXT,
  resolucion TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seguros_ipid_log (
  id TEXT PRIMARY KEY,
  seguro_id TEXT,
  cliente_id TEXT,
  empresa_id TEXT,
  documento_key TEXT,
  documento_url TEXT,
  fecha_entrega TEXT,
  metodo TEXT,
  usuario TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seguros_idd_asesoramiento (
  id TEXT PRIMARY KEY,
  seguro_id TEXT NOT NULL,
  cliente_id TEXT,
  empresa_id TEXT,
  fecha_asesoramiento TEXT,
  canal TEXT,
  necesidades TEXT,
  recomendacion TEXT,
  justificacion TEXT,
  comparacion_json TEXT,
  documentos_json TEXT,
  created_by TEXT,
  updated_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (seguro_id)
);

CREATE INDEX IF NOT EXISTS idx_seguros_idd_empresa_updated
ON seguros_idd_asesoramiento (empresa_id, updated_at);

CREATE INDEX IF NOT EXISTS idx_seguros_idd_cliente_updated
ON seguros_idd_asesoramiento (cliente_id, updated_at);

CREATE TABLE IF NOT EXISTS seguros_consentimientos (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  cliente_id TEXT,
  consent_json TEXT NOT NULL,
  metodo TEXT,
  created_by TEXT,
  updated_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (empresa_id, cliente_id)
);

CREATE INDEX IF NOT EXISTS idx_seguros_consent_empresa_updated
ON seguros_consentimientos (empresa_id, updated_at);

CREATE INDEX IF NOT EXISTS idx_seguros_consent_cliente_updated
ON seguros_consentimientos (cliente_id, updated_at);

CREATE TABLE IF NOT EXISTS fin_checklist (
  id TEXT PRIMARY KEY,
  asesoramiento_id TEXT NOT NULL,
  tarea TEXT,
  estado TEXT,
  responsable TEXT,
  fecha_limite TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (asesoramiento_id) REFERENCES asesoramientos_financiacion(id)
);

CREATE TABLE IF NOT EXISTS demandas (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  cliente_id TEXT,
  focalizacion TEXT,
  pedido TEXT,
  tipo TEXT,
  zona TEXT,
  tipologia TEXT,
  subtipologia TEXT,
  precio_max REAL,
  m2_min REAL,
  habitaciones_min INTEGER,
  banos_min INTEGER,
  estado TEXT,
  fase TEXT,
  prioridad TEXT,
  motivo TEXT,
  agencia_insercion TEXT,
  origen TEXT,
  pedido_web INTEGER NOT NULL DEFAULT 0,
  anuncio_mi_cartera INTEGER NOT NULL DEFAULT 0,
  presentacion_servicio INTEGER NOT NULL DEFAULT 0,
  fecha_insercion TEXT,
  motivo_ultimo_contacto TEXT,
  fecha_ultimo_contacto_interno TEXT,
  fecha_prox_act_cita TEXT,
  fecha_ultima_cita_venta_red TEXT,
  estado_contacto TEXT,
  responsable TEXT,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS visitas (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  inmueble_id TEXT,
  demanda_id TEXT,
  fecha TEXT,
  hora TEXT,
  estado TEXT,
  asesor TEXT,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (inmueble_id) REFERENCES inmuebles(id),
  FOREIGN KEY (demanda_id) REFERENCES demandas(id)
);

CREATE TABLE IF NOT EXISTS acciones (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  servicio TEXT NOT NULL,
  cliente_id TEXT,
  inmueble_id TEXT,
  asesoramiento_id TEXT,
  cliente_nombre TEXT,
  fecha TEXT,
  hora TEXT,
  hora_fin TEXT,
  asunto TEXT,
  tipo TEXT,
  modalidad_contacto TEXT,
  responsable TEXT,
  estado TEXT,
  resultado_cierre TEXT,
  estado_siguiente TEXT,
  documento_tipo TEXT,
  importe_propuesta REAL,
  notas TEXT,
  recordatorio_min INTEGER,
  related_id TEXT,
  related_tipo TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id),
  FOREIGN KEY (inmueble_id) REFERENCES inmuebles(id)
);

CREATE TABLE IF NOT EXISTS inmueble_compradores (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  inmueble_id TEXT NOT NULL,
  demanda_id TEXT,
  cliente_id TEXT,
  estado TEXT NOT NULL DEFAULT 'Pendiente',
  fecha_ultimo_contacto TEXT,
  fecha_proxima_accion TEXT,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (inmueble_id, demanda_id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (inmueble_id) REFERENCES inmuebles(id),
  FOREIGN KEY (demanda_id) REFERENCES demandas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE INDEX IF NOT EXISTS idx_inmueble_compradores_inmueble
ON inmueble_compradores (inmueble_id, updated_at);

CREATE INDEX IF NOT EXISTS idx_inmueble_compradores_cliente
ON inmueble_compradores (cliente_id, updated_at);

CREATE TABLE IF NOT EXISTS legal_radar_items (
  id TEXT PRIMARY KEY,
  area TEXT NOT NULL DEFAULT 'inmobiliaria',
  fuente TEXT,
  referencia TEXT,
  titulo TEXT NOT NULL,
  fecha_publicacion TEXT,
  estado TEXT NOT NULL DEFAULT 'Pendiente',
  impacto TEXT,
  topic_key TEXT,
  url TEXT,
  resumen TEXT,
  accion_recomendada TEXT,
  affected_documents TEXT,
  affected_workflows TEXT,
  affected_clauses TEXT,
  impact_score REAL,
  source_key TEXT,
  matched_keywords TEXT,
  auto_detected INTEGER NOT NULL DEFAULT 0,
  knowledge_synced_at TEXT,
  reviewed_at TEXT,
  reviewed_by TEXT,
  applied_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cliente_profesional (
  id TEXT PRIMARY KEY,
  cliente_id TEXT NOT NULL,
  cnae TEXT,
  iae TEXT,
  actividad TEXT,
  iban TEXT,
  principal INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS hipotecas (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  cliente TEXT,
  cliente_id TEXT,
  banco TEXT,
  precio REAL,
  importe_hipoteca REAL,
  porcentaje REAL,
  entrada REAL,
  comision REAL,
  oficina TEXT,
  fecha_encargo TEXT,
  encargo TEXT,
  tipo_hipoteca TEXT,
  fecha_firma TEXT,
  cesion REAL,
  comision_juan REAL,
  comision_modernia REAL,
  inmobiliaria_compra TEXT,
  asesor TEXT,
  estado TEXT,
  anio INTEGER,
  cliente_inmueble_json TEXT,
  hipoteca_detalle_json TEXT,
  liquidacion_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS asesoramientos_financiacion (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  origen TEXT,
  inmueble_id TEXT,
  accion_origen_id TEXT,
  inmobiliaria_asesor TEXT,
  asesor TEXT,
  fecha TEXT,
  estado TEXT,
  cliente1_id TEXT,
  cliente1_nombre TEXT,
  cliente1_dni TEXT,
  cliente1_telefono TEXT,
  cliente1_email TEXT,
  cliente1_fecha_nacimiento TEXT,
  cliente1_estado_civil TEXT,
  cliente1_regimen TEXT,
  cliente1_hijos TEXT,
  cliente1_profesion TEXT,
  cliente1_tipo_contrato TEXT,
  cliente1_tiempo_contrato TEXT,
  cliente1_ingresos REAL,
  cliente1_patrimonio TEXT,
  cliente1_prestamos TEXT,
  cliente1_prestamo_activo TEXT,
  cliente1_prestamo_entidad TEXT,
  cliente1_prestamo_resto REAL,
  cliente2_id TEXT,
  cliente2_nombre TEXT,
  cliente2_dni TEXT,
  cliente2_telefono TEXT,
  cliente2_email TEXT,
  cliente2_fecha_nacimiento TEXT,
  cliente2_estado_civil TEXT,
  cliente2_regimen TEXT,
  cliente2_hijos TEXT,
  cliente2_profesion TEXT,
  cliente2_tipo_contrato TEXT,
  cliente2_tiempo_contrato TEXT,
  cliente2_ingresos REAL,
  cliente2_patrimonio TEXT,
  cliente2_prestamos TEXT,
  cliente2_prestamo_activo TEXT,
  cliente2_prestamo_entidad TEXT,
  cliente2_prestamo_resto REAL,
  ingresos_conjuntos REAL,
  entidades_financieras TEXT,
  avalistas TEXT,
  aportacion_cv REAL,
  notas TEXT,
  notas_ocr TEXT,
  calidad_ocr TEXT,
  campos_ocr TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS alquileres (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  fecha TEXT,
  direccion TEXT,
  propietario TEXT,
  telefono TEXT,
  precio REAL,
  seguro TEXT,
  hacienda TEXT,
  comision TEXT,
  importe_comision REAL,
  total REAL,
  inquilino TEXT,
  telefono2 TEXT,
  agente TEXT,
  numero_alquileres REAL,
  tipo TEXT,
  oficina TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS inversores (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  nombre TEXT,
  aportacion REAL,
  fecha TEXT,
  proyecto TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS inversure_operaciones (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  proyecto TEXT,
  precio REAL,
  concepto TEXT,
  tipo TEXT,
  sujeto TEXT,
  fecha TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS usuarios (
  id TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  apellido TEXT,
  usuario TEXT UNIQUE,
  email TEXT UNIQUE,
  servicio TEXT,
  rol TEXT,
  registro_horario_activo INTEGER DEFAULT 0,
  password_hash TEXT,
  activo INTEGER DEFAULT 1,
  invite_token TEXT,
  invite_expires_at TEXT,
  invite_sent_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Cache persistente de geocodificación (reduce dependencias de terceros).
CREATE TABLE IF NOT EXISTS geocode_cache (
  cache_key TEXT PRIMARY KEY,
  query TEXT,
  municipio TEXT,
  provincia TEXT,
  codigo_postal TEXT,
  lat REAL,
  lon REAL,
  display_name TEXT,
  provider TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Simuladores fiscales (IIVTNU / plusvalía municipal) - parámetros por municipio y vigencia.
CREATE TABLE IF NOT EXISTS iivtnu_municipios (
  ine TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  provincia TEXT,
  comunidad TEXT,
  es_capital INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS iivtnu_param_sets (
  id TEXT PRIMARY KEY,
  municipio_ine TEXT NOT NULL,
  vigente_desde TEXT,
  vigente_hasta TEXT,
  tipo_gravamen_pct REAL,
  coeficientes_json TEXT,
  bonificaciones_json TEXT,
  source_url TEXT,
  source_label TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (municipio_ine) REFERENCES iivtnu_municipios(ine)
);

-- Seguros: recibos (cobros/impagos) y siniestros (seguimiento operativo).
CREATE TABLE IF NOT EXISTS seguros_recibos (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  seguro_id TEXT,
  cliente_id TEXT,
  referencia TEXT,
  poliza_numero TEXT,
  compania TEXT,
  ramo TEXT,
  fecha_emision TEXT,
  fecha_vencimiento TEXT,
  fecha_cobro TEXT,
  estado TEXT,
  prima_total REAL,
  comision REAL,
  comision_pct REAL,
  importe_liquidacion REAL,
  notas TEXT,
  doc_key TEXT,
  doc_url TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id),
  FOREIGN KEY (seguro_id) REFERENCES seguros(id)
);

CREATE TABLE IF NOT EXISTS seguros_siniestros (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  seguro_id TEXT,
  cliente_id TEXT,
  numero_expediente TEXT,
  compania TEXT,
  ramo TEXT,
  fecha_siniestro TEXT,
  fecha_apertura TEXT,
  fecha_cierre TEXT,
  estado TEXT,
  tipo TEXT,
  descripcion TEXT,
  importe_reserva REAL,
  importe_pagado REAL,
  gestor TEXT,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id),
  FOREIGN KEY (seguro_id) REFERENCES seguros(id)
);

-- Índices mínimos para rendimiento (CREATE INDEX IF NOT EXISTS es idempotente).
CREATE INDEX IF NOT EXISTS idx_clientes_empresa_id ON clientes(empresa_id);
CREATE INDEX IF NOT EXISTS idx_clientes_nif ON clientes(nif);
CREATE INDEX IF NOT EXISTS idx_clientes_nombre ON clientes(nombre);

CREATE INDEX IF NOT EXISTS idx_captaciones_empresa_etapa ON captaciones(empresa_id, etapa);
CREATE INDEX IF NOT EXISTS idx_captaciones_inmueble_id ON captaciones(inmueble_id);

CREATE INDEX IF NOT EXISTS idx_inmuebles_empresa_estado ON inmuebles(empresa_id, estado);
CREATE INDEX IF NOT EXISTS idx_inmuebles_empresa_refcat ON inmuebles(empresa_id, referencia_catastral);
CREATE INDEX IF NOT EXISTS idx_inmuebles_empresa_direccion ON inmuebles(empresa_id, direccion);

CREATE INDEX IF NOT EXISTS idx_inmueble_docs_inmueble_tipo ON inmueble_docs(inmueble_id, tipo);
CREATE INDEX IF NOT EXISTS idx_inmueble_propietarios_inmueble ON inmueble_propietarios(inmueble_id);

CREATE INDEX IF NOT EXISTS idx_demandas_empresa_estado ON demandas(empresa_id, estado);

CREATE INDEX IF NOT EXISTS idx_visitas_empresa_fecha ON visitas(empresa_id, fecha);
CREATE INDEX IF NOT EXISTS idx_visitas_inmueble_id ON visitas(inmueble_id);
CREATE INDEX IF NOT EXISTS idx_visitas_demanda_id ON visitas(demanda_id);

CREATE INDEX IF NOT EXISTS idx_acciones_empresa_servicio_fecha ON acciones(empresa_id, servicio, fecha);
CREATE INDEX IF NOT EXISTS idx_acciones_inmueble_id ON acciones(inmueble_id);
CREATE INDEX IF NOT EXISTS idx_acciones_cliente_id ON acciones(cliente_id);

CREATE INDEX IF NOT EXISTS idx_gestoria_docs_empresa_cliente ON gestoria_docs(empresa_id, cliente_id);
CREATE INDEX IF NOT EXISTS idx_geocode_cache_updated_at ON geocode_cache(updated_at);

CREATE INDEX IF NOT EXISTS idx_iivtnu_param_sets_municipio ON iivtnu_param_sets(municipio_ine);
CREATE INDEX IF NOT EXISTS idx_iivtnu_param_sets_vigencia ON iivtnu_param_sets(municipio_ine, vigente_desde, vigente_hasta);
