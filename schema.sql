PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS empresas (
  id TEXT PRIMARY KEY,
  nombre TEXT NOT NULL UNIQUE,
  activo INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clientes (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  nombre TEXT NOT NULL,
  tipo_persona TEXT,
  nif TEXT,
  telefono TEXT,
  email TEXT,
  fecha_nacimiento TEXT,
  direccion TEXT,
  codigo_postal TEXT,
  poblacion TEXT,
  provincia TEXT,
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
  produccion TEXT,
  colaborador TEXT,
  estado TEXT,
  estado_renovacion TEXT,
  renovacion_fecha TEXT,
  nueva_poliza_ref TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS gestoria (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  cliente TEXT,
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
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id)
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
  fecha TEXT,
  concepto TEXT,
  gestion TEXT,
  tipo TEXT,
  importe REAL,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (cliente_id) REFERENCES clientes(id),
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
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

CREATE TABLE IF NOT EXISTS captaciones (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  inmueble_id TEXT,
  propietario TEXT,
  tipo_inmueble TEXT,
  direccion TEXT,
  zona TEXT,
  m2 REAL,
  habitaciones INTEGER,
  banos INTEGER,
  precio_objetivo REAL,
  precio_valoracion REAL,
  urgencia TEXT,
  motivo TEXT,
  canal TEXT,
  etapa TEXT,
  probabilidad REAL,
  proxima_accion TEXT,
  fecha_contacto TEXT,
  asesor TEXT,
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
  direccion TEXT,
  zona TEXT,
  tipo_inmueble TEXT,
  m2 REAL,
  habitaciones INTEGER,
  banos INTEGER,
  precio_objetivo REAL,
  precio_valoracion REAL,
  valor_referencia REAL,
  estado TEXT,
  lat REAL,
  lon REAL,
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

CREATE TABLE IF NOT EXISTS inmueble_docs (
  id TEXT PRIMARY KEY,
  inmueble_id TEXT NOT NULL,
  nombre TEXT,
  url TEXT,
  tipo TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (inmueble_id) REFERENCES inmuebles(id)
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
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS demandas (
  id TEXT PRIMARY KEY,
  empresa_id TEXT NOT NULL,
  cliente_id TEXT,
  tipo TEXT,
  zona TEXT,
  precio_max REAL,
  m2_min REAL,
  habitaciones_min INTEGER,
  banos_min INTEGER,
  estado TEXT,
  prioridad TEXT,
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
  cliente_nombre TEXT,
  fecha TEXT,
  hora TEXT,
  tipo TEXT,
  responsable TEXT,
  estado TEXT,
  notas TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id),
  FOREIGN KEY (cliente_id) REFERENCES clientes(id),
  FOREIGN KEY (inmueble_id) REFERENCES inmuebles(id)
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
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (empresa_id) REFERENCES empresas(id)
);

CREATE TABLE IF NOT EXISTS asesoramientos_financiacion (
  id TEXT PRIMARY KEY,
  empresa_id TEXT,
  origen TEXT,
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
  cliente1_hijos TEXT,
  cliente1_profesion TEXT,
  cliente1_tipo_contrato TEXT,
  cliente1_ingresos REAL,
  cliente1_patrimonio TEXT,
  cliente1_prestamos TEXT,
  cliente2_id TEXT,
  cliente2_nombre TEXT,
  cliente2_dni TEXT,
  cliente2_telefono TEXT,
  cliente2_email TEXT,
  cliente2_fecha_nacimiento TEXT,
  cliente2_estado_civil TEXT,
  cliente2_hijos TEXT,
  cliente2_profesion TEXT,
  cliente2_tipo_contrato TEXT,
  cliente2_ingresos REAL,
  cliente2_patrimonio TEXT,
  cliente2_prestamos TEXT,
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
  apellido TEXT NOT NULL,
  usuario TEXT NOT NULL,
  email TEXT NOT NULL,
  servicio TEXT,
  rol TEXT,
  password_hash TEXT,
  activo INTEGER DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
