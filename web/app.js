const api = (path) => fetch(path).then((res) => res.json());

const randomId = () => {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
};

const setCrmMode = (mode = "") => {
  if (!document.body) return;
  document.body.classList.toggle("crm-seguros", mode === "seguros");
  document.body.classList.toggle("crm-fin", mode === "fin");
};

const uploadFileToS3 = async (file, prefix, statusEl) => {
  if (!file) return null;
  if (statusEl) statusEl.textContent = "Firmando subida...";
  const presign = await fetch("/api/s3_presign", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name || "archivo.pdf",
      content_type: file.type || "application/pdf",
      prefix: prefix || "seguros",
    }),
  }).then((res) => res.json());
  if (presign.error) {
    throw new Error(presign.error);
  }
  if (!presign.url) {
    throw new Error("Presign inválido.");
  }
  if (statusEl) statusEl.textContent = "Subiendo a la nube...";
  const putRes = await fetch(presign.url, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/pdf" },
    body: file,
  });
  if (!putRes.ok) {
    let message = `S3 error ${putRes.status}`;
    try {
      const text = await putRes.text();
      const msgMatch = text.match(/<Message>([^<]+)<\/Message>/i);
      if (msgMatch && msgMatch[1]) {
        message = msgMatch[1];
      }
    } catch {}
    throw new Error(message);
  }
  return presign;
};

const openS3File = async (key, fallbackUrl) => {
  if (key) {
    const data = await api(`/api/s3_url?key=${encodeURIComponent(key)}`);
    if (data && data.url) {
      window.open(data.url, "_blank", "noopener");
      return;
    }
  }
  if (fallbackUrl) {
    window.open(fallbackUrl, "_blank", "noopener");
  }
};

const getCurrentUser = () => {
  if (state.currentUser) {
    return state.currentUser;
  }
  const saved = localStorage.getItem("crm_current_user");
  if (saved) {
    state.currentUser = saved;
    return saved;
  }
  return "";
};

const setCurrentUser = (name) => {
  state.currentUser = name || "";
  if (state.currentUser) {
    localStorage.setItem("crm_current_user", state.currentUser);
  } else {
    localStorage.removeItem("crm_current_user");
  }
};

const state = {
  empresas: [],
  tablas: [],
  resumen: [],
  homeDashboard: null,
  homeYears: [],
  homeHipotecaStats: null,
  homeFincasStats: null,
  clientesStats: null,
  currentEmpresaId: "",
  currentEmpresaName: "",
  currentModule: "empresas",
  currentInmuebleId: "",
  currentInmueble: null,
  clientesList: [],
  demandasList: [],
  usersList: [],
  currentUser: "",
  currentClienteId: "",
  lastCreatedClientId: "",
  currentPage: "home",
  prevPage: "home",
  prevModule: "empresas",
  prevTab: "operativa",
  clientesShowAll: false,
  gestoriaCrmFull: false,
  gestoriaCrmTab: "all",
  gestoriaCrmView: "crm",
  segurosTab: "dashboard",
  segurosBdtCache: null,
  segurosOcrClienteId: "",
  segurosBdtOcrClienteId: "",
  segurosOcrQuality: null,
};

const empresaSelect = document.getElementById("empresaSelect");
const tablaSelect = document.getElementById("tablaSelect");
const searchInput = document.getElementById("searchInput");
const applyBtn = document.getElementById("applyBtn");
const resetBtn = document.getElementById("resetBtn");
const tableContainer = document.getElementById("tableContainer");
const tableInfo = document.getElementById("tableInfo");
const tableToolbar = document.getElementById("tableToolbar");
const bdtSection = document.getElementById("bdtSection");
const clientesColumnsBtn = document.getElementById("clientesColumnsBtn");
const clientesColumnsPanel = document.getElementById("clientesColumnsPanel");
const clientesColumnsList = document.getElementById("clientesColumnsList");
const clientesShowAllBtn = document.getElementById("clientesShowAllBtn");
const coreCards = document.getElementById("coreCards");
const userSelect = document.getElementById("userSelect");
const adminSection = document.getElementById("adminSection");
const adminBackBtn = document.getElementById("adminBackBtn");
const adminUserForm = document.getElementById("adminUserForm");
const adminUserStatus = document.getElementById("adminUserStatus");
const adminUsersTable = document.getElementById("adminUsersTable");
const adminUsersInfo = document.getElementById("adminUsersInfo");
const adminPasswordInput = document.getElementById("adminPasswordInput");
const adminPasswordToggle = document.getElementById("adminPasswordToggle");
const holdingSection = document.getElementById("holdingSection");
const holdingBackBtn = document.getElementById("holdingBackBtn");
const holdingOrgChart = document.getElementById("holdingOrgChart");
const agendaSection = document.getElementById("agendaSection");
const agendaBackBtn = document.getElementById("agendaBackBtn");
const agendaGeneral = document.getElementById("agendaGeneral");
const yearSelect = document.getElementById("yearSelect");
const dbStatus = document.getElementById("dbStatus");
const bdtYearFilter = document.getElementById("bdtYearFilter");
const bdtFieldFilter = document.getElementById("bdtFieldFilter");
const clientesEstadoFilter = document.getElementById("clientesEstadoFilter");
const explorerTitle = document.getElementById("explorerTitle");
const explorerSubtitle = document.getElementById("explorerSubtitle");
const homeSection = document.getElementById("homeSection");
const homeBtn = document.getElementById("homeBtn");
const brandHome = document.getElementById("brandHome");
const explorerSection = document.getElementById("explorerSection");
const dashboardSection = document.getElementById("dashboardSection");
const dashboardTitle = document.getElementById("dashboardTitle");
const dashboardKpis = document.getElementById("dashboardKpis");
const ventasChart = document.getElementById("ventasChart");
const facturadoChart = document.getElementById("facturadoChart");
const alquileresChart = document.getElementById("alquileresChart");
const ventasVarChart = document.getElementById("ventasVarChart");
const alquileresVarChart = document.getElementById("alquileresVarChart");
const facturadoVarChart = document.getElementById("facturadoVarChart");
const facturadoProgress = document.getElementById("facturadoProgress");
const viewTabs = document.getElementById("viewTabs");
const altaSection = document.getElementById("altaSection");
const bdtForm = document.getElementById("bdtForm");
const bdtFormStatus = document.getElementById("bdtFormStatus");
const fincasBdtForm = document.getElementById("fincasBdtForm");
const fincasBdtFormStatus = document.getElementById("fincasBdtFormStatus");
const estudioAltaTabs = document.getElementById("estudioAltaTabs");
const estudioAltaBdt = document.getElementById("estudioAltaBdt");
const estudioAltaCaptacion = document.getElementById("estudioAltaCaptacion");
const estudioAltaDemanda = document.getElementById("estudioAltaDemanda");
const captacionForm = document.getElementById("captacionForm");
const captacionFormStatus = document.getElementById("captacionFormStatus");
const demandaForm = document.getElementById("demandaForm");
const demandaFormStatus = document.getElementById("demandaFormStatus");
const demandaCliente = document.getElementById("demandaCliente");
const clientesAltaSection = document.getElementById("clientesAltaSection");
const clientesForm = document.getElementById("clientesForm");
const clientesFormStatus = document.getElementById("clientesFormStatus");
const clienteTipoPersona = document.getElementById("clienteTipoPersona");
const clienteAltaPersonaFields = clientesForm
  ? clientesForm.querySelectorAll('[data-cliente-persona="fisica"]')
  : [];
const clientesLinkForm = document.getElementById("clientesLinkForm");
const clientesLinkFormStatus = document.getElementById("clientesLinkFormStatus");
const clientesSelect = document.getElementById("clientesSelect");
const clientesEmpresaSelect = document.getElementById("clientesEmpresaSelect");
const clientesServicioSelect = document.getElementById("clientesServicioSelect");
const clientesLinkRows = document.getElementById("clientesLinkRows");
const clientesLinkAdd = document.getElementById("clientesLinkAdd");
const clientePage = document.getElementById("clientePage");
const clientesDetail = document.getElementById("clientesDetail");
const clienteDetailTitle = document.getElementById("clienteDetailTitle");
const clienteDetailSubtitle = document.getElementById("clienteDetailSubtitle");
const clienteDetailBack = document.getElementById("clienteDetailBack");
const clienteSaveBtn = document.getElementById("clienteSaveBtn");
const clienteSaveStatus = document.getElementById("clienteSaveStatus");
const clienteTabs = document.getElementById("clienteTabs");
const clienteTabDatos = document.getElementById("clienteTabDatos");
const clienteTabProfesional = document.getElementById("clienteTabProfesional");
const clienteTabSeguros = document.getElementById("clienteTabSeguros");
const clienteTabInmobiliaria = document.getElementById("clienteTabInmobiliaria");
const clienteTabHipotecas = document.getElementById("clienteTabHipotecas");
const clienteTabFacturas = document.getElementById("clienteTabFacturas");
const clienteTabTrabajos = document.getElementById("clienteTabTrabajos");
const clienteGestoriaForm = document.getElementById("clienteGestoriaForm");
const clienteGestoriaStatus = document.getElementById("clienteGestoriaStatus");
const gestoriaModeloForm = document.getElementById("gestoriaModeloForm");
const gestoriaModeloStatus = document.getElementById("gestoriaModeloStatus");
const clienteDetailGrid = document.getElementById("clienteDetailGrid");
const clienteEmpresasList = document.getElementById("clienteEmpresasList");
const clienteAssignForm = document.getElementById("clienteAssignForm");
const clienteAssignServicio = document.getElementById("clienteAssignServicio");
const clienteAssignEmpresa = document.getElementById("clienteAssignEmpresa");
const clienteAssignStatus = document.getElementById("clienteAssignStatus");
const clienteFacturas = document.getElementById("clienteFacturas");
const clienteTrabajos = document.getElementById("clienteTrabajos");
const clienteSegurosFicha = document.getElementById("clienteSegurosFicha");
const responsableSelects = document.querySelectorAll(".responsable-select");
const clienteProfesionalSection = document.getElementById("clienteProfesionalSection");
const clienteProfesionalList = document.getElementById("clienteProfesionalList");
const clienteProfesionalHint = document.getElementById("clienteProfesionalHint");
const clienteProfesionalCnaeForm = document.getElementById("clienteProfesionalCnaeForm");
const clienteProfesionalIaeForm = document.getElementById("clienteProfesionalIaeForm");
const clienteProfesionalActividadForm = document.getElementById("clienteProfesionalActividadForm");
const clienteProfesionalIbanForm = document.getElementById("clienteProfesionalIbanForm");
const clienteProfesionalStatus = document.getElementById("clienteProfesionalStatus");
const cnaeCatalogo = document.getElementById("cnaeCatalogo");
const iaeCatalogo = document.getElementById("iaeCatalogo");
const cnaeSuggest = document.getElementById("cnaeSuggest");
const iaeSuggest = document.getElementById("iaeSuggest");
const actividadSuggest = document.getElementById("actividadSuggest");
const captacionPropietarios = document.getElementById("captacionPropietarios");
const fincasSegurosForm = document.getElementById("fincasSegurosForm");
const fincasSegurosFormStatus = document.getElementById("fincasSegurosFormStatus");
const aieTab = document.getElementById("aieTab");
const operativaTab = document.querySelector('#viewTabs [data-tab="operativa"]');
const bdtTab = document.querySelector('#viewTabs [data-tab="bdt"]');
const altaTab = document.querySelector('#viewTabs [data-tab="alta"]');
const crmTab = document.getElementById("crmTab");
const fincasCrmTab = document.getElementById("fincasCrmTab");
const segurosCrmTab = document.getElementById("segurosCrmTab");
const finCrmTab = document.getElementById("finCrmTab");
const finSimTab = document.getElementById("finSimTab");
const gestoriaFactTab = document.getElementById("gestoriaFactTab");
const gestoriaContaTab = document.getElementById("gestoriaContaTab");
const gestoriaDashTab = document.getElementById("gestoriaDashTab");
const gestoriaAgendaTab = document.getElementById("gestoriaAgendaTab");
const crmSection = document.getElementById("crmSection");
const gestoriaCrmSection = document.getElementById("gestoriaCrmSection");
const gestoriaCrmViews = document.getElementById("gestoriaCrmViews");
const gestoriaCrmViewCrm = document.getElementById("gestoriaCrmViewCrm");
const gestoriaCrmViewBdt = document.getElementById("gestoriaCrmViewBdt");
const gestoriaCrmViewAlta = document.getElementById("gestoriaCrmViewAlta");
const gestoriaBdtTable = document.getElementById("gestoriaBdtTable");
const gestoriaBdtInfo = document.getElementById("gestoriaBdtInfo");
const gestoriaAltaForm = document.getElementById("gestoriaAltaForm");
const gestoriaAltaStatus = document.getElementById("gestoriaAltaStatus");
const gestoriaAltaTipoPersona = document.getElementById("gestoriaAltaTipoPersona");
const gestoriaAltaPersonaFields = gestoriaAltaForm
  ? gestoriaAltaForm.querySelectorAll('[data-gestoria-persona="fisica"]')
  : [];
const gestoriaDashboardSection = document.getElementById("gestoriaDashboardSection");
const gestoriaContaSection = document.getElementById("gestoriaContaSection");
const gestoriaAgendaSection = document.getElementById("gestoriaAgendaSection");
const segurosCrmSection = document.getElementById("segurosCrmSection");
const finCrmSection = document.getElementById("finCrmSection");
const finSimSection = document.getElementById("finSimSection");
const gestoriaFactSection = document.getElementById("gestoriaFactSection");
const gestoriaCrmSearch = document.getElementById("gestoriaCrmSearch");
const gestoriaCrmClientes = document.getElementById("gestoriaCrmClientes");
const gestoriaCrmTipo = document.getElementById("gestoriaCrmTipo");
const gestoriaCrmSubtipo = document.getElementById("gestoriaCrmSubtipo");
const gestoriaCrmEstado = document.getElementById("gestoriaCrmEstado");
const gestoriaCrmLimit = document.getElementById("gestoriaCrmLimit");
const gestoriaCrmApply = document.getElementById("gestoriaCrmApply");
const gestoriaCrmReset = document.getElementById("gestoriaCrmReset");
const gestoriaCrmTable = document.getElementById("gestoriaCrmTable");
const gestoriaCrmInfo = document.getElementById("gestoriaCrmInfo");
const gestoriaCrmForm = document.getElementById("gestoriaCrmForm");
const gestoriaCrmStatus = document.getElementById("gestoriaCrmStatus");
const gestoriaCrmCliente = document.getElementById("gestoriaCrmCliente");
const gestoriaCrmSummary = document.getElementById("gestoriaCrmSummary");
const gestoriaCrmToggleView = document.getElementById("gestoriaCrmToggleView");
const gestoriaCrmTabs = document.getElementById("gestoriaCrmTabs");
const gestoriaTrabajoForm = document.getElementById("gestoriaTrabajoForm");
const gestoriaTrabajoCliente = document.getElementById("gestoriaTrabajoCliente");
const gestoriaTrabajoStatus = document.getElementById("gestoriaTrabajoStatus");
const gestoriaTrabajosTable = document.getElementById("gestoriaTrabajosTable");
const gestoriaTrabajosInfo = document.getElementById("gestoriaTrabajosInfo");
const gestoriaModelosTable = document.getElementById("gestoriaModelosTable");
const gestoriaModelosInfo = document.getElementById("gestoriaModelosInfo");
const gestoriaModelosOverviewTable = document.getElementById("gestoriaModelosOverviewTable");
const gestoriaModelosOverviewInfo = document.getElementById("gestoriaModelosOverviewInfo");
const gestoriaTrabajosTipoFilter = document.getElementById("gestoriaTrabajosTipoFilter");
const gestoriaTrabajosEstadoFilter = document.getElementById("gestoriaTrabajosEstadoFilter");
const gestoriaTrabajosLimit = document.getElementById("gestoriaTrabajosLimit");
const gestoriaPipeline = document.getElementById("gestoriaPipeline");
const gestoriaPipelineServicio = document.getElementById("gestoriaPipelineServicio");
const gestoriaPipelineGroup = document.getElementById("gestoriaPipelineGroup");
const gestoriaDocsRecent = document.getElementById("gestoriaDocsRecent");
const gestoriaDocsRecentInfo = document.getElementById("gestoriaDocsRecentInfo");
const gestoriaDocsForm = document.getElementById("gestoriaDocsForm");
const gestoriaDocsCliente = document.getElementById("gestoriaDocsCliente");
const gestoriaDocsFile = document.getElementById("gestoriaDocsFile");
const gestoriaDocsStatus = document.getElementById("gestoriaDocsStatus");
const gestoriaClienteDocsForm = document.getElementById("gestoriaClienteDocsForm");
const gestoriaClienteDocsFile = document.getElementById("gestoriaClienteDocsFile");
const gestoriaClienteDocsStatus = document.getElementById("gestoriaClienteDocsStatus");
const gestoriaAuditTable = document.getElementById("gestoriaAuditTable");
const gestoriaAuditInfo = document.getElementById("gestoriaAuditInfo");
const gestoriaDocForm = document.getElementById("gestoriaDocForm");
const gestoriaDocStatus = document.getElementById("gestoriaDocStatus");
const gestoriaDocsTable = document.getElementById("gestoriaDocsTable");
const gestoriaClienteKpis = document.getElementById("gestoriaClienteKpis");
const gestoriaClienteKpiModelos = document.getElementById("gestoriaClienteKpiModelos");
const gestoriaClienteKpiVencen = document.getElementById("gestoriaClienteKpiVencen");
const gestoriaClienteKpiGestiones = document.getElementById("gestoriaClienteKpiGestiones");
const gestoriaClienteKpiDocs = document.getElementById("gestoriaClienteKpiDocs");
const gestoriaClienteAlerts = document.getElementById("gestoriaClienteAlerts");
const gestoriaModuleTabs = document.getElementById("gestoriaModuleTabs");
const gestoriaModuleContabilidad = document.getElementById("gestoriaModuleContabilidad");
const gestoriaModuleFiscal = document.getElementById("gestoriaModuleFiscal");
const gestoriaModuleLaboral = document.getElementById("gestoriaModuleLaboral");
const gestoriaModuleRenta = document.getElementById("gestoriaModuleRenta");
const gestoriaModuleAdmin = document.getElementById("gestoriaModuleAdmin");
const gestoriaFiscalTrabajosTable = document.getElementById("gestoriaFiscalTrabajosTable");
const gestoriaFiscalTrabajosInfo = document.getElementById("gestoriaFiscalTrabajosInfo");
const gestoriaLaboralForm = document.getElementById("gestoriaLaboralForm");
const gestoriaLaboralStatus = document.getElementById("gestoriaLaboralStatus");
const gestoriaLaboralTable = document.getElementById("gestoriaLaboralTable");
const gestoriaLaboralInfo = document.getElementById("gestoriaLaboralInfo");
const gestoriaRentaForm = document.getElementById("gestoriaRentaForm");
const gestoriaRentaStatus = document.getElementById("gestoriaRentaStatus");
const gestoriaRentaTable = document.getElementById("gestoriaRentaTable");
const gestoriaRentaInfo = document.getElementById("gestoriaRentaInfo");
const gestoriaRentaDetallesForm = document.getElementById("gestoriaRentaDetallesForm");
const gestoriaRentaDetallesStatus = document.getElementById("gestoriaRentaDetallesStatus");
const gestoriaAdminForm = document.getElementById("gestoriaAdminForm");
const gestoriaAdminStatus = document.getElementById("gestoriaAdminStatus");
const gestoriaAdminTable = document.getElementById("gestoriaAdminTable");
const gestoriaAdminInfo = document.getElementById("gestoriaAdminInfo");
const gestoriaClienteAgendaForm = document.getElementById("gestoriaClienteAgendaForm");
const gestoriaClienteAgendaStatus = document.getElementById("gestoriaClienteAgendaStatus");
const gestoriaClienteAgendaTable = document.getElementById("gestoriaClienteAgendaTable");
const gestoriaClienteAgendaInfo = document.getElementById("gestoriaClienteAgendaInfo");
const gestoriaKpiTotal = document.getElementById("gestoriaKpiTotal");
const gestoriaKpiActivos = document.getElementById("gestoriaKpiActivos");
const gestoriaKpiAutonomos = document.getElementById("gestoriaKpiAutonomos");
const gestoriaKpiEmpresas = document.getElementById("gestoriaKpiEmpresas");
const gestoriaKpiPuntuales = document.getElementById("gestoriaKpiPuntuales");
const gestoriaKpiModelosMes = document.getElementById("gestoriaKpiModelosMes");
const gestoriaKpiGestionesCurso = document.getElementById("gestoriaKpiGestionesCurso");
const gestoriaKpiGestionesEspera = document.getElementById("gestoriaKpiGestionesEspera");
const gestoriaKpiGestionesVencidas = document.getElementById("gestoriaKpiGestionesVencidas");
const gestoriaAlertModelos = document.getElementById("gestoriaAlertModelos");
const gestoriaAlertAcciones = document.getElementById("gestoriaAlertAcciones");
const gestoriaAlertModelosOverdue = document.getElementById("gestoriaAlertModelosOverdue");
const gestoriaAlertAccionesOverdue = document.getElementById("gestoriaAlertAccionesOverdue");
const gestoriaAlertGestiones = document.getElementById("gestoriaAlertGestiones");
const gestoriaAlertGestionesProximas = document.getElementById("gestoriaAlertGestionesProximas");
const gestoriaAlertDays = document.getElementById("gestoriaAlertDays");
const gestoriaResponsablesTable = document.getElementById("gestoriaResponsablesTable");
const gestoriaAgendaForm = document.getElementById("gestoriaAgendaForm");
const gestoriaAgendaStatus = document.getElementById("gestoriaAgendaStatus");
const gestoriaAgendaClienteInput = document.getElementById("gestoriaAgendaClienteInput");
const gestoriaAgendaClienteId = document.getElementById("gestoriaAgendaClienteId");
const gestoriaAgendaClientes = document.getElementById("gestoriaAgendaClientes");
const gestoriaAgendaTable = document.getElementById("gestoriaAgendaTable");
const gestoriaAgendaInfo = document.getElementById("gestoriaAgendaInfo");
const gestoriaContabilidadForm = document.getElementById("gestoriaContabilidadForm");
const gestoriaContabilidadStatus = document.getElementById("gestoriaContabilidadStatus");
const gestoriaContabilidadCliente = document.getElementById("gestoriaContabilidadCliente");
const gestoriaContabilidadTable = document.getElementById("gestoriaContabilidadTable");
const gestoriaContabilidadInfo = document.getElementById("gestoriaContabilidadInfo");
const gestoriaContaConfigForm = document.getElementById("gestoriaContaConfigForm");
const gestoriaContaConfigStatus = document.getElementById("gestoriaContaConfigStatus");
const gestoriaContaTasksBtn = document.getElementById("gestoriaContaTasksBtn");
const gestoriaContaTasksTable = document.getElementById("gestoriaContaTasksTable");
const gestoriaContaTasksInfo = document.getElementById("gestoriaContaTasksInfo");
const gestoriaContaSummaryDone = document.getElementById("gestoriaContaSummaryDone");
const gestoriaContaSummaryPending = document.getElementById("gestoriaContaSummaryPending");
const gestoriaContaSummaryNext = document.getElementById("gestoriaContaSummaryNext");
const gestoriaContaQueueBtn = document.getElementById("gestoriaContaQueueBtn");
const gestoriaContaQueueFilter = document.getElementById("gestoriaContaQueueFilter");
const gestoriaContaQueueTable = document.getElementById("gestoriaContaQueueTable");
const gestoriaContaQueueInfo = document.getElementById("gestoriaContaQueueInfo");
const segurosCrmSearch = document.getElementById("segurosCrmSearch");
const segurosCrmTable = document.getElementById("segurosCrmTable");
const segurosCrmInfo = document.getElementById("segurosCrmInfo");
const segurosCrmOportunidades = document.getElementById("segurosCrmOportunidades");
const segurosCrmClienteInput = document.getElementById("segurosCrmClienteInput");
const segurosCrmClienteId = document.getElementById("segurosCrmClienteId");
const segurosCrmClientes = document.getElementById("segurosCrmClientes");
const segurosCrmClienteOpen = document.getElementById("segurosCrmClienteOpen");
const segurosPreferenciasForm = document.getElementById("segurosPreferenciasForm");
const segurosPreferenciasStatus = document.getElementById("segurosPreferenciasStatus");
const segurosPreferenciasClienteInput = document.getElementById("segurosPreferenciasClienteInput");
const segurosPreferenciasClienteId = document.getElementById("segurosPreferenciasClienteId");
const segurosPreferenciasClientes = document.getElementById("segurosPreferenciasClientes");
const segurosOfertasForm = document.getElementById("segurosOfertasForm");
const segurosOfertasStatus = document.getElementById("segurosOfertasStatus");
const segurosOfertasClienteInput = document.getElementById("segurosOfertasClienteInput");
const segurosOfertasClienteId = document.getElementById("segurosOfertasClienteId");
const segurosOfertasClientes = document.getElementById("segurosOfertasClientes");
const segurosOfertasTable = document.getElementById("segurosOfertasTable");
const segurosOfertasInfo = document.getElementById("segurosOfertasInfo");
const segurosOfertasSearch = document.getElementById("segurosOfertasSearch");
const segurosReferidosForm = document.getElementById("segurosReferidosForm");
const segurosReferidosStatus = document.getElementById("segurosReferidosStatus");
const segurosReferidosClienteInput = document.getElementById("segurosReferidosClienteInput");
const segurosReferidosClienteId = document.getElementById("segurosReferidosClienteId");
const segurosReferidosClientes = document.getElementById("segurosReferidosClientes");
const segurosReferidosTable = document.getElementById("segurosReferidosTable");
const segurosReferidosInfo = document.getElementById("segurosReferidosInfo");
const segurosReferidosSearch = document.getElementById("segurosReferidosSearch");
const segurosCampanasForm = document.getElementById("segurosCampanasForm");
const segurosCampanasStatus = document.getElementById("segurosCampanasStatus");
const segurosCampanasTable = document.getElementById("segurosCampanasTable");
const segurosCampanasInfo = document.getElementById("segurosCampanasInfo");
const segurosCampanasSearch = document.getElementById("segurosCampanasSearch");
const segurosComisionesForm = document.getElementById("segurosComisionesForm");
const segurosComisionesStatus = document.getElementById("segurosComisionesStatus");
const segurosComisionesTable = document.getElementById("segurosComisionesTable");
const segurosComisionesInfo = document.getElementById("segurosComisionesInfo");
const segurosComisionesSearch = document.getElementById("segurosComisionesSearch");
const segurosInsights = document.getElementById("segurosInsights");
const segurosAlertasList = document.getElementById("segurosAlertasList");
const segurosChecklistPoliza = document.getElementById("segurosChecklistPoliza");
const segurosChecklistGenerate = document.getElementById("segurosChecklistGenerate");
const segurosChecklistTable = document.getElementById("segurosChecklistTable");
const segurosChecklistInfo = document.getElementById("segurosChecklistInfo");
const segurosAiPoliza = document.getElementById("segurosAiPoliza");
const segurosAiTask = document.getElementById("segurosAiTask");
const segurosAiExtra = document.getElementById("segurosAiExtra");
const segurosAiRun = document.getElementById("segurosAiRun");
const segurosAiStatus = document.getElementById("segurosAiStatus");
const segurosAiOutput = document.getElementById("segurosAiOutput");
const segurosKpis = document.getElementById("segurosKpis");
const segurosOcrQuality = document.getElementById("segurosOcrQuality");
const segurosUpdateSelect = document.getElementById("segurosUpdateSelect");
const segurosUpdateFile = document.getElementById("segurosUpdateFile");
const segurosUpdateButton = document.getElementById("segurosUpdateButton");
const segurosUpdateStatus = document.getElementById("segurosUpdateStatus");
const segurosOcrFile = document.getElementById("segurosOcrFile");
const segurosOcrButton = document.getElementById("segurosOcrButton");
const segurosOcrPreview = document.getElementById("segurosOcrPreview");
const segurosOcrStatus = document.getElementById("segurosOcrStatus");
const segurosOcrSave = document.getElementById("segurosOcrSave");
const segurosOcrSaveStatus = document.getElementById("segurosOcrSaveStatus");
const segurosOcrRaw = document.getElementById("segurosOcrRaw");
const seguroOcrEstado = document.getElementById("seguroOcrEstado");
const seguroOcrProduccion = document.getElementById("seguroOcrProduccion");
const seguroOcrRamo = document.getElementById("seguroOcrRamo");
const seguroOcrColaborador = document.getElementById("seguroOcrColaborador");
const seguroOcrTomador = document.getElementById("seguroOcrTomador");
const seguroOcrDni = document.getElementById("seguroOcrDni");
const seguroOcrTelefono = document.getElementById("seguroOcrTelefono");
const seguroOcrEmail = document.getElementById("seguroOcrEmail");
const seguroOcrCompania = document.getElementById("seguroOcrCompania");
const seguroOcrPoliza = document.getElementById("seguroOcrPoliza");
const seguroOcrDireccion = document.getElementById("seguroOcrDireccion");
const seguroOcrNacimiento = document.getElementById("seguroOcrNacimiento");
const seguroOcrFechaEfecto = document.getElementById("seguroOcrFechaEfecto");
const seguroOcrFechaVencimiento = document.getElementById("seguroOcrFechaVencimiento");
const seguroOcrPrimaNeta = document.getElementById("seguroOcrPrimaNeta");
const seguroOcrPrimaTotal = document.getElementById("seguroOcrPrimaTotal");
const segurosBdtOcrFile = document.getElementById("segurosBdtOcrFile");
const segurosBdtOcrButton = document.getElementById("segurosBdtOcrButton");
const segurosBdtOcrStatus = document.getElementById("segurosBdtOcrStatus");
const segurosBdtOcrTomador = document.getElementById("segurosBdtOcrTomador");
const segurosBdtOcrDni = document.getElementById("segurosBdtOcrDni");
const segurosBdtOcrCompania = document.getElementById("segurosBdtOcrCompania");
const segurosBdtOcrPoliza = document.getElementById("segurosBdtOcrPoliza");
const segurosBdtOcrRamo = document.getElementById("segurosBdtOcrRamo");
const segurosBdtOcrFechaEfecto = document.getElementById("segurosBdtOcrFechaEfecto");
const segurosBdtOcrFechaVencimiento = document.getElementById("segurosBdtOcrFechaVencimiento");
const segurosBdtOcrPrimaNeta = document.getElementById("segurosBdtOcrPrimaNeta");
const segurosBdtOcrPrimaTotal = document.getElementById("segurosBdtOcrPrimaTotal");
const segurosBdtOcrSelect = document.getElementById("segurosBdtOcrSelect");
const segurosBdtOcrMatchButton = document.getElementById("segurosBdtOcrMatchButton");
const segurosBdtOcrLink = document.getElementById("segurosBdtOcrLink");
const segurosAgendaForm = document.getElementById("segurosAgendaForm");
const segurosAgendaStatus = document.getElementById("segurosAgendaStatus");
const segurosAgendaClienteInput = document.getElementById("segurosAgendaClienteInput");
const segurosAgendaClienteId = document.getElementById("segurosAgendaClienteId");
const segurosAgendaClientes = document.getElementById("segurosAgendaClientes");
const segurosAgendaTable = document.getElementById("segurosAgendaTable");
const segurosAgendaInfo = document.getElementById("segurosAgendaInfo");
const finCrmSearch = document.getElementById("finCrmSearch");
const finCrmClienteInput = document.getElementById("finCrmClienteInput");
const finCrmClienteId = document.getElementById("finCrmClienteId");
const finCrmClientes = document.getElementById("finCrmClientes");
const finCrmClienteOpen = document.getElementById("finCrmClienteOpen");
const finAsesoramientosSearch = document.getElementById("finAsesoramientosSearch");
const finAsesorOcrButton = document.getElementById("finAsesorOcrButton");
const finAsesorOcrAutoButton = document.getElementById("finAsesorOcrAutoButton");
const finAsesorOcrPreview = document.getElementById("finAsesorOcrPreview");
const finAsesorOcrStatus = document.getElementById("finAsesorOcrStatus");
const finAsesorOcrFile = document.getElementById("finAsesorOcrFile");
const finAsesorOcrRaw = document.getElementById("finAsesorOcrRaw");
const finAsesorOcrExternal = document.getElementById("finAsesorOcrExternal");
const finAsesorOcrMode = document.getElementById("finAsesorOcrMode");
const finAsesorInmobiliaria = document.getElementById("finAsesorInmobiliaria");
const finAsesorOcrGuidedHeader = document.getElementById("finAsesorOcrGuidedHeader");
const finAsesorOcrGuidedCliente1 = document.getElementById("finAsesorOcrGuidedCliente1");
const finAsesorOcrGuidedCliente2 = document.getElementById("finAsesorOcrGuidedCliente2");
const finAsesorOcrGuidedResumen = document.getElementById("finAsesorOcrGuidedResumen");
const finAsesorOcrGuidedButton = document.getElementById("finAsesorOcrGuidedButton");
const finAsesorOcrGuidedStatus = document.getElementById("finAsesorOcrGuidedStatus");
const finAsesoramientoForm = document.getElementById("finAsesoramientoForm");
const finAsesoramientoId = document.getElementById("finAsesoramientoId");
const finAsesoramientoStatus = document.getElementById("finAsesoramientoStatus");
const finAsesoramientoConvert = document.getElementById("finAsesoramientoConvert");
const finAsesoramientosTable = document.getElementById("finAsesoramientosTable");
const finAsesoramientosInfo = document.getElementById("finAsesoramientosInfo");
const finAsesorKpis = document.getElementById("finAsesorKpis");
const finChecklistGenerate = document.getElementById("finChecklistGenerate");
const finChecklistStatus = document.getElementById("finChecklistStatus");
const finChecklistTable = document.getElementById("finChecklistTable");
const finChecklistInfo = document.getElementById("finChecklistInfo");
const finAlertsTable = document.getElementById("finAlertsTable");
const finAlertsInfo = document.getElementById("finAlertsInfo");
const finCopilotForm = document.getElementById("finCopilotForm");
const finCopilotStatus = document.getElementById("finCopilotStatus");
const finCopilotOutput = document.getElementById("finCopilotOutput");
const finCrmTable = document.getElementById("finCrmTable");
const finCrmInfo = document.getElementById("finCrmInfo");
const finAgendaForm = document.getElementById("finAgendaForm");
const finAgendaStatus = document.getElementById("finAgendaStatus");
const finAgendaClienteInput = document.getElementById("finAgendaClienteInput");
const finAgendaClienteId = document.getElementById("finAgendaClienteId");
const finAgendaClientes = document.getElementById("finAgendaClientes");
const actionModal = document.getElementById("actionModal");
const actionModalClose = document.getElementById("actionModalClose");
const actionModalClienteInput = document.getElementById("actionModalClienteInput");
const actionModalClienteId = document.getElementById("actionModalClienteId");
const actionModalClientes = document.getElementById("actionModalClientes");
const actionModalServicioSelect = document.getElementById("actionModalServicioSelect");
const actionModalFecha = document.getElementById("actionModalFecha");
const actionModalHora = document.getElementById("actionModalHora");
const actionModalTipo = document.getElementById("actionModalTipo");
const actionModalResponsable = document.getElementById("actionModalResponsable");
const actionModalEstado = document.getElementById("actionModalEstado");
const actionModalNotas = document.getElementById("actionModalNotas");
const actionModalRecordatorio = document.getElementById("actionModalRecordatorio");
const actionModalSave = document.getElementById("actionModalSave");
const actionModalStatus = document.getElementById("actionModalStatus");
const actionModalOpenCliente = document.getElementById("actionModalOpenCliente");
const finAgendaTable = document.getElementById("finAgendaTable");
const finAgendaInfo = document.getElementById("finAgendaInfo");
const gestoriaFacturasTable = document.getElementById("gestoriaFacturasTable");
const crmNuevaCaptacionBtn = document.getElementById("crmNuevaCaptacionBtn");
const crmCaptacionesTable = document.getElementById("crmCaptacionesTable");
const crmCaptacionesInfo = document.getElementById("crmCaptacionesInfo");
const crmInmueblesTable = document.getElementById("crmInmueblesTable");
const crmInmueblesInfo = document.getElementById("crmInmueblesInfo");
const crmInmueblesRecent = document.getElementById("crmInmueblesRecent");
const crmInmuebleSearch = document.getElementById("crmInmuebleSearch");
const crmDemandasTable = document.getElementById("crmDemandasTable");
const crmDemandasInfo = document.getElementById("crmDemandasInfo");
const crmNuevaDemandaBtn = document.getElementById("crmNuevaDemandaBtn");
const demandaDetail = document.getElementById("demandaDetail");
const demandaBackBtn = document.getElementById("demandaBackBtn");
const demandaMatching = document.getElementById("demandaMatching");
const demandaTitle = document.getElementById("demandaTitle");
const demandaSubtitle = document.getElementById("demandaSubtitle");
const visitaForm = document.getElementById("visitaForm");
const visitaFormStatus = document.getElementById("visitaFormStatus");
const visitaInmueble = document.getElementById("visitaInmueble");
const visitaDemanda = document.getElementById("visitaDemanda");
const crmVisitasTable = document.getElementById("crmVisitasTable");
const crmVisitasInfo = document.getElementById("crmVisitasInfo");
const crmKanban = document.getElementById("crmKanban");
const crmPipeline = document.getElementById("crmPipeline");
const crmEtapaFilter = document.getElementById("crmEtapaFilter");
const crmKpiCaptaciones = document.getElementById("crmKpiCaptaciones");
const crmKpiInmuebles = document.getElementById("crmKpiInmuebles");
const crmKpiEtapa = document.getElementById("crmKpiEtapa");
const inmuebleDetail = document.getElementById("inmuebleDetail");
const inmuebleBackBtn = document.getElementById("inmuebleBackBtn");
const inmuebleTabs = document.getElementById("inmuebleTabs");
const inmuebleSaveStatus = document.getElementById("inmuebleSaveStatus");
const inmuebleTabDatos = document.getElementById("inmuebleTabDatos");
const inmuebleTabCaptacion = document.getElementById("inmuebleTabCaptacion");
const inmuebleTabDemandas = document.getElementById("inmuebleTabDemandas");
const inmuebleTabVisitas = document.getElementById("inmuebleTabVisitas");
const inmuebleTabActividad = document.getElementById("inmuebleTabActividad");
const inmuebleTabMapa = document.getElementById("inmuebleTabMapa");
const inmuebleTabDocs = document.getElementById("inmuebleTabDocs");
const inmuebleTabEstado = document.getElementById("inmuebleTabEstado");
const inmuebleDocsForm = document.getElementById("inmuebleDocsForm");
const inmuebleDocsFile = document.getElementById("inmuebleDocsFile");
const inmuebleDocsStatus = document.getElementById("inmuebleDocsStatus");
const inmuebleChecklistTable = document.getElementById("inmuebleChecklistTable");
const inmuebleChecklistInfo = document.getElementById("inmuebleChecklistInfo");
const inmuebleChecklistBtn = document.getElementById("inmuebleChecklistBtn");
const inmuebleActividadTable = document.getElementById("inmuebleActividadTable");
const inmuebleActividadInfo = document.getElementById("inmuebleActividadInfo");
const inmuebleActividadTimeline = document.getElementById("inmuebleActividadTimeline");
const inmuebleActividadForm = document.getElementById("inmuebleActividadForm");
const inmuebleActividadStatus = document.getElementById("inmuebleActividadStatus");
const inmuebleActividadClienteInput = document.getElementById("inmuebleActividadClienteInput");
const inmuebleActividadClienteId = document.getElementById("inmuebleActividadClienteId");
const inmuebleActividadClientes = document.getElementById("inmuebleActividadClientes");
const inmuebleDatosGrid = document.getElementById("inmuebleDatosGrid");
const inmuebleCaptacionGrid = document.getElementById("inmuebleCaptacionGrid");
const inmuebleDemandasTable = document.getElementById("inmuebleDemandasTable");
const inmuebleDemandaForm = document.getElementById("inmuebleDemandaForm");
const inmuebleDemandaStatus = document.getElementById("inmuebleDemandaStatus");
const inmuebleDemandaCliente = document.getElementById("inmuebleDemandaCliente");
const inmuebleVisitaForm = document.getElementById("inmuebleVisitaForm");
const inmuebleVisitaStatus = document.getElementById("inmuebleVisitaStatus");
const inmuebleVisitaDemanda = document.getElementById("inmuebleVisitaDemanda");
const inmuebleVisitasTable = document.getElementById("inmuebleVisitasTable");
const inmuebleVisitasInfo = document.getElementById("inmuebleVisitasInfo");
const inmuebleMap = document.getElementById("inmuebleMap");
const inmuebleDocsList = document.getElementById("inmuebleDocsList");
const inmuebleEstadoInfo = document.getElementById("inmuebleEstadoInfo");
const inmuebleTitle = document.getElementById("inmuebleTitle");
const inmuebleSubtitle = document.getElementById("inmuebleSubtitle");
const aieSection = document.getElementById("aieSection");
const aieForm = document.getElementById("aieForm");
const aieFormStatus = document.getElementById("aieFormStatus");
const hipotecaSection = document.getElementById("hipotecaSection");
const hipotecaForm = document.getElementById("hipotecaForm");
const hipotecaFormStatus = document.getElementById("hipotecaFormStatus");
const finDashboardSection = document.getElementById("finDashboardSection");
const finDashboardKpis = document.getElementById("finDashboardKpis");
const finHipotecasChart = document.getElementById("finHipotecasChart");
const finComisionChart = document.getElementById("finComisionChart");
const finEntidadChart = document.getElementById("finEntidadChart");
const finOficinaChart = document.getElementById("finOficinaChart");
const fincasDashboardSection = document.getElementById("fincasDashboardSection");
const fincasDashboardKpis = document.getElementById("fincasDashboardKpis");
const fincasPresupuestoChart = document.getElementById("fincasPresupuestoChart");
const fincasResponsableChart = document.getElementById("fincasResponsableChart");
const fincasConversionChart = document.getElementById("fincasConversionChart");
const fincasBdtTabs = document.getElementById("fincasBdtTabs");
const renewalAlert = document.getElementById("renewalAlert");
const companySummary = document.getElementById("companySummary");
const companySummaryTitle = document.getElementById("companySummaryTitle");
const companySummarySubtitle = document.getElementById("companySummarySubtitle");
const companySummaryMeta = document.getElementById("companySummaryMeta");

let currentTab = "operativa";
let lastDashboardData = null;

const TABLE_LABELS = {
  movimientos: "BDT (Ingresos/Gastos)",
  seguros: "Seguros",
  gestoria: "Gestoría",
  captaciones: "Captación",
  hipotecas: "Hipotecas",
  alquileres: "Alquileres",
  inversores: "Inversores",
  inversure_operaciones: "Inversure Operaciones",
  clientes: "Clientes",
};

const EDITABLE_FIELDS = {
  seguros: {
    fecha_vencimiento: { type: "date" },
    estado_renovacion: {
      type: "select",
      options: ["Pendiente", "Renovada", "Cambio compania", "Baja"],
    },
    renovacion_fecha: { type: "date" },
    nueva_poliza_ref: { type: "text" },
  },
  gestoria: {
    estado: { type: "select", options: ["Alta", "Baja"] },
    fecha_baja: { type: "date" },
  },
};

const CLIENTES_SOURCE_COLUMNS = [
  "nombre",
  "tipo_persona",
  "nif",
  "telefono",
  "email",
  "fecha_nacimiento",
  "direccion",
  "codigo_postal",
  "poblacion",
  "provincia",
  "empresas",
  "servicios",
];

const CLIENTES_COLUMNS = [
  "apellidos",
  "nombre",
  "servicios",
  "nif",
  "telefono",
  "email",
  "fecha_nacimiento",
  "direccion",
  "codigo_postal",
  "poblacion",
  "provincia",
];

const CLIENTES_COLUMNS_STORAGE = "crm_clientes_columns";

const getClientesVisibleColumns = () => {
  const raw = localStorage.getItem(CLIENTES_COLUMNS_STORAGE);
  if (!raw) return [...CLIENTES_COLUMNS];
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length) {
      const filtered = parsed.filter((col) => CLIENTES_COLUMNS.includes(col));
      if (!filtered.includes("apellidos") && filtered.includes("nombre")) {
        const idx = filtered.indexOf("nombre");
        filtered.splice(idx, 0, "apellidos");
      }
      if (!filtered.includes("servicios")) {
        const idx = filtered.indexOf("nombre");
        if (idx >= 0) {
          filtered.splice(idx + 1, 0, "servicios");
        } else {
          filtered.push("servicios");
        }
      }
      return filtered;
    }
  } catch (err) {
    return [...CLIENTES_COLUMNS];
  }
  return [...CLIENTES_COLUMNS];
};

const saveClientesVisibleColumns = (cols) => {
  localStorage.setItem(CLIENTES_COLUMNS_STORAGE, JSON.stringify(cols));
};

const DASHBOARD_COMPANY = "Estudio Velazquez 2012 SL";
const AIE_COMPANY = "Inmovere Gestión AIE";
const FIN_COMPANY = "Financiaciones Modernia";
const FINCAS_COMPANY = "Fincas Velazquez";

const createOption = (value, label) => {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  return option;
};

const euroFormatter = new Intl.NumberFormat("es-ES", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const numberFormatter = new Intl.NumberFormat("es-ES");

const formatPercent = (value) => {
  const num = Number(value) || 0;
  const normalized = num > 0 && num <= 1 ? num * 100 : num;
  return `${normalized.toFixed(2)}%`;
};

const normalizeName = (value) => {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toUpperCase();
};

const normalizeSimple = (value) =>
  String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();

const normalizeMatch = (value) =>
  String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "")
    .trim();

let currentActionEdit = null;
let modalLoading = false;

const populateActionModalResponsables = (serviceValue = "") => {
  if (!actionModalResponsable) return;
  const filter = normalizeSimple(serviceValue || "");
  const users = state.usersList || [];
  actionModalResponsable.innerHTML = "";
  actionModalResponsable.appendChild(createOption("", "Selecciona responsable"));
  users
    .filter((user) => {
      if (!filter) return true;
      const service = normalizeSimple(user.servicio || "");
      if (!service) return true;
      if (service.includes(filter)) return true;
      if (["direccion", "administracion"].includes(service)) return true;
      return false;
    })
    .forEach((user) => {
      const label = `${user.nombre || ""} ${user.apellido || ""}`.trim();
      const value = user.usuario || label || user.nombre || "";
      if (!value) return;
      actionModalResponsable.appendChild(createOption(value, label || value));
    });
};

const ensureModalDataLoaded = async () => {
  if (modalLoading) return;
  modalLoading = true;
  try {
    if (!state.usersList || !state.usersList.length) {
      await loadUsuarios();
    }
    if (!state.clientesList || !state.clientesList.length) {
      await loadClientesList();
    }
    populateAgendaClientes(actionModalClientes, actionModalClienteInput, actionModalClienteId);
    populateActionModalResponsables(actionModalServicioSelect?.value || "");
  } finally {
    modalLoading = false;
  }
};

const openActionEditor = (ev) => {
  if (!actionModal) return;
  ensureModalDataLoaded();
  currentActionEdit = ev;
  if (actionModalStatus) actionModalStatus.textContent = "";
  if (actionModalClienteInput) actionModalClienteInput.value = ev.cliente || "";
  if (actionModalClienteId) actionModalClienteId.value = ev.cliente_id || "";
  if (actionModalServicioSelect) {
    actionModalServicioSelect.value = ev.serviceId || ev.service || "";
    if (!actionModalServicioSelect.value) {
      actionModalServicioSelect.value = "gestoria";
    }
  }
  if (actionModalFecha) actionModalFecha.value = ev.dateKey || "";
  if (actionModalHora) actionModalHora.value = ev.time || "";
  if (actionModalTipo) actionModalTipo.value = ev.tipo || "";
  if (actionModalNotas) actionModalNotas.value = ev.notas || "";
  if (actionModalRecordatorio) {
    actionModalRecordatorio.value =
      ev.recordatorio_min !== undefined && ev.recordatorio_min !== null
        ? String(ev.recordatorio_min)
        : "";
  }
  if (actionModalEstado) actionModalEstado.value = ev.estado || "Pendiente";
  if (actionModalResponsable) {
    populateActionModalResponsables(ev.serviceId || ev.service || "");
    if (ev.responsable) {
      actionModalResponsable.value = ev.responsable;
    }
  }
  actionModal.classList.remove("hidden");
};

const openActionCreator = (dateValue, timeValue, serviceValue) => {
  if (!actionModal) return;
  ensureModalDataLoaded();
  currentActionEdit = null;
  if (actionModalStatus) actionModalStatus.textContent = "";
  if (actionModalClienteInput) actionModalClienteInput.value = "";
  if (actionModalClienteId) actionModalClienteId.value = "";
  if (actionModalServicioSelect) actionModalServicioSelect.value = serviceValue || "";
  if (actionModalFecha) actionModalFecha.value = dateValue || formatAgendaDate(new Date());
  if (actionModalHora) actionModalHora.value = timeValue || "";
  if (actionModalTipo) actionModalTipo.value = "";
  if (actionModalNotas) actionModalNotas.value = "";
  if (actionModalRecordatorio) actionModalRecordatorio.value = "";
  if (actionModalEstado) actionModalEstado.value = "Pendiente";
  if (actionModalResponsable) {
    populateActionModalResponsables(serviceValue || "gestoria");
  }
  actionModal.classList.remove("hidden");
};

const closeActionEditor = () => {
  if (actionModal) actionModal.classList.add("hidden");
  currentActionEdit = null;
};

const agendaStates = new Map();
const agendaViews = ["day", "week", "month", "year"];
let lastAgendaEvents = [];

const parseAgendaDate = (value) => {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
};

const formatAgendaDate = (date) => date.toISOString().slice(0, 10);

const getWeekStart = (date) => {
  const day = new Date(date);
  const dow = (day.getDay() + 6) % 7;
  day.setDate(day.getDate() - dow);
  day.setHours(0, 0, 0, 0);
  return day;
};

const buildAgendaEvents = (rows = [], serviceId = "", serviceLabel = "") => {
  return rows
    .map((row) => {
      const date = parseAgendaDate(row.fecha);
      if (!date) return null;
      return {
        id: row.id || "",
        cliente_id: row.cliente_id || "",
        inmueble_id: row.inmueble_id || "",
        date,
        dateKey: formatAgendaDate(date),
        time: row.hora || "",
        tipo: row.tipo || "",
        cliente: row.cliente || "",
        responsable: row.responsable || "",
        estado: row.estado || "",
        notas: row.notas || "",
        recordatorio_min: row.recordatorio_min || "",
        serviceId: serviceId || row.servicio || "",
        serviceLabel: serviceLabel || SERVICE_LABELS[row.servicio] || row.servicio || "",
      };
    })
    .filter(Boolean);
};

const renderAgendaCalendar = (container, events, label = "") => {
  if (!container) return;
  const today = new Date();
  const state =
    agendaStates.get(container) || {
      view: "month",
      month: today.getMonth(),
      year: today.getFullYear(),
      day: formatAgendaDate(today),
      serviceFilter: "all",
      responsableFilter: "all",
    };
  const readOnly = container.dataset.readonly === "1";
  const defaultService = (container.dataset.service || "").trim();
  const availableServices = Array.from(
    new Set(events.map((ev) => ev.serviceId || ev.service).filter(Boolean))
  );
  const filteredEvents = events.filter((ev) => {
    if (state.serviceFilter && state.serviceFilter !== "all") {
      if ((ev.serviceId || ev.service) !== state.serviceFilter) return false;
    }
    if (state.responsableFilter && state.responsableFilter !== "all") {
      if ((ev.responsable || "") !== state.responsableFilter) return false;
    }
    return true;
  });
  const eventsByDate = new Map();
  filteredEvents.forEach((ev) => {
    if (!eventsByDate.has(ev.dateKey)) {
      eventsByDate.set(ev.dateKey, []);
    }
    eventsByDate.get(ev.dateKey).push(ev);
  });
  lastAgendaEvents = filteredEvents;

  const reminderEvents = filteredEvents.filter((ev) => {
    if (!ev.recordatorio_min || !ev.dateKey) return false;
    const time = ev.time || "00:00";
    const eventDate = new Date(`${ev.dateKey}T${time}`);
    if (Number.isNaN(eventDate.getTime())) return false;
    const minutes = (eventDate.getTime() - Date.now()) / 60000;
    if (minutes < 0 || minutes > Number(ev.recordatorio_min)) return false;
    const estado = normalizeSimple(ev.estado);
    if (["hecho", "completado", "finalizado", "cancelado"].includes(estado)) return false;
    const currentUser = getCurrentUser();
    if (currentUser && ev.responsable && ev.responsable !== currentUser) {
      return false;
    }
    return true;
  });

  const years = Array.from(
    new Set(filteredEvents.map((ev) => ev.date.getFullYear()).concat([today.getFullYear()]))
  ).sort((a, b) => a - b);

  container.innerHTML = "";
  const header = document.createElement("div");
  header.className = "agenda-controls";
  const title = document.createElement("div");
  title.innerHTML = `<strong>${label || "Agenda"}</strong>`;
  header.appendChild(title);

  const viewControls = document.createElement("div");
  viewControls.className = "agenda-view-controls";
  agendaViews.forEach((view) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = view === state.view ? "active" : "";
    btn.textContent =
      view === "day" ? "Día" : view === "week" ? "Semana" : view === "month" ? "Mes" : "Año";
    btn.addEventListener("click", () => {
      state.view = view;
      agendaStates.set(container, state);
      renderAgendaCalendar(container, events, label);
    });
    viewControls.appendChild(btn);
  });
  header.appendChild(viewControls);

  const rangeControls = document.createElement("div");
  rangeControls.className = "agenda-range-controls";
  const monthSelect = document.createElement("select");
  const monthNames = Array.from({ length: 12 }, (_, idx) =>
    new Date(2000, idx, 1).toLocaleString("es-ES", { month: "long" })
  );
  monthNames.forEach((name, idx) => {
    const option = createOption(idx, name);
    monthSelect.appendChild(option);
  });
  monthSelect.value = state.month;
  monthSelect.addEventListener("change", () => {
    state.month = Number(monthSelect.value);
    state.day = formatAgendaDate(new Date(state.year, state.month, 1));
    agendaStates.set(container, state);
    renderAgendaCalendar(container, events, label);
  });

  const yearSelect = document.createElement("select");
  years.forEach((year) => {
    yearSelect.appendChild(createOption(year, String(year)));
  });
  yearSelect.value = state.year;
  yearSelect.addEventListener("change", () => {
    state.year = Number(yearSelect.value);
    state.day = formatAgendaDate(new Date(state.year, state.month, 1));
    agendaStates.set(container, state);
    renderAgendaCalendar(container, events, label);
  });
  rangeControls.appendChild(monthSelect);
  rangeControls.appendChild(yearSelect);
  header.appendChild(rangeControls);

  const inferredService =
    availableServices.length === 1 ? availableServices[0] : defaultService || "";
  if (!readOnly) {
    const createBtn = document.createElement("button");
    createBtn.type = "button";
    createBtn.className = "agenda-create";
    createBtn.textContent = "Nueva cita";
    createBtn.addEventListener("click", () => {
      const serviceValue =
        state.serviceFilter && state.serviceFilter !== "all"
          ? state.serviceFilter
          : inferredService;
      openActionCreator(state.day, "", serviceValue);
    });
    header.appendChild(createBtn);
  }

  const filterControls = document.createElement("div");
  filterControls.className = "agenda-filters";
  if (availableServices.length > 1) {
    const serviceSelect = document.createElement("select");
    serviceSelect.appendChild(createOption("all", "Todos los servicios"));
    availableServices.forEach((service) => {
      const label = SERVICE_LABELS[service] || service;
      serviceSelect.appendChild(createOption(service, label));
    });
    serviceSelect.value = state.serviceFilter || "all";
    serviceSelect.addEventListener("change", () => {
      state.serviceFilter = serviceSelect.value;
      agendaStates.set(container, state);
      renderAgendaCalendar(container, events, label);
    });
    filterControls.appendChild(serviceSelect);
  }
  const responsableSelect = document.createElement("select");
  responsableSelect.appendChild(createOption("all", "Todos los responsables"));
  const responsables = Array.from(
    new Set(filteredEvents.map((ev) => ev.responsable).filter(Boolean))
  ).sort();
  responsables.forEach((responsable) => {
    responsableSelect.appendChild(createOption(responsable, responsable));
  });
  responsableSelect.value = state.responsableFilter || "all";
  responsableSelect.addEventListener("change", () => {
    state.responsableFilter = responsableSelect.value;
    agendaStates.set(container, state);
    renderAgendaCalendar(container, events, label);
  });
  filterControls.appendChild(responsableSelect);
  header.appendChild(filterControls);

  container.appendChild(header);

  if (reminderEvents.length) {
    const reminderBox = document.createElement("div");
    reminderBox.className = "agenda-reminders";
    reminderBox.innerHTML = "<strong>Recordatorios próximos</strong>";
    const list = document.createElement("div");
    list.className = "agenda-reminders-list";
    reminderEvents.slice(0, 5).forEach((ev) => {
      const row = document.createElement("div");
      row.className = "agenda-reminder-row";
      row.textContent = `${ev.time || ""} · ${ev.cliente || ev.tipo || "Acción"} · ${ev.serviceLabel || ev.service || ""}`;
      list.appendChild(row);
    });
    reminderBox.appendChild(list);
    container.appendChild(reminderBox);
  }

  const body = document.createElement("div");
  body.className = "agenda-body";

  const updateActionDate = (id, fecha, hora = "") => {
    if (readOnly) return;
    if (!id || !fecha) return;
    fetch("/api/acciones_update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, fecha, hora }),
    })
      .then(() => {
        const target = events.find((ev) => ev.id === id);
        if (target) {
          const newDate = parseAgendaDate(fecha);
          if (newDate) {
            target.date = newDate;
            target.dateKey = formatAgendaDate(newDate);
          }
          if (hora) {
            target.time = hora;
          }
        }
        renderAgendaCalendar(container, events, label);
      })
      .catch(() => {});
  };

  const makeEventRow = (ev, compact = false) => {
    const row = document.createElement("div");
    const estadoKey = normalizeSimple(ev.estado || "pendiente") || "pendiente";
    row.className = compact
      ? `agenda-week-row agenda-event estado-${estadoKey}`
      : `agenda-day-row agenda-event estado-${estadoKey}`;
    row.draggable = !readOnly;
    row.dataset.id = ev.id || "";
    row.dataset.date = ev.dateKey;
    row.innerHTML = `
      <div class="agenda-time">${ev.time || "-"}</div>
      <div class="agenda-info">
        <div class="agenda-title">${ev.cliente || ev.tipo || "Acción"}</div>
        <div class="agenda-meta">${ev.serviceLabel || ev.service || ""} · ${ev.responsable || "Sin responsable"} · ${ev.estado || "Pendiente"}</div>
        ${compact ? "" : `<div class="agenda-notes">${ev.notas || ""}</div>`}
      </div>
    `;
    if (ev.inmueble_id) {
      const link = document.createElement("button");
      link.type = "button";
      link.className = "agenda-link";
      link.textContent = "Ver inmueble";
      link.addEventListener("click", (event) => {
        event.stopPropagation();
        openInmuebleFromAgenda(ev.inmueble_id);
      });
      row.appendChild(link);
    }
    if (!readOnly) {
      row.addEventListener("click", () => {
        openActionEditor(ev);
      });
      row.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("text/plain", ev.id || "");
      });
    }
    return row;
  };

  if (state.view === "year") {
    const grid = document.createElement("div");
    grid.className = "agenda-year-grid";
    monthNames.forEach((name, idx) => {
      const monthCell = document.createElement("button");
      monthCell.type = "button";
      monthCell.className = "agenda-year-cell";
      const count = filteredEvents.filter(
        (ev) => ev.date.getFullYear() === state.year && ev.date.getMonth() === idx
      ).length;
      monthCell.innerHTML = `<div class="month-name">${name}</div><div class="month-count">${count} acciones</div>`;
      monthCell.addEventListener("click", () => {
        state.view = "month";
        state.month = idx;
        agendaStates.set(container, state);
        renderAgendaCalendar(container, events, label);
      });
      grid.appendChild(monthCell);
    });
    body.appendChild(grid);
  } else if (state.view === "month") {
    const monthGrid = document.createElement("div");
    monthGrid.className = "agenda-month-grid";
    const monthStart = new Date(state.year, state.month, 1);
    const monthEnd = new Date(state.year, state.month + 1, 0);
    const startDay = (monthStart.getDay() + 6) % 7;
    const totalDays = monthEnd.getDate();
    const weekHeader = document.createElement("div");
    weekHeader.className = "agenda-weekdays";
    ["L", "M", "X", "J", "V", "S", "D"].forEach((labelDay) => {
      const cell = document.createElement("div");
      cell.textContent = labelDay;
      weekHeader.appendChild(cell);
    });
    monthGrid.appendChild(weekHeader);
    const daysGrid = document.createElement("div");
    daysGrid.className = "agenda-days";
    for (let i = 0; i < startDay; i += 1) {
      const empty = document.createElement("div");
      empty.className = "agenda-day empty";
      daysGrid.appendChild(empty);
    }
    for (let day = 1; day <= totalDays; day += 1) {
      const date = new Date(state.year, state.month, day);
      const dateKey = formatAgendaDate(date);
      const dayEvents = eventsByDate.get(dateKey) || [];
      const statusCounts = dayEvents.reduce((acc, ev) => {
        const key = normalizeSimple(ev.estado || "pendiente") || "pendiente";
        acc[key] = (acc[key] || 0) + 1;
        return acc;
      }, {});
      const dominantStatus = Object.entries(statusCounts).sort((a, b) => b[1] - a[1])[0]?.[0];
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "agenda-day";
      if (dominantStatus) {
        cell.classList.add(`day-status-${dominantStatus}`);
      }
      if (dateKey === state.day) {
        cell.classList.add("active");
      }
      cell.innerHTML = `<span class="day-number">${day}</span><span class="day-count">${dayEvents.length || ""}</span>`;
      cell.addEventListener("click", () => {
        state.day = dateKey;
        agendaStates.set(container, state);
        renderAgendaCalendar(container, events, label);
        if (!readOnly) {
          const serviceValue =
            state.serviceFilter && state.serviceFilter !== "all"
              ? state.serviceFilter
              : inferredService;
          openActionCreator(dateKey, "", serviceValue);
        }
      });
      if (!readOnly) {
        cell.addEventListener("dragover", (event) => event.preventDefault());
        cell.addEventListener("drop", (event) => {
          event.preventDefault();
          const id = event.dataTransfer.getData("text/plain");
          updateActionDate(id, dateKey);
        });
      }
      daysGrid.appendChild(cell);
    }
    monthGrid.appendChild(daysGrid);
    const side = document.createElement("div");
    side.className = "agenda-side";
    const sideEvents = eventsByDate.get(state.day) || [];
    const sideTitle = document.createElement("div");
    sideTitle.className = "agenda-side-title";
    sideTitle.textContent = state.day;
    side.appendChild(sideTitle);
    if (!sideEvents.length) {
      side.innerHTML += "<p class='muted'>Sin acciones.</p>";
    } else {
      sideEvents
        .sort((a, b) => (a.time || "").localeCompare(b.time || ""))
        .forEach((ev) => {
          const row = makeEventRow(ev);
          const openBtn = document.createElement("button");
          openBtn.type = "button";
          openBtn.className = "agenda-open-client";
          openBtn.textContent = "Abrir cliente";
          openBtn.addEventListener("click", (event) => {
            event.stopPropagation();
            if (ev.cliente_id) {
              openClienteDetail(ev.cliente_id);
            }
          });
          row.appendChild(openBtn);
          side.appendChild(row);
        });
    }
    const wrap = document.createElement("div");
    wrap.className = "agenda-split";
    wrap.appendChild(monthGrid);
    wrap.appendChild(side);
    body.appendChild(wrap);
  } else if (state.view === "week") {
    const weekStart = getWeekStart(state.day || formatAgendaDate(today));
    const week = document.createElement("div");
    week.className = "agenda-week-grid";
    const hours = Array.from({ length: 13 }, (_, idx) => 8 + idx);
    for (let i = 0; i < 7; i += 1) {
      const dayDate = new Date(weekStart);
      dayDate.setDate(dayDate.getDate() + i);
      const dayKey = formatAgendaDate(dayDate);
      const dayEvents = eventsByDate.get(dayKey) || [];
      const column = document.createElement("div");
      column.className = "agenda-week-day";
      const headerDay = document.createElement("div");
      headerDay.className = "agenda-week-title";
      headerDay.textContent = dayDate.toLocaleString("es-ES", {
        weekday: "short",
        day: "numeric",
        month: "short",
      });
      column.appendChild(headerDay);
      if (!readOnly) {
        column.addEventListener("dragover", (event) => event.preventDefault());
        column.addEventListener("drop", (event) => {
          event.preventDefault();
          const id = event.dataTransfer.getData("text/plain");
          updateActionDate(id, dayKey);
        });
      }
      const hoursGrid = document.createElement("div");
      hoursGrid.className = "agenda-week-hours";
      hours.forEach((hour) => {
        const hourCell = document.createElement("div");
        hourCell.className = "agenda-week-hour";
        const label = document.createElement("div");
        label.className = "agenda-hour-label";
        label.textContent = `${String(hour).padStart(2, "0")}:00`;
        hourCell.appendChild(label);
        const slot = document.createElement("div");
        slot.className = "agenda-hour-slot";
        if (!readOnly) {
          slot.addEventListener("dragover", (event) => event.preventDefault());
          slot.addEventListener("drop", (event) => {
            event.preventDefault();
            const id = event.dataTransfer.getData("text/plain");
            updateActionDate(id, dayKey, `${String(hour).padStart(2, "0")}:00`);
          });
          slot.addEventListener("dblclick", () => {
            const serviceValue =
              state.serviceFilter && state.serviceFilter !== "all"
                ? state.serviceFilter
                : inferredService;
            openActionCreator(dayKey, `${String(hour).padStart(2, "0")}:00`, serviceValue);
          });
        }
        const slotEvents = dayEvents.filter((ev) => {
          if (!ev.time) return false;
          const evHour = Number(ev.time.split(":")[0]);
          return evHour === hour;
        });
        if (slotEvents.length) {
          slotEvents.forEach((ev) => {
            slot.appendChild(makeEventRow(ev, true));
          });
        }
        hourCell.appendChild(slot);
        hoursGrid.appendChild(hourCell);
      });
      if (!dayEvents.length) {
        const empty = document.createElement("div");
        empty.className = "muted";
        empty.textContent = "Sin acciones";
        column.appendChild(empty);
      }
      column.appendChild(hoursGrid);
      week.appendChild(column);
    }
    body.appendChild(week);
  } else {
    const dayEvents = eventsByDate.get(state.day) || [];
    const hours = Array.from({ length: 13 }, (_, idx) => 8 + idx);
    const dayGrid = document.createElement("div");
    dayGrid.className = "agenda-day-hours";
    hours.forEach((hour) => {
      const hourCell = document.createElement("div");
      hourCell.className = "agenda-week-hour";
      const label = document.createElement("div");
      label.className = "agenda-hour-label";
      label.textContent = `${String(hour).padStart(2, "0")}:00`;
      hourCell.appendChild(label);
      const slot = document.createElement("div");
      slot.className = "agenda-hour-slot";
      if (!readOnly) {
        slot.addEventListener("dragover", (event) => event.preventDefault());
        slot.addEventListener("drop", (event) => {
          event.preventDefault();
          const id = event.dataTransfer.getData("text/plain");
          updateActionDate(id, state.day, `${String(hour).padStart(2, "0")}:00`);
        });
      }
      const slotEvents = dayEvents.filter((ev) => {
        if (!ev.time) return false;
        const evHour = Number(ev.time.split(":")[0]);
        return evHour === hour;
      });
      if (slotEvents.length) {
        slotEvents.forEach((ev) => {
          slot.appendChild(makeEventRow(ev, true));
        });
      }
      hourCell.appendChild(slot);
      dayGrid.appendChild(hourCell);
    });
    body.appendChild(dayGrid);
    const list = document.createElement("div");
    list.className = "agenda-day-list";
    if (!dayEvents.length) {
      list.innerHTML = "<p class='muted'>Sin acciones para este día.</p>";
    } else {
      dayEvents
        .sort((a, b) => (a.time || "").localeCompare(b.time || ""))
        .forEach((ev) => {
          list.appendChild(makeEventRow(ev));
        });
    }
    body.appendChild(list);
  }

  container.appendChild(body);
};

const normalizeYear = (value) => {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  return String(value);
};

const getYearValue = (series, year) => {
  const target = normalizeYear(year);
  const entry = series.find((item) => normalizeYear(item.year) === target);
  return entry ? entry.total || 0 : 0;
};

const buildCompanyMeta = (item, selectedYear) => {
  const isEstudio = item.empresa === DASHBOARD_COMPANY;
  const isFin = item.empresa === FIN_COMPANY;
  const isFincas = item.empresa === FINCAS_COMPANY;
  if (isEstudio && state.homeDashboard && selectedYear) {
    const ventas = getYearValue(state.homeDashboard.ventas, selectedYear);
    const alquileres = getYearValue(state.homeDashboard.alquileres, selectedYear);
    const facturado = getYearValue(state.homeDashboard.ingresos, selectedYear);
    const gastos = getYearValue(state.homeDashboard.gastos, selectedYear);
    return [
      `Compraventas ${selectedYear}: ${numberFormatter.format(ventas)}`,
      `Alquileres ${selectedYear}: ${numberFormatter.format(alquileres)}`,
      `Facturado: ${euroFormatter.format(facturado)}`,
      `Gastos: ${euroFormatter.format(gastos)}`,
    ];
  }
  if (isFin && state.homeHipotecaStats) {
    const stats = state.homeHipotecaStats;
    return [
      `Hipotecas totales: ${numberFormatter.format(stats.total || 0)}`,
      `Firmadas mes: ${numberFormatter.format(stats.firmadas_mes || 0)}`,
      `Financiacion media: ${formatPercent(stats.porcentaje_medio)}`,
      `Comision media: ${euroFormatter.format(stats.comision_media || 0)}`,
    ];
  }
  if (isFincas && state.homeFincasStats) {
    const stats = state.homeFincasStats;
    return [
      `Facturado ${stats.year}: ${euroFormatter.format(stats.facturado || 0)}`,
      `Gastos ${stats.year}: ${euroFormatter.format(stats.gastos || 0)}`,
      `Clientes empresa: ${numberFormatter.format(stats.clientes_empresas || 0)}`,
      `Autónomos: ${numberFormatter.format(stats.autonomos || 0)}`,
      `Pólizas en vigor: ${numberFormatter.format(stats.polizas_vigor || 0)}`,
      `Comunidades: ${numberFormatter.format(stats.comunidades || 0)}`,
    ];
  }
  return [
    `Seguros: ${item.seguros} · Gestoría: ${item.gestoria}`,
    `Hipotecas: ${item.hipotecas} · Alquileres: ${item.alquileres}`,
    `Inversores: ${item.inversores} · Ops: ${item.inversure_ops}`,
  ];
};

const renderCompanyCards = () => {
  if (coreCards) {
    coreCards.innerHTML = "";
  }
  if (coreCards) {
    const holdingCard = document.createElement("div");
    holdingCard.className = "company-card";
    holdingCard.dataset.action = "holding";
    holdingCard.innerHTML = `
      <h3>Histórico empresas</h3>
      <div class="company-meta">Acceso al histórico por sociedades.</div>
      <div class="company-meta">Dashboards por empresa (fase final).</div>
      <a class="card-link" href="?holding=1" data-action="holding">Entrar</a>
    `;
    coreCards.appendChild(holdingCard);

    const crmCard = document.createElement("div");
    crmCard.className = "company-card";
    crmCard.dataset.action = "crm-inmo";
    crmCard.innerHTML = `
      <h3>CRM Inmobiliario</h3>
      <div class="company-meta">Captación, inmuebles y operaciones.</div>
      <div class="company-meta">Servicio inmobiliario.</div>
      <a class="card-link" href="?crm=inmo" data-action="crm-inmo">Entrar</a>
    `;
    coreCards.appendChild(crmCard);

    const gestoriaCard = document.createElement("div");
    gestoriaCard.className = "company-card";
    gestoriaCard.dataset.action = "crm-gestoria";
    gestoriaCard.innerHTML = `
      <h3>CRM Gestoría</h3>
      <div class="company-meta">Clientes en gestión y seguimiento.</div>
      <div class="company-meta">Servicio de gestoría.</div>
      <a class="card-link" href="?crm=gestoria" data-action="crm-gestoria">Entrar</a>
    `;
    coreCards.appendChild(gestoriaCard);

    const segurosCard = document.createElement("div");
    segurosCard.className = "company-card";
    segurosCard.dataset.action = "crm-seguros";
    segurosCard.innerHTML = `
      <h3>CRM Seguros</h3>
      <div class="company-meta">Pólizas, renovaciones y oportunidades.</div>
      <div class="company-meta">Servicio de seguros.</div>
      <a class="card-link" href="?crm=seguros" data-action="crm-seguros">Entrar</a>
    `;
    coreCards.appendChild(segurosCard);

    const finCard = document.createElement("div");
    finCard.className = "company-card";
    finCard.dataset.action = "crm-fin";
    finCard.innerHTML = `
      <h3>CRM Financiaciones</h3>
      <div class="company-meta">Hipotecas y seguimiento.</div>
      <div class="company-meta">Servicio financiero.</div>
      <a class="card-link" href="?crm=fin" data-action="crm-fin">Entrar</a>
    `;
    coreCards.appendChild(finCard);

    const clientesCard = document.createElement("div");
    clientesCard.className = "company-card";
    clientesCard.dataset.action = "clientes";
    const clientesCount =
      state.clientesStats?.total ??
      (Array.isArray(state.clientesList) ? state.clientesList.length : 0);
    clientesCard.innerHTML = `
      <h3>Clientes</h3>
      <div class="company-meta">Total registrados: ${numberFormatter.format(clientesCount)}</div>
      <div class="company-meta">Módulo compartido entre CRMs.</div>
      <a class="card-link" href="?clientes=1" data-action="clientes">Entrar</a>
    `;
    coreCards.appendChild(clientesCard);

    const agendaCard = document.createElement("div");
    agendaCard.className = "company-card";
    agendaCard.dataset.action = "agenda";
    agendaCard.innerHTML = `
      <h3>Agenda</h3>
      <div class="company-meta">Tareas y seguimientos del grupo.</div>
      <div class="company-meta">Centraliza las agendas por servicio.</div>
      <a class="card-link" href="?agenda=1" data-action="agenda">Entrar</a>
    `;
    coreCards.appendChild(agendaCard);

    const adminCard = document.createElement("div");
    adminCard.className = "company-card";
    adminCard.dataset.action = "admin";
    adminCard.innerHTML = `
      <h3>Panel admin</h3>
      <div class="company-meta">Usuarios y permisos.</div>
      <a class="card-link" href="?admin=1" data-action="admin">Entrar</a>
    `;
    coreCards.appendChild(adminCard);
  }
};

const renderHoldingOrgChart = () => {
  if (!holdingOrgChart) {
    return;
  }
  const selectedYear = yearSelect?.value;
  const companies = state.empresas.map((empresa) => empresa.nombre);
  const siblings = companies.filter((name) => name !== AIE_COMPANY);
  const aieMembers = siblings;
  const resumenMap = new Map(
    state.resumen.map((item) => [item.empresa, item])
  );
  const buildNode = (name, isAie) => {
    const item = resumenMap.get(name);
    const lines = item ? buildCompanyMeta(item, selectedYear) : [];
    const metaHtml = lines
      .map((line) => `<div class="muted">${line}</div>`)
      .join("");
    return `
      <div class="org-node${isAie ? " org-aie" : ""}" data-empresa="${name}">
        <h4>${name}</h4>
        ${metaHtml}
        ${isAie ? '<div class="muted">Subsidiaria AIE</div>' : ""}
        <button type="button">Entrar</button>
      </div>
    `;
  };
  const root = `
    <ul>
      <li>
        <div class="org-node">
          <h4>Inmovere Holding</h4>
          <div class="muted">Grupo principal</div>
        </div>
        <ul>
          ${siblings
            .filter((name) => name !== AIE_COMPANY)
            .map(
              (name) => `
            <li>
              ${buildNode(name, false)}
            </li>
          `
            )
            .join("")}
          <li class="org-aie-node">
            ${buildNode(AIE_COMPANY, true)}
            <div class="muted">Socias: ${aieMembers.join(" · ")}</div>
          </li>
        </ul>
      </li>
    </ul>
  `;
  holdingOrgChart.innerHTML = root;
  holdingOrgChart.querySelectorAll(".org-node button").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      const node = event.currentTarget.closest(".org-node");
      if (!node) return;
      const name = node.dataset.empresa;
      if (name) {
        openCompany(name);
      }
    });
  });
};

const updateExplorerHeader = (empresaName) => {
  if (empresaName) {
    explorerTitle.textContent = `Explorador de datos · ${empresaName}`;
    explorerSubtitle.textContent = "Entrada de datos y revisión por módulo.";
  } else {
    explorerTitle.textContent = "Explorador de datos";
    explorerSubtitle.textContent = "Filtra por empresa, módulo y texto.";
  }
  updateCompanySummary(empresaName);
  if (aieTab) {
    aieTab.classList.toggle("hidden", empresaName !== AIE_COMPANY);
    if (empresaName !== AIE_COMPANY && currentTab === "aie") {
      setTab("operativa");
    }
  }
  if (operativaTab) {
    operativaTab.classList.toggle("hidden", empresaName === FINCAS_COMPANY);
    if (empresaName === FINCAS_COMPANY && currentTab === "operativa") {
      setTab("gestoria-dash");
    }
  }
  if (empresaName === FINCAS_COMPANY && currentTab === "alta") {
    setTab("gestoria-crm");
  }
  if (crmTab) {
    const showCrm = empresaName === DASHBOARD_COMPANY;
    crmTab.classList.toggle("hidden", !showCrm);
    if (!showCrm && currentTab === "crm") {
      setTab("operativa");
    }
  }
  if (fincasCrmTab) {
    const showGestoria = empresaName === FINCAS_COMPANY;
    fincasCrmTab.classList.toggle("hidden", !showGestoria);
    if (!showGestoria && currentTab === "gestoria-crm") {
      setTab("operativa");
    }
  }
  if (gestoriaDashTab) {
    const showDash = empresaName === FINCAS_COMPANY;
    gestoriaDashTab.classList.toggle("hidden", !showDash);
    if (!showDash && currentTab === "gestoria-dash") {
      setTab("operativa");
    }
  }
  if (gestoriaAgendaTab) {
    const showAgenda = empresaName === FINCAS_COMPANY;
    gestoriaAgendaTab.classList.toggle("hidden", !showAgenda);
    if (!showAgenda && currentTab === "gestoria-agenda") {
      setTab("operativa");
    }
  }
  if (gestoriaFactTab) {
    const showFact = empresaName === FINCAS_COMPANY;
    gestoriaFactTab.classList.toggle("hidden", !showFact);
    if (!showFact && currentTab === "gestoria-fact") {
      setTab("operativa");
    }
  }
  if (gestoriaContaTab) {
    const showConta = empresaName === FINCAS_COMPANY;
    gestoriaContaTab.classList.toggle("hidden", !showConta);
    if (!showConta && currentTab === "gestoria-conta") {
      setTab("operativa");
    }
  }
  if (gestoriaDashTab) {
    const showDash = empresaName === FINCAS_COMPANY;
    gestoriaDashTab.classList.toggle("hidden", !showDash);
    if (!showDash && currentTab === "gestoria-dash") {
      setTab("operativa");
    }
  }
  if (gestoriaAgendaTab) {
    const showAgenda = empresaName === FINCAS_COMPANY;
    gestoriaAgendaTab.classList.toggle("hidden", !showAgenda);
    if (!showAgenda && currentTab === "gestoria-agenda") {
      setTab("operativa");
    }
  }
  if (segurosCrmTab) {
    // CRM Seguros se accede desde la home, no como pestaña interna
    segurosCrmTab.classList.add("hidden");
  }
  if (finCrmTab) {
    // CRM Financiaciones se accede desde la home, no como pestaña interna
    finCrmTab.classList.add("hidden");
  }
  if (finSimTab) {
    const showSim = empresaName === FIN_COMPANY;
    finSimTab.classList.toggle("hidden", !showSim);
    if (!showSim && currentTab === "fin-sim") {
      setTab("operativa");
    }
  }
};

const slugify = (value) =>
  String(value || "")
    .toLowerCase()
    .replace(/\./g, "")
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "");

const setUrlParams = (params) => {
  const url = new URL(window.location.href);
  url.search = params.toString();
  history.pushState({}, "", url.toString());
};

const setPage = (page) => {
  state.currentPage = page;
  document.body.classList.toggle("page-empresa", page !== "home");
  if (homeSection) {
    homeSection.classList.toggle("hidden", page !== "home");
  }
  if (renewalAlert) {
    renewalAlert.classList.toggle("hidden", page !== "home");
  }
  if (explorerSection) {
    explorerSection.classList.toggle("hidden", page !== "empresa");
  }
  if (holdingSection) {
    holdingSection.classList.toggle("hidden", page !== "holding");
  }
  if (adminSection) {
    adminSection.classList.toggle("hidden", page !== "admin");
  }
  if (clientePage) {
    clientePage.classList.toggle("hidden", page !== "cliente");
  }
  if (clientesDetail) {
    clientesDetail.classList.toggle("hidden", page !== "cliente");
  }
};

const openCompany = (empresaName) => {
  setCrmMode("");
  const empresa = state.empresas.find((e) => e.nombre === empresaName);
  if (!empresa) {
    if (!state.empresas.length) {
      api("/api/empresas")
        .then((empresas) => {
          state.empresas = empresas;
          empresaSelect.innerHTML = "";
          empresaSelect.appendChild(createOption("", "Todas las empresas"));
          empresas.forEach((item) => {
            empresaSelect.appendChild(createOption(item.id, item.nombre));
          });
          openCompany(empresaName);
        })
        .catch(() => {
          alert("No se pudieron cargar las empresas. Revisa el servidor.");
        });
      return;
    }
    alert("Empresa no encontrada.");
    return;
  }
  if (homeSection) {
    homeSection.classList.add("hidden");
  }
  setModule("empresas");
  empresaSelect.value = empresa.id;
  state.currentEmpresaId = empresa.id;
  state.currentEmpresaName = empresa.nombre;
  setTab("operativa");
  updateExplorerHeader(empresa.nombre);
  setDefaultTableForCompany(
    state.resumen.find((item) => item.empresa === empresaName)
  );
  ensureOperativaTable();
  updateTableVisibility();
  explorerSection.classList.remove("hidden");
  loadTable();
  setPage("empresa");
  setUrlParams(new URLSearchParams({ empresa: slugify(empresaName) }));
  if (currentTab === "crm") {
    loadCrmCaptaciones();
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
};

const openClientesModule = () => {
  if (homeSection) {
    homeSection.classList.add("hidden");
  }
  setModule("clientes");
  setPage("empresa");
  setUrlParams(new URLSearchParams({ clientes: "1" }));
};

const openCrmInmobiliario = () => {
  openCompany(DASHBOARD_COMPANY);
  setTab("crm");
  updateTableVisibility();
  loadCrmCaptaciones();
  loadCrmInmuebles();
};

const openInmuebleFromAgenda = (inmuebleId) => {
  if (!inmuebleId) return;
  openCrmInmobiliario();
  setTimeout(() => {
    openInmuebleDetail(inmuebleId);
  }, 300);
};

const openGestoriaCrm = () => {
  openCompany(FINCAS_COMPANY);
  setTab("gestoria-dash");
  updateTableVisibility();
  loadGestoriaDashboard();
};

const openSegurosCrm = () => {
  openCompany(FINCAS_COMPANY);
  setTab("seguros-crm");
  updateTableVisibility();
  setCrmMode("seguros");
  setSegurosTab("dashboard");
  if (viewTabs) viewTabs.classList.add("hidden");
  if (segurosCrmSection) segurosCrmSection.classList.remove("hidden");
  if (tableToolbar) tableToolbar.classList.add("hidden");
  if (tableContainer) tableContainer.classList.add("hidden");
  if (tableInfo) tableInfo.classList.add("hidden");
  loadSegurosCrm();
  if (state.currentEmpresaId) {
    renderFincasDashboard(state.currentEmpresaId);
  }
};

const openFinCrm = () => {
  openCompany(FIN_COMPANY);
  setTab("fin-crm");
  updateTableVisibility();
  setCrmMode("fin");
  if (viewTabs) viewTabs.classList.add("hidden");
  if (finCrmSection) finCrmSection.classList.remove("hidden");
  if (tableToolbar) tableToolbar.classList.add("hidden");
  if (tableContainer) tableContainer.classList.add("hidden");
  if (tableInfo) tableInfo.classList.add("hidden");
  loadFinCrm();
};

const openServiceCrm = (service) => {
  if (!service) return;
  if (service === "Inmobiliaria") {
    openCrmInmobiliario();
    return;
  }
  if (service === "Gestoría" || service === "Administración Fincas") {
    openGestoriaCrm();
    return;
  }
  if (service === "Seguros") {
    openSegurosCrm();
    return;
  }
  if (service === "Hipotecas") {
    openFinCrm();
    return;
  }
  alert("CRM en preparación para " + service);
};

const setClienteTab = (tab) => {
  if (!clienteTabs) return;
  clienteTabs.querySelectorAll(".tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  if (clienteTabDatos) clienteTabDatos.classList.toggle("hidden", tab !== "datos");
  if (clienteTabProfesional) clienteTabProfesional.classList.toggle("hidden", tab !== "profesional");
  if (clienteTabSeguros) clienteTabSeguros.classList.toggle("hidden", tab !== "seguros");
  if (clienteTabInmobiliaria) clienteTabInmobiliaria.classList.toggle("hidden", tab !== "inmobiliaria");
  if (clienteTabHipotecas) clienteTabHipotecas.classList.toggle("hidden", tab !== "hipotecas");
  if (clienteTabFacturas) clienteTabFacturas.classList.toggle("hidden", tab !== "facturas");
  if (clienteTabTrabajos) clienteTabTrabajos.classList.toggle("hidden", tab !== "trabajos");
};

const openHolding = () => {
  setModule("empresas");
  explorerSection.classList.add("hidden");
  setPage("holding");
  setUrlParams(new URLSearchParams({ holding: "1" }));
  window.scrollTo({ top: 0, behavior: "smooth" });
};

const openAgenda = () => {
  setModule("empresas");
  explorerSection.classList.add("hidden");
  setPage("agenda");
  if (agendaSection) {
    agendaSection.classList.remove("hidden");
  }
  loadAgendaGeneral();
  setUrlParams(new URLSearchParams({ agenda: "1" }));
  window.scrollTo({ top: 0, behavior: "smooth" });
};

const openAdmin = () => {
  setModule("empresas");
  explorerSection.classList.add("hidden");
  setPage("admin");
  if (adminSection) {
    adminSection.classList.remove("hidden");
  }
  loadUsuarios()
    .then(() => {
      renderUsuariosSelect();
      renderUsuariosTable();
    })
    .catch(() => {
      if (adminUsersTable) {
        adminUsersTable.innerHTML = "<p class='muted'>No se pudieron cargar los usuarios.</p>";
      }
    });
  setUrlParams(new URLSearchParams({ admin: "1" }));
  window.scrollTo({ top: 0, behavior: "smooth" });
};

const goHome = () => {
  setCrmMode("");
  setModule("empresas");
  empresaSelect.value = "";
  state.currentEmpresaId = "";
  state.currentEmpresaName = "";
  updateExplorerHeader("");
  renderDashboard("", "");
  setTab("operativa");
  if (crmSection) crmSection.classList.add("hidden");
  if (gestoriaCrmSection) gestoriaCrmSection.classList.add("hidden");
  if (segurosCrmSection) segurosCrmSection.classList.add("hidden");
  if (finCrmSection) finCrmSection.classList.add("hidden");
  if (gestoriaFactSection) gestoriaFactSection.classList.add("hidden");
  explorerSection.classList.add("hidden");
  updateTableVisibility();
  if (homeSection) {
    homeSection.classList.remove("hidden");
  }
  if (agendaSection) {
    agendaSection.classList.add("hidden");
  }
  if (holdingSection) {
    holdingSection.classList.add("hidden");
  }
  if (adminSection) {
    adminSection.classList.add("hidden");
  }
  if (adminSection) {
    adminSection.classList.add("hidden");
  }
  setPage("home");
  setUrlParams(new URLSearchParams());
  window.scrollTo({ top: 0, behavior: "smooth" });
};

const handleRoute = () => {
  const params = new URLSearchParams(window.location.search);
  if (params.has("agenda")) {
    openAgenda();
    return;
  }
  if (params.has("admin")) {
    openAdmin();
    return;
  }
  if (params.has("holding")) {
    openHolding();
    return;
  }
  if (params.has("clientes")) {
    openClientesModule();
    return;
  }
  if (params.has("crm")) {
    const crm = params.get("crm");
    if (crm === "inmo") {
      openCrmInmobiliario();
      return;
    }
    if (crm === "gestoria") {
      openGestoriaCrm();
      return;
    }
    if (crm === "seguros") {
      openSegurosCrm();
      return;
    }
    if (crm === "fin") {
      openFinCrm();
      return;
    }
  }
  if (params.has("cliente")) {
    const id = params.get("cliente");
    openClientesModule();
    openClienteDetail(id);
    return;
  }
  const slug = params.get("empresa");
  if (slug) {
    const empresa = state.empresas.find((item) => slugify(item.nombre) === slug);
    if (empresa) {
      openCompany(empresa.nombre);
      return;
    }
  }
  goHome();
};

const updateCompanySummary = (empresaName) => {
  if (!companySummary || !companySummaryTitle || !companySummarySubtitle) {
    return;
  }
  if (!empresaName) {
    companySummary.classList.add("hidden");
    return;
  }
  companySummary.classList.remove("hidden");
  companySummaryTitle.textContent = empresaName;
  if (empresaName === "Clientes") {
    companySummarySubtitle.textContent = "Modulo maestro de clientes compartido.";
    if (companySummaryMeta) {
      companySummaryMeta.textContent = "Asignacion por empresa y servicio.";
    }
    return;
  }
  companySummarySubtitle.textContent = "Gestion operativa y control diario.";
  if (companySummaryMeta) {
    const year = yearSelect?.value ? `Año ${yearSelect.value}` : "";
    companySummaryMeta.textContent = year;
  }
};

const updateBdtFiltersVisibility = () => {
  if (!bdtYearFilter || !bdtFieldFilter) {
    return;
  }
  const selectedCompany =
    state.currentEmpresaName ||
    state.empresas.find((e) => e.id === empresaSelect.value)?.nombre;
  const show =
    currentTab === "bdt" &&
    selectedCompany === DASHBOARD_COMPANY &&
    tablaSelect.value === "movimientos";
  bdtYearFilter.classList.toggle("hidden", !show);
  bdtFieldFilter.classList.toggle("hidden", !show);
  if (!show) {
    return;
  }
  const currentYear = String(new Date().getFullYear());
  if (!bdtYearFilter.options.length) {
    const years = state.homeYears.length ? state.homeYears : [currentYear];
    bdtYearFilter.innerHTML = "";
    years.forEach((year) => {
      bdtYearFilter.appendChild(createOption(year, year));
    });
  }
  if (!bdtYearFilter.value) {
    bdtYearFilter.value = currentYear;
  }
};

const setModule = (moduleName) => {
  state.currentModule = moduleName;
  const operativaTab = viewTabs.querySelector('[data-tab="operativa"]');
  if (operativaTab) {
    operativaTab.classList.toggle("hidden", moduleName === "clientes");
  }
  if (moduleName === "clientes") {
    state.currentEmpresaId = "";
    state.currentEmpresaName = "";
    state.currentClienteId = "";
    empresaSelect.value = "";
    updateExplorerHeader("Clientes");
    explorerSection.classList.remove("hidden");
    setTab("bdt");
    loadClientesTable();
    renderClientesColumnsPicker();
  } else {
    updateExplorerHeader(state.currentEmpresaName || "");
  }
  updateTableVisibility();
};

const ensureOperativaTable = () => {
  if (currentTab !== "operativa") {
    return;
  }
  if (tablaSelect.value === "movimientos") {
    const fallback = state.tablas.find((t) => t !== "movimientos");
    tablaSelect.value = fallback || "";
  }
};

const setTab = (tabName) => {
  currentTab = tabName;
  viewTabs.querySelectorAll(".tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });
  if (tabName === "fin-sim") {
    initFinSimulator();
  }
  populateTables();
  tablaSelect.selectedIndex = 0;
  if (state.currentModule !== "clientes") {
    const selectedCompany = state.empresas.find((e) => e.id === empresaSelect.value)?.nombre;
    if (currentTab === "bdt") {
      tablaSelect.value = selectedCompany === FIN_COMPANY ? "hipotecas" : "movimientos";
    }
  } else {
    tablaSelect.value = "clientes";
  }
  updateTableVisibility();
  if (state.currentModule === "clientes" && tabName === "alta") {
    refreshClientesAltaSelects();
  }
};

const populateTables = () => {
  tablaSelect.innerHTML = "";
  if (state.currentModule === "clientes") {
    tablaSelect.appendChild(createOption("clientes", "Clientes"));
    return;
  }
  const selectedCompany = state.currentEmpresaName || state.empresas.find((e) => e.id === empresaSelect.value)?.nombre;
  let tables = [];
  if (currentTab === "bdt") {
    if (selectedCompany === FIN_COMPANY) {
      tables = ["hipotecas"];
    } else if (selectedCompany === FINCAS_COMPANY) {
      tables = ["movimientos"];
    } else {
      tables = ["movimientos"];
    }
  } else {
    tables = state.tablas.filter((t) => t !== "movimientos");
    if (selectedCompany !== DASHBOARD_COMPANY) {
      tables = tables.filter((t) => t !== "captaciones");
    }
  }
  tables.forEach((tabla) => {
    tablaSelect.appendChild(
      createOption(tabla, TABLE_LABELS[tabla] || tabla)
    );
  });
};

const setDefaultTableForCompany = (resumenItem) => {
  if (!resumenItem) {
    return;
  }
  const selectedCompany =
    state.currentEmpresaName ||
    state.empresas.find((e) => e.id === empresaSelect.value)?.nombre;
  if (selectedCompany === DASHBOARD_COMPANY) {
    if (state.tablas.includes("captaciones")) {
      tablaSelect.value = "captaciones";
      return;
    }
  }
  const candidates = [
    { key: "seguros", table: "seguros" },
    { key: "gestoria", table: "gestoria" },
    { key: "hipotecas", table: "hipotecas" },
    { key: "alquileres", table: "alquileres" },
    { key: "inversores", table: "inversores" },
    { key: "inversure_ops", table: "inversure_operaciones" },
  ];
  const best = candidates.reduce(
    (acc, item) =>
      resumenItem[item.key] > acc.count
        ? { table: item.table, count: resumenItem[item.key] }
        : acc,
    { table: "seguros", count: -1 }
  );
  tablaSelect.value = best.table;
};

const HEADER_OVERRIDES = {
  anio: "AÑO",
};

const formatHeader = (value) => {
  const normalized = value.replace(/_/g, " ").replace(/\s+/g, " ").trim();
  const lower = normalized.toLowerCase();
  if (HEADER_OVERRIDES[lower]) {
    return HEADER_OVERRIDES[lower];
  }
  return normalized.toUpperCase();
};

const toNumber = (value) => {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  if (typeof value === "number") {
    return value;
  }
  let text = String(value).trim();
  if (!text) return null;
  // Keep digits, separators and sign
  text = text.replace(/[^\d.,-]/g, "");
  const hasComma = text.includes(",");
  const hasDot = text.includes(".");
  if (hasComma && hasDot) {
    // es-ES: dots for thousands, comma for decimals
    text = text.replace(/\./g, "").replace(",", ".");
  } else if (hasComma) {
    text = text.replace(",", ".");
  } else if (hasDot) {
    // If dots look like thousands separators (e.g. 200.000), remove them
    const parts = text.split(".");
    const last = parts[parts.length - 1];
    const allGroupsAre3 = parts.slice(1).every((p) => p.length === 3);
    if (allGroupsAre3 && last.length === 3) {
      text = parts.join("");
    }
  }
  const parsed = Number(text);
  return Number.isNaN(parsed) ? null : parsed;
};

const FIN_SIM_HIPOTECA_TARIFAS = [{"importe":0.0,"notaria":210.0,"registro":39.07,"gestoria":174.0},{"importe":5001.0,"notaria":277.14,"registro":71.45,"gestoria":174.0},{"importe":10001.0,"notaria":327.54,"registro":93.5,"gestoria":174.0},{"importe":15001.0,"notaria":377.94,"registro":115.55,"gestoria":174.0},{"importe":20001.0,"notaria":428.34,"registro":137.6,"gestoria":174.0},{"importe":25001.0,"notaria":478.74,"registro":159.65,"gestoria":174.0},{"importe":30001.0,"notaria":527.85,"registro":220.59,"gestoria":174.0},{"importe":35001.0,"notaria":544.05,"registro":234.09,"gestoria":174.0},{"importe":40001.0,"notaria":560.25,"registro":247.59,"gestoria":174.0},{"importe":45001.0,"notaria":576.45,"registro":261.09,"gestoria":174.0},{"importe":50001.0,"notaria":592.65,"registro":274.59,"gestoria":174.0},{"importe":55001.0,"notaria":608.85,"registro":288.09,"gestoria":174.0},{"importe":60001.0,"notaria":645.0,"registro":312.29,"gestoria":174.0},{"importe":65001.0,"notaria":655.8,"registro":320.39,"gestoria":179.8},{"importe":70001.0,"notaria":666.6,"registro":328.49,"gestoria":185.60000000000002},{"importe":75001.0,"notaria":677.4,"registro":336.59,"gestoria":191.40000000000003},{"importe":80001.0,"notaria":688.2,"registro":344.69,"gestoria":197.20000000000005},{"importe":85001.0,"notaria":699.0,"registro":352.79,"gestoria":203.00000000000006},{"importe":90001.0,"notaria":709.8,"registro":360.89,"gestoria":208.80000000000007},{"importe":95001.0,"notaria":720.6,"registro":368.99,"gestoria":214.60000000000008},{"importe":100001.0,"notaria":731.4,"registro":377.09,"gestoria":220.4000000000001},{"importe":105001.0,"notaria":742.2,"registro":385.19,"gestoria":226.2000000000001},{"importe":110001.0,"notaria":753.0,"registro":393.29,"gestoria":232.0000000000001},{"importe":115001.0,"notaria":763.8,"registro":401.39,"gestoria":237.80000000000013},{"importe":120001.0,"notaria":774.6,"registro":409.49,"gestoria":243.60000000000014},{"importe":125001.0,"notaria":785.4,"registro":417.59,"gestoria":249.40000000000015},{"importe":130001.0,"notaria":796.2,"registro":425.69,"gestoria":255.20000000000016},{"importe":135001.0,"notaria":807.0,"registro":433.79,"gestoria":261.00000000000017},{"importe":140001.0,"notaria":817.8,"registro":441.89,"gestoria":266.8000000000002},{"importe":145001.0,"notaria":828.6,"registro":449.99,"gestoria":272.6000000000002},{"importe":150001.0,"notaria":834.28,"registro":458.09,"gestoria":278.4000000000002},{"importe":155001.0,"notaria":839.68,"registro":466.19,"gestoria":284.2000000000002},{"importe":160001.0,"notaria":845.08,"registro":474.29,"gestoria":290.0000000000002},{"importe":165001.0,"notaria":850.48,"registro":482.39,"gestoria":295.80000000000024},{"importe":170001.0,"notaria":855.88,"registro":490.49,"gestoria":301.60000000000025},{"importe":175001.0,"notaria":861.28,"registro":498.59,"gestoria":307.40000000000026},{"importe":180001.0,"notaria":866.68,"registro":506.69,"gestoria":313.2000000000003},{"importe":185001.0,"notaria":872.08,"registro":514.79,"gestoria":319.0000000000003},{"importe":190001.0,"notaria":877.48,"registro":522.89,"gestoria":324.8000000000003},{"importe":195001.0,"notaria":882.88,"registro":530.99,"gestoria":330.6000000000003},{"importe":200001.0,"notaria":888.28,"registro":539.09,"gestoria":336.4000000000003},{"importe":205001.0,"notaria":893.68,"registro":547.19,"gestoria":342.20000000000033},{"importe":210001.0,"notaria":899.08,"registro":555.29,"gestoria":348.0},{"importe":215001.0,"notaria":904.48,"registro":563.39,"gestoria":348.0},{"importe":220001.0,"notaria":909.88,"registro":571.49,"gestoria":348.0},{"importe":225001.0,"notaria":915.28,"registro":579.59,"gestoria":348.0},{"importe":230001.0,"notaria":920.68,"registro":587.69,"gestoria":348.0},{"importe":235001.0,"notaria":926.08,"registro":595.79,"gestoria":348.0},{"importe":240001.0,"notaria":931.48,"registro":603.89,"gestoria":348.0},{"importe":245001.0,"notaria":936.88,"registro":611.99,"gestoria":348.0}];

const finSimLookupHipoteca = (amount, key) => {
  if (!Number.isFinite(amount) || amount <= 0) {
    return 0;
  }
  let last = FIN_SIM_HIPOTECA_TARIFAS[0];
  for (const row of FIN_SIM_HIPOTECA_TARIFAS) {
    if (amount >= row.importe) {
      last = row;
    } else {
      break;
    }
  }
  return last[key] || 0;
};

const finSimYes = (value) => String(value || "").trim().toLowerCase().startsWith("s");

const finSimPmt = (rate, nper, pv) => {
  if (!Number.isFinite(rate) || !Number.isFinite(nper) || !Number.isFinite(pv) || nper === 0) {
    return 0;
  }
  if (rate === 0) {
    return -(pv / nper);
  }
  return -(rate * pv) / (1 - Math.pow(1 + rate, -nper));
};

const NOTARIA_LIMIT = 6010121.04;
const REGISTRO_MAX = 2181.673939;
const REGISTRO_MIN = 24.040484;

const finSimNotariaScale = (amount) => {
  if (!Number.isFinite(amount) || amount <= 0) return 0;
  const tramos = [
    { min: 0, max: 6010.12, fixed: 90.151816 },
    { min: 6010.12, max: 30050.61, rate: 0.0045 },
    { min: 30050.61, max: 60101.21, rate: 0.0015 },
    { min: 60101.21, max: 150253.03, rate: 0.001 },
    { min: 150253.03, max: 601012.1, rate: 0.0005 },
    { min: 601012.1, max: NOTARIA_LIMIT, rate: 0.0003 },
  ];
  let total = 0;
  if (amount <= tramos[0].max) {
    return tramos[0].fixed;
  }
  total += tramos[0].fixed;
  for (let i = 1; i < tramos.length; i += 1) {
    const tramo = tramos[i];
    if (amount <= tramo.min) break;
    const upper = Math.min(amount, tramo.max);
    total += (upper - tramo.min) * tramo.rate;
    if (amount <= tramo.max) break;
  }
  return total;
};

const finSimRegistroScale = (amount) => {
  if (!Number.isFinite(amount) || amount <= 0) return 0;
  const tramos = [
    { min: 0, max: 6010.12, fixed: 24.040484 },
    { min: 6010.12, max: 30050.61, rate: 0.00175 },
    { min: 30050.61, max: 60101.21, rate: 0.00125 },
    { min: 60101.21, max: 150253.03, rate: 0.00075 },
    { min: 150253.03, max: 601012.1, rate: 0.0003 },
    { min: 601012.1, max: Infinity, rate: 0.0002 },
  ];
  let total = 0;
  if (amount <= tramos[0].max) {
    return tramos[0].fixed;
  }
  total += tramos[0].fixed;
  for (let i = 1; i < tramos.length; i += 1) {
    const tramo = tramos[i];
    if (amount <= tramo.min) break;
    const upper = Math.min(amount, tramo.max);
    total += (upper - tramo.min) * tramo.rate;
    if (amount <= tramo.max) break;
  }
  return Math.max(REGISTRO_MIN, Math.min(total, REGISTRO_MAX));
};

const finSimNotariaTotal = (amount, isHipoteca = false) => {
  let total = finSimNotariaScale(amount);
  // Rebaja general del 5% (RD 1612/2011) y adicional del 25% en hipotecas (RD 1426/1989).
  total *= 0.95;
  if (isHipoteca) total *= 0.75;
  return total;
};

const finSimRegistroTotal = (amount, isHipoteca = false) => {
  let total = finSimRegistroScale(amount);
  // Rebaja del 5% en hipotecas y compraventa de vivienda (RDL 6/2000).
  total *= 0.95;
  if (isHipoteca) total *= 0.75;
  return total;
};

const initFinSimulator = () => {
  const form = document.getElementById("finSimForm");
  if (!form) return;
  if (form.dataset.ready === "1") {
    return;
  }
  form.dataset.ready = "1";
  bindMoneyInputs(form);
  const formatMoneyInputs = () => {
    const moneyInputs = form.querySelectorAll("input[data-money='1']");
    moneyInputs.forEach((input) => {
      if (document.activeElement === input) return;
      const num = toNumber(input.value);
      if (num !== null) input.value = euroFormatter.format(num);
    });
  };
  const autoState = {
    lastEdited: "",
    manual: {
      escrituracion: false,
      hipoteca: false,
      entrada: false,
      finPct: false,
    },
  };
  const markManual = (name, key) => {
    const input = form.querySelector(`[name="${name}"]`);
    if (!input) return;
    input.addEventListener("input", () => {
      autoState.manual[key] = true;
      autoState.lastEdited = key;
    });
  };
  markManual("sim_escrituracion", "escrituracion");
  markManual("sim_hipoteca_importe", "hipoteca");
  markManual("sim_entrada", "entrada");
  markManual("sim_fin_pct", "finPct");
  const finPctQuick = document.getElementById("simFinPctQuick");
  if (finPctQuick && finPctQuick.dataset.bound !== "1") {
    finPctQuick.dataset.bound = "1";
    finPctQuick.addEventListener("change", () => {
      const raw = Number(finPctQuick.value);
      if (!Number.isFinite(raw) || raw <= 0) return;
      const input = form.querySelector('[name="sim_fin_pct"]');
      if (!input) return;
      input.value = String(raw * 100);
      autoState.manual.finPct = true;
      autoState.lastEdited = "finPct";
      form.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }
  const setDefault = (name, value) => {
    const input = form.querySelector(`[name="${name}"]`);
    if (!input) return;
    if (input.value !== "") return;
    input.value = value;
  };
  setDefault("sim_promo_nueva", "");
  setDefault("sim_tecnocasa", "");
  setDefault("sim_intervinientes", "");
  setDefault("sim_comision_modernia", "");
  setDefault("sim_compra_venta", "");
  setDefault("sim_interes_ratio", "");
  setDefault("sim_hipoteca_importe", "");
  setDefault("sim_interes_salida", "");
  setDefault("sim_escrituracion", "");
  setDefault("sim_tasacion_valor", "");
  setDefault("sim_fin_pct", "");
  setDefault("sim_base_bancaria", "");
  setDefault("sim_revision", "");
  setDefault("sim_bonificacion", "");
  setDefault("sim_iva_tecnocasa", "");
  setDefault("sim_inmobiliaria_pct", "");
  setDefault("sim_com_apertura", "");
  setDefault("sim_tasacion", "");
  setDefault("sim_seguros", "");
  setDefault("sim_cuota_vigente", "");
  setDefault("sim_entrada", "");
  setDefault("sim_otros", "");
  formatMoneyInputs();

  const moneyText = (value) => {
    if (value === null || value === undefined || Number.isNaN(value)) return "";
    return euroFormatter.format(value);
  };
  const setMoneyInput = (name, value) => {
    const input = form.querySelector(`[name="${name}"]`);
    if (!input) return;
    if (document.activeElement === input) return;
    input.value = euroFormatter.format(value || 0);
  };
  const setPercentInput = (name, value) => {
    const input = form.querySelector(`[name="${name}"]`);
    if (!input) return;
    if (document.activeElement === input) return;
    if (!Number.isFinite(value) || value <= 0) {
      input.value = "";
      return;
    }
    input.value = String((value * 100).toFixed(2)).replace(/\.00$/, "");
  };
  const setText = (id, value, money = true) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (typeof value === "string") {
      el.textContent = value;
      return;
    }
    el.textContent = money ? moneyText(value) : String(value ?? "");
  };

  const calculate = () => {
    const getVal = (name) => form.querySelector(`[name="${name}"]`)?.value;
    const num = (name) => {
      const n = toNumber(getVal(name));
      return Number.isNaN(n) || n === null ? 0 : n;
    };
    const promoNueva = finSimYes(getVal("sim_promo_nueva"));
    const tecnocasa = finSimYes(getVal("sim_tecnocasa"));
    const bonificacion = finSimYes(getVal("sim_bonificacion"));
    const ivaTecno = finSimYes(getVal("sim_iva_tecnocasa"));
    const ley2019 = true;
    const intervinientes = num("sim_intervinientes") || 1;

    const compraVenta = num("sim_compra_venta");
    const interesRatio = num("sim_interes_ratio");
    let hipotecaImporte = num("sim_hipoteca_importe");
    const interesSalida = num("sim_interes_salida");
    let escrituracion = num("sim_escrituracion");
    const tasacionValor = num("sim_tasacion_valor");
    let finPct = num("sim_fin_pct");
    if (finPct > 1.5) finPct = finPct / 100;
    if (finPct > 1) finPct = 1;
    if (finPct < 0) finPct = 0;
    const revision = num("sim_revision");
    let inmobiliariaPct = num("sim_inmobiliaria_pct");
    if (inmobiliariaPct > 1) {
      inmobiliariaPct = inmobiliariaPct / 100;
    }
    let comApertura = num("sim_com_apertura");
    if (comApertura > 0.2) {
      comApertura = comApertura / 100;
    }
    const comisionModernia = num("sim_comision_modernia");
    const tasacion = num("sim_tasacion");
    const segurosImporte = num("sim_seguros");
    const cuotaVigente = num("sim_cuota_vigente");
    const entrada = num("sim_entrada");
    const otros = num("sim_otros");

    if (!autoState.manual.escrituracion && compraVenta > 0) {
      escrituracion = compraVenta;
      setMoneyInput("sim_escrituracion", escrituracion);
    }
    const baseBancariaRaw =
      tasacionValor > 0 ? Math.min(escrituracion, tasacionValor) : escrituracion;
    const baseBancaria = baseBancariaRaw || 0;
    setMoneyInput("sim_base_bancaria", baseBancaria);

    const cvNotaria = finSimNotariaTotal(escrituracion, false);
    const cvRegistro = finSimRegistroTotal(escrituracion, false);
    const cvGestoria = escrituracion * 0.0027;
    const cvIvaLabel = promoNueva ? "IVA" : "ITP";
    const cvIva = escrituracion * (promoNueva ? (bonificacion ? 0.07 : 0.1) : (bonificacion ? 0.035 : 0.07));
    const baseInmobiliaria = compraVenta > 0 ? compraVenta : escrituracion;
    const cvTecnocasaBase = baseInmobiliaria * (inmobiliariaPct || 0);
    const cvTecnocasa = tecnocasa ? cvTecnocasaBase * (ivaTecno ? 1.21 : 1) : 0;
    const cvAjd = promoNueva ? escrituracion * 0.015 : 0;
    const cvTotal = cvNotaria + cvRegistro + cvGestoria + cvIva + cvTecnocasa + cvAjd;

    const calcHipotecaGastos = (importeHipoteca) => {
      const hipNotaria = ley2019 ? 0 : finSimNotariaTotal(importeHipoteca, true);
      const hipRegistro = ley2019 ? 0 : finSimRegistroTotal(importeHipoteca, true);
      const hipGestoria = ley2019 ? 0 : finSimLookupHipoteca(importeHipoteca, "gestoria");
      const hipAjd = ley2019 ? 0 : importeHipoteca * (bonificacion ? (importeHipoteca < 130001 ? 0.0054 : 0.027) : 0.027);
      const hipComApertura = importeHipoteca * comApertura;
      const hipTasacion = tasacion;
      const hipSeguros = segurosImporte || 0;
      const hipKiron = comisionModernia;
      const hipTotal = hipNotaria + hipRegistro + hipGestoria + hipAjd + hipComApertura + hipTasacion + hipSeguros + hipKiron;
      return { hipNotaria, hipRegistro, hipGestoria, hipAjd, hipComApertura, hipTasacion, hipSeguros, hipKiron, hipTotal };
    };

    const solveHipotecaFromEntrada = (entradaObjetivo) => {
      let guess = baseBancaria && finPct ? baseBancaria * finPct : hipotecaImporte || 0;
      for (let i = 0; i < 6; i += 1) {
        const { hipTotal } = calcHipotecaGastos(guess);
        const nuevo = compraVenta + cvTotal + hipTotal + otros - entradaObjetivo;
        if (!Number.isFinite(nuevo)) break;
        guess = nuevo;
      }
      return guess;
    };

    if (autoState.lastEdited === "entrada") {
      hipotecaImporte = solveHipotecaFromEntrada(entrada);
      if (baseBancaria) {
        finPct = hipotecaImporte / baseBancaria;
        if (finPct > 1) finPct = 1;
        setPercentInput("sim_fin_pct", finPct);
      }
    } else if (autoState.lastEdited === "hipoteca") {
      if (baseBancaria) {
        finPct = hipotecaImporte / baseBancaria;
        if (finPct > 1) finPct = 1;
        setPercentInput("sim_fin_pct", finPct);
      }
    } else {
      if (baseBancaria && finPct) {
        hipotecaImporte = baseBancaria * finPct;
      }
    }

    if (autoState.lastEdited !== "hipoteca") {
      setMoneyInput("sim_hipoteca_importe", hipotecaImporte);
    }

    const {
      hipNotaria,
      hipRegistro,
      hipGestoria,
      hipAjd,
      hipComApertura,
      hipTasacion,
      hipSeguros,
      hipKiron,
      hipTotal,
    } = calcHipotecaGastos(hipotecaImporte);

    const totalGastos = cvTotal + hipTotal;
    const precioCv = compraVenta;
    const gastos = totalGastos;
    const totalHipoteca = precioCv + gastos + otros;
    let entradaCalc = entrada;
    if (autoState.lastEdited !== "entrada") {
      entradaCalc = totalHipoteca - hipotecaImporte;
      setMoneyInput("sim_entrada", entradaCalc);
    }
    const faltante = totalHipoteca - entradaCalc - hipotecaImporte;

    const cuotaCarencia = hipotecaImporte * interesSalida / 12;
    const cuotas = {
      5: finSimPmt(interesSalida / 12, 5 * 12, -hipotecaImporte),
      10: finSimPmt(interesSalida / 12, 10 * 12, -hipotecaImporte),
      15: finSimPmt(interesSalida / 12, 15 * 12, -hipotecaImporte),
      18: finSimPmt(interesSalida / 12, 18 * 12, -hipotecaImporte),
      20: finSimPmt(interesSalida / 12, 20 * 12, -hipotecaImporte),
      25: finSimPmt(interesSalida / 12, 25 * 12, -hipotecaImporte),
      30: finSimPmt(interesSalida / 12, 30 * 12, -hipotecaImporte),
      35: finSimPmt(interesSalida / 12, 35 * 12, -hipotecaImporte),
      40: finSimPmt(interesSalida / 12, 40 * 12, -hipotecaImporte),
    };

    const ratio = 0.35;
    const ingresos = {
      5: (finSimPmt(interesRatio / 12, 5 * 12, -hipotecaImporte) + cuotaVigente) / ratio,
      10: (finSimPmt(interesRatio / 12, 10 * 12, -hipotecaImporte) + cuotaVigente) / ratio,
      15: (finSimPmt(interesRatio / 12, 15 * 12, -hipotecaImporte) + cuotaVigente) / ratio,
      20: (finSimPmt(interesRatio / 12, 20 * 12, -hipotecaImporte) + cuotaVigente) / ratio,
      25: (finSimPmt(interesRatio / 12, 25 * 12, -hipotecaImporte) + cuotaVigente) / ratio,
      30: (finSimPmt(interesRatio / 12, 30 * 12, -hipotecaImporte) + cuotaVigente) / ratio,
      35: (finSimPmt(interesRatio / 12, 35 * 12, -hipotecaImporte) + cuotaVigente) / ratio,
      40: (finSimPmt(interesRatio / 12, 40 * 12, -hipotecaImporte) + cuotaVigente) / ratio,
    };


    const ivaLabel = document.getElementById("simCvIvaLabel");
    if (ivaLabel) ivaLabel.textContent = cvIvaLabel;

    setText("simCvNotaria", cvNotaria);
    setText("simCvRegistro", cvRegistro);
    setText("simCvGestoria", cvGestoria);
    setText("simCvIva", cvIva);
    setText("simCvTecnocasa", cvTecnocasa);
    setText("simCvAjd", cvAjd);
    setText("simCvTotal", cvTotal);

    setText("simHipNotaria", hipNotaria);
    setText("simHipRegistro", hipRegistro);
    setText("simHipGestoria", hipGestoria);
    setText("simHipAjd", hipAjd);
    setText("simHipComApertura", hipComApertura);
    setText("simHipTasacion", hipTasacion);
    setText("simHipSeguros", hipSeguros);
    setText("simHipKiron", hipKiron);
    setText("simHipTotal", hipTotal);

    setText("simTotalGastos", totalGastos);
    setText("simPrecioCv", precioCv);
    setText("simGastos", gastos);
    setText("simEntrada", entradaCalc);
    setText("simOtros", otros);
    setText("simTotalHipoteca", totalHipoteca);
    setText("simFaltante", faltante);

    setText("simCarencia", cuotaCarencia);
    setText("simCuota5", cuotas[5]);
    setText("simCuota10", cuotas[10]);
    setText("simCuota15", cuotas[15]);
    setText("simCuota18", cuotas[18]);
    setText("simCuota20", cuotas[20]);
    setText("simCuota25", cuotas[25]);
    setText("simCuota30", cuotas[30]);
    setText("simCuota35", cuotas[35]);
    setText("simCuota40", cuotas[40]);

    setText("simIng5", ingresos[5]);
    setText("simIng10", ingresos[10]);
    setText("simIng15", ingresos[15]);
    setText("simIng20", ingresos[20]);
    setText("simIng25", ingresos[25]);
    setText("simIng30", ingresos[30]);
    setText("simIng35", ingresos[35]);
    setText("simIng40", ingresos[40]);

    const interesFuturo = interesSalida + revision;
    const rev = {
      20: finSimPmt(interesFuturo / 12, 20 * 12, -hipotecaImporte),
      25: finSimPmt(interesFuturo / 12, 25 * 12, -hipotecaImporte),
      30: finSimPmt(interesFuturo / 12, 30 * 12, -hipotecaImporte),
      35: finSimPmt(interesFuturo / 12, 35 * 12, -hipotecaImporte),
      40: finSimPmt(interesFuturo / 12, 40 * 12, -hipotecaImporte),
    };
    setText("simRev20", rev[20]);
    setText("simRev25", rev[25]);
    setText("simRev30", rev[30]);
    setText("simRev35", rev[35]);
    setText("simRev40", rev[40]);
    setText("simRevExtra", "");
    setText("simRevAniosExtra", "");

    formatMoneyInputs();
  };

  form.addEventListener("input", calculate);
  form.addEventListener("change", calculate);
  calculate();
};

const normalizeDateInput = (value) => {
  if (!value) {
    return "";
  }
  const text = String(value).trim();
  if (!text) {
    return "";
  }
  if (text.includes("/")) {
    const parts = text.split(/[\\/.-]/).map((part) => part.trim());
    if (parts.length >= 3) {
      const [day, month, yearRaw] = parts;
      if (day && month && yearRaw) {
        const year = yearRaw.length === 2 ? `20${yearRaw}` : yearRaw;
        return `${year.padStart(4, "0")}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
      }
    }
  }
  if (text.includes("-")) {
    return text;
  }
  return "";
};

const addOneYear = (dateValue) => {
  const normalized = normalizeDateInput(dateValue);
  if (!normalized) {
    return "";
  }
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  date.setFullYear(date.getFullYear() + 1);
  return date.toISOString().slice(0, 10);
};

const MONEY_COLUMNS = new Set([
  "precio",
  "precio_objetivo",
  "precio_valoracion",
  "importe_hipoteca",
  "entrada",
  "comision",
  "comision_juan",
  "comision_modernia",
  "cesion",
  "ingresos_conjuntos",
  "cliente1_ingresos",
  "cliente2_ingresos",
  "aportacion_cv",
]);

const formatCell = (col, value, tipoPersona = "") => {
  const lower = col.toLowerCase();
  if (["nif", "dni", "cif"].includes(lower)) {
    return normalizeDocumento(value);
  }
  const isNombreCol =
    lower === "nombre" ||
    lower === "cliente" ||
    lower === "tomador" ||
    lower.endsWith("_nombre") ||
    (lower.includes("nombre") && !lower.includes("empresa")) ||
    (lower.includes("cliente") && !lower.includes("cliente_id"));
  if (isNombreCol) {
    return formatNombreCliente(value, tipoPersona);
  }
  if (MONEY_COLUMNS.has(lower) || lower.includes("comision")) {
    const number = toNumber(value);
    return number === null ? value : euroFormatter.format(number);
  }
  if (lower.includes("porcentaje")) {
    const number = toNumber(value);
    if (number === null) return value;
    const normalized = number > 0 && number <= 1 ? number * 100 : number;
    return `${normalized.toFixed(2)}%`;
  }
  return value;
};

const COMPANY_LOGOS = {
  ALLIANZ: "/assets/logos/allianz.svg",
  ADESLAS: "/assets/logos/adeslas.png",
  ARAG: "/assets/logos/arag.svg",
  AXA: "/assets/logos/axa.svg",
  CASER: "/assets/logos/caser.svg",
  "CATALANA OCCIDENTE": "/assets/logos/catalana-occidente.svg",
  DKV: "/assets/logos/dkv.svg",
  EUROINS: "/assets/logos/euroins.jpg",
  FIATC: "/assets/logos/fiatc.png",
  GALLEN: "/assets/logos/gallen.png",
  "GARANTIA YA": "/assets/logos/garantia-ya.png",
  GENERALI: "/assets/logos/generali.svg",
  "GES SEGUROS": "/assets/logos/ges.png",
  "LINEA DIRECTA": "/assets/logos/linea-directa.png",
  LLOYD: "/assets/logos/lloyds.svg",
  "LLOYD'S": "/assets/logos/lloyds.svg",
  MAPFRE: "/assets/logos/mapfre.svg",
  "MUTUA PROPIETARIOS": "/assets/logos/mutua-propietarios.jpg",
  OCASO: "/assets/logos/ocaso.png",
  OCCIDENT: "/assets/logos/occident.svg",
  PELAYO: "/assets/logos/pelayo.png",
  REALE: "/assets/logos/reale.jpg",
  SANITAS: "/assets/logos/sanitas.svg",
  "SANTA LUCIA": "/assets/logos/santalucia.svg",
  ZURICH: "/assets/logos/zurich.svg",
};

const COMPANY_ALIASES = {
  "ALLIANZ SEGUROS": "ALLIANZ",
  "MAPFRE SEGUROS": "MAPFRE",
  "ZURICH SEGUROS": "ZURICH",
  "SANTA LUCIA": "SANTA LUCIA",
  "SANTA LUCÍA": "SANTA LUCIA",
  "SEGURCAIXA ADESLAS": "ADESLAS",
  "SEGURCAIXA-ADESLAS": "ADESLAS",
  "FIACT": "FIATC",
  "FIACT SEGUROS": "FIATC",
  "FIATC SEGUROS": "FIATC",
  "LINEA DIRECTA": "LINEA DIRECTA",
  "LINEA DIRECTA ASEGURADORA": "LINEA DIRECTA",
  "LLOYDS": "LLOYD'S",
  "MUTUA PROPIETARIOS": "MUTUA PROPIETARIOS",
  "CATALANA OCCIDENTE": "CATALANA OCCIDENTE",
  "CATALANA OCCIDENT": "CATALANA OCCIDENTE",
  "CATALANA": "CATALANA OCCIDENTE",
};

const normalizeCompanyName = (value) => {
  if (!value) return "";
  let text = String(value).trim();
  text = text.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  text = text.toUpperCase();
  text = text.replace(/[^A-Z0-9 ]+/g, " ");
  text = text.replace(/\s+/g, " ").trim();
  return text;
};

const resolveCompanyKey = (value) => {
  const normalized = normalizeCompanyName(value);
  return COMPANY_ALIASES[normalized] || normalized;
};

const getCompanyLogo = (value) => {
  const key = resolveCompanyKey(value);
  return COMPANY_LOGOS[key] || "";
};

const getCompanyInitials = (value) => {
  const normalized = normalizeCompanyName(value);
  if (!normalized) return "";
  const parts = normalized.split(" ").filter(Boolean);
  if (!parts.length) return "";
  if (parts.length === 1) return parts[0].slice(0, 2);
  return `${parts[0][0]}${parts[1][0]}`.slice(0, 2);
};

const isCompanyColumn = (colName = "") => {
  const lower = colName.toLowerCase();
  return (
    lower.includes("compania") ||
    lower.includes("compañia") ||
    lower.includes("aseguradora") ||
    lower.includes("asegurador")
  );
};

const RAMO_ICONS = [
  { key: "hogar", icon: "🏠" },
  { key: "auto", icon: "🚗" },
  { key: "coche", icon: "🚗" },
  { key: "moto", icon: "🏍️" },
  { key: "salud", icon: "🩺" },
  { key: "vida", icon: "❤️" },
  { key: "decesos", icon: "⚰️" },
  { key: "comercio", icon: "🏬" },
  { key: "pyme", icon: "🏢" },
  { key: "empresa", icon: "🏢" },
  { key: "responsabilidad civil", icon: "🛡️" },
  { key: "rc", icon: "🛡️" },
  { key: "viaje", icon: "✈️" },
  { key: "impago", icon: "💳" },
  { key: "alquiler", icon: "🏘️" },
  { key: "accidentes", icon: "🦺" },
  { key: "mascotas", icon: "🐾" },
  { key: "dental", icon: "🦷" },
  { key: "ciber", icon: "🛡️" },
  { key: "embarcaciones", icon: "⛵" },
  { key: "subsidio", icon: "💶" },
];

const getRamoIcon = (value) => {
  const text = String(value || "").toLowerCase();
  if (!text) return "";
  const hit = RAMO_ICONS.find((item) => text.includes(item.key));
  return hit ? hit.icon : "📄";
};

const isRamoColumn = (colName = "") => colName.toLowerCase().includes("ramo");

const createRamoBadge = (value) => {
  const wrapper = document.createElement("span");
  wrapper.className = "ramo-badge";
  const icon = document.createElement("span");
  icon.className = "ramo-icon";
  icon.textContent = getRamoIcon(value);
  const label = document.createElement("span");
  label.textContent = value || "-";
  wrapper.appendChild(icon);
  wrapper.appendChild(label);
  return wrapper;
};

const applyRamoCell = (td, colName, value) => {
  if (!isRamoColumn(colName)) return false;
  td.appendChild(createRamoBadge(value));
  return true;
};

const createCompanyBadge = (value, options = {}) => {
  const name = String(value || "-").trim() || "-";
  const wrapper = document.createElement("span");
  wrapper.className = `company-badge${options.compact ? " compact" : ""}`;
  if (!name || name === "-") {
    wrapper.textContent = "-";
    return wrapper;
  }
  const logoUrl = getCompanyLogo(name);
  if (logoUrl) {
    const img = document.createElement("img");
    img.src = logoUrl;
    img.alt = name;
    img.loading = "lazy";
    img.decoding = "async";
    img.referrerPolicy = "no-referrer";
    img.className = "company-logo";
    img.addEventListener("error", () => {
      img.remove();
      if (!wrapper.querySelector(".company-initials")) {
        const initials = document.createElement("span");
        initials.className = "company-initials";
        initials.textContent = getCompanyInitials(name);
        wrapper.insertBefore(initials, wrapper.firstChild);
      }
    });
    wrapper.appendChild(img);
  } else {
    const initials = document.createElement("span");
    initials.className = "company-initials";
    initials.textContent = getCompanyInitials(name);
    wrapper.appendChild(initials);
  }
  const label = document.createElement("span");
  label.className = "company-name";
  label.textContent = name;
  wrapper.appendChild(label);
  return wrapper;
};

const applyCompanyCell = (td, colName, value, options = {}) => {
  if (!isCompanyColumn(colName)) return false;
  td.classList.add("company-cell");
  td.appendChild(createCompanyBadge(value, options));
  return true;
};

const filterRowsByQuery = (rows, query, fields = []) => {
  const q = (query || "").trim().toLowerCase();
  if (!q) return rows;
  return rows.filter((row) => {
    const values = fields.length
      ? fields.map((field) => row[field])
      : Object.values(row);
    return values.some((value) =>
      String(value || "").toLowerCase().includes(q)
    );
  });
};

const normalizeDocumento = (value) => {
  if (!value) return "";
  let text = String(value).toUpperCase().trim();
  text = text.replace(/\s+/g, "");
  text = text.replace(/DNI|NIF|CIF/g, "");
  text = text.replace(/[^A-Z0-9]/g, "");
  if (text.startsWith("ES") && text.length > 2) {
    text = text.slice(2);
  }
  return text;
};

const shouldReorderNombre = (value, tipoPersona = "") => {
  if (!value) return false;
  if (String(tipoPersona).toLowerCase() === "jurídica") return false;
  const text = String(value).trim();
  if (text.includes(",")) return false;
  const upper = text.toUpperCase();
  const companyTokens = [
    "SL",
    "S.L",
    "S.A",
    "SA",
    "SOCIEDAD",
    "COOP",
    "CB",
    "SCP",
    "ASOCIACION",
    "FUNDACION",
    "GRUPO",
  ];
  if (companyTokens.some((token) => upper.includes(token))) {
    return false;
  }
  if (/\d/.test(text)) return false;
  return true;
};

const formatNombreCliente = (value, tipoPersona = "") => {
  if (!value) return "";
  const text = String(value).trim();
  if (!shouldReorderNombre(text, tipoPersona)) return text;
  if (text.includes(",")) {
    const [left, right] = text.split(",").map((part) => part.trim());
    if (left && right) {
      return `${left} ${right}`.replace(/\s+/g, " ").trim();
    }
  }
  const parts = text.split(/\s+/).filter(Boolean);
  if (parts.length === 2) {
    return `${parts[1]} ${parts[0]}`;
  }
  if (parts.length >= 3) {
    const apellido1 = parts[parts.length - 2];
    const apellido2 = parts[parts.length - 1];
    const nombre = parts.slice(0, -2).join(" ");
    return `${apellido1} ${apellido2} ${nombre}`;
  }
  return text;
};

const normalizeNombre = (value) => {
  if (!value) return "";
  return String(value).toLowerCase().replace(/\s+/g, " ").trim();
};

const resolveClienteIdFromName = (value) => {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^[0-9a-f]{32}$/i.test(raw)) {
    return raw;
  }
  const target = normalizeNombre(raw);
  const clientes = Array.isArray(state.clientesList) ? state.clientesList : [];
  let match = clientes.find((c) => {
    const original = normalizeNombre(c.nombre);
    const formatted = normalizeNombre(formatNombreCliente(c.nombre));
    return original === target || formatted === target;
  });
  if (match) return match.id;
  match = clientes.find((c) => {
    const original = normalizeNombre(c.nombre);
    const formatted = normalizeNombre(formatNombreCliente(c.nombre));
    return original.includes(target) || formatted.includes(target) || target.includes(original);
  });
  return match ? match.id : "";
};

const splitNombreApellidos = (value, tipoPersona = "") => {
  const text = String(value || "").trim();
  if (!text) return { apellidos: "", nombre: "" };
  if (text.includes(",")) {
    const [left, right] = text.split(",").map((part) => part.trim());
    return { apellidos: left || "", nombre: right || "" };
  }
  if (!shouldReorderNombre(text, tipoPersona)) {
    return { apellidos: "", nombre: text };
  }
  const parts = text.split(/\s+/).filter(Boolean);
  if (parts.length >= 3) {
    return {
      apellidos: `${parts[parts.length - 2]} ${parts[parts.length - 1]}`,
      nombre: parts.slice(0, -2).join(" "),
    };
  }
  if (parts.length === 2) {
    return { apellidos: parts[1], nombre: parts[0] };
  }
  return { apellidos: "", nombre: parts[0] || "" };
};

const buildDisplayName = (payload) => {
  const tipoPersona = String(payload.tipo_persona || "").toLowerCase();
  const nombreBase = String(payload.nombre || "").trim();
  const apellido1 = String(payload.apellido1 || "").trim();
  const apellido2 = String(payload.apellido2 || "").trim();
  if (tipoPersona === "jurídica") {
    return nombreBase;
  }
  const apellidos = [apellido1, apellido2].filter(Boolean).join(" ").trim();
  return apellidos || nombreBase
    ? `${apellidos}${apellidos && nombreBase ? ", " : ""}${nombreBase}`.trim()
    : "";
};

const isValidDocumento = (value) => {
  const text = normalizeDocumento(value);
  if (!text) return true;
  const letras = "TRWAGMYFPDXBNJZSQVHLCKET";
  const dniMatch = text.match(/^(\d{8})([A-Z])$/);
  if (dniMatch) {
    const num = parseInt(dniMatch[1], 10);
    return letras[num % 23] === dniMatch[2];
  }
  const nieMatch = text.match(/^([XYZ])(\d{7})([A-Z])$/);
  if (nieMatch) {
    const map = { X: "0", Y: "1", Z: "2" };
    const num = parseInt(map[nieMatch[1]] + nieMatch[2], 10);
    return letras[num % 23] === nieMatch[3];
  }
  const cifMatch = text.match(/^([ABCDEFGHJNPQRSUVW])(\d{7})([0-9A-J])$/);
  if (cifMatch) {
    const letter = cifMatch[1];
    const numbers = cifMatch[2];
    const control = cifMatch[3];
    let sumEven = 0;
    let sumOdd = 0;
    numbers.split("").forEach((digit, idx) => {
      const n = parseInt(digit, 10);
      if ((idx + 1) % 2 === 0) {
        sumEven += n;
      } else {
        const prod = n * 2;
        sumOdd += Math.floor(prod / 10) + (prod % 10);
      }
    });
    const total = sumEven + sumOdd;
    const controlDigit = (10 - (total % 10)) % 10;
    const controlLetter = "JABCDEFGHI"[controlDigit];
    if ("PQRSNW".includes(letter)) {
      return control === controlLetter;
    }
    if ("ABEH".includes(letter)) {
      return control === String(controlDigit);
    }
    return control === String(controlDigit) || control === controlLetter;
  }
  return false;
};

const CRM_ETAPAS = [
  "Prospecto",
  "Contactado",
  "Visita/Valoración",
  "Negociación",
  "Encargo firmado",
  "Publicado",
  "Perdido",
];

const INMUEBLE_CHECKLISTS = {
  Prospecto: [
    "Registrar lead y origen",
    "Verificar datos del propietario",
    "Primera llamada de contacto",
    "Calificar interés",
  ],
  Contactado: [
    "Agendar visita/valoración",
    "Enviar dossier inicial",
    "Confirmar documentación básica",
    "Recoger datos registrales",
  ],
  "Visita/Valoración": [
    "Realizar visita",
    "Tomar fotos y medidas",
    "Preparar valoración",
    "Revisión de cargas",
  ],
  Negociación: [
    "Revisión de oferta",
    "Negociar honorarios",
    "Confirmar condiciones",
    "Validar documentación del propietario",
  ],
  "Encargo firmado": [
    "Firmar encargo",
    "Subir documentación",
    "Preparar anuncio",
    "Solicitar nota simple",
    "Verificar referencia catastral",
  ],
  Publicado: [
    "Publicar en portales",
    "Activar campaña de leads",
    "Planificar visitas",
    "Enviar reporte al propietario",
  ],
  Perdido: [
    "Registrar motivo pérdida",
    "Cerrar expediente",
    "Programar seguimiento futuro",
  ],
};

const INMUEBLE_FIELDS = [
  { key: "estado", label: "Estado", type: "select", options: CRM_ETAPAS },
  { key: "tipo_inmueble", label: "Tipo", type: "text" },
  { key: "zona", label: "Zona", type: "text" },
  { key: "direccion", label: "Dirección", type: "text" },
  { key: "m2", label: "m²", type: "number" },
  { key: "habitaciones", label: "Habitaciones", type: "number" },
  { key: "banos", label: "Baños", type: "number" },
  { key: "precio_objetivo", label: "Precio objetivo", type: "number" },
  { key: "precio_valoracion", label: "Precio valoración", type: "number" },
  { key: "valor_referencia", label: "Valor de referencia", type: "number" },
  { key: "referencia", label: "Referencia catastral", type: "text" },
  { key: "lat", label: "Latitud", type: "number" },
  { key: "lon", label: "Longitud", type: "number" },
];

const CAPTACION_FIELDS = [
  { key: "propietario", label: "Propietario", type: "text" },
  { key: "urgencia", label: "Urgencia", type: "select", options: ["Baja", "Media", "Alta"] },
  { key: "motivo", label: "Motivo", type: "text" },
  { key: "canal", label: "Canal", type: "text" },
  { key: "etapa", label: "Etapa", type: "select", options: CRM_ETAPAS },
  { key: "probabilidad", label: "Probabilidad (%)", type: "number" },
  { key: "proxima_accion", label: "Próxima acción", type: "text" },
  { key: "fecha_contacto", label: "Fecha contacto", type: "date" },
  { key: "asesor", label: "Asesor", type: "text" },
  { key: "notas", label: "Notas", type: "textarea" },
];

const CLIENTE_FIELDS = [
  { key: "tipo_persona", label: "Tipo persona", type: "select", options: ["Física", "Jurídica"] },
  { key: "apellidos", label: "Apellidos", type: "text" },
  { key: "nombre", label: "Nombre", type: "text" },
  { key: "nif", label: "NIF", type: "text" },
  { key: "telefono", label: "Teléfono", type: "text" },
  { key: "email", label: "Email", type: "text" },
  { key: "fecha_nacimiento", label: "Fecha nacimiento", type: "date" },
  { key: "direccion", label: "Dirección", type: "text" },
  { key: "codigo_postal", label: "Código postal", type: "text" },
  { key: "poblacion", label: "Población", type: "text" },
  { key: "provincia", label: "Provincia", type: "text" },
  {
    key: "perfil",
    label: "Perfil",
    type: "select",
    options: [
      "Autónomo",
      "Empresa",
      "Comunidad",
      "Particular",
      "Comprador",
      "Vendedor",
      "Inquilino",
      "Arrendador",
      "Promotor",
      "Inversor",
    ],
  },
  { key: "estado", label: "Estado", type: "text" },
];

const SERVICE_OPTIONS = [
  "Inmobiliaria",
  "Gestoría",
  "Administración Fincas",
  "Seguros",
  "Hipotecas",
  "Obras",
  "Inversión",
];

const SERVICE_LABELS = {
  inmobiliaria: "Inmobiliaria",
  gestoria: "Gestoría",
  fincas: "Administración Fincas",
  seguros: "Seguros",
  financiaciones: "Hipotecas",
  hipotecas: "Hipotecas",
  obras: "Obras",
  inversion: "Inversión",
  clientes: "Clientes",
};

const SERVICE_COMPANY_MAP = {
  Inmobiliaria: "Estudio Velazquez 2012 SL",
  "Gestoría": "Fincas Velazquez",
  "Administración Fincas": "Fincas Velazquez",
  Seguros: "Fincas Velazquez",
  Hipotecas: "Financiaciones Modernia",
  Obras: "Grupo Modernia",
  Inversión: "Inversure",
};

const POSTAL_PROVINCES = {
  "01": { provincia: "Álava", poblacion: "Vitoria-Gasteiz" },
  "02": { provincia: "Albacete", poblacion: "Albacete" },
  "03": { provincia: "Alicante", poblacion: "Alicante" },
  "04": { provincia: "Almería", poblacion: "Almería" },
  "05": { provincia: "Ávila", poblacion: "Ávila" },
  "06": { provincia: "Badajoz", poblacion: "Badajoz" },
  "07": { provincia: "Islas Baleares", poblacion: "Palma" },
  "08": { provincia: "Barcelona", poblacion: "Barcelona" },
  "09": { provincia: "Burgos", poblacion: "Burgos" },
  "10": { provincia: "Cáceres", poblacion: "Cáceres" },
  "11": { provincia: "Cádiz", poblacion: "Cádiz" },
  "12": { provincia: "Castellón", poblacion: "Castellón" },
  "13": { provincia: "Ciudad Real", poblacion: "Ciudad Real" },
  "14": { provincia: "Córdoba", poblacion: "Córdoba" },
  "15": { provincia: "A Coruña", poblacion: "A Coruña" },
  "16": { provincia: "Cuenca", poblacion: "Cuenca" },
  "17": { provincia: "Girona", poblacion: "Girona" },
  "18": { provincia: "Granada", poblacion: "Granada" },
  "19": { provincia: "Guadalajara", poblacion: "Guadalajara" },
  "20": { provincia: "Guipúzcoa", poblacion: "San Sebastián" },
  "21": { provincia: "Huelva", poblacion: "Huelva" },
  "22": { provincia: "Huesca", poblacion: "Huesca" },
  "23": { provincia: "Jaén", poblacion: "Jaén" },
  "24": { provincia: "León", poblacion: "León" },
  "25": { provincia: "Lleida", poblacion: "Lleida" },
  "26": { provincia: "La Rioja", poblacion: "Logroño" },
  "27": { provincia: "Lugo", poblacion: "Lugo" },
  "28": { provincia: "Madrid", poblacion: "Madrid" },
  "29": { provincia: "Málaga", poblacion: "Málaga" },
  "30": { provincia: "Murcia", poblacion: "Murcia" },
  "31": { provincia: "Navarra", poblacion: "Pamplona" },
  "32": { provincia: "Ourense", poblacion: "Ourense" },
  "33": { provincia: "Asturias", poblacion: "Oviedo" },
  "34": { provincia: "Palencia", poblacion: "Palencia" },
  "35": { provincia: "Las Palmas", poblacion: "Las Palmas de Gran Canaria" },
  "36": { provincia: "Pontevedra", poblacion: "Pontevedra" },
  "37": { provincia: "Salamanca", poblacion: "Salamanca" },
  "38": { provincia: "Santa Cruz de Tenerife", poblacion: "Santa Cruz de Tenerife" },
  "39": { provincia: "Cantabria", poblacion: "Santander" },
  "40": { provincia: "Segovia", poblacion: "Segovia" },
  "41": { provincia: "Sevilla", poblacion: "Sevilla" },
  "42": { provincia: "Soria", poblacion: "Soria" },
  "43": { provincia: "Tarragona", poblacion: "Tarragona" },
  "44": { provincia: "Teruel", poblacion: "Teruel" },
  "45": { provincia: "Toledo", poblacion: "Toledo" },
  "46": { provincia: "Valencia", poblacion: "Valencia" },
  "47": { provincia: "Valladolid", poblacion: "Valladolid" },
  "48": { provincia: "Vizcaya", poblacion: "Bilbao" },
  "49": { provincia: "Zamora", poblacion: "Zamora" },
  "50": { provincia: "Zaragoza", poblacion: "Zaragoza" },
  "51": { provincia: "Ceuta", poblacion: "Ceuta" },
  "52": { provincia: "Melilla", poblacion: "Melilla" },
};

const normalizePostalCode = (value) => String(value || "").replace(/\D/g, "").slice(0, 5);

const getPostalInfo = (value) => {
  const code = normalizePostalCode(value);
  if (code.length < 2) return null;
  const provinceKey = code.slice(0, 2);
  return POSTAL_PROVINCES[provinceKey] || null;
};

const postalCache = new Map();

const fetchPostalLookup = (value) => {
  const code = normalizePostalCode(value);
  if (!code) return Promise.resolve(null);
  if (postalCache.has(code)) {
    return Promise.resolve(postalCache.get(code));
  }
  return api(`/api/postal_lookup?cp=${encodeURIComponent(code)}`)
    .then((data) => {
      if (!data || data.error) return null;
      if (data.provincia || data.poblacion) {
        postalCache.set(code, data);
        return data;
      }
      return null;
    })
    .catch(() => null);
};

const bindPostalLookup = (formEl) => {
  if (!formEl) return;
  const postalInput = formEl.querySelector('[name="codigo_postal"]');
  const poblacionInput = formEl.querySelector('[name="poblacion"]');
  const provinciaInput = formEl.querySelector('[name="provincia"]');
  if (!postalInput || !poblacionInput || !provinciaInput) return;
  let poblacionSelect = null;
  const label = poblacionInput.closest("label");
  if (label) {
    poblacionSelect = document.createElement("select");
    poblacionSelect.className = "postal-options hidden";
    poblacionSelect.appendChild(createOption("", "Selecciona población"));
    label.appendChild(poblacionSelect);
    poblacionSelect.addEventListener("change", () => {
      const value = poblacionSelect.value;
      if (!value) return;
      poblacionInput.value = value;
      poblacionInput.dataset.auto = "0";
      if (poblacionSelect.dataset.provincia && provinciaInput) {
        provinciaInput.value = poblacionSelect.dataset.provincia;
      }
    });
  }
  poblacionInput.addEventListener("input", () => {
    poblacionInput.dataset.auto = "0";
  });
  const applyPostal = () => {
    const fallback = getPostalInfo(postalInput.value);
    fetchPostalLookup(postalInput.value).then((info) => {
      const resolved = info || fallback;
      if (!resolved) return;
      const provinciaValue = resolved.provincia || fallback?.provincia || "";
      const poblacionValue = resolved.poblacion || fallback?.poblacion || "";
      if (provinciaInput && provinciaValue) {
        provinciaInput.value = provinciaValue;
      }
      if (poblacionInput && poblacionValue) {
        const shouldAuto =
          !poblacionInput.value || poblacionInput.dataset.auto === "1";
        if (shouldAuto) {
          poblacionInput.value = poblacionValue;
          poblacionInput.dataset.auto = "1";
        }
      }
      if (poblacionSelect) {
        const options = (info && info.opciones) || [];
        const unique = Array.from(
          new Set(options.map((opt) => opt.poblacion).filter(Boolean))
        );
        poblacionSelect.innerHTML = "";
        poblacionSelect.appendChild(createOption("", "Selecciona población"));
        unique.forEach((name) => {
          poblacionSelect.appendChild(createOption(name, name));
        });
        if (unique.length > 1) {
          poblacionSelect.classList.remove("hidden");
          poblacionSelect.dataset.provincia = provinciaValue || "";
        } else {
          poblacionSelect.classList.add("hidden");
          poblacionSelect.dataset.provincia = "";
        }
      }
    });
  };
  postalInput.addEventListener("input", () => {
    postalInput.value = normalizePostalCode(postalInput.value);
    applyPostal();
  });
  postalInput.addEventListener("blur", () => {
    postalInput.value = normalizePostalCode(postalInput.value);
    applyPostal();
  });
};

const GESTORIA_SUBTIPOS = {
  "Cuota mensual": ["Autónomo", "Empresa"],
  "Gestión administrativa": ["Cliente Renta", "Gestiones Administrativas", "Renta", "Puntual"],
};

const sumTotals = (items) =>
  items.reduce((acc, item) => acc + (item.total || 0), 0);

const getYearValueFromSeries = (series, year) => {
  const target = normalizeYear(year);
  const entry = series.find((item) => normalizeYear(item.year) === target);
  return entry ? entry.total || 0 : 0;
};

const computeVariations = (series) => {
  const sorted = [...series]
    .filter((item) => item.year !== null && item.year !== undefined)
    .map((item) => ({ year: normalizeYear(item.year), total: item.total || 0 }))
    .sort((a, b) => Number(a.year) - Number(b.year));
  const output = [];
  for (let i = 1; i < sorted.length; i += 1) {
    const prev = sorted[i - 1].total;
    const current = sorted[i].total;
    const change = prev === 0 ? 0 : ((current - prev) / prev) * 100;
    output.push({ year: sorted[i].year, total: change });
  }
  return output;
};

const buildYearIndex = (series) => {
  const years = new Set();
  series.forEach((items) =>
    items.forEach((item) => {
      const normalized = normalizeYear(item.year);
      if (normalized) {
        years.add(normalized);
      }
    })
  );
  return Array.from(years).sort();
};

const alignSeries = (years, items) => {
  const lookup = new Map(
    items.map((item) => [normalizeYear(item.year), item.total])
  );
  return years.map((year) => lookup.get(normalizeYear(year)) || 0);
};

const prepareCanvas = (canvas) => {
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  let width = rect.width;
  let height = rect.height;
  if (width < 10 || height < 10) {
    const parent = canvas.parentElement;
    const parentWidth = parent ? parent.clientWidth : 0;
    width = parentWidth && parentWidth > 10 ? parentWidth : 600;
    height = height && height > 10 ? height : 300;
  }
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  return ctx;
};

const drawBarChart = (canvas, labels, datasets, options = {}) => {
  if (!canvas) return;
  const ctx = prepareCanvas(canvas);
  const width = canvas.getBoundingClientRect().width;
  const height = canvas.getBoundingClientRect().height;
  ctx.clearRect(0, 0, width, height);

  const padding = {
    top: 22,
    right: 18,
    bottom: 92,
    left: 32,
  };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const maxValue = Math.max(
    1,
    ...datasets.flatMap((set) => set.values.map((val) => Math.abs(val)))
  );

  const gridLines = 4;
  ctx.strokeStyle = "#efe9df";
  ctx.lineWidth = 1;
  for (let i = 0; i <= gridLines; i += 1) {
    const y = padding.top + (chartHeight / gridLines) * i;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
  }

  ctx.strokeStyle = "#e6e0d6";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padding.left, padding.top);
  ctx.lineTo(padding.left, height - padding.bottom);
  ctx.lineTo(width - padding.right, height - padding.bottom);
  ctx.stroke();

  const groupWidth = chartWidth / Math.max(1, labels.length);
  const barWidth = Math.max(6, (groupWidth - 18) / datasets.length);

  labels.forEach((label, i) => {
    const xBase = padding.left + i * groupWidth;
    datasets.forEach((dataset, j) => {
      const value = dataset.values[i];
      const barHeight = (Math.abs(value) / maxValue) * chartHeight;
      const x = xBase + 5 + j * barWidth;
      const y = height - padding.bottom - barHeight;
      ctx.fillStyle = dataset.color;
      ctx.fillRect(x, y, barWidth, barHeight);

      if (options.showValues) {
        const labelText = dataset.format
          ? dataset.format(value)
          : numberFormatter.format(value);
        ctx.font = "10px Baskerville, serif";
        const textWidth = ctx.measureText(labelText).width;
        const textX = x + (barWidth - textWidth) / 2;
        const textY = y + 14;
        ctx.fillStyle = "#ffffff";
        ctx.strokeStyle = "rgba(0,0,0,0.15)";
        ctx.lineWidth = 2;
        ctx.strokeText(labelText, textX, textY);
        ctx.fillText(labelText, textX, textY);
      }
    });

    const labelText = String(label);
    const shouldRotate = labels.length > 8 || groupWidth < 40;
    const shouldSkip = labels.length > 14 && i % 2 === 1;
    if (!shouldSkip) {
      ctx.fillStyle = "#6d665a";
      ctx.font = "9px Baskerville, serif";
      if (shouldRotate) {
        ctx.save();
        const labelX = xBase + Math.max(0, (groupWidth - ctx.measureText(labelText).width) / 2);
        const labelY = height - 1;
        ctx.translate(labelX, labelY);
        ctx.rotate(-Math.PI / 4);
        ctx.fillText(labelText, 0, 0);
        ctx.restore();
      } else {
        const labelX = xBase + Math.max(0, (groupWidth - ctx.measureText(labelText).width) / 2);
        const labelY = height - 1;
        ctx.fillText(labelText, labelX, labelY);
      }
    }
  });

  if (options.legend) {
    let offsetX = padding.left;
    const offsetY = padding.top - 12;
    datasets.forEach((dataset) => {
      ctx.fillStyle = dataset.color;
      ctx.fillRect(offsetX, offsetY, 10, 10);
      ctx.fillStyle = "#4c4540";
      ctx.font = "11px Baskerville, serif";
      ctx.fillText(dataset.label, offsetX + 14, offsetY + 9);
      offsetX += ctx.measureText(dataset.label).width + 30;
    });
  }
};

const saveTimers = new Map();

const setInmuebleSaveStatus = (text) => {
  if (!inmuebleSaveStatus) {
    return;
  }
  inmuebleSaveStatus.textContent = text || "";
  if (text === "Guardado") {
    window.clearTimeout(inmuebleSaveStatus._timer);
    inmuebleSaveStatus._timer = window.setTimeout(() => {
      inmuebleSaveStatus.textContent = "";
    }, 2000);
  }
};

const scheduleSave = (key, fn, delay = 500) => {
  if (saveTimers.has(key)) {
    clearTimeout(saveTimers.get(key));
  }
  const timer = setTimeout(() => {
    saveTimers.delete(key);
    fn();
  }, delay);
  saveTimers.set(key, timer);
};

const updateInmuebleMapFromInputs = () => {
  const latInput = document.querySelector(
    '.inline-input[data-target="inmueble"][data-field="lat"]'
  );
  const lonInput = document.querySelector(
    '.inline-input[data-target="inmueble"][data-field="lon"]'
  );
  const lat = latInput ? Number(latInput.value) : null;
  const lon = lonInput ? Number(lonInput.value) : null;
  updateInmuebleMap(lat, lon);
};

const saveInmuebleField = (field, value) => {
  if (!state.currentInmuebleId) {
    return;
  }
  setInmuebleSaveStatus("Guardando...");
  fetch("/api/inmueble_update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      inmueble_id: state.currentInmuebleId,
      [field]: value,
    }),
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.error) {
        setInmuebleSaveStatus(data.error);
        return;
      }
      if (field === "direccion" && inmuebleTitle) {
        inmuebleTitle.textContent = value || "Ficha de inmueble";
      }
      if (field === "referencia" && inmuebleSubtitle) {
        inmuebleSubtitle.textContent = value || "Referencia sin asignar";
      }
      if (field === "estado" && inmuebleEstadoInfo) {
        if (state.currentInmueble) {
          state.currentInmueble.estado = value;
        }
        inmuebleEstadoInfo.textContent = `Estado actual: ${value || "-"}`;
        generateInmuebleChecklist(value);
        loadInmuebleChecklist(state.currentInmuebleId, value);
      }
      if (field === "lat" || field === "lon") {
        updateInmuebleMapFromInputs();
      }
      setInmuebleSaveStatus("Guardado");
      loadCrmInmuebles();
    })
    .catch(() => {
      setInmuebleSaveStatus("Error al guardar.");
    });
};

const saveCaptacionField = (field, value) => {
  if (!state.currentInmuebleId) {
    return;
  }
  setInmuebleSaveStatus("Guardando...");
  fetch("/api/captacion_update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      inmueble_id: state.currentInmuebleId,
      [field]: value,
    }),
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.error) {
        setInmuebleSaveStatus(data.error);
        return;
      }
      if (field === "etapa") {
        if (state.currentInmueble) {
          state.currentInmueble.estado = value;
        }
        generateInmuebleChecklist(value);
        loadInmuebleChecklist(state.currentInmuebleId, value);
      }
      setInmuebleSaveStatus("Guardado");
    })
    .catch(() => {
      setInmuebleSaveStatus("Error al guardar.");
    });
};

const saveClienteField = (field, value) => {
  if (!state.currentClienteId) {
    return;
  }
  let normalizedValue =
    field === "nif" ? normalizeDocumento(value) : value;
  if (clienteDetailSubtitle) {
    clienteDetailSubtitle.textContent = "Guardando...";
  }
  if (field === "nombre" || field === "apellidos") {
    const nombreInput = document.querySelector('.inline-input[data-target="cliente"][data-field="nombre"]');
    const apellidosInput = document.querySelector('.inline-input[data-target="cliente"][data-field="apellidos"]');
    const nombre = nombreInput ? nombreInput.value.trim() : "";
    const apellidos = apellidosInput ? apellidosInput.value.trim() : "";
    const tipoPersonaInput = document.querySelector('.inline-input[data-target="cliente"][data-field="tipo_persona"]');
    const tipoPersona = tipoPersonaInput ? tipoPersonaInput.value : "";
    normalizedValue = apellidos || nombre
      ? (String(tipoPersona).toLowerCase() === "jurídica"
          ? `${nombre}`.trim()
          : `${apellidos}, ${nombre}`.replace(/\s+/g, " ").trim())
      : "";
    field = "nombre";
  }
  fetch("/api/cliente_update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: state.currentClienteId,
      [field]: normalizedValue,
    }),
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.error) {
        if (clienteDetailSubtitle) {
          clienteDetailSubtitle.textContent = data.error;
        }
        return;
      }
      if (clienteDetailSubtitle) {
        clienteDetailSubtitle.textContent = "Guardado.";
      }
      loadClientesList().then(() => {
        loadClientesTable();
        if (clienteDetailTitle && field === "nombre") {
          const split = splitNombreApellidos(normalizedValue);
          clienteDetailTitle.textContent = `${split.apellidos} ${split.nombre}`.trim() || "Ficha de cliente";
        }
      });
    })
    .catch(() => {
      if (clienteDetailSubtitle) {
        clienteDetailSubtitle.textContent = "Error al guardar.";
      }
    });
};

const saveClienteNombreApellidos = () => {
  if (!state.currentClienteId) {
    return;
  }
  const nombreInput = document.querySelector('.inline-input[data-target="cliente"][data-field="nombre"]');
  const apellidosInput = document.querySelector('.inline-input[data-target="cliente"][data-field="apellidos"]');
  const nombre = nombreInput ? nombreInput.value.trim() : "";
  const apellidos = apellidosInput ? apellidosInput.value.trim() : "";
  const combined = apellidos || nombre
    ? `${apellidos}, ${nombre}`.replace(/\s+/g, " ").trim()
    : "";
  saveClienteField("nombre", combined);
};

const saveClienteForm = () => {
  if (!state.currentClienteId) {
    return;
  }
  if (clienteSaveStatus) {
    clienteSaveStatus.textContent = "Guardando...";
  }
  const inputs = document.querySelectorAll('.inline-input[data-target="cliente"]');
  const payload = { id: state.currentClienteId };
  inputs.forEach((input) => {
    const field = input.dataset.field;
    if (!field || field === "apellidos") {
      return;
    }
    if (field === "nif") {
      payload[field] = normalizeDocumento(input.value);
      return;
    }
    if (field === "codigo_postal") {
      payload[field] = normalizePostalCode(input.value);
      return;
    }
    if (field === "nombre") {
      const apellidosInput = document.querySelector('.inline-input[data-target="cliente"][data-field="apellidos"]');
      const tipoPersonaInput = document.querySelector('.inline-input[data-target="cliente"][data-field="tipo_persona"]');
      const apellidos = apellidosInput ? apellidosInput.value.trim() : "";
      const nombre = input.value.trim();
      const tipoPersona = tipoPersonaInput ? tipoPersonaInput.value : "";
      payload.nombre = apellidos || nombre
        ? (String(tipoPersona).toLowerCase() === "jurídica"
            ? `${nombre}`.trim()
            : `${apellidos}, ${nombre}`.replace(/\s+/g, " ").trim())
        : "";
      return;
    }
    payload[field] = input.value;
  });
  fetch("/api/cliente_update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then((res) => res.json())
    .then((data) => {
      if (clienteSaveStatus) {
        clienteSaveStatus.textContent = data.error || "Guardado.";
      }
      if (!data.error) {
        loadClientesList().then(() => {
          loadClientesTable();
          if (clienteDetailTitle) {
            clienteDetailTitle.textContent = formatNombreCliente(payload.nombre || "");
          }
        });
      }
    })
    .catch(() => {
      if (clienteSaveStatus) {
        clienteSaveStatus.textContent = "Error al guardar.";
      }
    });
};

const saveClienteEmpresaField = (relId, field, value) => {
  if (!relId) {
    return;
  }
  if (clienteDetailSubtitle) {
    clienteDetailSubtitle.textContent = "Guardando...";
  }
  fetch("/api/cliente_empresa_update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: relId,
      [field]: value,
    }),
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.error) {
        if (clienteDetailSubtitle) {
          clienteDetailSubtitle.textContent = data.error;
        }
        return;
      }
      if (clienteDetailSubtitle) {
        clienteDetailSubtitle.textContent = "Guardado.";
      }
    })
    .catch(() => {
      if (clienteDetailSubtitle) {
        clienteDetailSubtitle.textContent = "Error al guardar.";
      }
    });
};

const renderEditableGrid = (grid, fields, data, target) => {
  if (!grid) return;
  grid.innerHTML = "";
  const tipoPersonaValue =
    target === "cliente" ? String(data?.tipo_persona || "").toLowerCase() : "";
  const isJuridica = target === "cliente" && tipoPersonaValue === "jurídica";
  const isInmueble = target === "inmueble";
  const inputMap = {};
  const cardMap = {};
  fields.forEach((field) => {
    if (target === "cliente" && field.key === "apellidos" && isJuridica) {
      return;
    }
    const card = document.createElement("div");
    card.className = "card editable-card";
    if (target === "cliente") {
      cardMap[field.key] = card;
    }
    const label = document.createElement("h3");
    if (target === "cliente" && field.key === "nombre") {
      label.textContent = isJuridica ? "Nombre social" : "Nombre";
    } else if (target === "cliente" && field.key === "nif") {
      label.textContent = isJuridica ? "CIF" : "DNI";
    } else {
      label.textContent = field.label;
    }
    card.appendChild(label);

    let input;
    const currentValue =
      data && data[field.key] !== undefined && data[field.key] !== null
        ? data[field.key]
        : "";
    if (field.type === "select") {
      input = document.createElement("select");
      const options = field.options || [];
      options.forEach((option) => {
        input.appendChild(createOption(option, option));
      });
      if (currentValue && !options.includes(currentValue)) {
        input.appendChild(createOption(currentValue, currentValue));
      }
      if (currentValue) {
        input.value = currentValue;
      }
    } else if (field.type === "textarea") {
      input = document.createElement("textarea");
      input.rows = 3;
      input.value = currentValue || "";
    } else {
      input = document.createElement("input");
      input.type = field.type || "text";
      if (target === "cliente" && field.key === "nif") {
        input.value = normalizeDocumento(currentValue);
      } else if (target === "cliente" && field.key === "nombre") {
        input.value = formatNombreCliente(currentValue);
      } else {
        input.value = currentValue || "";
      }
    }
    input.classList.add("inline-input");
    input.dataset.target = target;
    input.dataset.field = field.key;
    if (target === "cliente" || isInmueble) {
      inputMap[field.key] = input;
    }

    let status;
    if (target === "cliente" && field.key === "nif") {
      status = document.createElement("div");
      status.className = "muted";
      status.textContent = input.value
        ? isValidDocumento(input.value)
          ? "Documento válido"
          : "Documento no válido"
        : "";
    }

    const saveHandler = () => {
      if (target === "cliente" && (field.key === "nombre" || field.key === "apellidos")) {
        saveClienteNombreApellidos();
        return;
      }
      const value =
        target === "cliente" && field.key === "nif"
          ? normalizeDocumento(input.value)
          : input.value;
      if (target === "inmueble") {
        saveInmuebleField(field.key, value);
      } else if (target === "captacion") {
        saveCaptacionField(field.key, value);
      } else if (target === "cliente") {
        saveClienteField(field.key, value);
      }
    };

    if (field.type === "select") {
      input.addEventListener("change", saveHandler);
    } else {
      input.addEventListener("input", () => {
        if (status) {
          const val = input.value;
          status.textContent = val
            ? isValidDocumento(val)
              ? "Documento válido"
              : "Documento no válido"
            : "";
        }
        scheduleSave(`${target}:${field.key}`, saveHandler);
      });
      input.addEventListener("blur", saveHandler);
    }
    card.appendChild(input);
    if (status) {
      card.appendChild(status);
    }
    grid.appendChild(card);
  });

  if (target === "cliente" && inputMap.codigo_postal) {
    const cpInput = inputMap.codigo_postal;
    const provinciaInput = inputMap.provincia;
    const poblacionInput = inputMap.poblacion;
    let poblacionSelect = null;
    if (poblacionInput && cardMap.poblacion) {
      poblacionSelect = document.createElement("select");
      poblacionSelect.className = "postal-options hidden";
      poblacionSelect.appendChild(createOption("", "Selecciona población"));
      cardMap.poblacion.appendChild(poblacionSelect);
      poblacionSelect.addEventListener("change", () => {
        const value = poblacionSelect.value;
        if (!value) return;
        poblacionInput.value = value;
        poblacionInput.dataset.auto = "0";
        saveClienteField("poblacion", value);
        if (poblacionSelect.dataset.provincia) {
          provinciaInput.value = poblacionSelect.dataset.provincia;
          saveClienteField("provincia", poblacionSelect.dataset.provincia);
        }
      });
    }
    if (poblacionInput) {
      poblacionInput.addEventListener("input", () => {
        poblacionInput.dataset.auto = "0";
      });
    }
    const applyPostal = () => {
      const fallback = getPostalInfo(cpInput.value);
      fetchPostalLookup(cpInput.value).then((info) => {
        const resolved = info || fallback;
        if (!resolved) return;
        const provinciaValue = resolved.provincia || fallback?.provincia || "";
        const poblacionValue = resolved.poblacion || fallback?.poblacion || "";
        if (provinciaInput && provinciaValue) {
          provinciaInput.value = provinciaValue;
          saveClienteField("provincia", provinciaValue);
        }
        if (poblacionInput && poblacionValue) {
          const shouldAuto =
            !poblacionInput.value || poblacionInput.dataset.auto === "1";
          if (shouldAuto) {
            poblacionInput.value = poblacionValue;
            poblacionInput.dataset.auto = "1";
            saveClienteField("poblacion", poblacionValue);
          }
        }
        if (poblacionSelect) {
          const options = (info && info.opciones) || [];
          const unique = Array.from(
            new Set(options.map((opt) => opt.poblacion).filter(Boolean))
          );
          poblacionSelect.innerHTML = "";
          poblacionSelect.appendChild(createOption("", "Selecciona población"));
          unique.forEach((name) => {
            poblacionSelect.appendChild(createOption(name, name));
          });
          if (unique.length > 1) {
            poblacionSelect.classList.remove("hidden");
            poblacionSelect.dataset.provincia = provinciaValue || "";
          } else {
            poblacionSelect.classList.add("hidden");
            poblacionSelect.dataset.provincia = "";
          }
        }
      });
    };
    cpInput.addEventListener("input", () => {
      cpInput.value = normalizePostalCode(cpInput.value);
      scheduleSave(`cliente:codigo_postal`, () => {
        saveClienteField("codigo_postal", cpInput.value);
        applyPostal();
      });
    });
    cpInput.addEventListener("blur", () => {
      cpInput.value = normalizePostalCode(cpInput.value);
      saveClienteField("codigo_postal", cpInput.value);
      applyPostal();
    });
    applyPostal();
  }

  if (isInmueble) {
    const direccionInput = inputMap.direccion;
    const latInput = inputMap.lat;
    const lonInput = inputMap.lon;
    const refInput = inputMap.referencia;
    if (direccionInput && latInput && lonInput) {
      direccionInput.addEventListener("blur", () => {
        const address = direccionInput.value.trim();
        if (!address) return;
        geocodeInmuebleAddress(address, latInput, lonInput);
      });
    }
    const catastroCard = document.createElement("div");
    catastroCard.className = "card editable-card";
    const label = document.createElement("h3");
    label.textContent = "Catastro";
    catastroCard.appendChild(label);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Abrir Catastro";
    btn.addEventListener("click", () => {
      const ref = refInput ? refInput.value.trim() : "";
      const address = direccionInput ? direccionInput.value.trim() : "";
      const url = buildCatastroUrl(ref, address);
      window.open(url, "_blank");
    });
    catastroCard.appendChild(btn);
    grid.appendChild(catastroCard);
  }
};

let inmuebleGeocodeTimer = null;
let lastGeocodeAddress = "";

const updateInmuebleMap = (lat, lon) => {
  if (!inmuebleMap) return;
  if (!lat || !lon) {
    inmuebleMap.innerHTML = "<p class='muted'>Sin coordenadas.</p>";
    return;
  }
  const bbox = [lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01].join(",");
  inmuebleMap.innerHTML = `
    <iframe
      width="100%"
      height="320"
      frameborder="0"
      src="https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat},${lon}"
    ></iframe>
    <a class="muted" href="https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=16/${lat}/${lon}" target="_blank">Abrir en OpenStreetMap</a>
  `;
};

const buildCatastroUrl = (ref, address) => {
  const base = "https://www.sedecatastro.gob.es/";
  if (ref) {
    return `${base}?rc=${encodeURIComponent(ref)}`;
  }
  if (address) {
    return `${base}?address=${encodeURIComponent(address)}`;
  }
  return base;
};

const geocodeInmuebleAddress = (address, latInput, lonInput) => {
  if (!address) return;
  if (address === lastGeocodeAddress) return;
  lastGeocodeAddress = address;
  if (inmuebleGeocodeTimer) {
    clearTimeout(inmuebleGeocodeTimer);
  }
  inmuebleGeocodeTimer = setTimeout(() => {
    fetch(
      `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(
        address
      )}&limit=1`,
      {
        headers: { "Accept-Language": "es" },
      }
    )
      .then((res) => res.json())
      .then((rows) => {
        if (!rows || !rows.length) return;
        const lat = Number(rows[0].lat);
        const lon = Number(rows[0].lon);
        if (Number.isNaN(lat) || Number.isNaN(lon)) return;
        if (latInput) latInput.value = String(lat);
        if (lonInput) lonInput.value = String(lon);
        saveInmuebleField("lat", lat);
        saveInmuebleField("lon", lon);
        updateInmuebleMap(lat, lon);
      })
      .catch(() => {});
  }, 600);
};

const populateClientesSelect = (selectEl, selectedId = "") => {
  if (!selectEl) return;
  selectEl.innerHTML = "";
  selectEl.appendChild(createOption("", "Selecciona cliente"));
  const clientes = Array.isArray(state.clientesList) ? state.clientesList : [];
  clientes.forEach((cliente) => {
    const option = createOption(cliente.id, formatNombreCliente(cliente.nombre));
    selectEl.appendChild(option);
  });
  if (selectedId) {
    selectEl.value = selectedId;
  }
};

const loadDemandasList = (empresaId) => {
  if (!empresaId) {
    state.demandasList = [];
    return Promise.resolve([]);
  }
  return api(`/api/demandas?empresa_id=${empresaId}`).then((data) => {
    state.demandasList = data.rows || [];
    return state.demandasList;
  });
};

const populateDemandasSelect = (selectEl, selectedId = "") => {
  if (!selectEl) return;
  selectEl.innerHTML = "";
  selectEl.appendChild(createOption("", "Selecciona demanda"));
  state.demandasList.forEach((demanda) => {
    const label = `${demanda.cliente || "Sin cliente"} · ${demanda.zona || "-"}`;
    selectEl.appendChild(createOption(demanda.id, label));
  });
  if (selectedId) {
    selectEl.value = selectedId;
  }
};

const populateGestoriaClientes = () => {
  const selects = [gestoriaCrmCliente, gestoriaTrabajoCliente, gestoriaDocsCliente].filter(Boolean);
  if (!selects.length) {
    return;
  }
  const clientes = Array.isArray(state.clientesList) ? state.clientesList : [];
  selects.forEach((selectEl) => {
    selectEl.innerHTML = "";
    selectEl.appendChild(createOption("", "Selecciona cliente"));
    clientes.forEach((cliente) => {
      const label = formatNombreCliente(cliente.nombre);
      const value = selectEl === gestoriaCrmCliente ? cliente.nombre : cliente.id;
      selectEl.appendChild(createOption(value, label));
    });
  });
};

const populateAgendaClientes = (listEl, inputEl, hiddenEl) => {
  if (!listEl) return;
  listEl.innerHTML = "";
  const clientes = Array.isArray(state.clientesList) ? state.clientesList : [];
  clientes.forEach((cliente) => {
    const option = document.createElement("option");
    option.value = formatNombreCliente(cliente.nombre);
    option.dataset.id = cliente.id;
    listEl.appendChild(option);
  });
  if (inputEl) {
    const handler = () => {
      const value = inputEl.value.trim();
      if (!value || !hiddenEl) return;
      const match = clientes.find(
        (c) => formatNombreCliente(c.nombre) === value
      );
      hiddenEl.value = match ? match.id : "";
    };
    inputEl.addEventListener("input", handler);
    inputEl.addEventListener("change", handler);
  }
};

const resolveClienteFromInput = (inputEl, hiddenEl) => {
  const clientes = Array.isArray(state.clientesList) ? state.clientesList : [];
  const nombre = inputEl ? inputEl.value.trim() : "";
  let clienteId = hiddenEl ? hiddenEl.value.trim() : "";
  if (!clienteId && nombre) {
    const match = clientes.find(
      (c) => formatNombreCliente(c.nombre) === nombre
    );
    if (match) {
      clienteId = match.id;
      if (hiddenEl) hiddenEl.value = clienteId;
    }
  }
  return { cliente_id: clienteId || "", cliente_nombre: nombre || "" };
};

const loadGestoriaContabilidad = () => {
  if (!gestoriaContabilidadTable || !gestoriaContabilidadInfo) return;
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) {
    gestoriaContabilidadTable.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  api(`/api/gestoria_contabilidad?empresa_id=${empresa.id}`).then((data) => {
    const rows = data.rows || [];
    if (!rows.length) {
      gestoriaContabilidadTable.innerHTML = "<p class='muted'>Sin anotaciones contables.</p>";
      gestoriaContabilidadInfo.textContent = "";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["fecha", "concepto", "gestion", "tipo", "importe", "cliente", "notas", "accion"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const buildInput = (value, field, type = "text") => {
        const input = document.createElement("input");
        input.type = type;
        input.value = value || "";
        input.classList.add("inline-input");
        input.addEventListener("change", () => {
          saveGestoriaContabilidadField(row.id, field, input.value);
        });
        return input;
      };
      const buildSelect = (value, field, options) => {
        const select = document.createElement("select");
        select.classList.add("inline-input");
        options.forEach((opt) => select.appendChild(createOption(opt, opt)));
        select.value = value || options[0];
        select.addEventListener("change", () => {
          saveGestoriaContabilidadField(row.id, field, select.value);
        });
        return select;
      };
      const fechaTd = document.createElement("td");
      fechaTd.appendChild(buildInput(row.fecha, "fecha", "date"));
      tr.appendChild(fechaTd);
      const conceptoTd = document.createElement("td");
      conceptoTd.appendChild(buildInput(row.concepto, "concepto"));
      tr.appendChild(conceptoTd);
      const gestionTd = document.createElement("td");
      const gestiones = [
        "Herencias",
        "Tráfico",
        "Renta",
        "Modelos Hacienda",
        "Laboral",
        "Fiscal",
        "Contable",
        "Registro Mercantil",
        "Presentación cuentas",
        "Constitución sociedad",
        "Bajas/Altas",
        "Otros",
      ];
      const gestionSelect = document.createElement("select");
      gestionSelect.classList.add("inline-input");
      gestionSelect.appendChild(createOption("", "-"));
      gestiones.forEach((opt) => gestionSelect.appendChild(createOption(opt, opt)));
      if (row.gestion && !gestiones.includes(row.gestion)) {
        gestionSelect.appendChild(createOption(row.gestion, row.gestion));
      }
      gestionSelect.value = row.gestion || "";
      gestionSelect.addEventListener("change", () => {
        saveGestoriaContabilidadField(row.id, "gestion", gestionSelect.value);
      });
      gestionTd.appendChild(gestionSelect);
      tr.appendChild(gestionTd);
      const tipoTd = document.createElement("td");
      tipoTd.appendChild(buildSelect(row.tipo, "tipo", ["Ingreso", "Gasto"]));
      tr.appendChild(tipoTd);
      const importeTd = document.createElement("td");
      importeTd.appendChild(buildInput(row.importe, "importe", "number"));
      tr.appendChild(importeTd);
      const clienteTd = document.createElement("td");
      const clienteSelect = document.createElement("select");
      clienteSelect.classList.add("inline-input");
      clienteSelect.appendChild(createOption("", "-"));
      const clientes = Array.isArray(state.clientesList) ? state.clientesList : [];
      clientes.forEach((cliente) => {
        clienteSelect.appendChild(
          createOption(cliente.id, formatNombreCliente(cliente.nombre))
        );
      });
      clienteSelect.value = row.cliente_id || "";
      clienteSelect.addEventListener("change", () => {
        saveGestoriaContabilidadField(row.id, "cliente_id", clienteSelect.value);
      });
      clienteTd.appendChild(clienteSelect);
      tr.appendChild(clienteTd);
      const notasTd = document.createElement("td");
      notasTd.appendChild(buildInput(row.notas, "notas"));
      tr.appendChild(notasTd);
      const actionTd = document.createElement("td");
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.textContent = "Eliminar";
      delBtn.addEventListener("click", () => {
        deleteGestoriaContabilidad(row.id);
      });
      actionTd.appendChild(delBtn);
      tr.appendChild(actionTd);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    gestoriaContabilidadTable.innerHTML = "";
    gestoriaContabilidadTable.appendChild(table);
    gestoriaContabilidadInfo.textContent = `Mostrando ${rows.length} anotaciones.`;
  });
};

const formatInputDate = (date) => {
  if (!date) return "";
  const d = new Date(date);
  if (Number.isNaN(d.getTime())) return "";
  return d.toISOString().slice(0, 10);
};

const getContaPeriodEnd = (fechaInicio, periodo) => {
  const base = new Date(fechaInicio);
  if (Number.isNaN(base.getTime())) return "";
  let end;
  if (periodo === "Trimestral") {
    const quarter = Math.floor(base.getMonth() / 3);
    end = new Date(base.getFullYear(), quarter * 3 + 3, 0);
  } else if (periodo === "Anual") {
    end = new Date(base.getFullYear(), 11, 31);
  } else {
    end = new Date(base.getFullYear(), base.getMonth() + 1, 0);
  }
  return formatInputDate(end);
};

const getContaTemplate = (periodo) => {
  if (periodo === "Trimestral") {
    return [
      "Registro de facturas",
      "Conciliación bancaria",
      "Revisión gastos",
      "Modelo 303 (IVA)",
      "Modelo 111 (retenciones)",
      "Modelo 115 (alquileres)",
      "Cierres contables trimestrales",
    ];
  }
  if (periodo === "Anual") {
    return [
      "Cierre contable anual",
      "Regularización impuestos",
      "Cuentas anuales",
      "Impuesto de sociedades",
      "Revisión de libros oficiales",
    ];
  }
  return [
    "Registro de facturas",
    "Conciliación bancaria",
    "Revisión gastos",
    "Control de cobros y pagos",
    "Actualización libro mayor",
  ];
};

const renderGestoriaContaTasks = (rows = []) => {
  if (!gestoriaContaTasksTable) return;
  if (!rows.length) {
    gestoriaContaTasksTable.innerHTML = "<p class='muted'>Sin checklist.</p>";
    if (gestoriaContaTasksInfo) gestoriaContaTasksInfo.textContent = "";
    if (gestoriaContaSummaryDone) gestoriaContaSummaryDone.textContent = "0";
    if (gestoriaContaSummaryPending) gestoriaContaSummaryPending.textContent = "0";
    if (gestoriaContaSummaryNext) gestoriaContaSummaryNext.textContent = "-";
    return;
  }
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const trHead = document.createElement("tr");
  ["tarea", "estado", "fecha_limite", "responsable", "accion"].forEach((col) => {
    const th = document.createElement("th");
    th.textContent = formatHeader(col);
    trHead.appendChild(th);
  });
  thead.appendChild(trHead);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const tareaTd = document.createElement("td");
    tareaTd.textContent = row.tarea || "";
    tr.appendChild(tareaTd);
    const estadoTd = document.createElement("td");
    const estadoSelect = document.createElement("select");
    ["Pendiente", "En curso", "Completada"].forEach((opt) =>
      estadoSelect.appendChild(createOption(opt, opt))
    );
    estadoSelect.value = row.estado || "Pendiente";
    estadoSelect.addEventListener("change", () => {
      updateGestoriaContaTask(row.id, { estado: estadoSelect.value });
    });
    estadoTd.appendChild(estadoSelect);
    tr.appendChild(estadoTd);
    const fechaTd = document.createElement("td");
    const fechaInput = document.createElement("input");
    fechaInput.type = "date";
    fechaInput.value = row.fecha_limite || "";
    fechaInput.addEventListener("change", () => {
      updateGestoriaContaTask(row.id, { fecha_limite: fechaInput.value });
    });
    fechaTd.appendChild(fechaInput);
    tr.appendChild(fechaTd);
    const respTd = document.createElement("td");
    const respSelect = document.createElement("select");
    respSelect.appendChild(createOption("", "Sin asignar"));
    (state.usersList || []).forEach((user) => {
      const nombre = `${user.nombre || ""} ${user.apellido || ""}`.trim();
      const value = user.usuario || nombre;
      if (!value) return;
      respSelect.appendChild(createOption(value, nombre || value));
    });
    respSelect.value = row.responsable || "";
    respSelect.addEventListener("change", () => {
      updateGestoriaContaTask(row.id, { responsable: respSelect.value });
    });
    respTd.appendChild(respSelect);
    tr.appendChild(respTd);
    const actionTd = document.createElement("td");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Abrir ficha";
    btn.addEventListener("click", () => {
      if (row.cliente_id) {
        openCliente(row.cliente_id);
      }
    });
    actionTd.appendChild(btn);
    tr.appendChild(actionTd);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  gestoriaContaTasksTable.innerHTML = "";
  gestoriaContaTasksTable.appendChild(table);
  if (gestoriaContaTasksInfo) {
    gestoriaContaTasksInfo.textContent = `Mostrando ${rows.length} tareas.`;
  }
  const done = rows.filter((r) => String(r.estado || "").toLowerCase() === "completada").length;
  const pending = rows.length - done;
  if (gestoriaContaSummaryDone) gestoriaContaSummaryDone.textContent = String(done);
  if (gestoriaContaSummaryPending) gestoriaContaSummaryPending.textContent = String(pending);
  const upcoming = rows
    .filter((r) => r.fecha_limite)
    .sort((a, b) => String(a.fecha_limite).localeCompare(String(b.fecha_limite)));
  if (gestoriaContaSummaryNext) {
    gestoriaContaSummaryNext.textContent = upcoming.length ? formatCell("fecha", upcoming[0].fecha_limite) : "-";
  }
};

const loadGestoriaContaConfig = (clienteId) => {
  if (!gestoriaContaConfigForm || !clienteId) return;
  api(`/api/gestoria_conta_config?cliente_id=${clienteId}`).then((data) => {
    const row = data.row || {};
    const periodo = row.periodo || "Mensual";
    gestoriaContaConfigForm.querySelector('[name="periodo"]').value = periodo;
    gestoriaContaConfigForm.querySelector('[name="fecha_inicio"]').value =
      row.fecha_inicio || formatInputDate(new Date());
    gestoriaContaConfigForm.querySelector('[name="responsable"]').value = row.responsable || "";
    loadGestoriaContaTasks(clienteId, periodo);
  });
};

const loadGestoriaContaTasks = (clienteId, periodo = "") => {
  if (!clienteId) return;
  const query = new URLSearchParams({ cliente_id: clienteId });
  if (periodo) query.set("periodo", periodo);
  api(`/api/gestoria_conta_tasks?${query.toString()}`).then((data) => {
    renderGestoriaContaTasks(data.rows || []);
  });
};

const updateGestoriaContaTask = (id, updates) => {
  fetch("/api/gestoria_conta_task_update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, ...updates, usuario: getCurrentUser() }),
  })
    .then(() => {
      if (state.currentClienteId) {
        loadGestoriaContaTasks(state.currentClienteId);
      }
    })
    .catch(() => {});
};

const createGestoriaContaChecklist = () => {
  if (!gestoriaContaConfigForm || !state.currentClienteId) return;
  const formData = new FormData(gestoriaContaConfigForm);
  const periodo = formData.get("periodo") || "Mensual";
  const fechaInicio = formData.get("fecha_inicio") || formatInputDate(new Date());
  const responsable = formData.get("responsable") || "";
  const fechaLimite = getContaPeriodEnd(fechaInicio, periodo);
  const tareas = getContaTemplate(periodo).map((tarea) => ({
    tarea,
    estado: "Pendiente",
    fecha_limite: fechaLimite,
    responsable,
  }));
  fetch("/api/gestoria_conta_tasks_bulk", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      cliente_id: state.currentClienteId,
      periodo,
      tareas,
      usuario: getCurrentUser(),
    }),
  })
    .then((res) => res.json())
    .then((data) => {
      if (gestoriaContaConfigStatus) {
        gestoriaContaConfigStatus.textContent = data.error || "Checklist creada.";
      }
      loadGestoriaContaTasks(state.currentClienteId, periodo);
    })
    .catch(() => {
      if (gestoriaContaConfigStatus) {
        gestoriaContaConfigStatus.textContent = "Error al crear checklist.";
      }
    });
};

const loadGestoriaContaQueue = () => {
  if (!gestoriaContaQueueTable || !gestoriaContaQueueInfo) return;
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) {
    gestoriaContaQueueTable.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  const params = new URLSearchParams({ empresa_id: empresa.id });
  if (gestoriaContaQueueFilter && gestoriaContaQueueFilter.value) {
    params.set("estado", gestoriaContaQueueFilter.value);
  }
  api(`/api/gestoria_conta_tasks?${params.toString()}`).then((data) => {
    const rows = data.rows || [];
    if (!rows.length) {
      gestoriaContaQueueTable.innerHTML = "<p class='muted'>Sin tareas contables.</p>";
      gestoriaContaQueueInfo.textContent = "";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["cliente", "periodo", "tarea", "estado", "fecha_limite", "responsable"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      ["cliente", "periodo", "tarea", "estado", "fecha_limite", "responsable"].forEach((field) => {
        const td = document.createElement("td");
        td.textContent = field === "fecha_limite" ? formatCell("fecha", row[field]) : (row[field] || "");
        tr.appendChild(td);
      });
      tr.addEventListener("click", () => {
        if (row.cliente_id) {
          openCliente(row.cliente_id);
        }
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    gestoriaContaQueueTable.innerHTML = "";
    gestoriaContaQueueTable.appendChild(table);
    gestoriaContaQueueInfo.textContent = `Mostrando ${rows.length} tareas.`;
  });
};

const loadGestoriaTrabajosOverview = () => {
  if (!gestoriaTrabajosTable || !gestoriaTrabajosInfo) return;
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) {
    gestoriaTrabajosTable.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  api(`/api/gestoria_trabajos?empresa_id=${empresa.id}`).then((data) => {
    let rows = data.rows || [];
    const tipoFilter = gestoriaTrabajosTipoFilter ? gestoriaTrabajosTipoFilter.value.trim() : "";
    const estadoFilter = gestoriaTrabajosEstadoFilter ? gestoriaTrabajosEstadoFilter.value.trim() : "";
    const limitValue = gestoriaTrabajosLimit ? parseInt(gestoriaTrabajosLimit.value, 10) : 20;
    if (tipoFilter) {
      rows = rows.filter((row) => (row.tipo_trabajo || "") === tipoFilter);
    }
    if (estadoFilter) {
      rows = rows.filter((row) => (row.estado || "") === estadoFilter);
    }
    rows.sort((a, b) => String(a.fecha_fin || "").localeCompare(String(b.fecha_fin || "")));
    if (!rows.length) {
      gestoriaTrabajosTable.innerHTML = "<p class='muted'>Sin gestiones activas.</p>";
      gestoriaTrabajosInfo.textContent = "";
      return;
    }
    const visibleRows = rows.slice(0, Number.isFinite(limitValue) ? limitValue : 20);
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["cliente", "tipo_trabajo", "estado", "fecha_inicio", "fecha_fin", "responsable", "importe"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    visibleRows.forEach((row) => {
      const tr = document.createElement("tr");
      const values = [
        row.cliente || "-",
        row.tipo_trabajo || "-",
        row.estado || "-",
        row.fecha_inicio || "-",
        row.fecha_fin || "-",
        row.responsable || "-",
        row.importe || "-",
      ];
      const cols = ["cliente", "tipo_trabajo", "estado", "fecha_inicio", "fecha_fin", "responsable", "importe"];
      values.forEach((value, idx) => {
        const td = document.createElement("td");
        if (!applyCompanyCell(td, cols[idx], value, { compact: true }) && !applyRamoCell(td, cols[idx], value)) {
          const formatted = formatCell(cols[idx], value);
          td.textContent = formatted === null ? "" : formatted;
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    gestoriaTrabajosTable.innerHTML = "";
    gestoriaTrabajosTable.appendChild(table);
    gestoriaTrabajosInfo.textContent = `Mostrando ${visibleRows.length} gestiones.`;
  });
};

const loadGestoriaModelosOverview = () => {
  if (!gestoriaModelosOverviewTable || !gestoriaModelosOverviewInfo) return;
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) {
    gestoriaModelosOverviewTable.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  const params = new URLSearchParams({ empresa_id: empresa.id, scope: "proximos" });
  api(`/api/gestoria_modelos?${params.toString()}`).then((data) => {
    const rows = data.rows || [];
    if (!rows.length) {
      gestoriaModelosOverviewTable.innerHTML = "<p class='muted'>Sin vencimientos próximos.</p>";
      gestoriaModelosOverviewInfo.textContent = "";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["cliente", "modelo", "proxima_fecha", "estado", "responsable"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.slice(0, 20).forEach((row) => {
      const tr = document.createElement("tr");
      const values = [
        row.cliente || "-",
        row.modelo || "-",
        row.proxima_fecha || "-",
        row.estado || "-",
        row.responsable || "-",
      ];
      const cols = ["cliente", "modelo", "proxima_fecha", "estado", "responsable"];
      values.forEach((value, idx) => {
        const td = document.createElement("td");
        const formatted = formatCell(cols[idx], value);
        td.textContent = formatted === null ? "" : formatted;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    gestoriaModelosOverviewTable.innerHTML = "";
    gestoriaModelosOverviewTable.appendChild(table);
    gestoriaModelosOverviewInfo.textContent = `Mostrando ${Math.min(rows.length, 20)} modelos próximos.`;
  });
};

const loadGestoriaPipeline = () => {
  if (!gestoriaPipeline) return;
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) {
    gestoriaPipeline.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  api(`/api/gestoria_trabajos?empresa_id=${empresa.id}`).then((data) => {
    const rows = data.rows || [];
    const servicio = gestoriaPipelineServicio ? gestoriaPipelineServicio.value.trim() : "";
    const groupBy = gestoriaPipelineGroup ? gestoriaPipelineGroup.value : "estado";
    const filtered = servicio ? rows.filter((row) => (row.tipo_trabajo || "") === servicio) : rows;
    const estados = ["En espera", "En curso", "Completado"];
    const responsables = Array.from(
      new Set(
        filtered.map((row) => (row.responsable || "").trim()).filter(Boolean)
      )
    ).sort();
    const hasSinAsignar = filtered.some((row) => !(row.responsable || "").trim());
    if (hasSinAsignar) {
      responsables.push("Sin asignar");
    }
    if (!responsables.length) {
      responsables.push("Sin asignar");
    }
    const board = document.createElement("div");
    board.className = "pipeline-board";
    const columns = groupBy === "responsable" ? responsables : estados;
    columns.forEach((colKey) => {
      const columnRows =
        groupBy === "responsable"
          ? filtered.filter((row) => (row.responsable || "Sin asignar") === colKey)
          : filtered.filter((row) => (row.estado || "") === colKey);
      const col = document.createElement("div");
      col.className = "pipeline-col";
      const header = document.createElement("div");
      header.className = "pipeline-head";
      header.innerHTML = `<h4>${colKey}</h4><span>${columnRows.length}</span>`;
      col.appendChild(header);
      const list = document.createElement("div");
      list.className = "pipeline-list";
      columnRows.forEach((row) => {
          const card = document.createElement("button");
          card.type = "button";
          card.className = "pipeline-card";
          const cliente = row.cliente || "Cliente";
          const tipo = row.tipo_trabajo || "Gestión";
          const fecha = row.fecha_fin || row.fecha_inicio || "-";
          const estado = row.estado || "-";
          const responsable = row.responsable || "Sin asignar";
          let slaBadge = "";
          if (row.sla_dias && row.fecha_inicio && String(estado).toLowerCase() !== "completado") {
            const due = new Date(row.fecha_inicio);
            const days = parseInt(row.sla_dias, 10);
            if (!Number.isNaN(due.getTime()) && !Number.isNaN(days)) {
              const dueDate = new Date(due.getTime() + days * 86400000);
              if (dueDate < new Date()) {
                slaBadge = `<span class="crm-badge">SLA vencido</span>`;
              }
            }
          }
          card.innerHTML = `
            <h5>${cliente}</h5>
            <div class="muted">${tipo}</div>
            <div class="muted">${groupBy === "responsable" ? estado : responsable}</div>
            <div class="muted">${formatCell("fecha", fecha) || fecha}</div>
            ${slaBadge}
          `;
          card.addEventListener("click", () => {
            const clientes = Array.isArray(state.clientesList) ? state.clientesList : [];
            const match = clientes.find((c) => c.id === row.cliente_id);
            if (match) {
              openClienteDetail(match.id);
            }
          });
          list.appendChild(card);
        });
      if (!list.childElementCount) {
        const empty = document.createElement("div");
        empty.className = "muted";
        empty.textContent = "Sin gestiones";
        list.appendChild(empty);
      }
      col.appendChild(list);
      board.appendChild(col);
    });
    gestoriaPipeline.innerHTML = "";
    gestoriaPipeline.appendChild(board);
  });
};

const loadGestoriaDocsRecent = () => {
  if (!gestoriaDocsRecent || !gestoriaDocsRecentInfo) return;
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) {
    gestoriaDocsRecent.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  api(`/api/gestoria_docs?empresa_id=${empresa.id}&limit=30`).then((data) => {
    const rows = data.rows || [];
    if (!rows.length) {
      gestoriaDocsRecent.innerHTML = "<p class='muted'>Sin documentos recientes.</p>";
      gestoriaDocsRecentInfo.textContent = "";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["cliente", "nombre", "tipo", "fecha", "estado", "pdf"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const values = [
        row.cliente || "-",
        row.nombre || "-",
        row.tipo || "-",
        row.fecha || "-",
        row.estado || "-",
      ];
      const cols = ["cliente", "nombre", "tipo", "fecha", "estado"];
      values.forEach((value, idx) => {
        const td = document.createElement("td");
        const formatted = formatCell(cols[idx], value);
        td.textContent = formatted === null ? "" : formatted;
        tr.appendChild(td);
      });
      const pdfTd = document.createElement("td");
      if (row.doc_key || row.doc_url) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "secondary";
        btn.textContent = "Ver";
        btn.addEventListener("click", () => {
          openS3File(row.doc_key, row.doc_url);
        });
        pdfTd.appendChild(btn);
      } else {
        pdfTd.textContent = "-";
      }
      tr.appendChild(pdfTd);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    gestoriaDocsRecent.innerHTML = "";
    gestoriaDocsRecent.appendChild(table);
    gestoriaDocsRecentInfo.textContent = `Mostrando ${rows.length} documentos.`;
  });
};

const loadGestoriaAuditoria = () => {
  if (!gestoriaAuditTable || !gestoriaAuditInfo) return;
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) {
    gestoriaAuditTable.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  api(`/api/auditoria?empresa_id=${empresa.id}&limit=50`).then((data) => {
    const rows = data.rows || [];
    if (!rows.length) {
      gestoriaAuditTable.innerHTML = "<p class='muted'>Sin actividad reciente.</p>";
      gestoriaAuditInfo.textContent = "";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["fecha", "usuario", "accion", "cliente", "entidad"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const values = [
        row.created_at || "-",
        row.usuario || "-",
        row.accion || "-",
        row.cliente || "-",
        row.entidad || "-",
      ];
      const cols = ["fecha", "usuario", "accion", "cliente", "entidad"];
      values.forEach((value, idx) => {
        const td = document.createElement("td");
        const formatted = formatCell(cols[idx], value);
        td.textContent = formatted === null ? "" : formatted;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    gestoriaAuditTable.innerHTML = "";
    gestoriaAuditTable.appendChild(table);
    gestoriaAuditInfo.textContent = `Mostrando ${rows.length} movimientos.`;
  });
};


const populateServiciosSelect = (selectEl, selectedValue = "") => {
  if (!selectEl) return;
  selectEl.innerHTML = "";
  selectEl.appendChild(createOption("", "Selecciona servicio"));
  SERVICE_OPTIONS.forEach((service) => {
    selectEl.appendChild(createOption(service, service));
  });
  if (selectedValue) {
    selectEl.value = selectedValue;
  }
};

const populateResponsableSelects = () => {
  if (!responsableSelects || !responsableSelects.length) return;
  const users = state.usersList || [];
  responsableSelects.forEach((selectEl) => {
    if (!selectEl) return;
    const serviceFilter = normalizeSimple(selectEl.dataset.service || "");
    const current = selectEl.value;
    selectEl.innerHTML = "";
    selectEl.appendChild(createOption("", "Selecciona responsable"));
    users
      .filter((user) => {
        if (!serviceFilter) return true;
        const service = normalizeSimple(user.servicio || "");
        if (!service) return true;
        if (service.includes(serviceFilter)) return true;
        if (["direccion", "administracion"].includes(service)) {
          return true;
        }
        return false;
      })
      .forEach((user) => {
      const label = `${user.nombre || ""} ${user.apellido || ""}`.trim();
      const value = user.usuario || label || user.nombre || "";
      if (!value) return;
      selectEl.appendChild(createOption(value, label || value));
    });
    if (current) {
      selectEl.value = current;
    }
  });
};

const loadUsuarios = () =>
  api("/api/usuarios").then((data) => {
    state.usersList = data.rows || [];
    populateResponsableSelects();
    return state.usersList;
  });

const renderUsuariosSelect = () => {
  if (!userSelect) return;
  userSelect.innerHTML = "";
  state.usersList.forEach((user) => {
    const label = `${user.nombre || ""} ${user.apellido || ""}`.trim();
    const value = user.usuario || label || user.nombre;
    userSelect.appendChild(createOption(value, label));
  });
  const saved = getCurrentUser();
  if (saved) {
    userSelect.value = saved;
  } else if (state.usersList.length) {
    userSelect.value = state.usersList[0].nombre;
    setCurrentUser(state.usersList[0].nombre);
  }
};

const renderUsuariosTable = () => {
  if (!adminUsersTable || !adminUsersInfo) return;
  const rows = state.usersList;
  if (!rows.length) {
    adminUsersTable.innerHTML = "<p class='muted'>Sin usuarios.</p>";
    adminUsersInfo.textContent = "";
    return;
  }
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const trHead = document.createElement("tr");
  ["nombre", "apellido", "usuario", "email", "servicio", "rol", "activo", "password", "acciones"].forEach((col) => {
    const th = document.createElement("th");
    th.textContent = formatHeader(col);
    trHead.appendChild(th);
  });
  thead.appendChild(trHead);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const nombreInput = document.createElement("input");
    nombreInput.className = "inline-input";
    nombreInput.value = row.nombre || "";
    const nombreTd = document.createElement("td");
    nombreTd.appendChild(nombreInput);
    tr.appendChild(nombreTd);
    const apellidoInput = document.createElement("input");
    apellidoInput.className = "inline-input";
    apellidoInput.value = row.apellido || "";
    const apellidoTd = document.createElement("td");
    apellidoTd.appendChild(apellidoInput);
    tr.appendChild(apellidoTd);
    const usuarioInput = document.createElement("input");
    usuarioInput.className = "inline-input";
    usuarioInput.value = row.usuario || "";
    const usuarioTd = document.createElement("td");
    usuarioTd.appendChild(usuarioInput);
    tr.appendChild(usuarioTd);
    const emailInput = document.createElement("input");
    emailInput.className = "inline-input";
    emailInput.value = row.email || "";
    const emailTd = document.createElement("td");
    emailTd.appendChild(emailInput);
    tr.appendChild(emailTd);
    const servicioInput = document.createElement("input");
    servicioInput.className = "inline-input";
    servicioInput.value = row.servicio || "";
    const servicioTd = document.createElement("td");
    servicioTd.appendChild(servicioInput);
    tr.appendChild(servicioTd);
    const rolInput = document.createElement("input");
    rolInput.className = "inline-input";
    rolInput.value = row.rol || "";
    const rolTd = document.createElement("td");
    rolTd.appendChild(rolInput);
    tr.appendChild(rolTd);
    const activoSelect = document.createElement("select");
    activoSelect.className = "inline-input";
    activoSelect.appendChild(createOption("1", "Activo"));
    activoSelect.appendChild(createOption("0", "Inactivo"));
    activoSelect.value = row.activo ? "1" : "0";
    const activoTd = document.createElement("td");
    activoTd.appendChild(activoSelect);
    tr.appendChild(activoTd);
    const passwordInput = document.createElement("input");
    passwordInput.className = "inline-input";
    passwordInput.type = "password";
    passwordInput.placeholder = "Nueva contraseña";
    const passwordTd = document.createElement("td");
    passwordTd.appendChild(passwordInput);
    tr.appendChild(passwordTd);
    const actionTd = document.createElement("td");
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "icon-action";
    saveBtn.setAttribute("aria-label", "Guardar");
    saveBtn.title = "Guardar";
    saveBtn.innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5 3h11l3 3v15H5V3zm2 2v4h8V5H7zm8 14v-6H9v6h6z"></path>
      </svg>
    `;
    saveBtn.addEventListener("click", () => {
      const payload = {
        id: row.id,
        nombre: nombreInput.value.trim(),
        apellido: apellidoInput.value.trim(),
        usuario: usuarioInput.value.trim(),
        email: emailInput.value.trim(),
        servicio: servicioInput.value.trim(),
        rol: rolInput.value.trim(),
        activo: activoSelect.value,
      };
      if (passwordInput.value.trim()) {
        payload.password = passwordInput.value.trim();
      }
      fetch("/api/usuarios_update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then((res) => res.json())
        .then((data) => {
          if (data.error) return;
          loadUsuarios().then(() => {
            renderUsuariosSelect();
            renderUsuariosTable();
            renderCompanyCards();
          });
        });
    });
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "icon-action danger";
    delBtn.setAttribute("aria-label", "Eliminar");
    delBtn.title = "Eliminar";
    delBtn.innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M9 3h6l1 2h4v2H4V5h4l1-2zm1 6h2v9h-2V9zm4 0h2v9h-2V9z"></path>
      </svg>
    `;
    delBtn.addEventListener("click", () => {
      fetch("/api/usuarios_delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: row.id }),
      })
        .then((res) => res.json())
        .then((data) => {
          if (data.error) return;
          loadUsuarios().then(() => {
            renderUsuariosSelect();
            renderUsuariosTable();
            renderCompanyCards();
          });
        });
    });
    actionTd.appendChild(saveBtn);
    actionTd.appendChild(delBtn);
    tr.appendChild(actionTd);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  adminUsersTable.innerHTML = "";
  adminUsersTable.appendChild(table);
  adminUsersInfo.textContent = `Mostrando ${rows.length} usuarios.`;
};

const populateGestoriaSubtipos = (groupValue = "") => {
  if (!gestoriaCrmSubtipo) return;
  gestoriaCrmSubtipo.innerHTML = "";
  gestoriaCrmSubtipo.appendChild(createOption("", "Subtipo (todos)"));
  const items = GESTORIA_SUBTIPOS[groupValue] || [];
  items.forEach((item) => {
    gestoriaCrmSubtipo.appendChild(createOption(item, item));
  });
};

const setGestoriaCrmTab = (tabName = "autonomo") => {
  state.gestoriaCrmTab = tabName;
  if (gestoriaCrmTabs) {
    gestoriaCrmTabs.querySelectorAll(".tab").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.gestoriaTab === tabName);
    });
  }
  if (!gestoriaCrmTipo || !gestoriaCrmSubtipo) return;
  if (tabName === "all") {
    gestoriaCrmTipo.value = "";
    populateGestoriaSubtipos("");
    gestoriaCrmSubtipo.value = "";
  } else if (tabName === "autonomo") {
    gestoriaCrmTipo.value = "Cuota mensual";
    populateGestoriaSubtipos("Cuota mensual");
    gestoriaCrmSubtipo.value = "Autónomo";
  } else if (tabName === "empresa") {
    gestoriaCrmTipo.value = "Cuota mensual";
    populateGestoriaSubtipos("Cuota mensual");
    gestoriaCrmSubtipo.value = "Empresa";
  } else if (tabName === "renta") {
    gestoriaCrmTipo.value = "Gestión administrativa";
    populateGestoriaSubtipos("Gestión administrativa");
    gestoriaCrmSubtipo.value = "Cliente Renta";
  } else if (tabName === "admin") {
    gestoriaCrmTipo.value = "Gestión administrativa";
    populateGestoriaSubtipos("Gestión administrativa");
    gestoriaCrmSubtipo.value = "Gestiones Administrativas";
  }
};

const setGestoriaCrmView = (viewName = "crm") => {
  state.gestoriaCrmView = viewName;
  if (gestoriaCrmViews) {
    gestoriaCrmViews.querySelectorAll(".tab").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.gestoriaView === viewName);
    });
  }
  if (gestoriaCrmViewCrm) {
    gestoriaCrmViewCrm.classList.toggle("hidden", viewName !== "crm");
  }
  if (gestoriaCrmViewBdt) {
    gestoriaCrmViewBdt.classList.toggle("hidden", viewName !== "bdt");
  }
  if (gestoriaCrmViewAlta) {
    gestoriaCrmViewAlta.classList.toggle("hidden", viewName !== "alta");
  }
  if (viewName === "bdt") {
    loadGestoriaBdt();
  }
  if (viewName === "crm") {
    loadGestoriaCrm();
  }
};

const setSegurosTab = (name) => {
  const tabs = document.getElementById("segurosTabs");
  if (!tabs) return;
  const sections = Array.from(document.querySelectorAll(".seguros-tab"));
  state.segurosTab = name;
  tabs.querySelectorAll(".tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.segurosTab === name);
  });
  sections.forEach((section) => {
    section.classList.toggle("active", section.dataset.segurosTab === name);
  });
  if (name === "dashboard" && state.currentEmpresaId) {
    window.requestAnimationFrame(() => {
      renderFincasDashboard(state.currentEmpresaId);
    });
  }
};

const initSegurosTabs = () => {
  const tabs = document.getElementById("segurosTabs");
  if (!tabs || tabs.dataset.ready === "1") return;
  tabs.dataset.ready = "1";
  tabs.addEventListener("click", (event) => {
    const btn = event.target.closest(".tab");
    if (!btn || !btn.dataset.segurosTab) return;
    setSegurosTab(btn.dataset.segurosTab);
  });
  setSegurosTab(state.segurosTab || "dashboard");
};

document.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-seguros-tab]");
  if (!btn) return;
  setSegurosTab(btn.dataset.segurosTab);
});

const setGestoriaClientModuleTab = (tabName = "") => {
  if (!gestoriaModuleTabs) return;
  const map = {
    contabilidad: gestoriaModuleContabilidad,
    fiscal: gestoriaModuleFiscal,
    laboral: gestoriaModuleLaboral,
    renta: gestoriaModuleRenta,
    admin: gestoriaModuleAdmin,
  };
  const target = tabName || "contabilidad";
  gestoriaModuleTabs.querySelectorAll(".tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.gestoriaModule === target);
  });
  Object.entries(map).forEach(([key, section]) => {
    if (!section) return;
    section.classList.toggle("hidden", key !== target);
  });
  if (!state.currentClienteId) return;
  if (target === "fiscal") {
    loadGestoriaModelos(state.currentClienteId);
    loadGestoriaTrabajosFiltered(
      state.currentClienteId,
      ["Fiscal", "Modelos Hacienda", "Registro Mercantil"],
      gestoriaFiscalTrabajosTable,
      gestoriaFiscalTrabajosInfo,
      "incidencias fiscales"
    );
  }
  if (target === "laboral") {
    loadGestoriaTrabajosFiltered(
      state.currentClienteId,
      ["Altas/Bajas", "Contratos", "Nóminas", "Seguros sociales", "IT/Bajas médicas", "Finiquitos", "Otros laboral"],
      gestoriaLaboralTable,
      gestoriaLaboralInfo,
      "gestiones laborales"
    );
  }
  if (target === "renta") {
    loadGestoriaTrabajosFiltered(
      state.currentClienteId,
      [
        "Declaración en periodo",
        "Declaración extemporánea",
        "Requerimiento",
        "Complementaria",
        "Rectificativa",
        "Otros renta",
      ],
      gestoriaRentaTable,
      gestoriaRentaInfo,
      "expedientes de renta"
    );
  }
  if (target === "admin") {
    loadGestoriaTrabajosFiltered(
      state.currentClienteId,
      [
        "Tráfico - Transferencias",
        "Tráfico - Matriculaciones",
        "Herencias",
        "Extinción de condominio",
        "IMV",
        "Becas",
        "Complemento brecha de género",
        "Otros administrativos",
      ],
      gestoriaAdminTable,
      gestoriaAdminInfo,
      "gestiones administrativas"
    );
  }
};

const updateGestoriaModuleTabsFromForm = () => {
  if (!clienteGestoriaForm || !gestoriaModuleTabs) return;
  const hasContable = !!clienteGestoriaForm.querySelector('[name="mod_contable"]')?.checked;
  const hasFiscal = !!clienteGestoriaForm.querySelector('[name="mod_fiscal"]')?.checked;
  const hasLaboral = !!clienteGestoriaForm.querySelector('[name="mod_laboral"]')?.checked;
  const hasRenta = !!clienteGestoriaForm.querySelector('[name="mod_renta"]')?.checked;
  const hasAdmin =
    !!clienteGestoriaForm.querySelector('[name="mod_puntuales"]')?.checked ||
    !!clienteGestoriaForm.querySelector('[name="mod_trafico"]')?.checked ||
    !!clienteGestoriaForm.querySelector('[name="mod_registro"]')?.checked;
  const availability = {
    contabilidad: hasContable,
    fiscal: hasFiscal,
    laboral: hasLaboral,
    renta: hasRenta,
    admin: hasAdmin,
  };
  let firstActive = "";
  gestoriaModuleTabs.querySelectorAll(".tab").forEach((btn) => {
    const key = btn.dataset.gestoriaModule;
    const active = !!availability[key];
    btn.classList.toggle("hidden", !active);
    if (!firstActive && active) {
      firstActive = key;
    }
  });
  setGestoriaClientModuleTab(firstActive || "contabilidad");
};

const syncEmpresaFromServicio = (service) => {
  if (!clientesEmpresaSelect || !service) return;
  const targetName = SERVICE_COMPANY_MAP[service];
  if (!targetName) return;
  const match = state.empresas.find((e) => e.nombre === targetName);
  if (match) {
    clientesEmpresaSelect.value = match.id;
  }
};

const populateEmpresasSelect = (selectEl) => {
  if (!selectEl) return;
  selectEl.innerHTML = "";
  selectEl.appendChild(createOption("", "Selecciona empresa"));
  state.empresas.forEach((empresa) => {
    selectEl.appendChild(createOption(empresa.id, empresa.nombre));
  });
};

const syncAssignEmpresaFromServicio = (service) => {
  if (!clienteAssignEmpresa || !service) return;
  const targetName = SERVICE_COMPANY_MAP[service];
  if (!targetName) return;
  const match = state.empresas.find((e) => e.nombre === targetName);
  if (match) {
    clienteAssignEmpresa.value = match.id;
  }
};

const renderPropietariosEditor = (propietarios) => {
  if (!inmuebleDatosGrid) return;
  const wrapper = document.createElement("div");
  wrapper.className = "card editable-card";
  wrapper.innerHTML = "<h3>Propietarios</h3>";

  const list = document.createElement("div");
  list.className = "inline-list";
  wrapper.appendChild(list);

  const addOwnerRow = (clienteId = "") => {
    const row = document.createElement("div");
    row.className = "inline-row";
    const select = document.createElement("select");
    select.classList.add("inline-input");
    populateClientesSelect(select, clienteId);
    select.addEventListener("change", () => {
      savePropietariosFromList();
    });
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "ghost";
    removeBtn.textContent = "Quitar";
    removeBtn.addEventListener("click", () => {
      row.remove();
      savePropietariosFromList();
    });
    row.appendChild(select);
    row.appendChild(removeBtn);
    list.appendChild(row);
  };

  const savePropietariosFromList = () => {
    const ids = Array.from(list.querySelectorAll("select"))
      .map((sel) => sel.value)
      .filter(Boolean);
    if (!state.currentInmuebleId) {
      return;
    }
    setInmuebleSaveStatus("Guardando...");
    fetch("/api/inmueble_propietarios_update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        inmueble_id: state.currentInmuebleId,
        cliente_ids: ids,
      }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          setInmuebleSaveStatus(data.error);
          return;
        }
        setInmuebleSaveStatus("Guardado");
        loadCrmInmuebles();
      })
      .catch(() => {
        setInmuebleSaveStatus("Error al guardar.");
      });
  };

  (propietarios || []).forEach((prop) => addOwnerRow(prop.id));
  if (!propietarios || !propietarios.length) {
    addOwnerRow("");
  }
  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.textContent = "Añadir propietario";
  addBtn.addEventListener("click", () => addOwnerRow(""));
  wrapper.appendChild(addBtn);
  inmuebleDatosGrid.appendChild(wrapper);
};

const updateTableVisibility = () => {
  if (explorerSection) {
    explorerSection.classList.toggle("operativa-mode", currentTab === "operativa");
  }
  const isClientePage = state.currentPage === "cliente";
  const isClientesModule = state.currentModule === "clientes";
  const isServiceCrm = ["crm", "gestoria-crm", "seguros-crm", "fin-crm", "gestoria-fact", "gestoria-conta", "gestoria-agenda", "gestoria-dash"].includes(currentTab);
  const isFinSim = currentTab === "fin-sim";
  const selectedCompany =
    state.currentEmpresaName ||
    state.empresas.find((e) => e.id === empresaSelect.value)?.nombre ||
    "";
  const isSegurosCrmVisible = segurosCrmSection && !segurosCrmSection.classList.contains("hidden");
  const isFinCrmVisible = finCrmSection && !finCrmSection.classList.contains("hidden");
  if (viewTabs) {
    viewTabs.classList.toggle(
      "hidden",
      isClientePage ||
        currentTab === "seguros-crm" ||
        currentTab === "fin-crm" ||
        isSegurosCrmVisible ||
        isFinCrmVisible
    );
  }
  if (altaTab) {
    const company = state.empresas.find((e) => e.id === empresaSelect.value)?.nombre;
    const hideAlta = !isClientesModule && company === FINCAS_COMPANY;
    altaTab.classList.toggle("hidden", hideAlta);
  }
  if (companySummary) {
    companySummary.classList.toggle("hidden", isClientePage || isServiceCrm);
  }
  if (tableToolbar) {
    tableToolbar.classList.toggle("hidden", isClientePage || isFinSim);
  }
  if (clientesEstadoFilter) {
    clientesEstadoFilter.classList.toggle("hidden", state.currentModule !== "clientes");
  }
  const isClientesAlta = state.currentModule === "clientes" && currentTab === "alta";
  if (tableContainer) {
    const hideTable = isClientePage || isClientesAlta || isFinSim;
    tableContainer.classList.toggle("hidden", hideTable);
  }
  if (tableInfo) {
    const hideInfo = isClientePage || isClientesAlta || isFinSim;
    tableInfo.classList.toggle("hidden", hideInfo);
  }
  if (clientesAltaSection && state.currentModule === "clientes") {
    clientesAltaSection.classList.toggle("hidden", !isClientesAlta);
  }
  if (clientesColumnsBtn) {
    clientesColumnsBtn.classList.toggle("hidden", state.currentModule !== "clientes" || isClientePage);
  }
  if (clientesColumnsPanel) {
    clientesColumnsPanel.classList.toggle("hidden", state.currentModule !== "clientes" || isClientePage);
  }
  if (clientesShowAllBtn) {
    clientesShowAllBtn.classList.toggle("hidden", state.currentModule !== "clientes" || isClientePage);
  }
  const showTable = currentTab === "bdt";
  if (bdtSection) {
    bdtSection.classList.toggle("hidden", !showTable || isClientePage || isServiceCrm);
  }
  if (crmSection) {
    crmSection.classList.toggle("hidden", currentTab !== "crm" || isClientePage);
  }
  if (gestoriaCrmSection) {
    gestoriaCrmSection.classList.toggle(
      "hidden",
      currentTab !== "gestoria-crm" || isClientePage
    );
  }
  if (currentTab === "gestoria-crm" && !isClientePage) {
    setGestoriaCrmView(state.gestoriaCrmView || "crm");
  }
  if (gestoriaDashboardSection) {
    gestoriaDashboardSection.classList.toggle(
      "hidden",
      currentTab !== "gestoria-dash" || isClientePage
    );
  }
  if (gestoriaContaSection) {
    gestoriaContaSection.classList.toggle(
      "hidden",
      currentTab !== "gestoria-conta" || isClientePage
    );
  }
  if (gestoriaAgendaSection) {
    gestoriaAgendaSection.classList.toggle(
      "hidden",
      currentTab !== "gestoria-agenda" || isClientePage
    );
  }
  if (gestoriaFactSection) {
    gestoriaFactSection.classList.toggle(
      "hidden",
      currentTab !== "gestoria-fact" || isClientePage
    );
  }
  if (segurosCrmSection) {
    segurosCrmSection.classList.toggle(
      "hidden",
      currentTab !== "seguros-crm" || isClientePage
    );
  }
  if (fincasDashboardSection) {
    fincasDashboardSection.classList.toggle(
      "hidden",
      currentTab !== "seguros-crm" || isClientePage
    );
  }
  if (finCrmSection) {
    finCrmSection.classList.toggle("hidden", currentTab !== "fin-crm" || isClientePage);
  }
  if (finSimSection) {
    finSimSection.classList.toggle(
      "hidden",
      currentTab !== "fin-sim" || isClientePage || selectedCompany !== FIN_COMPANY
    );
  }
  if (altaSection) {
    const company = state.empresas.find((e) => e.id === empresaSelect.value)?.nombre;
    altaSection.classList.toggle(
      "hidden",
      isClientePage || currentTab !== "alta" || company !== DASHBOARD_COMPANY
    );
  }
  // clientesAltaSection visibility handled above for clientes module
  if (aieSection) {
    aieSection.classList.toggle("hidden", currentTab !== "aie" || isClientePage);
  }
  if (hipotecaSection) {
    const company = state.empresas.find((e) => e.id === empresaSelect.value)?.nombre;
    hipotecaSection.classList.toggle(
      "hidden",
      isClientePage || currentTab !== "alta" || company !== FIN_COMPANY
    );
  }
  updateFincasBdtTabs();
  updateEstudioAltaTabs();
  if (state.currentModule === "clientes") {
    if (dashboardSection) dashboardSection.classList.add("hidden");
    if (finDashboardSection) finDashboardSection.classList.add("hidden");
    if (fincasDashboardSection) fincasDashboardSection.classList.add("hidden");
    if (fincasBdtTabs) fincasBdtTabs.classList.add("hidden");
    tablaSelect.classList.add("hidden");
  } else {
    tablaSelect.classList.toggle("hidden", currentTab === "gestoria-crm");
    if (currentTab !== "operativa") {
      if (dashboardSection) dashboardSection.classList.add("hidden");
      if (finDashboardSection) finDashboardSection.classList.add("hidden");
      if (fincasDashboardSection) fincasDashboardSection.classList.add("hidden");
    }
    if (isServiceCrm) {
      if (dashboardSection) dashboardSection.classList.add("hidden");
      if (finDashboardSection) finDashboardSection.classList.add("hidden");
      if (fincasDashboardSection) fincasDashboardSection.classList.add("hidden");
    }
  }
  if (clientesDetail) {
    clientesDetail.classList.toggle("hidden", state.currentPage !== "cliente");
  }
  updateBdtFiltersVisibility();
};

const updateClienteAltaPersona = () => {
  if (!clienteTipoPersona || !clienteAltaPersonaFields.length) {
    return;
  }
  const isJuridica = String(clienteTipoPersona.value || "").toLowerCase() === "jurídica";
  clienteAltaPersonaFields.forEach((field) => {
    field.classList.toggle("hidden", isJuridica);
  });
};

const updateFincasBdtTabs = () => {
  if (!fincasBdtTabs || !tablaSelect) {
    return;
  }
  const company =
    state.currentEmpresaName ||
    state.empresas.find((e) => e.id === empresaSelect.value)?.nombre;
  const showTabs = currentTab === "bdt" && company === FINCAS_COMPANY;
  fincasBdtTabs.classList.toggle("hidden", !showTabs);
  tablaSelect.classList.toggle("hidden", showTabs);
  if (!showTabs) {
    return;
  }
  const activeTable = tablaSelect.value || "movimientos";
  fincasBdtTabs.querySelectorAll(".tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.table === activeTable);
  });
};

const updateEstudioAltaTabs = () => {
  if (!estudioAltaTabs || !altaSection) {
    return;
  }
  const company =
    state.currentEmpresaName ||
    state.empresas.find((e) => e.id === empresaSelect.value)?.nombre;
  const showTabs = currentTab === "alta" && company === DASHBOARD_COMPANY;
  estudioAltaTabs.classList.toggle("hidden", !showTabs);
  if (!showTabs) {
    return;
  }
  if (!altaSection.dataset.estudioActive) {
    altaSection.dataset.estudioActive = "bdt";
  }
  const active = altaSection.dataset.estudioActive;
  if (estudioAltaBdt) {
    estudioAltaBdt.classList.toggle("hidden", active !== "bdt");
  }
  if (estudioAltaCaptacion) {
    estudioAltaCaptacion.classList.toggle("hidden", active !== "captacion");
  }
  if (estudioAltaDemanda) {
    estudioAltaDemanda.classList.toggle("hidden", active !== "demanda");
  }
  estudioAltaTabs.querySelectorAll(".tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.section === active);
  });
};

const drawSignedBarChart = (canvas, labels, values, color) => {
  if (!canvas) return;
  const ctx = prepareCanvas(canvas);
  const width = canvas.getBoundingClientRect().width;
  const height = canvas.getBoundingClientRect().height;
  ctx.clearRect(0, 0, width, height);

  const padding = { top: 22, right: 18, bottom: 32, left: 36 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const maxAbs = Math.max(1, ...values.map((v) => Math.abs(v)));
  const zeroY = padding.top + chartHeight / 2;

  ctx.strokeStyle = "#efe9df";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padding.left, zeroY);
  ctx.lineTo(width - padding.right, zeroY);
  ctx.stroke();

  const groupWidth = chartWidth / Math.max(1, labels.length);
  const barWidth = Math.max(6, groupWidth - 16);

  labels.forEach((label, i) => {
    const value = values[i];
    const barHeight = (Math.abs(value) / maxAbs) * (chartHeight / 2);
    const x = padding.left + i * groupWidth + (groupWidth - barWidth) / 2;
    const y = value >= 0 ? zeroY - barHeight : zeroY;
    ctx.fillStyle = color;
    ctx.fillRect(x, y, barWidth, barHeight);

    const labelText = `${value.toFixed(1)}%`;
    ctx.fillStyle = "#4f4941";
    ctx.font = "10px Baskerville, serif";
    const textWidth = ctx.measureText(labelText).width;
    const textX = x + (barWidth - textWidth) / 2;
    const textY = value >= 0 ? y - 6 : y + barHeight + 12;
    ctx.fillText(labelText, textX, textY);

    ctx.fillStyle = "#6d665a";
    ctx.font = "10px Baskerville, serif";
    const labelX = padding.left + i * groupWidth + (groupWidth - ctx.measureText(label).width) / 2;
    ctx.fillText(label, labelX, height - padding.bottom + 18);
  });
};

const renderDashboard = (empresaName, empresaId) => {
  if (!empresaId || (empresaName !== DASHBOARD_COMPANY && empresaName !== FIN_COMPANY && empresaName !== FINCAS_COMPANY)) {
    dashboardSection.classList.add("hidden");
    if (finDashboardSection) {
      finDashboardSection.classList.add("hidden");
    }
    if (fincasDashboardSection) {
      fincasDashboardSection.classList.add("hidden");
    }
    updateTableVisibility();
    return;
  }

  if (empresaName === FIN_COMPANY) {
    dashboardSection.classList.add("hidden");
    if (fincasDashboardSection) {
      fincasDashboardSection.classList.add("hidden");
    }
    renderFinDashboard(empresaId);
    return;
  }

  if (empresaName === FINCAS_COMPANY) {
    dashboardSection.classList.add("hidden");
    if (finDashboardSection) {
      finDashboardSection.classList.add("hidden");
    }
    if (fincasDashboardSection) {
      fincasDashboardSection.classList.add("hidden");
    }
    updateTableVisibility();
    return;
  }

  dashboardTitle.textContent = `Dashboard · ${empresaName}`;
  dashboardSection.classList.remove("hidden");
  if (finDashboardSection) {
    finDashboardSection.classList.add("hidden");
  }
  if (fincasDashboardSection) {
    fincasDashboardSection.classList.add("hidden");
  }
  updateTableVisibility();

  api(`/api/dashboard?empresa_id=${empresaId}`).then((data) => {
    lastDashboardData = data;
    const currentYear = String(new Date().getFullYear());
    const ventasYear = getYearValueFromSeries(data.ventas, currentYear);
    const ingresosYear = getYearValueFromSeries(data.ingresos, currentYear);
    const gastosYear = getYearValueFromSeries(data.gastos, currentYear);
    const alquileresYear = getYearValueFromSeries(data.alquileres, currentYear);
    const facturadoAlquileresYear = data.alquileres.reduce(
      (acc, item) => acc + (item.facturado || 0),
      0
    );

    dashboardKpis.innerHTML = "";
    const kpis = [
      {
        title: `Ventas ${currentYear}`,
        value: numberFormatter.format(ventasYear),
        note: "Operaciones COMPRAVENTA",
      },
      {
        title: `Facturado ${currentYear}`,
        value: euroFormatter.format(ingresosYear),
        note: "Ingresos BDT",
      },
      {
        title: `Gastos ${currentYear}`,
        value: euroFormatter.format(gastosYear),
        note: "Gastos BDT",
      },
      {
        title: `Alquileres ${currentYear}`,
        value: numberFormatter.format(alquileresYear),
        note: `${euroFormatter.format(facturadoAlquileresYear)} facturados`,
      },
    ];

    kpis.forEach((kpi) => {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
        <h3>${kpi.title}</h3>
        <div class="muted">${kpi.value}</div>
        <div class="muted">${kpi.note}</div>
      `;
      dashboardKpis.appendChild(card);
    });

    requestAnimationFrame(() => {
      const ventasYears = buildYearIndex([data.ventas]);
      const facturadoYears = buildYearIndex([data.ingresos, data.gastos]);
      const alquilerYears = buildYearIndex([data.alquileres]);

      drawBarChart(
        ventasChart,
        ventasYears,
        [
          {
            label: "Ventas",
            values: alignSeries(ventasYears, data.ventas),
            color: "#824c45",
            format: (value) => numberFormatter.format(value),
          },
        ],
        { legend: false, showValues: true }
      );

      drawBarChart(
        facturadoChart,
        facturadoYears,
        [
          {
            label: "Facturado",
            values: alignSeries(facturadoYears, data.ingresos),
            color: "#d7b04c",
            format: (value) => euroFormatter.format(value),
          },
          {
            label: "Gastos",
            values: alignSeries(facturadoYears, data.gastos),
            color: "#7e8878",
            format: (value) => euroFormatter.format(value),
          },
        ],
        { legend: true, showValues: true }
      );

      drawBarChart(
        alquileresChart,
        alquilerYears,
        [
          {
            label: "Alquileres",
            values: alignSeries(alquilerYears, data.alquileres),
            color: "#cca33c",
            format: (value) => numberFormatter.format(value),
          },
        ],
        { legend: false, showValues: true }
      );

      const prevYear = String(Number(currentYear) - 1);
      const prevFacturado = getYearValueFromSeries(data.ingresos, prevYear);
      const progress = prevFacturado > 0 ? Math.min((ingresosYear / prevFacturado) * 100, 150) : 0;
      if (facturadoProgress) {
        facturadoProgress.innerHTML = `
          <div class="progress-meta">
            <span>${currentYear}: ${euroFormatter.format(ingresosYear)}</span>
            <span>Meta ${prevYear}: ${euroFormatter.format(prevFacturado)}</span>
          </div>
          <div class="progress-bar"><span style="width:${progress}%"></span></div>
          <div class="progress-meta">
            <span>Avance: ${progress.toFixed(1)}%</span>
            <span>Objetivo ${prevYear}</span>
          </div>
        `;
      }

      const ventasVar = computeVariations(data.ventas);
      const alquilerVar = computeVariations(data.alquileres);
      const facturadoVar = computeVariations(data.ingresos);

      drawSignedBarChart(
        ventasVarChart,
        ventasVar.map((item) => item.year),
        ventasVar.map((item) => item.total),
        "#824c45"
      );

      drawSignedBarChart(
        alquileresVarChart,
        alquilerVar.map((item) => item.year),
        alquilerVar.map((item) => item.total),
        "#cca33c"
      );

      drawSignedBarChart(
        facturadoVarChart,
        facturadoVar.map((item) => item.year),
        facturadoVar.map((item) => item.total),
        "#d7b04c"
      );
    });
  });
};

const renderFincasDashboard = (empresaId) => {
  if (!fincasDashboardSection) {
    return;
  }
  fincasDashboardSection.classList.remove("hidden");
  updateTableVisibility();
  const selectedYear = yearSelect?.value || String(new Date().getFullYear());
  const params = new URLSearchParams({
    empresa_id: empresaId,
    year: selectedYear,
  });
  api(`/api/fincas_seguros_dashboard?${params.toString()}`).then((data) => {
    if (!fincasDashboardKpis) {
      return;
    }
    fincasDashboardKpis.innerHTML = "";
    const current = data.current || {};
    const kpis = [
      {
        title: `Conversión ${current.year || selectedYear}`,
        value: `${(current.conversion || 0).toFixed(1)}%`,
        note: "Pólizas en vigor / oportunidades",
      },
      {
        title: `Presupuestos ${current.year || selectedYear}`,
        value: numberFormatter.format(current.presupuesto || 0),
        note: "En estado Presupuesto",
      },
      {
        title: `En vigor ${current.year || selectedYear}`,
        value: numberFormatter.format(current.en_vigor || 0),
        note: "Pólizas activas",
      },
      {
        title: "Conversión total",
        value: `${(current.conversion_total || 0).toFixed(1)}%`,
        note: "Histórico completo",
      },
      {
        title: "Presupuestos total",
        value: numberFormatter.format(current.presupuesto_total || 0),
        note: "Histórico completo",
      },
    ];
    kpis.forEach((kpi) => {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
        <h3>${kpi.title}</h3>
        <div class="muted">${kpi.value}</div>
        <div class="muted">${kpi.note}</div>
      `;
      fincasDashboardKpis.appendChild(card);
    });

    requestAnimationFrame(() => {
      const chartRect = fincasPresupuestoChart?.getBoundingClientRect();
      if (!chartRect || chartRect.width < 10 || chartRect.height < 10) {
        window.setTimeout(() => renderFincasDashboard(empresaId), 200);
        return;
      }
      const series = data.series || [];
      const years = buildYearIndex([series]);
      const presupuestos = years.map((year) => {
        const found = series.find((item) => String(item.year) === String(year));
        return found ? found.presupuesto || 0 : 0;
      });
      const enVigor = years.map((year) => {
        const found = series.find((item) => String(item.year) === String(year));
        return found ? found.en_vigor || 0 : 0;
      });

      drawBarChart(
        fincasPresupuestoChart,
        years,
        [
          {
            label: "Presupuesto",
            values: presupuestos,
            color: "#7e8878",
            format: (value) => numberFormatter.format(value),
          },
          {
            label: "En vigor",
            values: enVigor,
            color: "#824c45",
            format: (value) => numberFormatter.format(value),
          },
        ],
        { legend: true, showValues: true }
      );

      const responsables = data.responsables || [];
      const respLabels = responsables.map((item) => item.label);
      const respValues = responsables.map((item) => item.total);
      drawBarChart(
        fincasResponsableChart,
        respLabels,
        [
          {
            label: "Pólizas",
            values: respValues,
            color: "#d7b04c",
            format: (value) => numberFormatter.format(value),
          },
        ],
        { legend: false, showValues: true }
      );

      const conversion = years.map((year) => {
        const found = series.find((item) => String(item.year) === String(year));
        return found ? Number(found.conversion || 0) : 0;
      });
      drawBarChart(
        fincasConversionChart,
        years,
        [
          {
            label: "Conversión",
            values: conversion,
            color: "#3f5d5a",
            format: (value) => `${Number(value || 0).toFixed(1)}%`,
          },
        ],
        { legend: false, showValues: true }
      );
    });
  });
};

const renderFinDashboard = (empresaId) => {
  if (!finDashboardSection) {
    return;
  }
  finDashboardSection.classList.remove("hidden");
  updateTableVisibility();
  api(`/api/hipoteca_dashboard?empresa_id=${empresaId}`).then((data) => {
    const currentYear = String(new Date().getFullYear());
    const kpis = [
      {
        title: `Hipotecas ${currentYear}`,
        value: numberFormatter.format(data.current.total || 0),
        note: "Firmadas + Indemnización",
      },
      {
        title: "Firmadas mes",
        value: numberFormatter.format(data.current.firmadas_mes || 0),
        note: "Mes actual",
      },
      {
        title: "Porcentaje medio",
        value: formatPercent(data.current.porcentaje_medio),
        note: "Financiación",
      },
      {
        title: "Comisión media",
        value: euroFormatter.format(data.current.comision_media || 0),
        note: "Firmadas + Indemnización",
      },
    ];

    finDashboardKpis.innerHTML = "";
    kpis.forEach((kpi) => {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
        <h3>${kpi.title}</h3>
        <div class="muted">${kpi.value}</div>
        <div class="muted">${kpi.note}</div>
      `;
      finDashboardKpis.appendChild(card);
    });

    const years = buildYearIndex([data.series_totales]);
    drawBarChart(
      finHipotecasChart,
      years,
      [
        {
          label: "Hipotecas",
          values: alignSeries(years, data.series_totales),
          color: "#824c45",
          format: (value) => numberFormatter.format(value),
        },
      ],
      { legend: false, showValues: true }
    );

    const comisionYears = buildYearIndex([data.series_comision]);
    drawBarChart(
      finComisionChart,
      comisionYears,
      [
        {
          label: "Comisión",
          values: alignSeries(comisionYears, data.series_comision),
          color: "#d7b04c",
          format: (value) => euroFormatter.format(value),
        },
      ],
      { legend: false, showValues: true }
    );

    const entidadLabels = data.series_entidades.map((item) => item.label);
    const entidadValues = data.series_entidades.map((item) => item.total);
    drawBarChart(
      finEntidadChart,
      entidadLabels,
      [
        {
          label: "Entidad",
          values: entidadValues,
          color: "#7e8878",
          format: (value) => numberFormatter.format(value),
        },
      ],
      { legend: false, showValues: true }
    );

    const officeLabels = data.series_oficinas.map((item) => item.label);
    const officeValues = data.series_oficinas.map((item) => item.total);
    drawBarChart(
      finOficinaChart,
      officeLabels,
      [
        {
          label: "Oficina",
          values: officeValues,
          color: "#cca33c",
          format: (value) => numberFormatter.format(value),
        },
      ],
      { legend: false, showValues: true }
    );
  });
};

const loadHomeDashboard = () => {
  const estudio = state.empresas.find(
    (empresa) => empresa.nombre === DASHBOARD_COMPANY
  );
  if (!estudio || !yearSelect) {
    renderCompanyCards();
    return;
  }

  const currentYear = String(new Date().getFullYear());
  const setYears = (years) => {
    yearSelect.innerHTML = "";
    if (!years.length) {
      yearSelect.appendChild(createOption("", "Sin datos"));
      yearSelect.disabled = true;
      renderCompanyCards();
      return;
    }
    yearSelect.disabled = false;
    years.forEach((year) => {
      yearSelect.appendChild(createOption(year, year));
    });
    yearSelect.value = years.includes(currentYear)
      ? currentYear
      : years[years.length - 1];
    renderCompanyCards();
    updateBdtFiltersVisibility();
  };

  api(`/api/years`)
    .then((data) => {
      const years = (data.years || []).map(String);
      if (years.length) {
        state.homeYears = years;
        setYears(years);
      }
    })
    .catch(() => {});

  api(`/api/dashboard?empresa_id=${estudio.id}`).then((data) => {
    state.homeDashboard = data;
    if (!state.homeYears.length) {
      const years = buildYearIndex([data.ventas, data.ingresos, data.gastos, data.alquileres]);
      state.homeYears = years;
      setYears(years);
    } else {
      renderCompanyCards();
      updateBdtFiltersVisibility();
    }
  });
};

const loadHomeHipotecaStats = () => {
  const fin = state.empresas.find((empresa) => empresa.nombre === FIN_COMPANY);
  if (!fin) {
    return Promise.resolve();
  }
  return api(`/api/hipoteca_stats?empresa_id=${fin.id}`).then((data) => {
    state.homeHipotecaStats = data;
  });
};

const loadHomeFincasStats = (year) => {
  const fincas = state.empresas.find((empresa) => empresa.nombre === FINCAS_COMPANY);
  if (!fincas) {
    return Promise.resolve();
  }
  const params = new URLSearchParams({ empresa_id: fincas.id });
  if (year) {
    params.set("year", year);
  }
  return api(`/api/fincas_stats?${params.toString()}`).then((data) => {
    state.homeFincasStats = data;
  });
};

const loadClientesStats = () =>
  api("/api/clientes_stats").then((data) => {
    state.clientesStats = data;
  });

const loadClientesList = () =>
  api("/api/clientes_list").then((data) => {
    const list = data || [];
    list.sort((a, b) => {
      const nameA = normalizeNombre(formatNombreCliente(a.nombre));
      const nameB = normalizeNombre(formatNombreCliente(b.nombre));
      return nameA.localeCompare(nameB, "es", { numeric: true, sensitivity: "base" });
    });
    state.clientesList = list;
    return state.clientesList;
  });

const renderClientesSelects = (clientes) => {
  if (clientesSelect) {
    clientesSelect.innerHTML = "";
    clientesSelect.appendChild(createOption("", "Selecciona cliente"));
    clientes.forEach((cliente) => {
      clientesSelect.appendChild(createOption(cliente.id, formatNombreCliente(cliente.nombre)));
    });
  }
  if (captacionPropietarios) {
    captacionPropietarios.innerHTML = "";
    clientes.forEach((cliente) => {
      captacionPropietarios.appendChild(createOption(cliente.id, formatNombreCliente(cliente.nombre)));
    });
  }
  if (demandaCliente) {
    demandaCliente.innerHTML = "";
    demandaCliente.appendChild(createOption("", "Selecciona cliente"));
    clientes.forEach((cliente) => {
      demandaCliente.appendChild(createOption(cliente.id, formatNombreCliente(cliente.nombre)));
    });
  }
  if (clientesEmpresaSelect) {
    clientesEmpresaSelect.innerHTML = "";
    clientesEmpresaSelect.appendChild(createOption("", "Selecciona empresa"));
    state.empresas.forEach((empresa) => {
      clientesEmpresaSelect.appendChild(createOption(empresa.id, empresa.nombre));
    });
  }
};

const refreshClientesAltaSelects = () => {
  const ensureEmpresas = state.empresas && state.empresas.length
    ? Promise.resolve(state.empresas)
    : api("/api/empresas").then((data) => {
        state.empresas = data || [];
        return state.empresas;
      });
  const ensureClientes = state.clientesList && state.clientesList.length
    ? Promise.resolve(state.clientesList)
    : loadClientesList();
  Promise.all([ensureEmpresas, ensureClientes]).then(([_, clientes]) => {
    renderClientesSelects(clientes || []);
    populateServiciosSelect(clientesServicioSelect);
    refreshClientesLinkRows();
  });
};

const buildClientesLinkRow = (data = {}) => {
  if (!clientesLinkRows) return;
  const row = document.createElement("div");
  row.className = "link-row";

  const empresaLabel = document.createElement("label");
  empresaLabel.textContent = "Empresa";
  const empresaSelect = document.createElement("select");
  empresaSelect.dataset.field = "empresa_id";
  empresaSelect.appendChild(createOption("", "Selecciona empresa"));
  state.empresas.forEach((empresa) => {
    empresaSelect.appendChild(createOption(empresa.id, empresa.nombre));
  });
  if (data.empresa_id) empresaSelect.value = data.empresa_id;
  empresaLabel.appendChild(empresaSelect);

  const servicioLabel = document.createElement("label");
  servicioLabel.textContent = "Servicio";
  const servicioSelect = document.createElement("select");
  servicioSelect.dataset.field = "servicio";
  populateServiciosSelect(servicioSelect, data.servicio || "");
  servicioLabel.appendChild(servicioSelect);

  const estadoLabel = document.createElement("label");
  estadoLabel.textContent = "Estado";
  const estadoSelect = document.createElement("select");
  estadoSelect.dataset.field = "estado";
  estadoSelect.appendChild(createOption("Activo", "Activo"));
  estadoSelect.appendChild(createOption("Inactivo", "Inactivo"));
  estadoSelect.value = data.estado || "Activo";
  estadoLabel.appendChild(estadoSelect);

  const fechaInicioLabel = document.createElement("label");
  fechaInicioLabel.textContent = "Fecha inicio";
  const fechaInicio = document.createElement("input");
  fechaInicio.type = "date";
  fechaInicio.dataset.field = "fecha_inicio";
  fechaInicio.value = data.fecha_inicio || "";
  fechaInicioLabel.appendChild(fechaInicio);

  const fechaFinLabel = document.createElement("label");
  fechaFinLabel.textContent = "Fecha fin";
  const fechaFin = document.createElement("input");
  fechaFin.type = "date";
  fechaFin.dataset.field = "fecha_fin";
  fechaFin.value = data.fecha_fin || "";
  fechaFinLabel.appendChild(fechaFin);

  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "ghost";
  removeBtn.textContent = "Quitar";
  removeBtn.addEventListener("click", () => {
    row.remove();
  });

  row.appendChild(empresaLabel);
  row.appendChild(servicioLabel);
  row.appendChild(estadoLabel);
  row.appendChild(fechaInicioLabel);
  row.appendChild(fechaFinLabel);
  row.appendChild(removeBtn);
  clientesLinkRows.appendChild(row);
};

const refreshClientesLinkRows = () => {
  if (!clientesLinkRows) return;
  const rows = Array.from(clientesLinkRows.querySelectorAll(".link-row"));
  if (!rows.length) {
    buildClientesLinkRow();
    return;
  }
  rows.forEach((row) => {
    const empresaSelect = row.querySelector('[data-field="empresa_id"]');
    const servicioSelect = row.querySelector('[data-field="servicio"]');
    if (empresaSelect) {
      const current = empresaSelect.value;
      empresaSelect.innerHTML = "";
      empresaSelect.appendChild(createOption("", "Selecciona empresa"));
      state.empresas.forEach((empresa) => {
        empresaSelect.appendChild(createOption(empresa.id, empresa.nombre));
      });
      if (current) empresaSelect.value = current;
    }
    if (servicioSelect) {
      const current = servicioSelect.value;
      populateServiciosSelect(servicioSelect, current || "");
    }
  });
};

const loadClientesTable = () => {
  const empresaId = empresaSelect.value || "";
  const q = searchInput.value.trim();
  const estado = clientesEstadoFilter ? clientesEstadoFilter.value.trim() : "";
  if (!q && !empresaId && !state.clientesShowAll) {
    tableContainer.innerHTML = "<p class='muted'>Usa búsqueda o filtros para cargar clientes.</p>";
    if (tableInfo) {
      tableInfo.textContent = "";
    }
    return;
  }
  const visibleColumns = getClientesVisibleColumns();
  const params = new URLSearchParams({ include_id: "1", limit: "50" });
  if (state.clientesShowAll) {
    params.set("limit", "500");
  }
  if (empresaId) {
    params.set("empresa_id", empresaId);
  }
  if (q) {
    params.set("q", q);
  }
  if (estado) {
    params.set("estado", estado);
  }
  return api(`/api/clientes?${params.toString()}`).then((data) => {
    const rows = data.rows || [];
    const dataColumns = Array.isArray(data.columns) ? data.columns : null;
    const getRowMeta = (row) => {
      let hasId = row.length === CLIENTES_SOURCE_COLUMNS.length + 1;
      const looksLikeId =
        typeof row[0] === "string" && /^[0-9a-f]{32}$/i.test(row[0]);
      if (!hasId && looksLikeId && row.length >= 2) {
        hasId = true;
      }
      const offset = hasId ? 1 : 0;
      const getValue = (col) => {
        if (dataColumns) {
          const idx = dataColumns.indexOf(col);
          return idx >= 0 && idx < row.length ? row[idx] : "";
        }
        const srcIndex = CLIENTES_SOURCE_COLUMNS.indexOf(col);
        return srcIndex >= 0 && srcIndex + offset < row.length
          ? row[srcIndex + offset]
          : "";
      };
      const fullName = getValue("nombre");
      const tipoPersona = getValue("tipo_persona");
      const nameParts = splitNombreApellidos(fullName, tipoPersona);
      return {
        row,
        hasId,
        offset,
        getValue,
        fullName,
        tipoPersona,
        nameParts,
      };
    };
    const sortedRows = rows
      .map(getRowMeta)
      .sort((a, b) => {
        const aLast = (a.nameParts.apellidos || "").toLowerCase();
        const bLast = (b.nameParts.apellidos || "").toLowerCase();
        if (aLast !== bLast) return aLast.localeCompare(bLast, "es");
        const aName = (a.nameParts.nombre || "").toLowerCase();
        const bName = (b.nameParts.nombre || "").toLowerCase();
        return aName.localeCompare(bName, "es");
      });
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    [...visibleColumns, "accion"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    sortedRows.forEach((meta) => {
      const { row, hasId, offset, getValue, tipoPersona, nameParts } = meta;
      let rowId = hasId ? row[0] : "";
      if (!rowId) {
        const nameValue = row[0] || "";
        rowId = state.clientesList.find((c) => c.nombre === nameValue)?.id || "";
      }
      const tr = document.createElement("tr");
      visibleColumns.forEach((col) => {
        const td = document.createElement("td");
        let value = "";
        if (col === "apellidos") {
          value = nameParts.apellidos;
        } else if (col === "nombre") {
          value = nameParts.nombre;
        } else {
          value = getValue(col);
        }
        const formatted =
          col === "apellidos" || col === "nombre"
            ? value
            : formatCell(col, value, tipoPersona);
        td.textContent = formatted === null ? "" : formatted;
        tr.appendChild(td);
      });
      const actionTd = document.createElement("td");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Ver ficha";
      btn.addEventListener("click", () => {
        if (!rowId) return;
        openClienteDetail(rowId);
      });
      actionTd.appendChild(btn);
      tr.appendChild(actionTd);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    tableContainer.innerHTML = "";
    tableContainer.appendChild(table);
    const baseText = `Mostrando ${rows.length} clientes.`;
    tableInfo.textContent = baseText;
    tableInfo.dataset.baseText = baseText;
    updateTableVisibility();
  });
};

const renderClientesColumnsPicker = () => {
  if (!clientesColumnsList) return;
  clientesColumnsList.innerHTML = "";
  const selected = new Set(getClientesVisibleColumns());
  CLIENTES_COLUMNS.forEach((col) => {
    const label = document.createElement("label");
    label.className = "column-toggle";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = selected.has(col);
    if (col === "servicios") {
      input.checked = true;
      input.disabled = true;
    }
    input.addEventListener("change", () => {
      if (input.checked) {
        selected.add(col);
      } else {
        selected.delete(col);
      }
      const next = CLIENTES_COLUMNS.filter((c) => selected.has(c));
      saveClientesVisibleColumns(next);
      loadClientesTable();
    });
    label.appendChild(input);
    label.appendChild(document.createTextNode(formatHeader(col)));
    clientesColumnsList.appendChild(label);
  });
};

const loadFincasRenewalAlert = () => {
  const fincas = state.empresas.find((empresa) => empresa.nombre === FINCAS_COMPANY);
  if (!fincas || !renewalAlert) {
    return Promise.resolve();
  }
  const params = new URLSearchParams({ empresa_id: fincas.id });
  return api(`/api/fincas_alerts?${params.toString()}`).then((data) => {
    if (!data || !data.count) {
      renewalAlert.classList.add("hidden");
      renewalAlert.textContent = "";
      return;
    }
    renewalAlert.classList.remove("hidden");
    renewalAlert.innerHTML = "";

    const text = document.createElement("div");
    text.textContent = `Alerta: ${data.count} pólizas vencen en los próximos 30 días.`;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Ver pólizas";
    button.addEventListener("click", () => {
      const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
      if (!empresa) return;
      empresaSelect.value = empresa.id;
      state.currentEmpresaId = empresa.id;
      state.currentEmpresaName = empresa.nombre;
      updateExplorerHeader(empresa.nombre);
      setTab("bdt");
      tablaSelect.value = "seguros";
      updateFincasBdtTabs();
      explorerSection.classList.remove("hidden");
      loadTable();
      window.scrollTo({ top: tableContainer.offsetTop - 120, behavior: "smooth" });
    });
    renewalAlert.appendChild(text);
    renewalAlert.appendChild(button);
  });
};

const sendTableUpdate = (table, recordId, column, value) => {
  if (!recordId) {
    return Promise.resolve();
  }
  const endpoint = table === "seguros" ? "/api/seguros_update" : "/api/gestoria_update";
  if (tableInfo) {
    tableInfo.textContent = "Actualizando...";
  }
  const payload = {
    id: recordId,
    empresa_nombre: FINCAS_COMPANY,
    [column]: value,
  };
  return fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.error) {
        if (tableInfo) {
          tableInfo.textContent = data.error;
        }
        return;
      }
      if (tableInfo) {
        tableInfo.textContent = "Actualizado.";
        const baseText = tableInfo.dataset.baseText;
        if (baseText) {
          setTimeout(() => {
            tableInfo.textContent = baseText;
          }, 1200);
        }
      }
    })
    .catch(() => {
      if (tableInfo) {
        tableInfo.textContent = "Error al actualizar.";
      }
    });
};

const renderTable = (data, options = {}) => {
  const { columns, rows } = data;
  const showActions = options.showActions;
  const editableTable = options.editableTable;
  const editableFields = editableTable ? EDITABLE_FIELDS[editableTable] : null;
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const trHead = document.createElement("tr");
  columns.forEach((col) => {
    if (col === "id" || col === "poliza_key" || col === "poliza_url") {
      return;
    }
    const th = document.createElement("th");
    th.textContent = formatHeader(col);
    trHead.appendChild(th);
  });
  if (showActions) {
    const th = document.createElement("th");
    th.textContent = "ACCION";
    trHead.appendChild(th);
  }
  thead.appendChild(trHead);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    let rowId = "";
    row.forEach((cell, idx) => {
      const colName = columns[idx] || "";
      if (colName === "id" || colName === "poliza_key" || colName === "poliza_url") {
        rowId = cell;
        return;
      }
      const td = document.createElement("td");
      if (editableFields && editableFields[colName]) {
        const config = editableFields[colName];
        if (config.type === "select") {
          const select = document.createElement("select");
          const empty = document.createElement("option");
          empty.value = "";
          empty.textContent = "-";
          select.appendChild(empty);
          config.options.forEach((optionValue) => {
            const option = document.createElement("option");
            option.value = optionValue;
            option.textContent = optionValue;
            select.appendChild(option);
          });
          select.value = cell ?? "";
          select.addEventListener("change", () => {
            sendTableUpdate(editableTable, rowId, colName, select.value);
          });
          td.appendChild(select);
        } else {
          const input = document.createElement("input");
          input.type = config.type;
          input.value = cell ?? "";
          input.addEventListener("change", () => {
            sendTableUpdate(editableTable, rowId, colName, input.value);
          });
          td.appendChild(input);
        }
      } else {
        const formatted = formatCell(colName, cell);
        td.textContent = formatted === null ? "" : formatted;
      }
      tr.appendChild(td);
    });
    if (showActions) {
      const td = document.createElement("td");
      const btn = document.createElement("button");
      btn.textContent = "Firmar";
      btn.addEventListener("click", () => {
        const fecha = prompt("Fecha firma (YYYY-MM-DD):");
        if (!fecha) return;
        const payload = { id: rowId, fecha_firma: fecha, estado: "FIRMADA" };
        fetch("/api/hipotecas/firmar", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        })
          .then((res) => res.json())
          .then((data) => {
            if (data.error) {
              alert(data.error);
              return;
            }
            loadTable();
            const empresa = state.empresas.find(
              (item) => item.nombre === FIN_COMPANY
            );
            if (empresa) {
              renderFinDashboard(empresa.id);
            }
          });
      });
      td.appendChild(btn);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  tableContainer.innerHTML = "";
  tableContainer.appendChild(table);
};

const renderTableInto = (data, container, infoEl, label) => {
  if (!container) {
    return;
  }
  const { columns, rows } = data;
  const hasPolizaKey = columns.includes("poliza_key");
  const hasPolizaUrl = columns.includes("poliza_url");
  const polizaKeyIndex = columns.indexOf("poliza_key");
  const polizaUrlIndex = columns.indexOf("poliza_url");
  const showPdf = label === "Seguros" && (hasPolizaKey || hasPolizaUrl);
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const trHead = document.createElement("tr");
  columns.forEach((col) => {
    if (col === "id" || col === "poliza_key" || col === "poliza_url") {
      return;
    }
    const th = document.createElement("th");
    th.textContent = formatHeader(col);
    trHead.appendChild(th);
  });
  if (showPdf) {
    const th = document.createElement("th");
    th.textContent = "PDF";
    trHead.appendChild(th);
  }
  thead.appendChild(trHead);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    row.forEach((cell, idx) => {
      const colName = columns[idx] || "";
      if (colName === "id" || colName === "poliza_key" || colName === "poliza_url") {
        return;
      }
      const td = document.createElement("td");
      if (!applyCompanyCell(td, colName, cell) && !applyRamoCell(td, colName, cell)) {
        const formatted = formatCell(colName, cell);
        td.textContent = formatted === null ? "" : formatted;
      }
      tr.appendChild(td);
    });
    if (showPdf) {
      const td = document.createElement("td");
      const key = polizaKeyIndex >= 0 ? row[polizaKeyIndex] : "";
      const url = polizaUrlIndex >= 0 ? row[polizaUrlIndex] : "";
      if (key || url) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "secondary";
        btn.textContent = "Ver";
        btn.addEventListener("click", () => {
          openS3File(key, url);
        });
        td.appendChild(btn);
      } else {
        td.textContent = "-";
      }
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.innerHTML = "";
  container.appendChild(table);
  if (infoEl) {
    infoEl.textContent = `Mostrando ${rows.length} filas de ${label}.`;
  }
};

const loadCrmCaptaciones = () => {
  if (!crmCaptacionesTable) {
    return;
  }
  const empresa = state.empresas.find((e) => e.nombre === DASHBOARD_COMPANY);
  if (!empresa) {
    crmCaptacionesTable.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  const params = new URLSearchParams({
    tabla: "captaciones",
    empresa_id: empresa.id,
  });
  params.set("include_id", "1");
  api(`/api/tabla?${params.toString()}`).then((data) => {
    const etapaIndex = data.columns.indexOf("etapa");
    const idIndex = data.columns.indexOf("id");
    const filteredRows = data.rows.filter((row) => {
      if (!crmEtapaFilter || !crmEtapaFilter.value) {
        return true;
      }
      return row[etapaIndex] === crmEtapaFilter.value;
    });
    const counts = {};
    data.rows.forEach((row) => {
      const etapa = row[etapaIndex] || "Sin etapa";
      counts[etapa] = (counts[etapa] || 0) + 1;
    });
    if (crmPipeline) {
      const etapas = [
        "Prospecto",
        "Contactado",
        "Visita/Valoración",
        "Negociación",
        "Encargo firmado",
        "Publicado",
        "Perdido",
      ];
      crmPipeline.innerHTML = "";
      etapas.forEach((etapa) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.classList.add(`stage-${slugify(etapa)}`);
        btn.textContent = `${etapa} (${counts[etapa] || 0})`;
        btn.classList.toggle("active", crmEtapaFilter?.value === etapa);
        btn.addEventListener("click", () => {
          if (crmEtapaFilter) {
            crmEtapaFilter.value = crmEtapaFilter.value === etapa ? "" : etapa;
          }
          loadCrmCaptaciones();
        });
        crmPipeline.appendChild(btn);
      });
    }
    if (crmKpiCaptaciones) {
      crmKpiCaptaciones.textContent = String(data.rows.length);
    }
    if (crmKpiEtapa) {
      const maxEtapa = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
      crmKpiEtapa.textContent = maxEtapa ? maxEtapa[0] : "-";
    }
    renderCrmKanban(data);
    renderTableInto(
      { columns: data.columns, rows: filteredRows },
      crmCaptacionesTable,
      crmCaptacionesInfo,
      "Captaciones"
    );
  });
};

const renderCrmKanban = (data) => {
  if (!crmKanban) {
    return;
  }
  const etapaIndex = data.columns.indexOf("etapa");
  const idIndex = data.columns.indexOf("id");
  const propietarioIndex = data.columns.indexOf("propietario");
  const direccionIndex = data.columns.indexOf("direccion");
  const zonaIndex = data.columns.indexOf("zona");
  const proximaIndex = data.columns.indexOf("proxima_accion");
  const etapas = [
    "Prospecto",
    "Contactado",
    "Visita/Valoración",
    "Negociación",
    "Encargo firmado",
    "Publicado",
    "Perdido",
  ];
  const grouped = new Map(etapas.map((e) => [e, []]));
  data.rows.forEach((row) => {
    const etapa = row[etapaIndex] || "Prospecto";
    if (!grouped.has(etapa)) {
      grouped.set(etapa, []);
    }
    grouped.get(etapa).push(row);
  });
  crmKanban.innerHTML = "";
  etapas.forEach((etapa) => {
    const column = document.createElement("div");
    column.className = "crm-kanban-column";
    column.innerHTML = `<h4>${etapa}</h4>`;
    column.dataset.etapa = etapa;
    column.addEventListener("dragover", (event) => {
      event.preventDefault();
      column.classList.add("drag-over");
    });
    column.addEventListener("dragleave", () => {
      column.classList.remove("drag-over");
    });
    column.addEventListener("drop", (event) => {
      event.preventDefault();
      column.classList.remove("drag-over");
      const id = event.dataTransfer.getData("text/plain");
      if (id) {
        updateCaptacionEtapa(id, etapa);
      }
    });
    const rows = grouped.get(etapa) || [];
    rows.slice(0, 5).forEach((row) => {
      const rowId = row[idIndex];
      const card = document.createElement("div");
      card.className = "crm-kanban-card";
      card.setAttribute("draggable", "true");
      card.addEventListener("dragstart", (event) => {
        event.dataTransfer.setData("text/plain", rowId);
        event.dataTransfer.effectAllowed = "move";
      });
      card.innerHTML = `
        <div><strong>${row[propietarioIndex] || "Propietario"}</strong></div>
        <div>${row[direccionIndex] || "-"} · ${row[zonaIndex] || "-"}</div>
        <div class="muted">${row[proximaIndex] || "Sin próxima acción"}</div>
      `;
      column.appendChild(card);
    });
    crmKanban.appendChild(column);
  });
};

const updateCaptacionEtapa = (id, etapa) => {
  fetch("/api/captaciones_update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, etapa }),
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.error) {
        alert(data.error);
        return;
      }
      loadCrmCaptaciones();
    });
};

let cachedCrmInmuebles = [];
let cachedCrmDemandas = [];

const renderCrmInmueblesRecent = (rows) => {
  if (!crmInmueblesRecent) {
    return;
  }
  if (!rows.length) {
    crmInmueblesRecent.innerHTML = "<p class='muted'>Sin inmuebles recientes.</p>";
    return;
  }
  const list = document.createElement("div");
  list.className = "crm-recent-list";
  rows.slice(0, 6).forEach((row) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "crm-recent-item";
    item.innerHTML = `
      <div>
        <strong>${row.direccion || "Sin dirección"}</strong>
        <div class="muted">${row.zona || "Sin zona"} · ${row.referencia || "Sin referencia"}</div>
      </div>
      <span class="crm-badge">${row.estado || "Sin estado"}</span>
    `;
    item.addEventListener("click", () => openInmuebleDetail(row.id));
    list.appendChild(item);
  });
  crmInmueblesRecent.innerHTML = "";
  crmInmueblesRecent.appendChild(list);
};

const loadCrmInmuebles = () => {
  if (!crmInmueblesTable) {
    return;
  }
  const empresa = state.empresas.find((e) => e.nombre === DASHBOARD_COMPANY);
  if (!empresa) {
    crmInmueblesTable.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  const q = crmInmuebleSearch ? crmInmuebleSearch.value.trim() : "";
  const params = new URLSearchParams({ empresa_id: empresa.id });
  if (q) {
    params.set("q", q);
  }
  api(`/api/inmuebles?${params.toString()}`).then((data) => {
    const rows = data.rows || [];
    cachedCrmInmuebles = rows;
    renderCrmInmueblesRecent(rows);
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["referencia", "direccion", "zona", "estado", "propietarios", "accion"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const cells = [
        row.referencia || "-",
        row.direccion || "-",
        row.zona || "-",
        row.estado || "-",
        row.propietarios || "-",
      ];
      cells.forEach((value, idx) => {
        const td = document.createElement("td");
        td.textContent = formatCell(["referencia", "direccion", "zona", "estado", "propietarios"][idx], value);
        tr.appendChild(td);
      });
      const actionTd = document.createElement("td");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Ver ficha";
      btn.addEventListener("click", () => {
        openInmuebleDetail(row.id);
      });
      actionTd.appendChild(btn);
      tr.appendChild(actionTd);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    crmInmueblesTable.innerHTML = "";
    crmInmueblesTable.appendChild(table);
    if (crmInmueblesInfo) {
      crmInmueblesInfo.textContent = `Mostrando ${rows.length} inmuebles.`;
    }
    if (crmKpiInmuebles) {
      crmKpiInmuebles.textContent = String(rows.length);
    }
  });
};

const loadCrmDemandas = () => {
  if (!crmDemandasTable) {
    return;
  }
  const empresa = state.empresas.find((e) => e.nombre === DASHBOARD_COMPANY);
  if (!empresa) {
    crmDemandasTable.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  const params = new URLSearchParams({ empresa_id: empresa.id });
  api(`/api/demandas?${params.toString()}`).then((data) => {
    const rows = data.rows || [];
    cachedCrmDemandas = rows;
    renderVisitaSelects();
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    [
      "cliente",
      "tipo",
      "zona",
      "precio_max",
      "m2_min",
      "habitaciones_min",
      "banos_min",
      "estado",
      "prioridad",
      "accion",
    ].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const cells = [
        row.cliente || "-",
        row.tipo || "-",
        row.zona || "-",
        row.precio_max,
        row.m2_min,
        row.habitaciones_min,
        row.banos_min,
        row.estado || "-",
        row.prioridad || "-",
      ];
      cells.forEach((value, idx) => {
        const td = document.createElement("td");
        const colName = [
          "cliente",
          "tipo",
          "zona",
          "precio_max",
          "m2_min",
          "habitaciones_min",
          "banos_min",
          "estado",
          "prioridad",
        ][idx];
        const formatted = formatCell(colName, value);
        td.textContent = formatted === null ? "" : formatted;
        tr.appendChild(td);
      });
      const actionTd = document.createElement("td");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Matching";
      btn.addEventListener("click", () => {
        openDemandaDetail(row.id);
      });
      actionTd.appendChild(btn);
      tr.appendChild(actionTd);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    crmDemandasTable.innerHTML = "";
    crmDemandasTable.appendChild(table);
    if (crmDemandasInfo) {
      crmDemandasInfo.textContent = `Mostrando ${rows.length} demandas.`;
    }
  });
};

const loadCrmVisitas = () => {
  if (!crmVisitasTable) {
    return;
  }
  const empresa = state.empresas.find((e) => e.nombre === DASHBOARD_COMPANY);
  if (!empresa) {
    crmVisitasTable.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  const params = new URLSearchParams({ empresa_id: empresa.id });
  api(`/api/visitas?${params.toString()}`).then((data) => {
    const rows = data.rows || [];
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["fecha", "hora", "estado", "inmueble", "cliente", "asesor"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const values = [
        row.fecha || "-",
        row.hora || "-",
        row.estado || "-",
        row.inmueble || "-",
        row.cliente || "-",
        row.asesor || "-",
      ];
      values.forEach((value, idx) => {
        const td = document.createElement("td");
        const colName = ["fecha", "hora", "estado", "inmueble", "cliente", "asesor"][idx];
        const formatted = formatCell(colName, value);
        td.textContent = formatted === null ? "" : formatted;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    crmVisitasTable.innerHTML = "";
    crmVisitasTable.appendChild(table);
    if (crmVisitasInfo) {
      crmVisitasInfo.textContent = `Mostrando ${rows.length} visitas.`;
    }
  });
};

const renderVisitaSelects = () => {
  if (visitaInmueble) {
    visitaInmueble.innerHTML = "";
    visitaInmueble.appendChild(createOption("", "Selecciona inmueble"));
    cachedCrmInmuebles.forEach((row) => {
      const label = row.direccion || row.referencia || "Inmueble";
      visitaInmueble.appendChild(createOption(row.id, label));
    });
  }
  if (visitaDemanda) {
    visitaDemanda.innerHTML = "";
    visitaDemanda.appendChild(createOption("", "Selecciona demanda"));
    cachedCrmDemandas.forEach((row) => {
      const label = `${row.cliente || "Sin cliente"} · ${row.zona || "-"}`;
      visitaDemanda.appendChild(createOption(row.id, label));
    });
  }
};

const openDemandaDetail = (id) => {
  if (!demandaDetail) return;
  const empresa = state.empresas.find((e) => e.nombre === DASHBOARD_COMPANY);
  if (!empresa) return;
  api(`/api/matching?empresa_id=${empresa.id}&demanda_id=${id}`).then((data) => {
    if (demandaTitle) {
      demandaTitle.textContent = "Matching de demanda";
    }
    if (demandaSubtitle) {
      demandaSubtitle.textContent = "Resultados sugeridos";
    }
    if (demandaMatching) {
      const rows = data.rows || [];
      if (!rows.length) {
        demandaMatching.innerHTML = "<p class='muted'>Sin inmuebles compatibles.</p>";
      } else {
        const table = document.createElement("table");
        const thead = document.createElement("thead");
        const trHead = document.createElement("tr");
        ["referencia", "direccion", "zona", "precio_objetivo", "m2", "habitaciones", "banos", "estado"].forEach((col) => {
          const th = document.createElement("th");
          th.textContent = formatHeader(col);
          trHead.appendChild(th);
        });
        thead.appendChild(trHead);
        table.appendChild(thead);
        const tbody = document.createElement("tbody");
        rows.forEach((row) => {
          const tr = document.createElement("tr");
          const values = [
            row.referencia || "-",
            row.direccion || "-",
            row.zona || "-",
            row.precio_objetivo,
            row.m2,
            row.habitaciones,
            row.banos,
            row.estado || "-",
          ];
          values.forEach((value, idx) => {
            const td = document.createElement("td");
            const colName = [
              "referencia",
              "direccion",
              "zona",
              "precio_objetivo",
              "m2",
              "habitaciones",
              "banos",
              "estado",
            ][idx];
            const formatted = formatCell(colName, value);
            td.textContent = formatted === null ? "" : formatted;
            tr.appendChild(td);
          });
          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        demandaMatching.innerHTML = "";
        demandaMatching.appendChild(table);
      }
    }
    demandaDetail.classList.remove("hidden");
  });
};

const setInmuebleTab = (tab) => {
  if (!inmuebleTabs) return;
  inmuebleTabs.querySelectorAll(".tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  if (inmuebleTabDatos) inmuebleTabDatos.classList.toggle("hidden", tab !== "datos");
  if (inmuebleTabCaptacion) inmuebleTabCaptacion.classList.toggle("hidden", tab !== "captacion");
  if (inmuebleTabDemandas) inmuebleTabDemandas.classList.toggle("hidden", tab !== "demandas");
  if (inmuebleTabVisitas) inmuebleTabVisitas.classList.toggle("hidden", tab !== "visitas");
  if (inmuebleTabActividad) inmuebleTabActividad.classList.toggle("hidden", tab !== "actividad");
  if (inmuebleTabMapa) inmuebleTabMapa.classList.toggle("hidden", tab !== "mapa");
  if (inmuebleTabDocs) inmuebleTabDocs.classList.toggle("hidden", tab !== "docs");
  if (inmuebleTabEstado) inmuebleTabEstado.classList.toggle("hidden", tab !== "estado");
};

const openInmuebleDetail = (id) => {
  if (!inmuebleDetail) return;
  state.currentInmuebleId = id;
  state.currentInmueble = null;
  setInmuebleSaveStatus("");
  const empresa = state.empresas.find((e) => e.nombre === DASHBOARD_COMPANY);
  const empresaId = empresa ? empresa.id : "";
  Promise.all([api(`/api/inmueble?id=${id}`), loadClientesList(), loadDemandasList(empresaId)])
    .then(([data]) => {
      const inmueble = data.inmueble || {};
      state.currentInmueble = inmueble;
      const captacion = data.captacion || {};
      if (inmuebleTitle) {
        inmuebleTitle.textContent = inmueble.direccion || "Ficha de inmueble";
      }
      if (inmuebleSubtitle) {
        inmuebleSubtitle.textContent = inmueble.referencia || "Referencia sin asignar";
      }
      if (inmuebleDatosGrid) {
        renderEditableGrid(inmuebleDatosGrid, INMUEBLE_FIELDS, inmueble, "inmueble");
        renderPropietariosEditor(data.propietarios || []);
      }
      if (inmuebleCaptacionGrid) {
        renderEditableGrid(inmuebleCaptacionGrid, CAPTACION_FIELDS, captacion, "captacion");
      }
      if (inmuebleDemandaCliente) {
        populateClientesSelect(inmuebleDemandaCliente);
      }
      if (inmuebleVisitaDemanda) {
        populateDemandasSelect(inmuebleVisitaDemanda);
      }
      if (inmuebleActividadClientes) {
        populateAgendaClientes(inmuebleActividadClientes, inmuebleActividadClienteInput, inmuebleActividadClienteId);
      }
      if (inmuebleMap) {
        updateInmuebleMap(inmueble.lat, inmueble.lon);
      }
      if (inmuebleEstadoInfo) {
        inmuebleEstadoInfo.textContent = `Estado actual: ${inmueble.estado || "-"}`;
      }
      loadInmuebleChecklist(id, inmueble.estado || "");
      if (inmuebleDocsList) {
        const docs = data.docs || [];
        if (!docs.length) {
          inmuebleDocsList.innerHTML = "<p class='muted'>Sin documentos cargados.</p>";
        } else {
          inmuebleDocsList.innerHTML = docs
            .map((doc) => `<div class="muted">${doc.nombre || doc.url}</div>`)
            .join("");
        }
      }
      if (inmuebleEstadoInfo) {
        inmuebleEstadoInfo.textContent = `Estado actual: ${inmueble.estado || "-"}`;
      }
      loadInmuebleDemandas(id);
      loadInmuebleVisitas(id, empresaId);
      loadInmuebleActividad(id, empresaId);
      loadInmuebleDocs(id);
      inmuebleDetail.classList.remove("hidden");
      setInmuebleTab("datos");
    })
    .catch(() => {
      if (inmuebleSaveStatus) {
        inmuebleSaveStatus.textContent = "Error al cargar.";
      }
    });
};

const loadInmuebleDemandas = (inmuebleId) => {
  if (!inmuebleDemandasTable || !inmuebleId) {
    return;
  }
  api(`/api/inmueble_matching?inmueble_id=${inmuebleId}`).then((data) => {
    const rows = data.rows || [];
    if (!rows.length) {
      inmuebleDemandasTable.innerHTML = "<p class='muted'>Sin demandas compatibles.</p>";
      return;
    }
    const inmueble = state.currentInmueble || {};
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["score", "cliente", "tipo", "zona", "precio_max", "m2_min", "habitaciones_min", "banos_min", "estado"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const constraints = [
        { key: "tipo", val: row.tipo, match: !row.tipo || row.tipo === inmueble.tipo_inmueble },
        { key: "zona", val: row.zona, match: !row.zona || (inmueble.zona || "").toLowerCase().includes(String(row.zona).toLowerCase()) },
        { key: "precio_max", val: row.precio_max, match: !row.precio_max || Number(inmueble.precio_objetivo || 0) <= Number(row.precio_max) },
        { key: "m2_min", val: row.m2_min, match: !row.m2_min || Number(inmueble.m2 || 0) >= Number(row.m2_min) },
        { key: "habitaciones_min", val: row.habitaciones_min, match: !row.habitaciones_min || Number(inmueble.habitaciones || 0) >= Number(row.habitaciones_min) },
        { key: "banos_min", val: row.banos_min, match: !row.banos_min || Number(inmueble.banos || 0) >= Number(row.banos_min) },
      ];
      const active = constraints.filter((c) => c.val !== null && c.val !== undefined && c.val !== "").length;
      const matched = constraints.filter((c) => c.match).length;
      const score = active ? Math.round((matched / active) * 100) : 100;
      const values = [
        `${score}%`,
        row.cliente || "-",
        row.tipo || "-",
        row.zona || "-",
        row.precio_max,
        row.m2_min,
        row.habitaciones_min,
        row.banos_min,
        row.estado || "-",
      ];
      const cols = ["score", "cliente", "tipo", "zona", "precio_max", "m2_min", "habitaciones_min", "banos_min", "estado"];
      values.forEach((value, idx) => {
        const td = document.createElement("td");
        const formatted = formatCell(cols[idx], value);
        td.textContent = formatted === null ? "" : formatted;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    inmuebleDemandasTable.innerHTML = "";
    inmuebleDemandasTable.appendChild(table);
  });
};

const loadInmuebleVisitas = (inmuebleId, empresaId) => {
  if (!inmuebleVisitasTable || !inmuebleId || !empresaId) {
    return;
  }
  api(`/api/visitas?empresa_id=${empresaId}&inmueble_id=${inmuebleId}`).then((data) => {
    const rows = data.rows || [];
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["fecha", "hora", "estado", "cliente", "asesor"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const values = [
        row.fecha || "-",
        row.hora || "-",
        row.estado || "-",
        row.cliente || "-",
        row.asesor || "-",
      ];
      values.forEach((value, idx) => {
        const td = document.createElement("td");
        const colName = ["fecha", "hora", "estado", "cliente", "asesor"][idx];
        const formatted = formatCell(colName, value);
        td.textContent = formatted === null ? "" : formatted;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    inmuebleVisitasTable.innerHTML = "";
    inmuebleVisitasTable.appendChild(table);
    if (inmuebleVisitasInfo) {
      inmuebleVisitasInfo.textContent = `Mostrando ${rows.length} visitas.`;
    }
  });
};

const renderInmuebleDocs = (rows = []) => {
  if (!inmuebleDocsList) return;
  if (!rows.length) {
    inmuebleDocsList.innerHTML = "<p class='muted'>Sin documentos.</p>";
    return;
  }
  const list = document.createElement("div");
  list.className = "inline-list";
  rows.forEach((row) => {
    const item = document.createElement("div");
    item.className = "inline-row";
    const name = row.nombre || row.url || "Documento";
    const tipo = row.tipo || "Documento";
    const link = row.url ? `<a href="${row.url}" target="_blank">Ver</a>` : "";
    item.innerHTML = `<div>${name}</div><div class="muted">${tipo}</div><div>${link}</div>`;
    list.appendChild(item);
  });
  inmuebleDocsList.innerHTML = "";
  inmuebleDocsList.appendChild(list);
};

const loadInmuebleDocs = (inmuebleId) => {
  if (!inmuebleId) return;
  api(`/api/inmueble_docs?inmueble_id=${inmuebleId}`).then((data) => {
    renderInmuebleDocs(data.rows || []);
  });
};

const renderInmuebleChecklist = (rows = []) => {
  if (!inmuebleChecklistTable) return;
  if (!rows.length) {
    inmuebleChecklistTable.innerHTML = "<p class='muted'>Sin checklist para esta etapa.</p>";
    if (inmuebleChecklistInfo) inmuebleChecklistInfo.textContent = "";
    return;
  }
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const trHead = document.createElement("tr");
  ["tarea", "estado", "responsable", "fecha_limite"].forEach((col) => {
    const th = document.createElement("th");
    th.textContent = formatHeader(col);
    trHead.appendChild(th);
  });
  thead.appendChild(trHead);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const tareaTd = document.createElement("td");
    tareaTd.textContent = row.tarea || "";
    tr.appendChild(tareaTd);
    const estadoTd = document.createElement("td");
    const estadoSelect = document.createElement("select");
    ["Pendiente", "En curso", "Completada"].forEach((opt) =>
      estadoSelect.appendChild(createOption(opt, opt))
    );
    estadoSelect.value = row.estado || "Pendiente";
    estadoSelect.addEventListener("change", () => {
      updateInmuebleChecklist(row.id, { estado: estadoSelect.value });
    });
    estadoTd.appendChild(estadoSelect);
    tr.appendChild(estadoTd);
    const respTd = document.createElement("td");
    const respSelect = document.createElement("select");
    respSelect.appendChild(createOption("", "Sin asignar"));
    (state.usersList || []).forEach((user) => {
      const label = `${user.nombre || ""} ${user.apellido || ""}`.trim();
      const value = user.usuario || label;
      if (!value) return;
      respSelect.appendChild(createOption(value, label || value));
    });
    respSelect.value = row.responsable || "";
    respSelect.addEventListener("change", () => {
      updateInmuebleChecklist(row.id, { responsable: respSelect.value });
    });
    respTd.appendChild(respSelect);
    tr.appendChild(respTd);
    const fechaTd = document.createElement("td");
    const fechaInput = document.createElement("input");
    fechaInput.type = "date";
    fechaInput.value = row.fecha_limite || "";
    fechaInput.addEventListener("change", () => {
      updateInmuebleChecklist(row.id, { fecha_limite: fechaInput.value });
    });
    fechaTd.appendChild(fechaInput);
    tr.appendChild(fechaTd);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  inmuebleChecklistTable.innerHTML = "";
  inmuebleChecklistTable.appendChild(table);
  if (inmuebleChecklistInfo) {
    inmuebleChecklistInfo.textContent = `Mostrando ${rows.length} tareas.`;
  }
};

const loadInmuebleChecklist = (inmuebleId, etapa = "") => {
  if (!inmuebleId || !inmuebleChecklistTable) return;
  const params = new URLSearchParams({ inmueble_id: inmuebleId });
  if (etapa) params.set("etapa", etapa);
  api(`/api/inmueble_checklist?${params.toString()}`).then((data) => {
    renderInmuebleChecklist(data.rows || []);
  });
};

const updateInmuebleChecklist = (id, updates) => {
  fetch("/api/inmueble_checklist_update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, ...updates, usuario: getCurrentUser() }),
  })
    .then(() => {
      if (state.currentInmuebleId) {
        loadInmuebleChecklist(state.currentInmuebleId);
      }
    })
    .catch(() => {});
};

const generateInmuebleChecklist = (etapa) => {
  if (!state.currentInmuebleId || !etapa) return;
  const tareas = (INMUEBLE_CHECKLISTS[etapa] || []).map((tarea) => ({
    tarea,
    estado: "Pendiente",
    responsable: getCurrentUser() || "",
    fecha_limite: "",
  }));
  fetch("/api/inmueble_checklist_generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      inmueble_id: state.currentInmuebleId,
      etapa,
      tareas,
      usuario: getCurrentUser(),
    }),
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.error) return;
      loadInmuebleChecklist(state.currentInmuebleId, etapa);
    })
    .catch(() => {});
};

const loadInmuebleActividad = (inmuebleId, empresaId) => {
  if (!inmuebleActividadTable || !inmuebleId || !empresaId) {
    return;
  }
  const accionesReq = api(
    `/api/acciones?servicio=inmobiliaria&empresa_id=${empresaId}&inmueble_id=${inmuebleId}`
  );
  const visitasReq = api(`/api/visitas?empresa_id=${empresaId}&inmueble_id=${inmuebleId}`);
  Promise.all([accionesReq, visitasReq]).then(([accionesData, visitasData]) => {
    const acciones = accionesData.rows || [];
    const visitas = visitasData.rows || [];
    const timeline = [
      ...acciones.map((row) => ({
        fecha: row.fecha,
        hora: row.hora,
        titulo: row.tipo || "Acción",
        meta: `${row.responsable || "Sin responsable"} · ${row.estado || "Pendiente"}`,
        notas: row.notas || "",
      })),
      ...visitas.map((row) => ({
        fecha: row.fecha,
        hora: row.hora,
        titulo: "Visita",
        meta: `${row.asesor || "Sin asesor"} · ${row.estado || "-"}`,
        notas: row.notas || "",
      })),
    ].filter((item) => item.fecha);
    timeline.sort((a, b) => String(b.fecha).localeCompare(String(a.fecha)));
    if (inmuebleActividadTimeline) {
      inmuebleActividadTimeline.innerHTML = "";
      if (!timeline.length) {
        inmuebleActividadTimeline.innerHTML = "<p class='muted'>Sin actividad.</p>";
      } else {
        timeline.slice(0, 10).forEach((item) => {
          const card = document.createElement("div");
          card.className = "crm-timeline-item";
          card.innerHTML = `
            <div class="title">${item.titulo}</div>
            <div class="meta">${formatCell("fecha", item.fecha)} ${item.hora || ""} · ${item.meta}</div>
            ${item.notas ? `<div class="notes">${item.notas}</div>` : ""}
          `;
          inmuebleActividadTimeline.appendChild(card);
        });
      }
    }
    const rows = acciones;
    if (!rows.length) {
      inmuebleActividadTable.innerHTML = "<p class='muted'>Sin actividad registrada.</p>";
      if (inmuebleActividadInfo) inmuebleActividadInfo.textContent = "";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["fecha", "hora", "tipo", "cliente", "responsable", "estado", "notas"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const values = [
        row.fecha || "-",
        row.hora || "-",
        row.tipo || "-",
        row.cliente || "-",
        row.responsable || "-",
        row.estado || "-",
        row.notas || "-",
      ];
      const cols = ["fecha", "hora", "tipo", "cliente", "responsable", "estado", "notas"];
      values.forEach((value, idx) => {
        const td = document.createElement("td");
        const formatted = formatCell(cols[idx], value);
        td.textContent = formatted === null ? "" : formatted;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    inmuebleActividadTable.innerHTML = "";
    inmuebleActividadTable.appendChild(table);
    if (inmuebleActividadInfo) {
      inmuebleActividadInfo.textContent = `Mostrando ${rows.length} acciones.`;
    }
  });
};

const loadGestoriaCrm = async () => {
  if (!gestoriaCrmTable || !gestoriaCrmInfo) {
    return;
  }
  loadGestoriaTrabajosOverview();
  loadGestoriaModelosOverview();
  loadGestoriaPipeline();
  loadGestoriaDocsRecent();
  loadGestoriaAuditoria();
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) {
    gestoriaCrmTable.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  const q = gestoriaCrmSearch ? gestoriaCrmSearch.value.trim() : "";
  const tipo = gestoriaCrmTipo ? gestoriaCrmTipo.value : "";
  const subtipo = gestoriaCrmSubtipo ? gestoriaCrmSubtipo.value.trim() : "";
  const estado = gestoriaCrmEstado ? gestoriaCrmEstado.value : "";
  const limit = gestoriaCrmLimit ? gestoriaCrmLimit.value : "50";
  const noFilters = !q && !estado && !tipo && !subtipo;
  const isFullWithoutFilters = noFilters && state.gestoriaCrmFull;
  const params = new URLSearchParams({
    tabla: "gestoria",
    empresa_id: empresa.id,
    q,
    include_id: "1",
  });
  if (tipo) {
    params.set("tipo", tipo);
  }
  if (subtipo) {
    params.set("perfil", subtipo);
  }
  if (estado) {
    params.set("estado", estado);
  }
  if (isFullWithoutFilters) {
    params.set("limit", "200");
  } else if (noFilters && !state.gestoriaCrmFull) {
    params.set("limit", "200");
  } else if (limit) {
    params.set("limit", limit);
  }
  let data = await api(`/api/tabla?${params.toString()}`);
  if (data && (!data.rows || data.rows.length === 0) && empresa?.id && state.gestoriaCrmFull) {
    const fallbackParams = new URLSearchParams(params);
    fallbackParams.delete("empresa_id");
    data = await api(`/api/tabla?${fallbackParams.toString()}`);
    if (gestoriaCrmInfo) {
      gestoriaCrmInfo.textContent =
        "Mostrando clientes sin empresa asignada. Asigna empresa para fijarlos.";
    }
  }
  if (!data) return;
  const columns = data.columns || [];
  let rows = data.rows || [];
  const perfilIndex = columns.indexOf("perfil");
  if (perfilIndex >= 0 && state.gestoriaCrmTab && state.gestoriaCrmTab !== "all") {
    const matchers = {
      autonomo: ["autónomo", "autonomo"],
      empresa: ["empresa"],
      renta: ["cliente renta", "renta"],
      admin: ["gestiones administrativas", "gestion administrativa", "administrativa", "puntual"],
    };
    const wanted = matchers[state.gestoriaCrmTab] || [];
    if (wanted.length) {
      rows = rows.filter((row) => {
        const perfilVal = String(row[perfilIndex] || "").toLowerCase();
        return wanted.some((value) => perfilVal.includes(value));
      });
    }
  }
    const clienteFilter = gestoriaCrmSearch ? gestoriaCrmSearch.value.trim().toLowerCase() : "";
    if (clienteFilter) {
      const clienteIndex = columns.indexOf("cliente");
      if (clienteIndex >= 0) {
        rows = rows.filter((row) =>
          String(row[clienteIndex] || "").toLowerCase().includes(clienteFilter)
        );
      }
    }
    const idIndex = columns.indexOf("id");
    const estadoIndex = columns.indexOf("estado");
    const fechaBajaIndex = columns.indexOf("fecha_baja");
    const displayCols = ["cliente", "tipo", "estado", "cuota", "precio"];

    if (gestoriaCrmSummary) {
      const summaryList = document.createElement("div");
      summaryList.className = "crm-mini-list";
      rows.slice(0, 15).forEach((row) => {
        const getValue = (col) => {
          const idx = columns.indexOf(col);
          return idx >= 0 ? row[idx] : "";
        };
        const nombre = getValue("cliente") || "-";
        const tipoVal = getValue("tipo") || "-";
        const perfilVal = getValue("perfil") || "";
        const estadoVal = getValue("estado") || "Alta";
        const cuotaVal = getValue("cuota") || "-";
        const precioVal = getValue("precio") || "";
        const card = document.createElement("button");
        card.type = "button";
        card.className = "crm-mini-card";
        card.innerHTML = `
          <div>
            <h4>${nombre}</h4>
            <div class="muted">${tipoVal}${perfilVal ? " · " + perfilVal : ""}</div>
          </div>
          <div class="crm-mini-meta">
            <div class="crm-badge">${estadoVal}</div>
            <div class="muted">${cuotaVal}${precioVal ? " · " + formatCell("precio", precioVal) : ""}</div>
          </div>
        `;
        card.addEventListener("click", () => {
          let id = resolveClienteIdFromName(nombre);
          if (id) {
            openClienteDetail(id);
            return;
          }
          loadClientesList()
            .then(() => {
              id = resolveClienteIdFromName(nombre);
              if (id) {
                openClienteDetail(id);
              }
            })
            .catch(() => {});
        });
        summaryList.appendChild(card);
      });
      gestoriaCrmSummary.innerHTML = "";
      if (rows.length) {
        gestoriaCrmSummary.appendChild(summaryList);
      } else {
        gestoriaCrmSummary.innerHTML = "<p class='muted'>Sin clientes con esos filtros.</p>";
      }
    }

    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    displayCols.forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    const actionTh = document.createElement("th");
    actionTh.textContent = "ACCION";
    trHead.appendChild(actionTh);
    thead.appendChild(trHead);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      displayCols.forEach((col) => {
        const idx = columns.indexOf(col);
        const td = document.createElement("td");
        if (idx === estadoIndex) {
          const select = document.createElement("select");
          ["Alta", "Baja"].forEach((option) => {
            select.appendChild(createOption(option, option));
          });
          select.value = row[idx] || "Alta";
          select.addEventListener("change", () => {
            fetch("/api/gestoria_update", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ id: row[idIndex], estado: select.value }),
            })
              .then((res) => res.json())
              .then((dataResp) => {
                if (dataResp.error && gestoriaCrmInfo) {
                  gestoriaCrmInfo.textContent = dataResp.error;
                }
              });
          });
          td.appendChild(select);
        } else if (idx === fechaBajaIndex) {
          const input = document.createElement("input");
          input.type = "date";
          input.value = row[idx] || "";
          input.addEventListener("change", () => {
            fetch("/api/gestoria_update", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ id: row[idIndex], fecha_baja: input.value }),
            })
              .then((res) => res.json())
              .then((dataResp) => {
                if (dataResp.error && gestoriaCrmInfo) {
                  gestoriaCrmInfo.textContent = dataResp.error;
                }
              });
          });
          td.appendChild(input);
        } else {
          const formatted = formatCell(col, row[idx]);
          td.textContent = formatted === null ? "" : formatted;
        }
        tr.appendChild(td);
      });
      const actionTd = document.createElement("td");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Ver cliente";
      btn.addEventListener("click", () => {
        const nombre = row[columns.indexOf("cliente")];
        let id = resolveClienteIdFromName(nombre);
        if (id) {
          openClienteDetail(id);
          return;
        }
        loadClientesList()
          .then(() => {
            id = resolveClienteIdFromName(nombre);
            if (id) {
              openClienteDetail(id);
            } else {
              actionTd.textContent = "Cliente no encontrado";
            }
          })
          .catch(() => {
            actionTd.textContent = "Cliente no encontrado";
          });
      });
      actionTd.appendChild(btn);
      tr.appendChild(actionTd);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    gestoriaCrmTable.innerHTML = "";
    gestoriaCrmTable.appendChild(table);
    if (!gestoriaCrmInfo.textContent) {
      gestoriaCrmInfo.textContent = `Mostrando ${rows.length} clientes de gestoría.`;
    }
    loadAcciones("gestoria", empresa.id, gestoriaAgendaTable, gestoriaAgendaInfo);
    const showFull = state.gestoriaCrmFull === true;
    if (gestoriaCrmTable) gestoriaCrmTable.classList.toggle("hidden", !showFull);
    if (gestoriaCrmSummary) gestoriaCrmSummary.classList.toggle("hidden", showFull);
    if (gestoriaCrmToggleView) {
      gestoriaCrmToggleView.textContent = showFull ? "Ver resumen" : "Ver tabla completa";
    }
  return;
};

const loadGestoriaDashboard = () => {
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) return;
  Promise.all([
    api(`/api/gestoria_dashboard?empresa_id=${empresa.id}`),
    api(`/api/gestoria_trabajos?empresa_id=${empresa.id}`),
  ]).then(([data, trabajosData]) => {
    const counts = data.counts || {};
    if (gestoriaKpiTotal) gestoriaKpiTotal.textContent = counts.total ?? 0;
    if (gestoriaKpiActivos) gestoriaKpiActivos.textContent = counts.activos ?? 0;
    if (gestoriaKpiAutonomos) gestoriaKpiAutonomos.textContent = counts.autonomos ?? 0;
    if (gestoriaKpiEmpresas) gestoriaKpiEmpresas.textContent = counts.empresas ?? 0;
    if (gestoriaKpiPuntuales) gestoriaKpiPuntuales.textContent = counts.puntuales ?? 0;
    if (gestoriaKpiModelosMes) gestoriaKpiModelosMes.textContent = counts.modelos_mes ?? 0;

    const renderAlertList = (target, items, emptyText, lineBuilder) => {
      if (!target) return;
      if (!items || !items.length) {
        target.innerHTML = `<p class="muted">${emptyText}</p>`;
        return;
      }
      const list = document.createElement("div");
      list.className = "inline-list";
      items.forEach((item) => {
        const row = document.createElement("div");
        row.className = "inline-row";
        row.innerHTML = lineBuilder(item);
        list.appendChild(row);
      });
      target.innerHTML = "";
      target.appendChild(list);
    };

    renderAlertList(
      gestoriaAlertModelos,
      data.modelos,
      "Sin vencimientos próximos.",
      (row) => {
        const fecha = formatCell("fecha", row.proxima_fecha) || row.proxima_fecha || "-";
        const cliente = row.cliente || "Cliente";
        const modelo = row.modelo || "Modelo";
        const estado = row.estado || "Pendiente";
        return `<div class="muted">${fecha}</div><div>${cliente}</div><div class="muted">${modelo} · ${estado}</div>`;
      }
    );

    renderAlertList(
      gestoriaAlertAcciones,
      data.acciones,
      "Sin acciones pendientes.",
      (row) => {
        const fecha = formatCell("fecha", row.fecha) || row.fecha || "-";
        const hora = row.hora ? ` ${row.hora}` : "";
        const cliente = row.cliente || "Cliente";
        const tipo = row.tipo || "Acción";
        return `<div class="muted">${fecha}${hora}</div><div>${cliente}</div><div class="muted">${tipo}</div>`;
      }
    );

    renderAlertList(
      gestoriaAlertModelosOverdue,
      data.modelos_vencidos,
      "Sin modelos vencidos.",
      (row) => {
        const fecha = formatCell("fecha", row.proxima_fecha) || row.proxima_fecha || "-";
        const cliente = row.cliente || "Cliente";
        const modelo = row.modelo || "Modelo";
        return `<div class="muted">${fecha}</div><div>${cliente}</div><div class="muted">${modelo}</div>`;
      }
    );

    renderAlertList(
      gestoriaAlertAccionesOverdue,
      data.acciones_vencidas,
      "Sin acciones vencidas.",
      (row) => {
        const fecha = formatCell("fecha", row.fecha) || row.fecha || "-";
        const hora = row.hora ? ` ${row.hora}` : "";
        const cliente = row.cliente || "Cliente";
        const tipo = row.tipo || "Acción";
        return `<div class="muted">${fecha}${hora}</div><div>${cliente}</div><div class="muted">${tipo}</div>`;
      }
    );
    const trabajos = trabajosData.rows || [];
    const today = new Date();
    const todayStr = today.toISOString().slice(0, 10);
    const daysWindow = gestoriaAlertDays ? parseInt(gestoriaAlertDays.value, 10) : 14;
    const limitDate = new Date(today.getTime() + (Number.isFinite(daysWindow) ? daysWindow : 14) * 86400000);
    const limitStr = limitDate.toISOString().slice(0, 10);
    const computeDueDate = (t) => {
      if (t.fecha_fin) return t.fecha_fin;
      if (t.fecha_inicio && t.sla_dias) {
        const base = new Date(t.fecha_inicio);
        const days = parseInt(t.sla_dias, 10);
        if (!Number.isNaN(base.getTime()) && !Number.isNaN(days)) {
          const due = new Date(base.getTime() + days * 86400000);
          return due.toISOString().slice(0, 10);
        }
      }
      return "";
    };
    const enCurso = trabajos.filter((t) => String(t.estado || "").toLowerCase() === "en curso");
    const enEspera = trabajos.filter((t) => String(t.estado || "").toLowerCase() === "en espera");
    const vencidas = trabajos.filter((t) => {
      const fin = computeDueDate(t);
      const estado = String(t.estado || "").toLowerCase();
      return fin && fin < todayStr && estado !== "completado";
    });
    if (gestoriaKpiGestionesCurso) gestoriaKpiGestionesCurso.textContent = enCurso.length;
    if (gestoriaKpiGestionesEspera) gestoriaKpiGestionesEspera.textContent = enEspera.length;
    if (gestoriaKpiGestionesVencidas) gestoriaKpiGestionesVencidas.textContent = vencidas.length;
    renderAlertList(
      gestoriaAlertGestiones,
      vencidas,
      "Sin gestiones vencidas.",
      (row) => {
        const due = computeDueDate(row) || row.fecha_fin || "-";
        const fecha = formatCell("fecha", due) || due || "-";
        const cliente = row.cliente || "Cliente";
        const tipo = row.tipo_trabajo || "Gestión";
        return `<div class="muted">${fecha}</div><div>${cliente}</div><div class="muted">${tipo}</div>`;
      }
    );
    const proximas = trabajos.filter((t) => {
      const fin = computeDueDate(t);
      const estado = String(t.estado || "").toLowerCase();
      return fin && fin >= todayStr && fin <= limitStr && estado !== "completado";
    });
    renderAlertList(
      gestoriaAlertGestionesProximas,
      proximas,
      "Sin gestiones próximas.",
      (row) => {
        const due = computeDueDate(row) || row.fecha_fin || "-";
        const fecha = formatCell("fecha", due) || due || "-";
        const cliente = row.cliente || "Cliente";
        const tipo = row.tipo_trabajo || "Gestión";
        return `<div class="muted">${fecha}</div><div>${cliente}</div><div class="muted">${tipo}</div>`;
      }
    );
    if (gestoriaResponsablesTable) {
      const grouped = {};
      trabajos.forEach((row) => {
        const responsable = (row.responsable || "Sin asignar").trim() || "Sin asignar";
        const estado = String(row.estado || "").toLowerCase();
        if (!grouped[responsable]) {
          grouped[responsable] = { enCurso: 0, enEspera: 0, vencidas: 0, total: 0 };
        }
        grouped[responsable].total += 1;
        if (estado === "en curso") grouped[responsable].enCurso += 1;
        if (estado === "en espera") grouped[responsable].enEspera += 1;
        const due = computeDueDate(row);
        if (due && due < todayStr && estado !== "completado") {
          grouped[responsable].vencidas += 1;
        }
      });
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const trHead = document.createElement("tr");
      ["responsable", "total", "en curso", "en espera", "vencidas"].forEach((col) => {
        const th = document.createElement("th");
        th.textContent = formatHeader(col);
        trHead.appendChild(th);
      });
      thead.appendChild(trHead);
      table.appendChild(thead);
      const tbody = document.createElement("tbody");
      Object.entries(grouped).forEach(([name, stats]) => {
        const tr = document.createElement("tr");
        const values = [
          name,
          stats.total,
          stats.enCurso,
          stats.enEspera,
          stats.vencidas,
        ];
        values.forEach((value) => {
          const td = document.createElement("td");
          td.textContent = String(value);
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      gestoriaResponsablesTable.innerHTML = "";
      gestoriaResponsablesTable.appendChild(table);
    }
  });
};

const loadSegurosCrm = () => {
  if (!segurosCrmTable || !segurosCrmInfo) {
    return;
  }
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) {
    segurosCrmTable.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  const q = segurosCrmSearch ? segurosCrmSearch.value.trim() : "";
  const params = new URLSearchParams({
    tabla: "seguros",
    empresa_id: empresa.id,
    q,
  });
  api(`/api/tabla?${params.toString()}`).then((data) => {
    const columns = data.columns || [];
    let rows = data.rows || [];
    const filtroCliente = segurosCrmClienteInput ? segurosCrmClienteInput.value.trim().toLowerCase() : "";
    if (filtroCliente) {
      const tomadorIndex = columns.indexOf("tomador");
      if (tomadorIndex >= 0) {
        rows = rows.filter((row) =>
          String(row[tomadorIndex] || "").toLowerCase().includes(filtroCliente)
        );
      }
    }
    renderTableInto({ columns, rows }, segurosCrmTable, segurosCrmInfo, "Seguros");
    renderSegurosUpdateSelect(data);
    renderSegurosChecklistSelect(data);
    renderSegurosAiSelect(data);
    loadSegurosOportunidades(empresa.id);
    loadAcciones("seguros", empresa.id, segurosAgendaTable, segurosAgendaInfo);
    loadSegurosOfertas();
    loadSegurosReferidos();
    loadSegurosCampanas();
    loadSegurosComisiones();
    loadSegurosInsights(empresa.id);
    loadSegurosAlertas();
    loadSegurosKpis();
    if (segurosPreferenciasClientes) {
      populateAgendaClientes(
        segurosPreferenciasClientes,
        segurosPreferenciasClienteInput,
        segurosPreferenciasClienteId
      );
    }
    if (segurosOfertasClientes) {
      populateAgendaClientes(
        segurosOfertasClientes,
        segurosOfertasClienteInput,
        segurosOfertasClienteId
      );
    }
    if (segurosReferidosClientes) {
      populateAgendaClientes(
        segurosReferidosClientes,
        segurosReferidosClienteInput,
        segurosReferidosClienteId
      );
    }
  });
};

const loadSegurosKpis = () => {
  if (!segurosKpis) return;
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) {
    segurosKpis.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  const params = new URLSearchParams({ empresa_id: empresa.id });
  api(`/api/seguros_kpis?${params.toString()}`).then((data) => {
    const wrapper = document.createElement("div");
    wrapper.className = "grid crm-kpis";
    const addKpi = (label, value) => {
      const card = document.createElement("div");
      card.className = "kpi-card";
      card.innerHTML = `<div class="kpi-label">${label}</div><div class="kpi-value">${value}</div>`;
      wrapper.appendChild(card);
    };
    addKpi("Pólizas en vigor", data.en_vigor || 0);
    addKpi("Vencen 30 días", data.vencen_30 || 0);
    addKpi("Con faltantes", data.faltantes || 0);
    if (data.prima_total !== undefined && data.prima_total !== null) {
      addKpi("Prima total", euroFormatter.format(data.prima_total || 0));
    }
    segurosKpis.innerHTML = "";
    segurosKpis.appendChild(wrapper);
  });
};

const loadSegurosAlertas = () => {
  if (!segurosAlertasList) return;
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) {
    segurosAlertasList.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  const params = new URLSearchParams({ empresa_id: empresa.id });
  api(`/api/seguros_alertas?${params.toString()}`).then((data) => {
    const items = data.items || [];
    if (!items.length) {
      segurosAlertasList.innerHTML = "<p class='muted'>Sin vencimientos próximos.</p>";
      return;
    }
    const list = document.createElement("div");
    list.className = "inline-list";
    items.forEach((row) => {
      const item = document.createElement("div");
      item.className = "inline-row";
      const title = document.createElement("div");
      const tomador = row.tomador || "Cliente";
      const poliza = row.poliza_numero || "-";
      const fecha = row.fecha_vencimiento || "-";
      title.innerHTML = `<strong>${tomador}</strong><div class="muted">${poliza} · vence ${fecha}</div>`;
      const actions = document.createElement("div");
      actions.className = "inline-actions";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "secondary";
      btn.textContent = "Crear acción";
      btn.addEventListener("click", () => {
        const payload = {
          servicio: "Seguros",
          cliente_id: row.cliente_id || "",
          cliente_nombre: tomador,
          fecha: row.fecha_vencimiento || "",
          tipo: "Renovación",
          estado: "Pendiente",
          notas: `Renovación póliza ${poliza}`,
        };
        fetch("/api/acciones", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        })
          .then((res) => res.json())
          .then(() => loadSegurosCrm())
          .catch(() => {});
      });
      actions.appendChild(btn);
      item.appendChild(title);
      item.appendChild(actions);
      list.appendChild(item);
    });
    segurosAlertasList.innerHTML = "";
    segurosAlertasList.appendChild(list);
  });
};

const loadSegurosChecklist = (polizaId) => {
  if (!segurosChecklistTable || !segurosChecklistInfo) return;
  if (!polizaId) {
    segurosChecklistTable.innerHTML = "<p class='muted'>Selecciona una póliza.</p>";
    segurosChecklistInfo.textContent = "";
    return;
  }
  const params = new URLSearchParams({ poliza_id: polizaId });
  api(`/api/seguros_checklist?${params.toString()}`).then((data) => {
    const rows = data.rows || [];
    if (!rows.length) {
      segurosChecklistTable.innerHTML = "<p class='muted'>Sin checklist.</p>";
      segurosChecklistInfo.textContent = "";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["tarea", "estado", "responsable", "fecha_limite"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const tarea = document.createElement("td");
      tarea.textContent = row.tarea || "";
      const estado = document.createElement("td");
      const estadoSelect = document.createElement("select");
      ["Pendiente", "En curso", "Hecho"].forEach((opt) => {
        estadoSelect.appendChild(createOption(opt, opt));
      });
      estadoSelect.value = row.estado || "Pendiente";
      estadoSelect.addEventListener("change", () => {
        fetch("/api/seguros_checklist_update", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: row.id, estado: estadoSelect.value }),
        }).catch(() => {});
      });
      estado.appendChild(estadoSelect);
      const responsable = document.createElement("td");
      responsable.textContent = row.responsable || "-";
      const fecha = document.createElement("td");
      fecha.textContent = row.fecha_limite || "-";
      tr.appendChild(tarea);
      tr.appendChild(estado);
      tr.appendChild(responsable);
      tr.appendChild(fecha);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    segurosChecklistTable.innerHTML = "";
    segurosChecklistTable.appendChild(table);
    segurosChecklistInfo.textContent = `Mostrando ${rows.length} tareas.`;
  });
};

const loadSegurosOfertas = (clienteId = "") => {
  if (!segurosOfertasTable || !segurosOfertasInfo) return;
  const params = new URLSearchParams();
  if (clienteId) params.set("cliente_id", clienteId);
  api(`/api/seguros_ofertas?${params.toString()}`).then((data) => {
    const rawRows = data.rows || [];
    const rows = filterRowsByQuery(
      rawRows,
      segurosOfertasSearch ? segurosOfertasSearch.value : "",
      ["cliente", "ramo", "compania", "propuesta", "estado", "responsable", "motivo", "notas"]
    );
    if (!rows.length) {
      segurosOfertasTable.innerHTML = "<p class='muted'>Sin ofrecimientos.</p>";
      segurosOfertasInfo.textContent = "";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["cliente", "ramo", "compania", "propuesta", "estado", "fecha", "responsable"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const values = [
        row.cliente || "-",
        row.ramo || "-",
        row.compania || "-",
        row.propuesta || "-",
        row.estado || "-",
        row.fecha || "-",
        row.responsable || "-",
      ];
      const cols = ["cliente", "ramo", "compania", "propuesta", "estado", "fecha", "responsable"];
      values.forEach((value, idx) => {
        const td = document.createElement("td");
        const formatted = formatCell(cols[idx], value);
        td.textContent = formatted === null ? "" : formatted;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    segurosOfertasTable.innerHTML = "";
    segurosOfertasTable.appendChild(table);
    segurosOfertasInfo.textContent = `Mostrando ${rows.length} ofrecimientos.`;
  });
};

const loadSegurosPreferencias = (clienteId) => {
  if (!clienteId || !segurosPreferenciasForm) return;
  api(`/api/seguros_preferencias?cliente_id=${clienteId}`).then((data) => {
    const row = data.row || {};
    ["prioridad_precio", "prioridad_compania", "prioridad_coberturas", "notas"].forEach((field) => {
      const el = segurosPreferenciasForm.querySelector(`[name="${field}"]`);
      if (!el) return;
      el.value = row[field] !== undefined && row[field] !== null ? String(row[field]) : el.value;
    });
  });
};

const loadSegurosReferidos = () => {
  if (!segurosReferidosTable || !segurosReferidosInfo) return;
  api("/api/seguros_referidos").then((data) => {
    const rawRows = data.rows || [];
    const rows = filterRowsByQuery(
      rawRows,
      segurosReferidosSearch ? segurosReferidosSearch.value : "",
      ["cliente", "referido_por", "notas"]
    );
    if (!rows.length) {
      segurosReferidosTable.innerHTML = "<p class='muted'>Sin referidos.</p>";
      segurosReferidosInfo.textContent = "";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["cliente", "referido_por", "notas"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      [row.cliente || "-", row.referido_por || "-", row.notas || "-"].forEach((value) => {
        const td = document.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    segurosReferidosTable.innerHTML = "";
    segurosReferidosTable.appendChild(table);
    segurosReferidosInfo.textContent = `Mostrando ${rows.length} registros.`;
  });
};

const loadSegurosCampanas = () => {
  if (!segurosCampanasTable || !segurosCampanasInfo) return;
  api("/api/seguros_campanas").then((data) => {
    const rawRows = data.rows || [];
    const rows = filterRowsByQuery(
      rawRows,
      segurosCampanasSearch ? segurosCampanasSearch.value : "",
      ["compania", "nombre", "ramo", "origen", "descripcion", "url"]
    );
    if (!rows.length) {
      segurosCampanasTable.innerHTML = "<p class='muted'>Sin campañas.</p>";
      segurosCampanasInfo.textContent = "";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["compania", "nombre", "ramo", "origen", "fecha_inicio", "fecha_fin", "url"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const link = row.url ? "Ver" : "";
      const values = [
        row.compania || "-",
        row.nombre || "-",
        row.ramo || "-",
        row.origen || "-",
        row.fecha_inicio || "-",
        row.fecha_fin || "-",
        link,
      ];
      const cols = ["compania", "nombre", "ramo", "origen", "fecha_inicio", "fecha_fin", "url"];
      values.forEach((value, idx) => {
        const td = document.createElement("td");
        if (cols[idx] === "url" && row.url) {
          const a = document.createElement("a");
          a.href = row.url;
          a.target = "_blank";
          a.textContent = "Ver";
          td.appendChild(a);
        } else {
          if (!applyCompanyCell(td, cols[idx], value, { compact: true }) && !applyRamoCell(td, cols[idx], value)) {
            const formatted = formatCell(cols[idx], value);
            td.textContent = formatted === null ? "" : formatted;
          }
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    segurosCampanasTable.innerHTML = "";
    segurosCampanasTable.appendChild(table);
    segurosCampanasInfo.textContent = `Mostrando ${rows.length} campañas.`;
  });
};

const loadSegurosComisiones = () => {
  if (!segurosComisionesTable || !segurosComisionesInfo) return;
  api("/api/seguros_comisiones").then((data) => {
    const rawRows = data.rows || [];
    const rows = filterRowsByQuery(
      rawRows,
      segurosComisionesSearch ? segurosComisionesSearch.value : "",
      ["compania", "ramo", "porcentaje", "notas"]
    );
    if (!rows.length) {
      segurosComisionesTable.innerHTML = "<p class='muted'>Sin comisiones.</p>";
      segurosComisionesInfo.textContent = "";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["compania", "ramo", "porcentaje", "vigencia_desde", "vigencia_hasta"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const values = [
        row.compania || "-",
        row.ramo || "-",
        row.porcentaje || "-",
        row.vigencia_desde || "-",
        row.vigencia_hasta || "-",
      ];
      const cols = ["compania", "ramo", "porcentaje", "vigencia_desde", "vigencia_hasta"];
      values.forEach((value, idx) => {
        const td = document.createElement("td");
        if (!applyCompanyCell(td, cols[idx], value, { compact: true }) && !applyRamoCell(td, cols[idx], value)) {
          const formatted = formatCell(cols[idx], value);
          td.textContent = formatted === null ? "" : formatted;
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    segurosComisionesTable.innerHTML = "";
    segurosComisionesTable.appendChild(table);
    segurosComisionesInfo.textContent = `Mostrando ${rows.length} comisiones.`;
  });
};

const loadSegurosInsights = (empresaId) => {
  if (!segurosInsights || !empresaId) return;
  api(`/api/seguros_insights?empresa_id=${empresaId}`).then((data) => {
    const porRamo = data.por_ramo || [];
    const porCompania = data.por_compania || [];
    const ofertasEstado = data.ofertas_estado || [];
    const preferencias = data.preferencias || {};
    const wrapper = document.createElement("div");
    wrapper.className = "crm-split";
    const buildList = (title, rows, key) => {
      const card = document.createElement("div");
      card.className = "form-card";
      card.innerHTML = `<h3>${title}</h3>`;
      const list = document.createElement("div");
      list.className = "inline-list";
      rows.slice(0, 8).forEach((row) => {
        const item = document.createElement("div");
        item.className = "inline-row";
        const label = document.createElement("div");
        if (key === "compania") {
          label.appendChild(createCompanyBadge(row[key] || "-", { compact: true }));
        } else if (key === "ramo") {
          label.appendChild(createRamoBadge(row[key] || "-"));
        } else {
          label.textContent = row[key] || "-";
        }
        const total = document.createElement("div");
        total.className = "muted";
        total.textContent = row.total;
        item.appendChild(label);
        item.appendChild(total);
        list.appendChild(item);
      });
      card.appendChild(list);
      return card;
    };
    wrapper.appendChild(buildList("Por ramo", porRamo, "ramo"));
    wrapper.appendChild(buildList("Por compañía", porCompania, "compania"));
    if (ofertasEstado.length) {
      wrapper.appendChild(buildList("Ofertas por estado", ofertasEstado, "estado"));
    }
    if (preferencias && preferencias.total) {
      const prefCard = document.createElement("div");
      prefCard.className = "form-card";
      prefCard.innerHTML = `
        <h3>Preferencias de clientes</h3>
        <div class="inline-list">
          <div class="inline-row"><div>Precio</div><div class="muted">${preferencias.prioriza_precio || 0}</div></div>
          <div class="inline-row"><div>Compañía</div><div class="muted">${preferencias.prioriza_compania || 0}</div></div>
          <div class="inline-row"><div>Coberturas</div><div class="muted">${preferencias.prioriza_coberturas || 0}</div></div>
        </div>
      `;
      wrapper.appendChild(prefCard);
    }
    segurosInsights.innerHTML = "";
    segurosInsights.appendChild(wrapper);
  });
};

const renderSegurosPresupuestos = (data) => {
  if (!segurosPresupuestosList) return;
  const columns = data.columns || [];
  const rows = data.rows || [];
  const estadoIndex = columns.indexOf("estado");
  const tomadorIndex = columns.indexOf("tomador");
  const companiaIndex = columns.indexOf("compania");
  const ramoIndex = columns.indexOf("ramo");
  const polizaIndex = columns.indexOf("poliza_numero");
  const primaIndex = columns.indexOf("prima_total");
  const idIndex = columns.indexOf("id");
  const presupuestos = rows
    .filter((row) => {
      const estado = (row[estadoIndex] || "").toString().toLowerCase();
      return estado === "presupuesto";
    })
    .slice(0, 50);
  if (!presupuestos.length) {
    segurosPresupuestosList.innerHTML = "<p class='muted'>Sin presupuestos pendientes.</p>";
    return;
  }
  const list = document.createElement("div");
  list.className = "inline-list";
  presupuestos.forEach((row) => {
    const card = document.createElement("div");
    card.className = "inline-row";
    const title = document.createElement("div");
    const tomador = row[tomadorIndex] || "Cliente";
    const compania = row[companiaIndex] || "-";
    const ramo = row[ramoIndex] || "-";
    const prima = row[primaIndex] ? euroFormatter.format(Number(row[primaIndex]) || 0) : "-";
    const poliza = row[polizaIndex] || "-";
    const main = document.createElement("strong");
    main.textContent = tomador;
    const meta = document.createElement("div");
    meta.className = "muted";
    meta.appendChild(createCompanyBadge(compania, { compact: true }));
    meta.appendChild(document.createTextNode(` · ${ramo} · ${poliza} · ${prima}`));
    title.appendChild(main);
    title.appendChild(meta);
    const actions = document.createElement("div");
    actions.className = "inline-actions";
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "secondary";
    editBtn.textContent = "Editar antes de convertir";
    editBtn.addEventListener("click", () => {
      openSegurosPresupuestoEdit(columns, row);
    });
    const convertBtn = document.createElement("button");
    convertBtn.type = "button";
    convertBtn.textContent = "Convertir a póliza";
    convertBtn.addEventListener("click", () => {
      const ok = window.confirm("¿Confirmas convertir este presupuesto en póliza?");
      if (!ok) return;
      const today = formatAgendaDate(new Date());
      const payload = {
        id: row[idIndex],
        estado: "En vigor",
        fecha_efecto: row[columns.indexOf("fecha_efecto")] || today,
      };
      const efecto = payload.fecha_efecto || today;
      payload.fecha_vencimiento = addOneYear(efecto);
      fetch("/api/seguros_update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then((res) => res.json())
        .then((resp) => {
          if (resp.error) return;
          loadSegurosCrm();
        });
    });
    const discardBtn = document.createElement("button");
    discardBtn.type = "button";
    discardBtn.className = "secondary";
    discardBtn.textContent = "Descartar";
    discardBtn.addEventListener("click", () => {
      const ok = window.confirm("¿Descartar este presupuesto?");
      if (!ok) return;
      fetch("/api/seguros_update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: row[idIndex], estado: "Descartado" }),
      })
        .then((res) => res.json())
        .then((resp) => {
          if (resp.error) return;
          loadSegurosCrm();
        });
    });
    actions.appendChild(editBtn);
    actions.appendChild(convertBtn);
    actions.appendChild(discardBtn);
    card.appendChild(title);
    card.appendChild(actions);
    list.appendChild(card);
  });
  segurosPresupuestosList.innerHTML = "";
  segurosPresupuestosList.appendChild(list);
};

const renderSegurosUpdateSelect = (data) => {
  if (!segurosUpdateSelect) return;
  const columns = data.columns || [];
  const rows = data.rows || [];
  const idIndex = columns.indexOf("id");
  const tomadorIndex = columns.indexOf("tomador");
  const polizaIndex = columns.indexOf("poliza_numero");
  const companiaIndex = columns.indexOf("compania");
  segurosUpdateSelect.innerHTML = "";
  segurosUpdateSelect.appendChild(createOption("", "Selecciona póliza"));
  rows.forEach((row) => {
    const id = idIndex >= 0 ? row[idIndex] : "";
    if (!id) return;
    const tomador = row[tomadorIndex] || "Cliente";
    const poliza = row[polizaIndex] || "-";
    const compania = row[companiaIndex] || "-";
    const label = `${tomador} · ${compania} · ${poliza}`;
    segurosUpdateSelect.appendChild(createOption(id, label));
  });
};

const renderSegurosChecklistSelect = (data) => {
  if (!segurosChecklistPoliza) return;
  const columns = data.columns || [];
  const rows = data.rows || [];
  const idIndex = columns.indexOf("id");
  const tomadorIndex = columns.indexOf("tomador");
  const polizaIndex = columns.indexOf("poliza_numero");
  const companiaIndex = columns.indexOf("compania");
  segurosChecklistPoliza.innerHTML = "";
  segurosChecklistPoliza.appendChild(createOption("", "Selecciona póliza"));
  rows.forEach((row) => {
    const id = idIndex >= 0 ? row[idIndex] : "";
    if (!id) return;
    const tomador = row[tomadorIndex] || "Cliente";
    const poliza = row[polizaIndex] || "-";
    const compania = row[companiaIndex] || "-";
    const label = `${tomador} · ${compania} · ${poliza}`;
    segurosChecklistPoliza.appendChild(createOption(id, label));
  });
};

const renderSegurosAiSelect = (data) => {
  if (!segurosAiPoliza) return;
  const columns = data.columns || [];
  const rows = data.rows || [];
  const idIndex = columns.indexOf("id");
  const tomadorIndex = columns.indexOf("tomador");
  const polizaIndex = columns.indexOf("poliza_numero");
  const companiaIndex = columns.indexOf("compania");
  segurosAiPoliza.innerHTML = "";
  segurosAiPoliza.appendChild(createOption("", "Selecciona póliza"));
  rows.forEach((row) => {
    const id = idIndex >= 0 ? row[idIndex] : "";
    if (!id) return;
    const tomador = row[tomadorIndex] || "Cliente";
    const poliza = row[polizaIndex] || "-";
    const compania = row[companiaIndex] || "-";
    const label = `${tomador} · ${compania} · ${poliza}`;
    segurosAiPoliza.appendChild(createOption(id, label));
  });
};

const getSegurosBdtOcrFields = () => {
  const primaNetaRaw = segurosBdtOcrPrimaNeta ? segurosBdtOcrPrimaNeta.value.trim() : "";
  const primaTotalRaw = segurosBdtOcrPrimaTotal ? segurosBdtOcrPrimaTotal.value.trim() : "";
  return {
    tomador: segurosBdtOcrTomador ? segurosBdtOcrTomador.value.trim() : "",
    nif: segurosBdtOcrDni ? segurosBdtOcrDni.value.trim() : "",
    cliente_id: state.segurosBdtOcrClienteId || "",
    compania: segurosBdtOcrCompania ? segurosBdtOcrCompania.value.trim() : "",
    ramo: segurosBdtOcrRamo ? segurosBdtOcrRamo.value.trim() : "",
    poliza_numero: segurosBdtOcrPoliza ? segurosBdtOcrPoliza.value.trim() : "",
    fecha_efecto: segurosBdtOcrFechaEfecto ? segurosBdtOcrFechaEfecto.value : "",
    fecha_vencimiento: segurosBdtOcrFechaVencimiento ? segurosBdtOcrFechaVencimiento.value : "",
    prima_neta: primaNetaRaw ? toNumber(primaNetaRaw) : "",
    prima_total: primaTotalRaw ? toNumber(primaTotalRaw) : "",
  };
};

const fillSegurosBdtOcrFields = (fields = {}) => {
  if (segurosBdtOcrTomador) segurosBdtOcrTomador.value = fields.tomador || "";
  if (segurosBdtOcrDni) segurosBdtOcrDni.value = fields.dni || fields.nif || "";
  if (segurosBdtOcrCompania) segurosBdtOcrCompania.value = fields.compania || "";
  if (segurosBdtOcrRamo) segurosBdtOcrRamo.value = fields.ramo || "";
  if (segurosBdtOcrPoliza) segurosBdtOcrPoliza.value = fields.poliza_numero || "";
  if (segurosBdtOcrFechaEfecto) {
    segurosBdtOcrFechaEfecto.value = normalizeDateInput(fields.fecha_efecto || "");
  }
  if (segurosBdtOcrFechaVencimiento) {
    if (fields.fecha_vencimiento) {
      segurosBdtOcrFechaVencimiento.value = normalizeDateInput(fields.fecha_vencimiento || "");
    } else if (segurosBdtOcrFechaEfecto && segurosBdtOcrFechaEfecto.value) {
      segurosBdtOcrFechaVencimiento.value = addOneYear(segurosBdtOcrFechaEfecto.value);
    }
  }
  if (segurosBdtOcrPrimaNeta) segurosBdtOcrPrimaNeta.value = fields.prima_neta || "";
  if (segurosBdtOcrPrimaTotal) segurosBdtOcrPrimaTotal.value = fields.prima_total || "";
};

const formatSegurosBdtLabel = (row, columns) => {
  const tomadorIndex = columns.indexOf("tomador");
  const companiaIndex = columns.indexOf("compania");
  const polizaIndex = columns.indexOf("poliza_numero");
  const tomador = (tomadorIndex >= 0 ? row[tomadorIndex] : "") || "Cliente";
  const compania = (companiaIndex >= 0 ? row[companiaIndex] : "") || "-";
  const poliza = (polizaIndex >= 0 ? row[polizaIndex] : "") || "-";
  return `${tomador} · ${compania} · ${poliza}`;
};

const populateSegurosBdtSelect = (rows, columns, selectedId = "") => {
  if (!segurosBdtOcrSelect) return;
  const idIndex = columns.indexOf("id");
  segurosBdtOcrSelect.innerHTML = "";
  segurosBdtOcrSelect.appendChild(createOption("", "Selecciona póliza"));
  rows.forEach((row) => {
    const id = idIndex >= 0 ? row[idIndex] : "";
    if (!id) return;
    const label = formatSegurosBdtLabel(row, columns);
    segurosBdtOcrSelect.appendChild(createOption(id, label));
  });
  if (selectedId) {
    segurosBdtOcrSelect.value = selectedId;
  }
};

const pickColumnValue = (row, columns, names = []) => {
  for (const name of names) {
    const idx = columns.indexOf(name);
    if (idx >= 0) return row[idx];
  }
  return "";
};

const levenshtein = (a, b) => {
  const s = String(a || "");
  const t = String(b || "");
  if (!s.length) return t.length;
  if (!t.length) return s.length;
  const v0 = new Array(t.length + 1).fill(0);
  const v1 = new Array(t.length + 1).fill(0);
  for (let i = 0; i <= t.length; i += 1) v0[i] = i;
  for (let i = 0; i < s.length; i += 1) {
    v1[0] = i + 1;
    for (let j = 0; j < t.length; j += 1) {
      const cost = s[i] === t[j] ? 0 : 1;
      v1[j + 1] = Math.min(v1[j] + 1, v0[j + 1] + 1, v0[j] + cost);
    }
    for (let j = 0; j <= t.length; j += 1) v0[j] = v1[j];
  }
  return v1[t.length];
};

const scoreSegurosBdtMatch = (row, columns, fields) => {
  const rowTomadorRaw = pickColumnValue(row, columns, ["tomador", "asegurado", "titular"]);
  const rowCompaniaRaw = pickColumnValue(row, columns, ["compania", "aseguradora"]);
  const rowRamoRaw = pickColumnValue(row, columns, ["ramo", "modalidad", "producto"]);
  const rowPolizaRaw = pickColumnValue(row, columns, ["poliza_numero", "poliza", "numero_poliza"]);
  const rowNifRaw = pickColumnValue(row, columns, ["nif", "dni", "documento"]);
  const rowFechaEfectoRaw = pickColumnValue(row, columns, ["fecha_efecto", "fecha_inicio", "efecto"]);
  const rowFechaVencRaw = pickColumnValue(row, columns, ["fecha_vencimiento", "vencimiento"]);
  const rowClienteIdRaw = pickColumnValue(row, columns, ["cliente_id"]);

  const rowTomador = normalizeName(rowTomadorRaw);
  const rowCompania = normalizeName(rowCompaniaRaw);
  const rowRamo = normalizeName(rowRamoRaw);
  const rowPoliza = normalizeMatch(rowPolizaRaw);
  const rowFechaEfecto = normalizeDateInput(rowFechaEfectoRaw || "");
  const rowFechaVenc = normalizeDateInput(rowFechaVencRaw || "");

  const wantTomador = normalizeName(fields.tomador || "");
  const wantNif = normalizeMatch(fields.nif || "");
  const wantCompania = normalizeName(fields.compania || "");
  const wantRamo = normalizeName(fields.ramo || "");
  const wantPoliza = normalizeMatch(fields.poliza_numero || "");
  const wantClienteId = String(fields.cliente_id || "").trim();
  const wantFechaEfecto = normalizeDateInput(fields.fecha_efecto || "");
  const wantFechaVenc = normalizeDateInput(fields.fecha_vencimiento || "");

  const digits = (value) => String(value || "").replace(/\D/g, "");
  const tokenSet = (value) =>
    normalizeName(value)
      .split(/\s+/)
      .filter(Boolean);
  const jaccard = (a, b) => {
    if (!a.length || !b.length) return 0;
    const aSet = new Set(a);
    const bSet = new Set(b);
    let inter = 0;
    aSet.forEach((t) => {
      if (bSet.has(t)) inter += 1;
    });
    const union = new Set([...aSet, ...bSet]).size || 1;
    return inter / union;
  };

  let score = 0;

  if (wantClienteId && rowClienteIdRaw) {
    if (String(rowClienteIdRaw) === wantClienteId) score += 15;
  }

  if (wantNif && rowNifRaw) {
    const rowNif = normalizeMatch(rowNifRaw);
    if (rowNif === wantNif) score += 10;
    else if (rowNif.includes(wantNif) || wantNif.includes(rowNif)) score += 6;
  }

  if (wantPoliza && rowPoliza) {
    const rowDigits = digits(rowPolizaRaw);
    const wantDigits = digits(fields.poliza_numero || "");
    if (rowPoliza === wantPoliza) score += 10;
    else if (rowPoliza.includes(wantPoliza) || wantPoliza.includes(rowPoliza)) score += 6;
    if (rowPoliza.length >= 6 && wantPoliza.length >= 6) {
      const dist = levenshtein(rowPoliza, wantPoliza);
      const maxLen = Math.max(rowPoliza.length, wantPoliza.length) || 1;
      const similarity = 1 - dist / maxLen;
      if (similarity >= 0.85) score += 5;
      else if (similarity >= 0.7) score += 3;
    }
    if (rowDigits && wantDigits) {
      if (rowDigits === wantDigits) score += 8;
      else if (
        rowDigits.length >= 5 &&
        wantDigits.length >= 5 &&
        rowDigits.slice(-5) === wantDigits.slice(-5)
      ) {
        score += 4;
      }
    }
  }

  if (wantTomador && rowTomador) {
    if (rowTomador === wantTomador) score += 5;
    else if (rowTomador.includes(wantTomador) || wantTomador.includes(rowTomador)) score += 3;
    score += Math.round(jaccard(tokenSet(rowTomadorRaw), tokenSet(fields.tomador || "")) * 4);
    if (rowTomador.length >= 5 && wantTomador.length >= 5) {
      const dist = levenshtein(rowTomador, wantTomador);
      const maxLen = Math.max(rowTomador.length, wantTomador.length) || 1;
      const similarity = 1 - dist / maxLen;
      if (similarity >= 0.9) score += 4;
      else if (similarity >= 0.8) score += 2;
    }
  }

  if (wantCompania && rowCompania) {
    if (rowCompania === wantCompania) score += 4;
    else if (rowCompania.includes(wantCompania) || wantCompania.includes(rowCompania)) score += 2;
    score += Math.round(jaccard(tokenSet(rowCompaniaRaw), tokenSet(fields.compania || "")) * 3);
    if (rowCompania.length >= 4 && wantCompania.length >= 4) {
      const dist = levenshtein(rowCompania, wantCompania);
      const maxLen = Math.max(rowCompania.length, wantCompania.length) || 1;
      const similarity = 1 - dist / maxLen;
      if (similarity >= 0.9) score += 2;
    }
  }

  if (wantRamo && rowRamo) {
    if (rowRamo === wantRamo) score += 2;
    else if (rowRamo.includes(wantRamo) || wantRamo.includes(rowRamo)) score += 1;
  }

  if (wantFechaEfecto && rowFechaEfecto) {
    if (rowFechaEfecto === wantFechaEfecto) score += 2;
    else if (rowFechaEfecto.slice(0, 7) === wantFechaEfecto.slice(0, 7)) score += 1;
  }
  if (wantFechaVenc && rowFechaVenc) {
    if (rowFechaVenc === wantFechaVenc) score += 2;
    else if (rowFechaVenc.slice(0, 7) === wantFechaVenc.slice(0, 7)) score += 1;
  }

  return score;
};

const ensureSegurosBdtData = async () => {
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) return null;
  if (state.segurosBdtCache && state.segurosBdtCache.empresaId === empresa.id) {
    return state.segurosBdtCache.data;
  }
  const params = new URLSearchParams({
    tabla: "seguros",
    empresa_id: empresa.id,
    include_id: "1",
    limit: "1000",
  });
  const data = await api(`/api/tabla?${params.toString()}`);
  if (!data?.error) {
    state.segurosBdtCache = { empresaId: empresa.id, data, ts: Date.now() };
  }
  return data;
};

const matchSegurosBdtFromFields = async () => {
  if (segurosBdtOcrStatus) segurosBdtOcrStatus.textContent = "";
  const data = await ensureSegurosBdtData();
  if (!data || data.error) {
    if (segurosBdtOcrStatus) {
      segurosBdtOcrStatus.textContent = data?.error || "No se pudo cargar BDT.";
    }
    return;
  }
  const fields = getSegurosBdtOcrFields();
  const columns = data.columns || [];
  const rows = data.rows || [];
  const idIndex = columns.indexOf("id");
  if (idIndex < 0) {
    if (segurosBdtOcrStatus) segurosBdtOcrStatus.textContent = "BDT sin identificador.";
    return;
  }
  const hasInput =
    fields.poliza_numero ||
    fields.tomador ||
    fields.nif ||
    fields.cliente_id ||
    fields.compania ||
    fields.ramo ||
    fields.fecha_efecto ||
    fields.fecha_vencimiento ||
    fields.prima_neta ||
    fields.prima_total;
  if (!hasInput) {
    populateSegurosBdtSelect(rows, columns);
    if (segurosBdtOcrStatus) {
      segurosBdtOcrStatus.textContent = "Completa campos para buscar o selecciona manualmente.";
    }
    return;
  }
  const matches = rows
    .map((row) => ({
      row,
      score: scoreSegurosBdtMatch(row, columns, fields),
    }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score);
  if (!matches.length) {
    populateSegurosBdtSelect(rows, columns);
    if (segurosBdtOcrStatus) {
      segurosBdtOcrStatus.textContent = "Sin coincidencias. Completa campos o selecciona manualmente.";
    }
    return;
  }
  const best = matches[0];
  const next = matches[1];
  const bestId = best.row[idIndex];
  const bestLabel = formatSegurosBdtLabel(best.row, columns);
  const topRows = matches.slice(0, 12).map((item) => item.row);
  populateSegurosBdtSelect(topRows, columns, bestId);
  const isStrong = best.score >= 12 && (!next || best.score >= next.score + 3);
  if (segurosBdtOcrStatus) {
    segurosBdtOcrStatus.textContent = isStrong
      ? `Coincidencia automática: ${bestLabel}.`
      : "Varias coincidencias. Selecciona la correcta.";
  }
};

const fillSegurosOcrFields = (fields = {}) => {
  if (seguroOcrTomador) seguroOcrTomador.value = fields.tomador || "";
  if (seguroOcrDni) seguroOcrDni.value = fields.dni || fields.nif || "";
  if (seguroOcrTelefono) seguroOcrTelefono.value = fields.telefono || "";
  if (seguroOcrEmail) seguroOcrEmail.value = fields.email || "";
  if (seguroOcrCompania) seguroOcrCompania.value = fields.compania || "";
  if (seguroOcrRamo) seguroOcrRamo.value = fields.ramo || "";
  if (seguroOcrPoliza) seguroOcrPoliza.value = fields.poliza_numero || "";
  if (seguroOcrDireccion) seguroOcrDireccion.value = fields.direccion || "";
  if (seguroOcrNacimiento) {
    seguroOcrNacimiento.value = normalizeDateInput(fields.fecha_nacimiento || "");
  }
  if (seguroOcrPrimaNeta) seguroOcrPrimaNeta.value = fields.prima_neta || "";
  if (seguroOcrPrimaTotal) seguroOcrPrimaTotal.value = fields.prima_total || "";
  if (seguroOcrFechaEfecto) {
    seguroOcrFechaEfecto.value = normalizeDateInput(fields.fecha_efecto || "");
  }
  if (seguroOcrFechaVencimiento) {
    if (fields.fecha_vencimiento) {
      seguroOcrFechaVencimiento.value = normalizeDateInput(fields.fecha_vencimiento || "");
    } else if (seguroOcrFechaEfecto && seguroOcrFechaEfecto.value) {
      seguroOcrFechaVencimiento.value = addOneYear(seguroOcrFechaEfecto.value);
    }
  }
};

const loadGestoriaBdt = async () => {
  if (!gestoriaBdtTable || !gestoriaBdtInfo) {
    return;
  }
  const empresa = state.empresas.find((item) => item.nombre === FINCAS_COMPANY);
  if (!empresa) {
    gestoriaBdtTable.innerHTML = "<p class='muted'>Sin empresa.</p>";
    gestoriaBdtInfo.textContent = "";
    return;
  }
  gestoriaBdtInfo.textContent = "Cargando...";
  try {
    const params = new URLSearchParams({ tabla: "gestoria", empresa_id: empresa.id });
    const data = await api(`/api/tabla?${params}`);
    if (data?.error) {
      gestoriaBdtTable.innerHTML = `<p class='muted'>${data.error}</p>`;
      gestoriaBdtInfo.textContent = "";
      return;
    }
    renderTableInto(data, gestoriaBdtTable, gestoriaBdtInfo, "Gestoria");
  } catch (error) {
    gestoriaBdtTable.innerHTML = "<p class='muted'>Error al cargar.</p>";
    gestoriaBdtInfo.textContent = "";
  }
};

const fillFinAsesoramientoOcrFields = (fields = {}) => {
  if (!finAsesoramientoForm) return;
  const set = (name, value, isDate = false) => {
    const el = finAsesoramientoForm.querySelector(`[name="${name}"]`);
    if (!el) return;
    el.value = isDate ? normalizeDateInput(value || "") : (value || "");
  };
  if (finAsesorInmobiliaria) {
    const raw = fields.inmobiliaria_asesor || "";
    const normalized = normalizeMatch(raw);
    const options = Array.from(finAsesorInmobiliaria.options);
    let match = options.find((opt) => normalizeMatch(opt.value) === normalized);
    if (!match && normalized) {
      match = options.find((opt) => normalizeMatch(opt.value).includes(normalized));
    }
    if (!match && normalized) {
      match = options.find((opt) => normalized.includes(normalizeMatch(opt.value)));
    }
    if (!match && raw) {
      finAsesorInmobiliaria.appendChild(createOption(raw, raw));
      finAsesorInmobiliaria.value = raw;
    } else if (match) {
      finAsesorInmobiliaria.value = match.value;
    }
  } else {
    set("inmobiliaria_asesor", fields.inmobiliaria_asesor);
  }
  set("fecha", fields.fecha, true);
  set("cliente1_nombre", fields.cliente1_nombre);
  set("cliente1_dni", fields.cliente1_dni);
  set("cliente1_telefono", fields.cliente1_telefono);
  set("cliente1_email", fields.cliente1_email);
  set("cliente1_fecha_nacimiento", fields.cliente1_fecha_nacimiento, true);
  set("cliente1_estado_civil", fields.cliente1_estado_civil);
  set("cliente1_regimen", fields.cliente1_regimen);
  set("cliente1_hijos", fields.cliente1_hijos);
  set("cliente1_profesion", fields.cliente1_profesion);
  set("cliente1_tipo_contrato", fields.cliente1_tipo_contrato);
  set("cliente1_tiempo_contrato", fields.cliente1_tiempo_contrato);
  set("cliente1_ingresos", fields.cliente1_ingresos);
  set("cliente1_patrimonio", fields.cliente1_patrimonio);
  set("cliente1_prestamos", fields.cliente1_prestamos);
  set("cliente1_prestamo_activo", fields.cliente1_prestamo_activo);
  set("cliente1_prestamo_entidad", fields.cliente1_prestamo_entidad);
  set("cliente1_prestamo_resto", fields.cliente1_prestamo_resto);
  set("cliente2_nombre", fields.cliente2_nombre);
  set("cliente2_dni", fields.cliente2_dni);
  set("cliente2_telefono", fields.cliente2_telefono);
  set("cliente2_email", fields.cliente2_email);
  set("cliente2_fecha_nacimiento", fields.cliente2_fecha_nacimiento, true);
  set("cliente2_estado_civil", fields.cliente2_estado_civil);
  set("cliente2_regimen", fields.cliente2_regimen);
  set("cliente2_hijos", fields.cliente2_hijos);
  set("cliente2_profesion", fields.cliente2_profesion);
  set("cliente2_tipo_contrato", fields.cliente2_tipo_contrato);
  set("cliente2_tiempo_contrato", fields.cliente2_tiempo_contrato);
  set("cliente2_ingresos", fields.cliente2_ingresos);
  set("cliente2_patrimonio", fields.cliente2_patrimonio);
  set("cliente2_prestamos", fields.cliente2_prestamos);
  set("cliente2_prestamo_activo", fields.cliente2_prestamo_activo);
  set("cliente2_prestamo_entidad", fields.cliente2_prestamo_entidad);
  set("cliente2_prestamo_resto", fields.cliente2_prestamo_resto);
  set("ingresos_conjuntos", fields.ingresos_conjuntos);
  set("entidades_financieras", fields.entidades_financieras);
  set("avalistas", fields.avalistas);
  set("aportacion_cv", fields.aportacion_cv);
  bindMoneyInputs(finAsesoramientoForm);
  bindIngresosConjuntos(finAsesoramientoForm);
  bindLoanToggles(finAsesoramientoForm);
  applyPrestamoFromOcr(fields, "cliente1");
  applyPrestamoFromOcr(fields, "cliente2");
};

const saveSegurosOcrRecord = async () => {
  if (segurosOcrSaveStatus) {
    segurosOcrSaveStatus.textContent = "";
  }
  const tomador = seguroOcrTomador ? seguroOcrTomador.value.trim() : "";
  const poliza = seguroOcrPoliza ? seguroOcrPoliza.value.trim() : "";
  if (!tomador || !poliza) {
    if (segurosOcrSaveStatus) {
      segurosOcrSaveStatus.textContent = "Indica tomador y Nº póliza.";
    }
    return;
  }
  const now = new Date();
  const mesCreacion = now.toLocaleString("es-ES", { month: "long" });
  const fechaEfecto = seguroOcrFechaEfecto ? seguroOcrFechaEfecto.value : "";
  const fechaVencimiento = seguroOcrFechaVencimiento && seguroOcrFechaVencimiento.value
    ? seguroOcrFechaVencimiento.value
    : addOneYear(fechaEfecto);
  const payload = {
    empresa_nombre: FINCAS_COMPANY,
    cliente_id: state.segurosOcrClienteId || "",
    ocr_quality: state.segurosOcrQuality || null,
    mes_creacion: mesCreacion,
    fecha_efecto: fechaEfecto,
    fecha_vencimiento: fechaVencimiento,
    tomador,
    nif: seguroOcrDni ? seguroOcrDni.value.trim() : "",
    telefono: seguroOcrTelefono ? seguroOcrTelefono.value.trim() : "",
    email: seguroOcrEmail ? seguroOcrEmail.value.trim() : "",
    direccion: seguroOcrDireccion ? seguroOcrDireccion.value.trim() : "",
    fecha_nacimiento: seguroOcrNacimiento ? seguroOcrNacimiento.value.trim() : "",
    compania: seguroOcrCompania ? seguroOcrCompania.value.trim() : "",
    ramo: seguroOcrRamo ? seguroOcrRamo.value.trim() : "",
    poliza_numero: poliza,
    prima_neta: toNumber(seguroOcrPrimaNeta ? seguroOcrPrimaNeta.value : ""),
    prima_total: toNumber(seguroOcrPrimaTotal ? seguroOcrPrimaTotal.value : ""),
    produccion: seguroOcrProduccion ? seguroOcrProduccion.value : "",
    colaborador: seguroOcrColaborador ? seguroOcrColaborador.value.trim() : "",
    estado: seguroOcrEstado ? seguroOcrEstado.value : "",
  };
  const file =
    segurosOcrFile && segurosOcrFile.files && segurosOcrFile.files.length
      ? segurosOcrFile.files[0]
      : null;
  if (file) {
    try {
      const upload = await uploadFileToS3(file, "seguros", segurosOcrSaveStatus);
      if (upload) {
        payload.poliza_key = upload.key || "";
        payload.poliza_url = upload.public_url || "";
      }
    } catch (err) {
      if (segurosOcrSaveStatus) {
        segurosOcrSaveStatus.textContent = `Error al subir: ${err.message}`;
      }
      return;
    }
  }
  if (segurosOcrSaveStatus) {
    segurosOcrSaveStatus.textContent = "Guardando...";
  }
  fetch("/api/seguros", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then((res) => res.json())
    .then((data) => {
      if (data.error) {
        if (segurosOcrSaveStatus) {
          segurosOcrSaveStatus.textContent = data.error;
        }
        return;
      }
      if (segurosOcrSaveStatus) {
        segurosOcrSaveStatus.textContent = "Guardado en BDT.";
      }
      state.segurosOcrClienteId = "";
      state.segurosOcrQuality = null;
      loadSegurosCrm();
    })
    .catch(() => {
      if (segurosOcrSaveStatus) {
        segurosOcrSaveStatus.textContent = "Error al guardar.";
      }
    });
};

const openSegurosPresupuestoEdit = (columns, row) => {
  if (!row || !columns) return;
  if (segurosOcrSaveStatus) segurosOcrSaveStatus.textContent = "";
  if (segurosOcrStatus) segurosOcrStatus.textContent = "Edita el presupuesto y guarda para convertir.";
  const getVal = (key) => {
    const idx = columns.indexOf(key);
    return idx >= 0 ? row[idx] : "";
  };
  if (seguroOcrTomador) seguroOcrTomador.value = getVal("tomador") || "";
  if (seguroOcrDni) seguroOcrDni.value = getVal("nif") || "";
  if (seguroOcrTelefono) seguroOcrTelefono.value = getVal("telefono") || "";
  if (seguroOcrEmail) seguroOcrEmail.value = getVal("email") || "";
  if (seguroOcrCompania) seguroOcrCompania.value = getVal("compania") || "";
  if (seguroOcrRamo) seguroOcrRamo.value = getVal("ramo") || "";
  if (seguroOcrPoliza) seguroOcrPoliza.value = getVal("poliza_numero") || "";
  if (seguroOcrDireccion) seguroOcrDireccion.value = getVal("direccion") || "";
  if (seguroOcrFechaEfecto) {
    seguroOcrFechaEfecto.value = normalizeDateInput(getVal("fecha_efecto") || "");
  }
  if (seguroOcrFechaVencimiento) {
    const fecha = normalizeDateInput(getVal("fecha_vencimiento") || "");
    seguroOcrFechaVencimiento.value = fecha || (seguroOcrFechaEfecto?.value ? addOneYear(seguroOcrFechaEfecto.value) : "");
  }
  if (seguroOcrPrimaNeta) seguroOcrPrimaNeta.value = getVal("prima_neta") || "";
  if (seguroOcrPrimaTotal) seguroOcrPrimaTotal.value = getVal("prima_total") || "";
  if (seguroOcrProduccion) seguroOcrProduccion.value = getVal("produccion") || "";
  if (seguroOcrColaborador) seguroOcrColaborador.value = getVal("colaborador") || "";
  if (seguroOcrEstado) seguroOcrEstado.value = "Presupuesto";
  if (segurosOcrSave) {
    segurosOcrSave.dataset.recordId = getVal("id") || "";
    segurosOcrSave.textContent = "Guardar cambios y convertir";
  }
  const editor = document.getElementById("segurosOcrFields");
  if (editor) {
    editor.scrollIntoView({ behavior: "smooth", block: "start" });
  }
};

const loadFinCrm = () => {
  if (!finCrmTable || !finCrmInfo) {
    return;
  }
  const empresa = state.empresas.find((e) => e.nombre === FIN_COMPANY);
  if (!empresa) {
    finCrmTable.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  loadFinInmobiliarias();
  const q = finCrmSearch ? finCrmSearch.value.trim() : "";
  const params = new URLSearchParams({
    tabla: "hipotecas",
    empresa_id: empresa.id,
    q,
  });
  api(`/api/tabla?${params.toString()}`).then((data) => {
    const columns = data.columns || [];
    let rows = data.rows || [];
    const filtroCliente = finCrmClienteInput ? finCrmClienteInput.value.trim().toLowerCase() : "";
    if (filtroCliente) {
      const clienteIndex = columns.indexOf("cliente");
      if (clienteIndex >= 0) {
        rows = rows.filter((row) =>
          String(row[clienteIndex] || "").toLowerCase().includes(filtroCliente)
        );
      }
    }
    renderTableInto({ columns, rows }, finCrmTable, finCrmInfo, "Hipotecas");
    loadAcciones("financiaciones", empresa.id, finAgendaTable, finAgendaInfo);
    loadFinAsesoramientos(empresa.id);
    bindMoneyInputs(finAsesoramientoForm);
    bindIngresosConjuntos(finAsesoramientoForm);
    bindLoanToggles(finAsesoramientoForm);
  });
};

const loadFinInmobiliarias = () => {
  if (!finAsesorInmobiliaria) return;
  api("/api/fin_inmobiliarias").then((data) => {
    const list = (data.items || []).filter(Boolean);
    const current = finAsesorInmobiliaria.value;
    finAsesorInmobiliaria.innerHTML = "";
    finAsesorInmobiliaria.appendChild(createOption("", "Selecciona inmobiliaria"));
    list.forEach((item) => {
      finAsesorInmobiliaria.appendChild(createOption(item, item));
    });
    if (current) {
      const exists = Array.from(finAsesorInmobiliaria.options).some(
        (opt) => opt.value === current
      );
      if (!exists) {
        finAsesorInmobiliaria.appendChild(createOption(current, current));
      }
      finAsesorInmobiliaria.value = current;
    }
  });
};

const fillFinAsesoramientoForm = (row) => {
  if (!finAsesoramientoForm || !row) return;
  if (finAsesoramientoId) finAsesoramientoId.value = row.id || "";
  if (finAsesoramientoConvert) {
    finAsesoramientoConvert.disabled = !row.id;
  }
  const map = {
    inmobiliaria_asesor: "inmobiliaria_asesor",
    asesor: "asesor",
    fecha: "fecha",
    origen: "origen",
    estado: "estado",
    cliente1_nombre: "cliente1_nombre",
    cliente1_dni: "cliente1_dni",
    cliente1_telefono: "cliente1_telefono",
    cliente1_email: "cliente1_email",
    cliente1_fecha_nacimiento: "cliente1_fecha_nacimiento",
    cliente1_estado_civil: "cliente1_estado_civil",
    cliente1_regimen: "cliente1_regimen",
    cliente1_hijos: "cliente1_hijos",
    cliente1_profesion: "cliente1_profesion",
    cliente1_tipo_contrato: "cliente1_tipo_contrato",
    cliente1_tiempo_contrato: "cliente1_tiempo_contrato",
    cliente1_ingresos: "cliente1_ingresos",
    cliente1_patrimonio: "cliente1_patrimonio",
    cliente1_prestamos: "cliente1_prestamos",
    cliente1_prestamo_activo: "cliente1_prestamo_activo",
    cliente1_prestamo_entidad: "cliente1_prestamo_entidad",
    cliente1_prestamo_resto: "cliente1_prestamo_resto",
    cliente2_nombre: "cliente2_nombre",
    cliente2_dni: "cliente2_dni",
    cliente2_telefono: "cliente2_telefono",
    cliente2_email: "cliente2_email",
    cliente2_fecha_nacimiento: "cliente2_fecha_nacimiento",
    cliente2_estado_civil: "cliente2_estado_civil",
    cliente2_regimen: "cliente2_regimen",
    cliente2_hijos: "cliente2_hijos",
    cliente2_profesion: "cliente2_profesion",
    cliente2_tipo_contrato: "cliente2_tipo_contrato",
    cliente2_tiempo_contrato: "cliente2_tiempo_contrato",
    cliente2_ingresos: "cliente2_ingresos",
    cliente2_patrimonio: "cliente2_patrimonio",
    cliente2_prestamos: "cliente2_prestamos",
    cliente2_prestamo_activo: "cliente2_prestamo_activo",
    cliente2_prestamo_entidad: "cliente2_prestamo_entidad",
    cliente2_prestamo_resto: "cliente2_prestamo_resto",
    ingresos_conjuntos: "ingresos_conjuntos",
    entidades_financieras: "entidades_financieras",
    avalistas: "avalistas",
    aportacion_cv: "aportacion_cv",
    notas: "notas",
    notas_ocr: "notas_ocr",
  };
  const moneyFields = new Set([
    "cliente1_ingresos",
    "cliente2_ingresos",
    "ingresos_conjuntos",
    "aportacion_cv",
  ]);
  Object.entries(map).forEach(([field, key]) => {
    const el = finAsesoramientoForm.querySelector(`[name="${field}"]`);
    if (!el) return;
    if (field.includes("fecha") && row[key]) {
      el.value = normalizeDateInput(row[key]);
      return;
    }
    if (moneyFields.has(field)) {
      const num = toNumber(row[key]);
      el.value = num === null ? (row[key] !== null && row[key] !== undefined ? row[key] : "") : euroFormatter.format(num);
      return;
    }
    el.value = row[key] !== null && row[key] !== undefined ? row[key] : "";
  });
  if (row.id) {
    loadFinChecklist(row.id);
  }
};

const renderFinAsesorKpis = (empresaId) => {
  if (!finAsesorKpis || !empresaId) return;
  api(`/api/fin_kpis?empresa_id=${empresaId}`).then((data) => {
    const kpis = [
      { title: "Asesoramientos", value: numberFormatter.format(data.total || 0), note: "Total" },
      { title: "En estudio", value: numberFormatter.format(data.estados?.en_estudio || 0), note: "Pendientes" },
      { title: "Aprobados", value: numberFormatter.format(data.estados?.aprobado || 0), note: "OK" },
      { title: "Faltantes", value: numberFormatter.format(data.faltantes || 0), note: "Campos obligatorios" },
    ];
    finAsesorKpis.innerHTML = "";
    kpis.forEach((kpi) => {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
        <h3>${kpi.title}</h3>
        <div class="muted">${kpi.value}</div>
        <div class="muted">${kpi.note}</div>
      `;
      finAsesorKpis.appendChild(card);
    });
  });
};

const loadFinAlerts = (empresaId) => {
  if (!finAlertsTable || !finAlertsInfo || !empresaId) return;
  api(`/api/fin_alertas?empresa_id=${empresaId}`).then((data) => {
    const rows = data.items || [];
    if (!rows.length) {
      finAlertsTable.innerHTML = "<p class='muted'>Sin alertas activas.</p>";
      finAlertsInfo.textContent = "";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["fecha", "cliente1", "estado", "alerta"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const alerta = row.alerta_tipo === "faltantes"
        ? `Faltan: ${(row.missing_fields || []).join(", ")}`
        : "Seguimiento pendiente";
      const values = [
        row.fecha || "-",
        row.cliente1_nombre || "-",
        row.estado || "-",
        alerta,
      ];
      values.forEach((value) => {
        const td = document.createElement("td");
        td.textContent = value === null ? "" : value;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    finAlertsTable.innerHTML = "";
    finAlertsTable.appendChild(table);
    finAlertsInfo.textContent = `Mostrando ${rows.length} alertas.`;
  });
};

const loadFinChecklist = (asesoramientoId) => {
  if (!finChecklistTable || !finChecklistInfo) return;
  if (!asesoramientoId) {
    finChecklistTable.innerHTML = "<p class='muted'>Selecciona un asesoramiento.</p>";
    finChecklistInfo.textContent = "";
    return;
  }
  api(`/api/fin_checklist?asesoramiento_id=${asesoramientoId}`).then((data) => {
    const rows = data.rows || [];
    if (!rows.length) {
      finChecklistTable.innerHTML = "<p class='muted'>Checklist vacío.</p>";
      finChecklistInfo.textContent = "";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["tarea", "estado", "responsable", "fecha límite"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const tdTask = document.createElement("td");
      tdTask.textContent = row.tarea || "-";
      tr.appendChild(tdTask);
      const tdEstado = document.createElement("td");
      const select = document.createElement("select");
      ["Pendiente", "En curso", "Hecho"].forEach((opt) => {
        const option = document.createElement("option");
        option.value = opt;
        option.textContent = opt;
        if ((row.estado || "") === opt) option.selected = true;
        select.appendChild(option);
      });
      select.addEventListener("change", () => {
        fetch("/api/fin_checklist_update", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            id: row.id,
            estado: select.value,
            empresa_nombre: FIN_COMPANY,
          }),
        }).catch(() => {});
      });
      tdEstado.appendChild(select);
      tr.appendChild(tdEstado);
      const tdResp = document.createElement("td");
      tdResp.textContent = row.responsable || "-";
      tr.appendChild(tdResp);
      const tdFecha = document.createElement("td");
      tdFecha.textContent = row.fecha_limite || "-";
      tr.appendChild(tdFecha);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    finChecklistTable.innerHTML = "";
    finChecklistTable.appendChild(table);
    finChecklistInfo.textContent = `Mostrando ${rows.length} tareas.`;
  });
};

const loadFinAsesoramientos = (empresaId) => {
  if (!finAsesoramientosTable || !finAsesoramientosInfo || !empresaId) return;
  const q = finAsesoramientosSearch ? finAsesoramientosSearch.value.trim() : "";
  const params = new URLSearchParams({ empresa_id: empresaId, q });
  api(`/api/fin_asesoramientos?${params.toString()}`).then((data) => {
    const rows = data.rows || [];
    if (!rows.length) {
      finAsesoramientosTable.innerHTML = "<p class='muted'>Sin asesoramientos aún.</p>";
      finAsesoramientosInfo.textContent = "";
      renderFinAsesorKpis(empresaId);
      loadFinAlerts(empresaId);
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    [
      "fecha",
      "cliente1",
      "cliente2",
      "telefono",
      "ingresos",
      "estado",
      "faltantes",
      "asesor",
      "acciones",
    ].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const telefono = row.cliente1_telefono || row.cliente2_telefono || "-";
      const ingresos = row.ingresos_conjuntos || row.cliente1_ingresos || "-";
      const values = [
        row.fecha || "-",
        row.cliente1_nombre || "-",
        row.cliente2_nombre || "-",
        telefono,
        ingresos,
        row.estado || "-",
        row.missing_count ? String(row.missing_count) : "-",
        row.asesor || row.inmobiliaria_asesor || "-",
      ];
      values.forEach((value, idx) => {
        const td = document.createElement("td");
        if (idx === 4) {
          const formatted = formatCell("ingresos_conjuntos", value);
          td.textContent = formatted === null ? "" : formatted;
        } else {
          td.textContent = value === null ? "" : value;
        }
        tr.appendChild(td);
      });
      const tdActions = document.createElement("td");
      tdActions.className = "inline-actions";
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "secondary";
      editBtn.textContent = "Editar";
      editBtn.addEventListener("click", () => {
        fillFinAsesoramientoForm(row);
        if (finAsesoramientoForm) {
          finAsesoramientoForm.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
      const convertBtn = document.createElement("button");
      convertBtn.type = "button";
      convertBtn.textContent = "Convertir";
      convertBtn.addEventListener("click", () => {
        const ok = window.confirm("¿Convertir este asesoramiento en hipoteca?");
        if (!ok) return;
        fetch("/api/fin_asesoramientos_convert", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            id: row.id,
            empresa_nombre: FIN_COMPANY,
          }),
        })
          .then((res) => res.json())
          .then((resp) => {
            if (resp.error) return;
            loadFinCrm();
          });
      });
      tdActions.appendChild(editBtn);
      tdActions.appendChild(convertBtn);
      tr.appendChild(tdActions);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    finAsesoramientosTable.innerHTML = "";
    finAsesoramientosTable.appendChild(table);
    finAsesoramientosInfo.textContent = `Mostrando ${rows.length} asesoramientos.`;
    renderFinAsesorKpis(empresaId);
    loadFinAlerts(empresaId);
  });
};

const bindMoneyInputs = (formEl) => {
  if (!formEl) return;
  const moneyInputs = formEl.querySelectorAll("input[data-money='1']");
  moneyInputs.forEach((input) => {
    if (input.dataset.boundMoney === "1") return;
    input.dataset.boundMoney = "1";
    input.addEventListener("focus", () => {
      const num = toNumber(input.value);
      if (num !== null) input.value = String(num);
    });
    input.addEventListener("blur", () => {
      const num = toNumber(input.value);
      if (num !== null) input.value = euroFormatter.format(num);
    });
  });
};

const bindIngresosConjuntos = (formEl) => {
  if (!formEl) return;
  const ingreso1 = formEl.querySelector('[name="cliente1_ingresos"]');
  const ingreso2 = formEl.querySelector('[name="cliente2_ingresos"]');
  const conjunto = formEl.querySelector('[name="ingresos_conjuntos"]');
  if (!ingreso1 || !ingreso2 || !conjunto) return;
  if (conjunto.dataset.boundIngresos === "1") return;
  conjunto.dataset.boundIngresos = "1";
  const update = () => {
    const n1 = toNumber(ingreso1.value);
    const n2 = toNumber(ingreso2.value);
    if (n1 === null && n2 === null) return;
    const sum = (n1 || 0) + (n2 || 0);
    if (!conjunto.value || conjunto.dataset.auto === "1") {
      conjunto.value = euroFormatter.format(sum);
      conjunto.dataset.auto = "1";
    }
  };
  ingreso1.addEventListener("blur", update);
  ingreso2.addEventListener("blur", update);
  conjunto.addEventListener("input", () => {
    conjunto.dataset.auto = "0";
  });
  update();
};

const bindLoanToggles = (formEl) => {
  if (!formEl) return;
  const toggles = formEl.querySelectorAll("[data-loan-toggle]");
  toggles.forEach((toggle) => {
    if (toggle.dataset.boundLoan === "1") return;
    toggle.dataset.boundLoan = "1";
    const key = toggle.dataset.loanToggle;
    const update = () => {
      const show = String(toggle.value || "").toLowerCase() === "si";
      formEl
        .querySelectorAll(`[data-loan-field="${key}"]`)
        .forEach((el) => {
          el.classList.toggle("hidden", !show);
        });
    };
    toggle.addEventListener("change", update);
    update();
  });
};

const extractLoanInfo = (text) => {
  if (!text) return { active: "", entidad: "", resto: "" };
  const cleaned = String(text).replace(/\s+/g, " ");
  const entidadList = Array.from(document.querySelectorAll("#bankList option")).map(
    (opt) => opt.value
  );
  let entidad = "";
  for (const name of entidadList) {
    if (name && cleaned.toLowerCase().includes(name.toLowerCase())) {
      entidad = name;
      break;
    }
  }
  const amounts = cleaned.match(/[0-9]{1,3}(?:[\\.,][0-9]{3})*(?:[\\.,][0-9]{2})?/g) || [];
  const resto = amounts.length ? amounts[amounts.length - 1] : "";
  return { active: "Si", entidad, resto };
};

const applyPrestamoFromOcr = (fields, prefix) => {
  const raw = fields[`${prefix}_prestamos`];
  if (!raw) return;
  const info = extractLoanInfo(raw);
  const form = finAsesoramientoForm;
  if (!form) return;
  const setValue = (name, value) => {
    const el = form.querySelector(`[name="${name}"]`);
    if (el && value !== undefined) el.value = value;
  };
  setValue(`${prefix}_prestamo_activo`, info.active);
  setValue(`${prefix}_prestamo_entidad`, info.entidad);
  setValue(`${prefix}_prestamo_resto`, info.resto);
};

const loadSegurosOportunidades = (empresaId) => {
  if (!segurosCrmOportunidades) {
    return;
  }
  const segurosParams = new URLSearchParams({ tabla: "seguros", empresa_id: empresaId });
  const gestoriaParams = new URLSearchParams({ tabla: "gestoria", empresa_id: empresaId });
  Promise.all([
    api(`/api/tabla?${segurosParams.toString()}`),
    api(`/api/tabla?${gestoriaParams.toString()}`),
  ]).then(([segurosData, gestoriaData]) => {
    const tomadorIndex = segurosData.columns.indexOf("tomador");
    const clienteIndex = gestoriaData.columns.indexOf("cliente");
    const tomadores = new Set(
      segurosData.rows.map((row) => (row[tomadorIndex] || "").trim()).filter(Boolean)
    );
    const candidatos = gestoriaData.rows
      .map((row) => (row[clienteIndex] || "").trim())
      .filter(Boolean);
    const oportunidades = candidatos.filter((name) => !tomadores.has(name));
    if (!oportunidades.length) {
      segurosCrmOportunidades.innerHTML = "<p class='muted'>Sin oportunidades pendientes.</p>";
      return;
    }
    const list = document.createElement("div");
    list.className = "inline-list";
    oportunidades.slice(0, 50).forEach((name) => {
      const row = document.createElement("div");
      row.className = "inline-row";
      row.innerHTML = `<div class="muted">${name}</div>`;
      list.appendChild(row);
    });
    segurosCrmOportunidades.innerHTML = "";
    segurosCrmOportunidades.appendChild(list);
  });
};

const loadAcciones = (servicio, empresaId, container, infoEl) => {
  if (!container || !infoEl) {
    return;
  }
  container.dataset.service = servicio || "";
  const params = new URLSearchParams({ servicio, empresa_id: empresaId });
  api(`/api/acciones?${params.toString()}`).then((data) => {
    const rows = data.rows || [];
    const events = buildAgendaEvents(rows, servicio, SERVICE_LABELS[servicio] || servicio);
    renderAgendaCalendar(container, events, `Agenda · ${SERVICE_LABELS[servicio] || servicio}`);
    infoEl.textContent = `Mostrando ${rows.length} acciones.`;
  });
};

const loadClienteProfesional = (clienteId) => {
  if (!clienteProfesionalList) return;
  api(`/api/cliente_profesional?cliente_id=${clienteId}`).then((data) => {
    const rows = data.rows || [];
    if (!rows.length) {
      clienteProfesionalList.innerHTML = "<p class='muted'>Sin datos profesionales.</p>";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["CNAE", "IAE", "Actividad", "IBAN", "Principal", "Accion"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = col;
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      ["cnae", "iae", "actividad", "iban"].forEach((key) => {
        const td = document.createElement("td");
        const input = document.createElement("input");
        input.value = row[key] || "";
        input.classList.add("inline-input");
        input.addEventListener("change", () => {
          saveClienteProfesionalField(row.id, key, input.value);
        });
        td.appendChild(input);
        tr.appendChild(td);
      });
      const principalTd = document.createElement("td");
      const principalSelect = document.createElement("select");
      principalSelect.classList.add("inline-input");
      principalSelect.appendChild(createOption("0", "No"));
      principalSelect.appendChild(createOption("1", "Sí"));
      principalSelect.value = String(row.principal || 0);
      principalSelect.addEventListener("change", () => {
        saveClienteProfesionalField(row.id, "principal", principalSelect.value);
      });
      principalTd.appendChild(principalSelect);
      tr.appendChild(principalTd);
      const actionTd = document.createElement("td");
      const del = document.createElement("button");
      del.type = "button";
      del.textContent = "Eliminar";
      del.addEventListener("click", () => {
        deleteClienteProfesional(row.id, clienteId);
      });
      actionTd.appendChild(del);
      tr.appendChild(actionTd);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    clienteProfesionalList.innerHTML = "";
    clienteProfesionalList.appendChild(table);
  });
};

const loadGestoriaTrabajos = (clienteId) => {
  if (!gestoriaTrabajosTable) return;
  api(`/api/gestoria_trabajos?cliente_id=${clienteId}`).then((data) => {
    const rows = data.rows || [];
    if (!rows.length) {
      gestoriaTrabajosTable.innerHTML = "<p class='muted'>Sin gestiones registradas.</p>";
      return;
    }
    const readonly = state.currentPage === "cliente";
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["Gestion", "Estado", "Inicio", "Fin", "Responsable", "Importe", "Notas"]
      .concat(readonly ? [] : ["Accion"])
      .forEach((col) => {
      const th = document.createElement("th");
      th.textContent = col;
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const buildInput = (value, field, type = "text") => {
        const input = document.createElement("input");
        input.type = type;
        input.value = value || "";
        input.classList.add("inline-input");
        input.addEventListener("change", () => {
          saveGestoriaTrabajoField(row.id, field, input.value);
        });
        return input;
      };
      const buildSelect = (value, field, options) => {
        const select = document.createElement("select");
        select.classList.add("inline-input");
        options.forEach((opt) => {
          select.appendChild(createOption(opt, opt));
        });
        select.value = value || options[0];
        select.addEventListener("change", () => {
          saveGestoriaTrabajoField(row.id, field, select.value);
        });
        return select;
      };
      const trabajoTd = document.createElement("td");
      trabajoTd.textContent = readonly ? (row.tipo_trabajo || "") : "";
      if (!readonly) {
        trabajoTd.appendChild(buildInput(row.tipo_trabajo, "tipo_trabajo"));
      }
      tr.appendChild(trabajoTd);

      const estadoTd = document.createElement("td");
      if (readonly) {
        estadoTd.textContent = row.estado || "";
      } else {
        estadoTd.appendChild(
          buildSelect(row.estado, "estado", [
            "Presupuesto",
            "En curso",
            "Finalizado",
            "Cancelado",
          ])
        );
      }
      tr.appendChild(estadoTd);

      const inicioTd = document.createElement("td");
      if (readonly) {
        inicioTd.textContent = row.fecha_inicio || "";
      } else {
        inicioTd.appendChild(buildInput(row.fecha_inicio, "fecha_inicio", "date"));
      }
      tr.appendChild(inicioTd);

      const finTd = document.createElement("td");
      if (readonly) {
        finTd.textContent = row.fecha_fin || "";
      } else {
        finTd.appendChild(buildInput(row.fecha_fin, "fecha_fin", "date"));
      }
      tr.appendChild(finTd);

      const respTd = document.createElement("td");
      if (readonly) {
        respTd.textContent = row.responsable || "";
      } else {
        respTd.appendChild(buildInput(row.responsable, "responsable"));
      }
      tr.appendChild(respTd);

      const importeTd = document.createElement("td");
      if (readonly) {
        importeTd.textContent = row.importe || "";
      } else {
        importeTd.appendChild(buildInput(row.importe, "importe", "number"));
      }
      tr.appendChild(importeTd);

      const notasTd = document.createElement("td");
      if (readonly) {
        notasTd.textContent = row.notas || "";
      } else {
        notasTd.appendChild(buildInput(row.notas, "notas"));
      }
      tr.appendChild(notasTd);

      if (!readonly) {
        const actionTd = document.createElement("td");
        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.textContent = "Eliminar";
        delBtn.addEventListener("click", () => {
          deleteGestoriaTrabajo(row.id);
        });
        actionTd.appendChild(delBtn);
        tr.appendChild(actionTd);
      }
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    gestoriaTrabajosTable.innerHTML = "";
    gestoriaTrabajosTable.appendChild(table);
  });
};

const loadGestoriaTrabajosFiltered = (clienteId, tipos, container, infoEl, label) => {
  if (!container || !clienteId) return;
  api(`/api/gestoria_trabajos?cliente_id=${clienteId}`).then((data) => {
    const rows = (data.rows || []).filter((row) => {
      if (!tipos || !tipos.length) return true;
      return tipos.includes(String(row.tipo_trabajo || ""));
    });
    if (!rows.length) {
      container.innerHTML = `<p class='muted'>Sin ${label || "gestiones"} registradas.</p>`;
      if (infoEl) infoEl.textContent = "";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["Gestión", "Estado", "Inicio", "Fin", "Responsable", "Importe", "Notas"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = col;
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const cells = [
        row.tipo_trabajo || "",
        row.estado || "",
        row.fecha_inicio || "",
        row.fecha_fin || "",
        row.responsable || "",
        row.importe || "",
        row.notas || "",
      ];
      cells.forEach((value) => {
        const td = document.createElement("td");
        td.textContent = value;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    container.innerHTML = "";
    container.appendChild(table);
    if (infoEl) infoEl.textContent = `Mostrando ${rows.length} ${label || "gestiones"}.`;
  });
};

const submitGestoriaTrabajoForm = async (form, statusEl, afterSubmit) => {
  if (!form) return;
  if (!state.currentClienteId) {
    if (statusEl) statusEl.textContent = "Selecciona un cliente.";
    return;
  }
  if (statusEl) statusEl.textContent = "Guardando...";
  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());
  payload.cliente_id = state.currentClienteId;
  payload.empresa_nombre = FINCAS_COMPANY;
  payload.usuario = getCurrentUser();
  try {
    const res = await fetch("/api/gestoria_trabajos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (statusEl) statusEl.textContent = data.error || "Guardado.";
    if (!data.error) {
      form.reset();
      if (typeof afterSubmit === "function") afterSubmit();
    }
  } catch (error) {
    if (statusEl) statusEl.textContent = "Error al guardar.";
  }
};

const loadGestoriaDocs = (clienteId) => {
  if (!gestoriaDocsTable) return;
  api(`/api/gestoria_docs?cliente_id=${clienteId}`).then((data) => {
    const rows = data.rows || [];
    if (!rows.length) {
      gestoriaDocsTable.innerHTML = "<p class='muted'>Sin documentación registrada.</p>";
      return;
    }
    const readonly = state.currentPage === "cliente";
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["Documento", "Tipo", "Fecha", "Estado", "Notas", "PDF"]
      .concat(readonly ? [] : ["Accion"])
      .forEach((col) => {
      const th = document.createElement("th");
      th.textContent = col;
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const buildInput = (value, field, type = "text") => {
        const input = document.createElement("input");
        input.type = type;
        input.value = value || "";
        input.classList.add("inline-input");
        input.addEventListener("change", () => {
          saveGestoriaDocField(row.id, field, input.value);
        });
        return input;
      };
      const buildSelect = (value, field, options) => {
        const select = document.createElement("select");
        select.classList.add("inline-input");
        options.forEach((opt) => {
          select.appendChild(createOption(opt, opt));
        });
        select.value = value || options[0];
        select.addEventListener("change", () => {
          saveGestoriaDocField(row.id, field, select.value);
        });
        return select;
      };
      const nombreTd = document.createElement("td");
      if (readonly) {
        nombreTd.textContent = row.nombre || "";
      } else {
        nombreTd.appendChild(buildInput(row.nombre, "nombre"));
      }
      tr.appendChild(nombreTd);

      const tipoTd = document.createElement("td");
      if (readonly) {
        tipoTd.textContent = row.tipo || "";
      } else {
        tipoTd.appendChild(buildInput(row.tipo, "tipo"));
      }
      tr.appendChild(tipoTd);

      const fechaTd = document.createElement("td");
      if (readonly) {
        fechaTd.textContent = row.fecha || "";
      } else {
        fechaTd.appendChild(buildInput(row.fecha, "fecha", "date"));
      }
      tr.appendChild(fechaTd);

      const estadoTd = document.createElement("td");
      if (readonly) {
        estadoTd.textContent = row.estado || "";
      } else {
        estadoTd.appendChild(
          buildSelect(row.estado, "estado", ["Pendiente", "Recibido", "Validado"])
        );
      }
      tr.appendChild(estadoTd);

      const notasTd = document.createElement("td");
      if (readonly) {
        notasTd.textContent = row.notas || "";
      } else {
        notasTd.appendChild(buildInput(row.notas, "notas"));
      }
      tr.appendChild(notasTd);

      const pdfTd = document.createElement("td");
      if (row.doc_key || row.doc_url) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "secondary";
        btn.textContent = "Ver";
        btn.addEventListener("click", () => {
          openS3File(row.doc_key, row.doc_url);
        });
        pdfTd.appendChild(btn);
      } else {
        pdfTd.textContent = "-";
      }
      tr.appendChild(pdfTd);

      if (!readonly) {
        const actionTd = document.createElement("td");
        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.textContent = "Eliminar";
        delBtn.addEventListener("click", () => {
          deleteGestoriaDoc(row.id);
        });
        actionTd.appendChild(delBtn);
        tr.appendChild(actionTd);
      }
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    gestoriaDocsTable.innerHTML = "";
    gestoriaDocsTable.appendChild(table);
  });
};

const loadGestoriaClienteAgenda = (clienteId) => {
  if (!gestoriaClienteAgendaTable || !gestoriaClienteAgendaInfo) return;
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) {
    gestoriaClienteAgendaTable.innerHTML = "<p class='muted'>Sin empresa.</p>";
    return;
  }
  gestoriaClienteAgendaTable.dataset.service = "gestoria";
  const params = new URLSearchParams({
    servicio: "gestoria",
    empresa_id: empresa.id,
    cliente_id: clienteId,
  });
  api(`/api/acciones?${params.toString()}`).then((data) => {
    const rows = data.rows || [];
    if (state.currentPage === "cliente") {
      const list = document.createElement("div");
      list.className = "inline-list";
      const sorted = rows
        .slice()
        .sort((a, b) => String(a.fecha || "").localeCompare(String(b.fecha || "")));
      const upcoming = sorted.slice(0, 5);
      if (!upcoming.length) {
        gestoriaClienteAgendaTable.innerHTML = "<p class='muted'>Sin acciones programadas.</p>";
        if (gestoriaClienteAgendaInfo) gestoriaClienteAgendaInfo.textContent = "";
        return;
      }
      upcoming.forEach((row) => {
        const item = document.createElement("div");
        item.className = "inline-row";
        const fecha = formatCell("fecha", row.fecha) || row.fecha || "-";
        const hora = row.hora ? ` ${row.hora}` : "";
        const tipo = row.tipo || "Acción";
        const estado = row.estado || "Pendiente";
        item.innerHTML = `<div class="muted">${fecha}${hora}</div><div>${tipo}</div><div class="muted">${estado}</div>`;
        list.appendChild(item);
      });
      gestoriaClienteAgendaTable.innerHTML = "";
      gestoriaClienteAgendaTable.appendChild(list);
      if (gestoriaClienteAgendaInfo) {
        gestoriaClienteAgendaInfo.textContent = `Mostrando ${upcoming.length} próximas acciones.`;
      }
      return;
    }
    const events = buildAgendaEvents(rows, "gestoria", "Gestoría");
    delete gestoriaClienteAgendaTable.dataset.readonly;
    renderAgendaCalendar(gestoriaClienteAgendaTable, events, "Agenda del cliente");
    gestoriaClienteAgendaInfo.textContent = `Mostrando ${rows.length} acciones.`;
  });
};

const loadGestoriaClienteDashboard = (clienteId) => {
  if (!clienteId || !gestoriaClienteKpis) return;
  const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  if (!empresa) return;
  const modelosReq = api(`/api/gestoria_modelos?cliente_id=${clienteId}`);
  const trabajosReq = api(`/api/gestoria_trabajos?cliente_id=${clienteId}`);
  const docsReq = api(`/api/gestoria_docs?cliente_id=${clienteId}`);
  const accionesReq = api(
    `/api/acciones?servicio=gestoria&empresa_id=${empresa.id}&cliente_id=${clienteId}`
  );
  Promise.all([modelosReq, trabajosReq, docsReq, accionesReq]).then(
    ([modelosData, trabajosData, docsData, accionesData]) => {
      const modelos = modelosData.rows || [];
      const trabajos = trabajosData.rows || [];
      const docs = docsData.rows || [];
      const acciones = accionesData.rows || [];
      const now = new Date();
      const inDays = (dateStr, days) => {
        if (!dateStr) return false;
        const d = new Date(dateStr);
        if (Number.isNaN(d.getTime())) return false;
        const limit = new Date(now);
        limit.setDate(limit.getDate() + days);
        return d <= limit;
      };
      const modelosActivos = modelos.filter((m) => String(m.estado || "").toLowerCase() !== "presentado");
      const modelosVencen = modelosActivos.filter((m) => inDays(m.proxima_fecha, 30));
      const gestionesActivas = trabajos.filter((t) => {
        const estado = String(t.estado || "").toLowerCase();
        return estado !== "finalizado" && estado !== "cancelado" && estado !== "completado";
      });
      const docsPendientes = docs.filter((d) => String(d.estado || "").toLowerCase() === "pendiente");
      if (gestoriaClienteKpiModelos) gestoriaClienteKpiModelos.textContent = modelosActivos.length;
      if (gestoriaClienteKpiVencen) gestoriaClienteKpiVencen.textContent = modelosVencen.length;
      if (gestoriaClienteKpiGestiones) gestoriaClienteKpiGestiones.textContent = gestionesActivas.length;
      if (gestoriaClienteKpiDocs) gestoriaClienteKpiDocs.textContent = docsPendientes.length;
      if (gestoriaClienteAlerts) {
        const list = document.createElement("div");
        list.className = "inline-list";
        const addAlert = (label, value) => {
          const row = document.createElement("div");
          row.className = "inline-row";
          row.innerHTML = `<div class="muted">${label}</div><div>${value}</div>`;
          list.appendChild(row);
        };
        addAlert("Acciones pendientes", acciones.filter((a) => String(a.estado || "").toLowerCase() === "pendiente").length);
        addAlert("Modelos próximos", modelosVencen.length);
        addAlert("Documentos pendientes", docsPendientes.length);
        gestoriaClienteAlerts.innerHTML = "";
        gestoriaClienteAlerts.appendChild(list);
      }
    }
  );
};

const loadClienteGestoria = (clienteId) => {
  if (!clienteGestoriaForm) return;
  api(`/api/cliente_gestoria?cliente_id=${clienteId}`).then((data) => {
    const row = data.row || {};
    const setValue = (name, value) => {
      const el = clienteGestoriaForm.querySelector(`[name="${name}"]`);
      if (!el) return;
      el.value = value || "";
    };
    const setCheck = (name, value) => {
      const el = clienteGestoriaForm.querySelector(`[name="${name}"]`);
      if (!el) return;
      el.checked = String(value || "0") === "1";
    };
    setValue("tipo_cliente", row.tipo_cliente || "");
    setCheck("mod_fiscal", row.mod_fiscal);
    setCheck("mod_laboral", row.mod_laboral);
    setCheck("mod_contable", row.mod_contable);
    setCheck("mod_renta", row.mod_renta);
    setCheck("mod_registro", row.mod_registro);
    setCheck("mod_trafico", row.mod_trafico);
    setCheck("mod_puntuales", row.mod_puntuales);
    if (gestoriaRentaDetallesForm) {
      const rentaInput = gestoriaRentaDetallesForm.querySelector('[name="renta_detalles"]');
      if (rentaInput) {
        rentaInput.value = row.renta_detalles || "";
      }
    }
    updateGestoriaModuleTabsFromForm();
  });
};

const loadGestoriaModelos = (clienteId) => {
  if (!gestoriaModelosTable) return;
  api(`/api/gestoria_modelos?cliente_id=${clienteId}`).then((data) => {
    const rows = data.rows || [];
    if (!rows.length) {
      gestoriaModelosTable.innerHTML = "<p class='muted'>Sin modelos asignados.</p>";
      return;
    }
    const readonly = state.currentPage === "cliente";
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["modelo", "periodicidad", "proxima_fecha", "responsable", "estado", "notas"]
      .concat(readonly ? [] : ["accion"])
      .forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      ["modelo", "periodicidad", "proxima_fecha", "responsable", "estado", "notas"].forEach((field) => {
        const td = document.createElement("td");
        if (readonly) {
          td.textContent = row[field] || "";
        } else if (field === "periodicidad" || field === "estado") {
          const select = document.createElement("select");
          const options =
            field === "periodicidad"
              ? ["Mensual", "Trimestral", "Anual", "Puntual"]
              : ["Pendiente", "En curso", "Presentado"];
          options.forEach((opt) => select.appendChild(createOption(opt, opt)));
          select.value = row[field] || options[0];
          select.addEventListener("change", () => {
            saveGestoriaModeloField(row.id, field, select.value);
          });
          td.appendChild(select);
        } else {
          const input = document.createElement("input");
          input.value = row[field] || "";
          if (field === "proxima_fecha") {
            input.type = "date";
          }
          input.addEventListener("change", () => {
            saveGestoriaModeloField(row.id, field, input.value);
          });
          td.appendChild(input);
        }
        tr.appendChild(td);
      });
      if (!readonly) {
        const actionTd = document.createElement("td");
        const del = document.createElement("button");
        del.type = "button";
        del.textContent = "Eliminar";
        del.addEventListener("click", () => {
          deleteGestoriaModelo(row.id, clienteId);
        });
        actionTd.appendChild(del);
        tr.appendChild(actionTd);
      }
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    gestoriaModelosTable.innerHTML = "";
    gestoriaModelosTable.appendChild(table);
  });
};

const saveGestoriaModeloField = (id, field, value) => {
  fetch("/api/gestoria_modelos_update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, [field]: value, usuario: getCurrentUser() }),
  });
};

const deleteGestoriaModelo = (id, clienteId) => {
  fetch("/api/gestoria_modelos_delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, usuario: getCurrentUser() }),
  })
    .then((res) => res.json())
    .then(() => {
      loadGestoriaModelos(clienteId);
    });
};

const saveClienteProfesionalField = (id, field, value) => {
  if (clienteProfesionalStatus) {
    clienteProfesionalStatus.textContent = "Guardando...";
  }
  fetch("/api/cliente_profesional_update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, [field]: value }),
  })
    .then((res) => res.json())
    .then((data) => {
      if (clienteProfesionalStatus) {
        clienteProfesionalStatus.textContent = data.error || "Guardado.";
      }
    })
    .catch(() => {
      if (clienteProfesionalStatus) {
        clienteProfesionalStatus.textContent = "Error al guardar.";
      }
    });
};

const deleteClienteProfesional = (id, clienteId) => {
  fetch("/api/cliente_profesional_delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  })
    .then((res) => res.json())
    .then(() => {
      loadClienteProfesional(clienteId);
    });
};

const saveGestoriaTrabajoField = (id, field, value) => {
  fetch("/api/gestoria_trabajos_update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, [field]: value, usuario: getCurrentUser() }),
  });
};

const deleteGestoriaTrabajo = (id) => {
  fetch("/api/gestoria_trabajos_delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, usuario: getCurrentUser() }),
  })
    .then((res) => res.json())
    .then(() => {
      if (state.currentClienteId) {
        loadGestoriaTrabajos(state.currentClienteId);
      }
    });
};

const saveGestoriaDocField = (id, field, value) => {
  fetch("/api/gestoria_docs_update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, [field]: value, usuario: getCurrentUser() }),
  });
};

const deleteGestoriaDoc = (id) => {
  fetch("/api/gestoria_docs_delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, usuario: getCurrentUser() }),
  })
    .then((res) => res.json())
    .then(() => {
      if (state.currentClienteId) {
        loadGestoriaDocs(state.currentClienteId);
      }
    });
};

const saveGestoriaContabilidadField = (id, field, value) => {
  fetch("/api/gestoria_contabilidad_update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, [field]: value }),
  });
};

const deleteGestoriaContabilidad = (id) => {
  fetch("/api/gestoria_contabilidad_delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  })
    .then((res) => res.json())
    .then(() => {
      loadGestoriaContabilidad();
    });
};

const updateCatalogoList = (datalist, rows) => {
  if (!datalist) return;
  datalist.innerHTML = "";
  rows.forEach((row) => {
    const opt = document.createElement("option");
    opt.value = row.codigo;
    opt.textContent = `${row.codigo} · ${row.descripcion}`;
    datalist.appendChild(opt);
  });
};

const loadCatalogo = (tipo, q = "") => {
  return api(`/api/catalogo?tipo=${tipo}&q=${encodeURIComponent(q)}`).then(
    (data) => data.rows || []
  );
};

const setSuggestText = (target, rows) => {
  if (!target) return;
  if (!rows || !rows.length) {
    target.textContent = "";
    return;
  }
  const line = rows
    .slice(0, 3)
    .map((row) => `${row.codigo} · ${row.descripcion}`)
    .join(" | ");
  target.textContent = `Sugerencias: ${line}`;
};

const setupCatalogoInputs = () => {
  const cnaeInput = clienteProfesionalCnaeForm?.querySelector('[name="cnae"]');
  const iaeInput = clienteProfesionalIaeForm?.querySelector('[name="iae"]');
  const actividadInput = clienteProfesionalActividadForm?.querySelector('[name="actividad"]');
  if (cnaeInput) {
    cnaeInput.addEventListener("input", () => {
      const q = cnaeInput.value.trim();
      loadCatalogo("cnae", q).then((rows) => {
        updateCatalogoList(cnaeCatalogo, rows);
        setSuggestText(cnaeSuggest, rows);
      });
    });
    cnaeInput.addEventListener("blur", () => {
      const codigo = cnaeInput.value.trim();
      if (!codigo) return;
      loadCatalogo("cnae", codigo).then((rows) => {
        const exact = rows.find((row) => row.codigo === codigo);
        if (exact && actividadInput && !actividadInput.value.trim()) {
          actividadInput.value = exact.descripcion;
        }
      });
    });
  }
  if (iaeInput) {
    iaeInput.addEventListener("input", () => {
      const q = iaeInput.value.trim();
      loadCatalogo("iae", q).then((rows) => {
        updateCatalogoList(iaeCatalogo, rows);
        setSuggestText(iaeSuggest, rows);
      });
    });
    iaeInput.addEventListener("blur", () => {
      const codigo = iaeInput.value.trim();
      if (!codigo) return;
      loadCatalogo("iae", codigo).then((rows) => {
        const exact = rows.find((row) => row.codigo === codigo);
        if (exact && actividadInput && !actividadInput.value.trim()) {
          actividadInput.value = exact.descripcion;
        }
      });
    });
  }
  if (actividadInput) {
    actividadInput.addEventListener("blur", () => {
      const texto = actividadInput.value.trim();
      if (!texto) return;
      api(`/api/catalogo_match?texto=${encodeURIComponent(texto)}`).then((data) => {
        const cnaeRows = data.cnae || [];
        const iaeRows = data.iae || [];
        setSuggestText(actividadSuggest, [
          ...cnaeRows.map((row) => ({ ...row, codigo: `CNAE ${row.codigo}` })),
          ...iaeRows.map((row) => ({ ...row, codigo: `IAE ${row.codigo}` })),
        ]);
        if (cnaeRows.length === 1 && cnaeInput && !cnaeInput.value.trim()) {
          cnaeInput.value = cnaeRows[0].codigo;
        }
        if (iaeRows.length === 1 && iaeInput && !iaeInput.value.trim()) {
          iaeInput.value = iaeRows[0].codigo;
        }
      });
    });
  }
};

const loadGestoriaFact = () => {
  if (!gestoriaFacturasTable) return;
  gestoriaFacturasTable.innerHTML =
    "<p class='muted'>Sin facturas cargadas. Se integrará en fase 2.</p>";
};

const loadAgendaGeneral = () => {
  if (!agendaGeneral) return;
  const fincas = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
  const fin = state.empresas.find((e) => e.nombre === FIN_COMPANY);
  const tasks = [];
  if (fincas) {
    tasks.push(api(`/api/acciones?servicio=gestoria&empresa_id=${fincas.id}`));
    tasks.push(api(`/api/acciones?servicio=seguros&empresa_id=${fincas.id}`));
  }
  if (fin) {
    tasks.push(api(`/api/acciones?servicio=financiaciones&empresa_id=${fin.id}`));
  }
  if (!tasks.length) {
    agendaGeneral.innerHTML = "<p class='muted'>Sin empresas cargadas.</p>";
    return;
  }
  agendaGeneral.dataset.readonly = "1";
  Promise.all(tasks).then((responses) => {
    const allRows = responses.flatMap((data) => data.rows || []);
    const events = buildAgendaEvents(allRows, "", "");
    renderAgendaCalendar(agendaGeneral, events, "Agenda general");
  });
};

const loadClienteSeguros = (cliente, empresaId) => {
  if (!clienteSegurosFicha) {
    return;
  }
  if (!empresaId) {
    clienteSegurosFicha.innerHTML = "<p class='muted'>Sin empresa de seguros.</p>";
    return;
  }
  const params = new URLSearchParams({ tabla: "seguros", empresa_id: empresaId });
  api(`/api/tabla?${params.toString()}`).then((data) => {
    const columns = data.columns || [];
    const rows = data.rows || [];
    const tomadorIndex = columns.indexOf("tomador");
    const companiaIndex = columns.indexOf("compania");
    const polizaIndex = columns.indexOf("poliza_numero");
    const efectoIndex = columns.indexOf("fecha_efecto");
    const vencIndex = columns.indexOf("fecha_vencimiento");
    const estadoIndex = columns.indexOf("estado");
    const primaIndex = columns.indexOf("prima_total");
    const target = normalizeName(cliente.nombre || "");
    const matches = rows.filter((row) => {
      const tomador = normalizeName(row[tomadorIndex] || "");
      return tomador && (tomador === target || tomador.includes(target));
    });
    if (!matches.length) {
      clienteSegurosFicha.innerHTML = "<p class='muted'>Sin pólizas vinculadas.</p>";
      return;
    }
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trHead = document.createElement("tr");
    ["poliza", "compania", "efecto", "vencimiento", "estado", "prima"].forEach((col) => {
      const th = document.createElement("th");
      th.textContent = formatHeader(col);
      trHead.appendChild(th);
    });
    thead.appendChild(trHead);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    matches.forEach((row) => {
      const tr = document.createElement("tr");
      const values = [
        row[polizaIndex] || "-",
        row[companiaIndex] || "-",
        row[efectoIndex] || "-",
        row[vencIndex] || "-",
        row[estadoIndex] || "-",
        row[primaIndex] ? euroFormatter.format(Number(row[primaIndex]) || 0) : "-",
      ];
      const cols = ["poliza", "compania", "efecto", "vencimiento", "estado", "prima"];
      values.forEach((value, idx) => {
        const td = document.createElement("td");
        if (!applyCompanyCell(td, cols[idx], value, { compact: true })) {
          td.textContent = value;
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    clienteSegurosFicha.innerHTML = "";
    clienteSegurosFicha.appendChild(table);
  });
};

const openClienteDetail = (id) => {
  if (!clientesDetail) {
    return;
  }
  state.prevPage = state.currentPage;
  state.prevModule = state.currentModule;
  state.prevTab = currentTab;
  state.currentClienteId = id;
  setPage("cliente");
  updateTableVisibility();
  setUrlParams(new URLSearchParams({ cliente: id }));
  api(`/api/cliente?id=${id}`).then((data) => {
    if (data.error) {
      if (clienteDetailSubtitle) {
        clienteDetailSubtitle.textContent = data.error;
      }
      return;
    }
    const cliente = data.cliente || {};
    const fincasEmpresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
    const fincasEmpresaId = fincasEmpresa ? fincasEmpresa.id : "";
    if (clienteDetailTitle) {
      clienteDetailTitle.textContent = formatNombreCliente(cliente.nombre || "Ficha de cliente");
    }
    if (clienteDetailSubtitle) {
      clienteDetailSubtitle.textContent = "Información general y asignaciones.";
    }
    if (clienteDetailGrid) {
      const nombreCompleto = cliente.nombre || "";
      const split = splitNombreApellidos(nombreCompleto, cliente.tipo_persona);
      const clienteData = {
        ...cliente,
        nombre: split.nombre || cliente.nombre || "",
        apellidos: split.apellidos || "",
      };
      renderEditableGrid(clienteDetailGrid, CLIENTE_FIELDS, clienteData, "cliente");
    }
    let hasGestoria = false;
    let hasSeguros = false;
    let hasInmo = false;
    let hasHipotecas = false;
    if (clienteEmpresasList) {
      const empresas = data.empresas || [];
      const serviceSet = new Set(
        empresas.map((row) => (row.servicio || "").toLowerCase())
      );
      hasGestoria = serviceSet.has("gestoría");
      hasSeguros = serviceSet.has("seguros");
      hasInmo = serviceSet.has("inmobiliaria");
      hasHipotecas = serviceSet.has("hipotecas");
      if (!empresas.length) {
        clienteEmpresasList.innerHTML = "<p class='muted'>Sin empresas asignadas.</p>";
      } else {
        const table = document.createElement("table");
        const thead = document.createElement("thead");
        const trHead = document.createElement("tr");
        ["empresa", "servicio", "estado", "fecha_inicio", "fecha_fin", "accion"].forEach((col) => {
          const th = document.createElement("th");
          th.textContent = formatHeader(col);
          trHead.appendChild(th);
        });
        thead.appendChild(trHead);
        table.appendChild(thead);
        const tbody = document.createElement("tbody");
        empresas.forEach((row) => {
          const tr = document.createElement("tr");
          const empresaTd = document.createElement("td");
          empresaTd.textContent = row.empresa || "-";
          tr.appendChild(empresaTd);

          const servicioTd = document.createElement("td");
          const servicioSelect = document.createElement("select");
          servicioSelect.classList.add("inline-input");
          populateServiciosSelect(servicioSelect, row.servicio || "");
          servicioSelect.addEventListener("change", () => {
            saveClienteEmpresaField(row.rel_id, "servicio", servicioSelect.value);
          });
          servicioTd.appendChild(servicioSelect);
          tr.appendChild(servicioTd);

          const estadoTd = document.createElement("td");
          const estadoInput = document.createElement("input");
          estadoInput.value = row.estado || "";
          estadoInput.classList.add("inline-input");
          estadoInput.addEventListener("change", () => {
            saveClienteEmpresaField(row.rel_id, "estado", estadoInput.value);
          });
          estadoTd.appendChild(estadoInput);
          tr.appendChild(estadoTd);

          const inicioTd = document.createElement("td");
          const inicioInput = document.createElement("input");
          inicioInput.type = "date";
          inicioInput.value = row.fecha_inicio || "";
          inicioInput.classList.add("inline-input");
          inicioInput.addEventListener("change", () => {
            saveClienteEmpresaField(row.rel_id, "fecha_inicio", inicioInput.value);
          });
          inicioTd.appendChild(inicioInput);
          tr.appendChild(inicioTd);

          const finTd = document.createElement("td");
          const finInput = document.createElement("input");
          finInput.type = "date";
          finInput.value = row.fecha_fin || "";
          finInput.classList.add("inline-input");
          finInput.addEventListener("change", () => {
            saveClienteEmpresaField(row.rel_id, "fecha_fin", finInput.value);
          });
          finTd.appendChild(finInput);
          tr.appendChild(finTd);

          const actionTd = document.createElement("td");
          const actionBtn = document.createElement("button");
          actionBtn.type = "button";
          actionBtn.textContent = "Abrir CRM";
          actionBtn.addEventListener("click", () => {
            const servicio = servicioSelect.value;
            openServiceCrm(servicio);
          });
          actionTd.appendChild(actionBtn);
          tr.appendChild(actionTd);

          tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        clienteEmpresasList.innerHTML = "";
        clienteEmpresasList.appendChild(table);
      }
    }
    if (clienteAssignServicio) {
      populateServiciosSelect(clienteAssignServicio);
    }
    if (clienteAssignEmpresa) {
      populateEmpresasSelect(clienteAssignEmpresa);
    }
    if (clienteFacturas) {
      clienteFacturas.innerHTML = "<p class='muted'>Sin facturas registradas.</p>";
    }
    if (clienteTrabajos) {
      clienteTrabajos.innerHTML = "<p class='muted'>Sin trabajos registrados.</p>";
    }
    if (clienteProfesionalHint) {
      clienteProfesionalHint.textContent = hasGestoria
        ? "Gestiona CNAE, IAE, actividad e IBAN."
        : "Asigna el cliente a Gestoría para activar estos datos.";
    }
    if (clienteProfesionalSection) {
      clienteProfesionalSection.classList.toggle("hidden", !hasGestoria);
    }
    if (clienteGestoriaForm) {
      clienteGestoriaForm.classList.toggle("hidden", !hasGestoria);
    }
    if (gestoriaModeloForm) {
      gestoriaModeloForm.classList.toggle("hidden", !hasGestoria);
    }
    if (gestoriaTrabajoForm) {
      gestoriaTrabajoForm.classList.toggle("hidden", !hasGestoria);
    }
    if (gestoriaDocForm) {
      gestoriaDocForm.classList.toggle("hidden", !hasGestoria);
    }
    if (gestoriaClienteAgendaForm) {
      gestoriaClienteAgendaForm.classList.toggle("hidden", !hasGestoria);
    }
    if (clienteTabs) {
      const gestoriaTab = clienteTabs.querySelector('[data-tab="profesional"]');
      const segurosTab = clienteTabs.querySelector('[data-tab="seguros"]');
      const inmoTab = clienteTabs.querySelector('[data-tab="inmobiliaria"]');
      const hipotecasTab = clienteTabs.querySelector('[data-tab="hipotecas"]');
      if (gestoriaTab) gestoriaTab.classList.toggle("hidden", !hasGestoria);
      if (segurosTab) segurosTab.classList.toggle("hidden", !hasSeguros);
      if (inmoTab) inmoTab.classList.toggle("hidden", !hasInmo);
      if (hipotecasTab) hipotecasTab.classList.toggle("hidden", !hasHipotecas);
    }
    if (clienteTabSeguros) {
      clienteTabSeguros.classList.toggle("hidden", !hasSeguros);
    }
    if (clienteTabInmobiliaria) {
      clienteTabInmobiliaria.classList.toggle("hidden", !hasInmo);
    }
    if (clienteTabHipotecas) {
      clienteTabHipotecas.classList.toggle("hidden", !hasHipotecas);
    }
    if (clienteProfesionalList) {
      if (hasGestoria) {
        loadClienteProfesional(id);
      } else {
        clienteProfesionalList.innerHTML = "<p class='muted'>Sin datos profesionales.</p>";
      }
    }
    if (hasGestoria) {
      loadClienteGestoria(id);
      loadGestoriaClienteDashboard(id);
      loadGestoriaModelos(id);
      loadGestoriaTrabajos(id);
      loadGestoriaDocs(id);
      loadGestoriaClienteAgenda(id);
      loadGestoriaContaConfig(id);
    } else {
      if (gestoriaModelosTable) {
        gestoriaModelosTable.innerHTML = "<p class='muted'>Sin modelos asignados.</p>";
      }
      if (gestoriaTrabajosTable) {
        gestoriaTrabajosTable.innerHTML = "<p class='muted'>Sin trabajos puntuales.</p>";
      }
      if (gestoriaDocsTable) {
        gestoriaDocsTable.innerHTML = "<p class='muted'>Sin documentación registrada.</p>";
      }
      if (gestoriaClienteAgendaTable) {
        gestoriaClienteAgendaTable.innerHTML = "<p class='muted'>Sin acciones.</p>";
      }
      if (gestoriaClienteAgendaInfo) {
        gestoriaClienteAgendaInfo.textContent = "";
      }
    }
    if (hasSeguros) {
      loadClienteSeguros(cliente, fincasEmpresaId);
    } else if (clienteSegurosFicha) {
      clienteSegurosFicha.innerHTML = "<p class='muted'>Sin pólizas vinculadas.</p>";
    }
    clientesDetail.classList.remove("hidden");
    const defaultTab = hasInmo
      ? "inmobiliaria"
      : hasGestoria
        ? "profesional"
        : hasSeguros
          ? "seguros"
          : hasHipotecas
            ? "hipotecas"
            : "datos";
    setClienteTab(defaultTab);
    window.scrollTo({ top: clientesDetail.offsetTop - 120, behavior: "smooth" });
  });
};

const closeClienteDetail = () => {
  state.currentClienteId = "";
  const returnPage = state.prevPage || "empresa";
  const returnModule = state.prevModule || "clientes";
  const returnTab = state.prevTab || "bdt";
  setModule(returnModule);
  setTab(returnTab);
  setPage(returnPage);
  updateTableVisibility();
  if (returnPage === "empresa") {
    explorerSection.classList.remove("hidden");
  }
  setUrlParams(
    returnModule === "clientes" ? new URLSearchParams({ clientes: "1" }) : new URLSearchParams()
  );
};

const loadTable = () => {
  const requestModule = state.currentModule;
  const requestTab = currentTab;
  if (state.currentModule === "clientes") {
    loadClientesTable();
    return;
  }
  if (currentTab === "crm") {
    loadCrmInmuebles();
    return;
  }
  const empresaId = empresaSelect.value || "";
  const selectedCompany = state.currentEmpresaName || state.empresas.find((e) => e.id === empresaId)?.nombre;
  let tabla =
    tablaSelect.value ||
    (currentTab === "bdt"
      ? (selectedCompany === FIN_COMPANY ? "hipotecas" : "movimientos")
      : state.tablas.find((t) => t !== "movimientos"));
  if (currentTab === "bdt" && selectedCompany === FIN_COMPANY) {
    tabla = "hipotecas";
    tablaSelect.value = "hipotecas";
  }
  if (currentTab === "operativa" && tabla === "movimientos") {
    tabla = state.tablas.find((t) => t !== "movimientos");
    tablaSelect.value = tabla;
  }
  const q = searchInput.value.trim();
  const showActions =
    currentTab === "bdt" &&
    selectedCompany === FIN_COMPANY &&
    tabla === "hipotecas";
  const isFincasEditable =
    currentTab === "bdt" &&
    selectedCompany === FINCAS_COMPANY &&
    (tabla === "seguros" || tabla === "gestoria");
  const params = new URLSearchParams({
    tabla,
    empresa_id: empresaId,
    q,
  });
  if (
    currentTab === "bdt" &&
    selectedCompany === DASHBOARD_COMPANY &&
    tabla === "movimientos"
  ) {
    const currentYear = String(new Date().getFullYear());
    const yearValue = bdtYearFilter?.value || currentYear;
    params.set("year", yearValue);
    if (bdtFieldFilter?.value) {
      params.set("field", bdtFieldFilter.value);
    }
  }
  if (showActions) {
    params.set("include_id", "1");
  }
  if (isFincasEditable) {
    params.set("include_id", "1");
  }
  api(`/api/tabla?${params.toString()}`).then((data) => {
    if (state.currentModule !== requestModule || currentTab !== requestTab) {
      return;
    }
    renderTable(data, { showActions, editableTable: isFincasEditable ? tabla : null });
    const baseText = `Mostrando ${data.rows.length} filas de ${TABLE_LABELS[tabla] || tabla}.`;
    tableInfo.textContent = baseText;
    tableInfo.dataset.baseText = baseText;
    const empresaName = state.empresas.find((e) => e.id === empresaId)?.nombre;
    if (currentTab === "operativa") {
      renderDashboard(empresaName, empresaId);
    }
    updateTableVisibility();
  });
};

const init = async () => {
  try {
  const results = await Promise.allSettled([
    api("/api/empresas"),
    api("/api/tablas"),
    api("/api/resumen"),
  ]);

    const empresas = results[0].status === "fulfilled" ? results[0].value : [];
    const tablas = results[1].status === "fulfilled" ? results[1].value : [];
    const resumen = results[2].status === "fulfilled" ? results[2].value : [];

    state.empresas = empresas;
    state.tablas = tablas;
    state.resumen = resumen;

    empresaSelect.appendChild(createOption("", "Todas las empresas"));
    empresas.forEach((empresa) => {
      empresaSelect.appendChild(createOption(empresa.id, empresa.nombre));
    });

    populateTables();

    const safe = (promise) => promise.catch(() => null);
    await safe(loadHomeDashboard());
    await safe(loadHomeHipotecaStats());
    await safe(loadHomeFincasStats(yearSelect?.value));
    await safe(loadClientesStats());
    const clientes = (await safe(loadClientesList())) || [];
    renderClientesSelects(clientes);
    populateGestoriaClientes();
    populateAgendaClientes(segurosAgendaClientes, segurosAgendaClienteInput, segurosAgendaClienteId);
    populateAgendaClientes(gestoriaAgendaClientes, gestoriaAgendaClienteInput, gestoriaAgendaClienteId);
    populateAgendaClientes(finAgendaClientes, finAgendaClienteInput, finAgendaClienteId);
    populateAgendaClientes(actionModalClientes, actionModalClienteInput, actionModalClienteId);
    populateAgendaClientes(segurosCrmClientes, segurosCrmClienteInput, segurosCrmClienteId);
    populateAgendaClientes(gestoriaCrmClientes, gestoriaCrmSearch, null);
    populateAgendaClientes(finCrmClientes, finCrmClienteInput, finCrmClienteId);
    populateClientesSelect(gestoriaContabilidadCliente);
    populateServiciosSelect(clientesServicioSelect);
    refreshClientesAltaSelects();
    await safe(loadUsuarios());
    renderUsuariosSelect();
    renderUsuariosTable();
    initFinSimulator();
    setGestoriaCrmTab(state.gestoriaCrmTab || "autonomo");
    initSegurosTabs();
    await safe(loadFincasRenewalAlert());
    setupCatalogoInputs();
    renderCompanyCards();
    loadTable();
    updateTableVisibility();
    handleRoute();
    const okCount = results.filter((r) => r.status === "fulfilled").length;
    dbStatus.innerHTML = okCount === 3
      ? `<span class="status"><span></span>Conectado</span>`
      : `<span class="status"><span></span>Con datos parciales</span>`;
  } catch (error) {
    dbStatus.textContent = "No se pudo conectar a la base de datos.";
    tableContainer.innerHTML =
      "<p class='muted'>Error al cargar los datos.</p>";
    renderCompanyCards();
  }
};

applyBtn.addEventListener("click", loadTable);
resetBtn.addEventListener("click", () => {
  empresaSelect.value = "";
  searchInput.value = "";
  if (state.currentModule === "clientes") {
    state.clientesShowAll = false;
    if (clientesAltaSection) {
      clientesAltaSection.dataset.mode = "list";
      clientesAltaSection.classList.add("hidden");
    }
    updateExplorerHeader("Clientes");
    setTab("bdt");
    loadClientesTable();
    updateTableVisibility();
    return;
  }
  setTab("operativa");
  updateExplorerHeader("");
  renderDashboard("", "");
  explorerSection.classList.add("hidden");
  updateTableVisibility();
  loadTable();
});

if (bdtYearFilter) {
  bdtYearFilter.addEventListener("change", loadTable);
}

if (bdtFieldFilter) {
  bdtFieldFilter.addEventListener("change", loadTable);
}

if (tablaSelect) {
  tablaSelect.addEventListener("change", () => {
    updateBdtFiltersVisibility();
    loadTable();
  });
}

homeBtn.addEventListener("click", () => {
  goHome();
});

brandHome.addEventListener("click", () => {
  goHome();
});

if (coreCards) {
  coreCards.addEventListener("click", (event) => {
    const target = event.target.closest("[data-action]");
    if (!target || !coreCards.contains(target)) {
      return;
    }
    if (target.tagName === "A") {
      event.preventDefault();
    }
    const action = target.dataset.action;
    if (action === "holding") {
      openHolding();
    } else if (action === "crm-inmo") {
      openCrmInmobiliario();
    } else if (action === "crm-gestoria") {
      openGestoriaCrm();
    } else if (action === "crm-seguros") {
      openSegurosCrm();
    } else if (action === "crm-fin") {
      openFinCrm();
    } else if (action === "clientes") {
      openClientesModule();
    } else if (action === "agenda") {
      openAgenda();
    } else if (action === "admin") {
      openAdmin();
    }
  });
}

viewTabs.addEventListener("click", (event) => {
  const btn = event.target.closest(".tab");
  if (!btn) return;
  setTab(btn.dataset.tab);
  if (state.currentModule === "clientes") {
    loadClientesTable();
    updateTableVisibility();
    return;
  }
  if (currentTab === "crm") {
    loadCrmInmuebles();
    updateTableVisibility();
    return;
  }
  if (currentTab === "gestoria-crm") {
    loadGestoriaCrm();
    updateTableVisibility();
    return;
  }
  if (currentTab === "gestoria-dash") {
    loadGestoriaDashboard();
    updateTableVisibility();
    return;
  }
  if (currentTab === "gestoria-conta") {
    loadGestoriaContabilidad();
    loadGestoriaContaQueue();
    updateTableVisibility();
    return;
  }
  if (currentTab === "gestoria-agenda") {
    const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
    if (empresa) {
      loadAcciones("gestoria", empresa.id, gestoriaAgendaTable, gestoriaAgendaInfo);
    }
    updateTableVisibility();
    return;
  }
  if (currentTab === "gestoria-fact") {
    loadGestoriaFact();
    updateTableVisibility();
    return;
  }
  if (currentTab === "seguros-crm") {
    loadSegurosCrm();
    updateTableVisibility();
    return;
  }
  if (currentTab === "fin-crm") {
    loadFinCrm();
    updateTableVisibility();
    return;
  }
  if (currentTab === "operativa") {
    const resumenItem = state.resumen.find(
      (item) => item.empresa === state.empresas.find((e) => e.id === empresaSelect.value)?.nombre
    );
    setDefaultTableForCompany(resumenItem);
    ensureOperativaTable();
  } else {
    tablaSelect.value = "movimientos";
  }
  loadTable();
  updateTableVisibility();
});

if (fincasBdtTabs) {
  fincasBdtTabs.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-table]");
    if (!btn) return;
    tablaSelect.value = btn.dataset.table;
    updateFincasBdtTabs();
    loadTable();
  });
}

if (estudioAltaTabs) {
  estudioAltaTabs.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-section]");
    if (!btn) return;
    if (altaSection) {
      altaSection.dataset.estudioActive = btn.dataset.section;
    }
    updateEstudioAltaTabs();
  });
}

if (crmNuevaCaptacionBtn) {
  crmNuevaCaptacionBtn.addEventListener("click", () => {
    if (altaSection) {
      altaSection.dataset.estudioActive = "captacion";
    }
    setTab("alta");
    updateEstudioAltaTabs();
  });
}

if (crmNuevaDemandaBtn) {
  crmNuevaDemandaBtn.addEventListener("click", () => {
    if (altaSection) {
      altaSection.dataset.estudioActive = "demanda";
    }
    setTab("alta");
    updateEstudioAltaTabs();
  });
}

if (crmEtapaFilter) {
  crmEtapaFilter.addEventListener("change", () => {
    loadCrmCaptaciones();
  });
}

if (crmInmuebleSearch) {
  crmInmuebleSearch.addEventListener("input", () => {
    scheduleSave("crm-inmuebles-search", () => {
      loadCrmInmuebles();
    }, 300);
  });
}

if (gestoriaCrmSearch) {
  const triggerGestoriaSearch = () => {
    scheduleSave("gestoria-crm-search", () => {
      loadGestoriaCrm();
    }, 250);
  };
  gestoriaCrmSearch.addEventListener("input", triggerGestoriaSearch);
  gestoriaCrmSearch.addEventListener("change", triggerGestoriaSearch);
  gestoriaCrmSearch.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      loadGestoriaCrm();
    }
  });
}
if (gestoriaCrmTipo) {
  gestoriaCrmTipo.addEventListener("change", () => {
    populateGestoriaSubtipos(gestoriaCrmTipo.value);
    loadGestoriaCrm();
  });
}
if (gestoriaCrmSubtipo) {
  gestoriaCrmSubtipo.addEventListener("change", () => {
    loadGestoriaCrm();
  });
}
if (gestoriaCrmApply) {
  gestoriaCrmApply.addEventListener("click", () => {
    loadGestoriaCrm();
  });
}
if (clientesEstadoFilter) {
  clientesEstadoFilter.addEventListener("change", () => {
    if (state.currentModule === "clientes") {
      loadClientesTable();
    }
  });
}
if (gestoriaCrmReset) {
  gestoriaCrmReset.addEventListener("click", () => {
    if (gestoriaCrmSearch) gestoriaCrmSearch.value = "";
    if (gestoriaCrmTipo) gestoriaCrmTipo.value = "";
    if (gestoriaCrmSubtipo) {
      gestoriaCrmSubtipo.value = "";
      populateGestoriaSubtipos("");
    }
    if (gestoriaCrmEstado) gestoriaCrmEstado.value = "";
    if (gestoriaCrmLimit) gestoriaCrmLimit.value = "50";
    gestoriaCrmTable.innerHTML = "<p class='muted'>Usa los filtros para cargar clientes.</p>";
    if (gestoriaCrmSummary) {
      gestoriaCrmSummary.innerHTML = "<p class='muted'>Usa los filtros para cargar clientes.</p>";
    }
    gestoriaCrmInfo.textContent = "";
    setGestoriaCrmTab("all");
  });
}

if (gestoriaCrmToggleView) {
  gestoriaCrmToggleView.addEventListener("click", () => {
    state.gestoriaCrmFull = !state.gestoriaCrmFull;
    loadGestoriaCrm();
  });
}

if (gestoriaTrabajosTipoFilter) {
  gestoriaTrabajosTipoFilter.addEventListener("change", loadGestoriaTrabajosOverview);
}
if (gestoriaTrabajosEstadoFilter) {
  gestoriaTrabajosEstadoFilter.addEventListener("change", loadGestoriaTrabajosOverview);
}
if (gestoriaTrabajosLimit) {
  gestoriaTrabajosLimit.addEventListener("change", loadGestoriaTrabajosOverview);
}
if (gestoriaPipelineServicio) {
  gestoriaPipelineServicio.addEventListener("change", loadGestoriaPipeline);
}
if (gestoriaPipelineGroup) {
  gestoriaPipelineGroup.addEventListener("change", loadGestoriaPipeline);
}
if (gestoriaAlertDays) {
  gestoriaAlertDays.addEventListener("change", loadGestoriaDashboard);
}

if (gestoriaCrmTabs) {
  gestoriaCrmTabs.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-gestoria-tab]");
    if (!btn) return;
    if (gestoriaCrmSearch) gestoriaCrmSearch.value = "";
    if (gestoriaCrmEstado) gestoriaCrmEstado.value = "";
    if (gestoriaCrmLimit) gestoriaCrmLimit.value = "50";
    setGestoriaCrmTab(btn.dataset.gestoriaTab);
    loadGestoriaCrm();
  });
}

if (gestoriaCrmViews) {
  gestoriaCrmViews.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-gestoria-view]");
    if (!btn) return;
    setGestoriaCrmView(btn.dataset.gestoriaView || "crm");
  });
}

if (actionModalClose) {
  actionModalClose.addEventListener("click", () => {
    closeActionEditor();
  });
}

if (actionModalServicioSelect) {
  actionModalServicioSelect.addEventListener("change", () => {
    populateActionModalResponsables(actionModalServicioSelect.value || "");
  });
}

if (actionModalSave) {
  actionModalSave.addEventListener("click", () => {
    if (actionModalStatus) actionModalStatus.textContent = "Guardando...";
    const serviceValue = actionModalServicioSelect ? actionModalServicioSelect.value : "";
    const service = serviceValue || "gestoria";
    if (!serviceValue) {
      if (actionModalStatus) actionModalStatus.textContent = "Selecciona servicio.";
      return;
    }
    const empresaNombre =
      service === "financiaciones" ? FIN_COMPANY : FINCAS_COMPANY;
    const clienteData = resolveClienteFromInput(actionModalClienteInput, actionModalClienteId);
    const payload = {
      id: currentActionEdit ? currentActionEdit.id : undefined,
      fecha: actionModalFecha ? actionModalFecha.value : currentActionEdit?.dateKey,
      hora: actionModalHora ? actionModalHora.value : currentActionEdit?.time,
      tipo: actionModalTipo ? actionModalTipo.value.trim() : currentActionEdit?.tipo,
      responsable: actionModalResponsable ? actionModalResponsable.value : currentActionEdit?.responsable,
      estado: actionModalEstado ? actionModalEstado.value : currentActionEdit?.estado,
      notas: actionModalNotas ? actionModalNotas.value.trim() : currentActionEdit?.notas,
      recordatorio_min: actionModalRecordatorio ? actionModalRecordatorio.value : currentActionEdit?.recordatorio_min,
      servicio: service,
      empresa_nombre: empresaNombre,
      cliente_id: clienteData.cliente_id,
      cliente_nombre: clienteData.cliente_nombre,
    };
    const conflict = lastAgendaEvents.find((ev) => {
      if (currentActionEdit && ev.id === currentActionEdit.id) return false;
      if (!ev.dateKey || !payload.fecha) return false;
      if (ev.dateKey !== payload.fecha) return false;
      if (!payload.hora || !ev.time) return false;
      if (ev.time !== payload.hora) return false;
      if (payload.responsable && ev.responsable && ev.responsable === payload.responsable) {
        return true;
      }
      return false;
    });
    if (conflict) {
      const ok = window.confirm(
        "Existe otra cita con el mismo responsable y hora. ¿Quieres guardarla igualmente?"
      );
      if (!ok) {
        if (actionModalStatus) actionModalStatus.textContent = "Cancelado.";
        return;
      }
    }
    const endpoint = currentActionEdit ? "/api/acciones_update" : "/api/acciones";
    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (actionModalStatus) actionModalStatus.textContent = data.error;
          return;
        }
        if (actionModalStatus) actionModalStatus.textContent = "Guardado.";
        closeActionEditor();
        loadAgendaGeneral();
        const fincas = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
        const fin = state.empresas.find((e) => e.nombre === FIN_COMPANY);
        if (fincas) {
          loadAcciones("gestoria", fincas.id, gestoriaAgendaTable, gestoriaAgendaInfo);
          loadAcciones("seguros", fincas.id, segurosAgendaTable, segurosAgendaInfo);
        }
        if (fin) {
          loadAcciones("financiaciones", fin.id, finAgendaTable, finAgendaInfo);
        }
        if (state.currentClienteId) {
          loadGestoriaClienteAgenda(state.currentClienteId);
        }
      })
      .catch(() => {
        if (actionModalStatus) actionModalStatus.textContent = "Error al guardar.";
      });
  });
}

if (actionModalOpenCliente) {
  actionModalOpenCliente.addEventListener("click", () => {
    if (currentActionEdit && currentActionEdit.cliente_id) {
      closeActionEditor();
      openClienteDetail(currentActionEdit.cliente_id);
    }
  });
}

if (actionModalServicioSelect) {
  actionModalServicioSelect.addEventListener("change", () => {
    if (!actionModalResponsable) return;
    const filter = normalizeSimple(actionModalServicioSelect.value);
    const users = state.usersList || [];
    actionModalResponsable.innerHTML = "";
    actionModalResponsable.appendChild(createOption("", "Selecciona responsable"));
    users
      .filter((user) => {
        if (!filter) return true;
        const service = normalizeSimple(user.servicio || "");
        if (!service) return true;
        if (service.includes(filter)) return true;
        if (["direccion", "administracion"].includes(service)) return true;
        return false;
      })
      .forEach((user) => {
        const label = `${user.nombre || ""} ${user.apellido || ""}`.trim();
        const value = user.usuario || label || user.nombre || "";
        if (!value) return;
        actionModalResponsable.appendChild(createOption(value, label || value));
      });
  });
}

if (clientesColumnsBtn) {
  clientesColumnsBtn.addEventListener("click", () => {
    if (!clientesColumnsPanel) return;
    clientesColumnsPanel.classList.toggle("hidden");
    renderClientesColumnsPicker();
  });
}
if (clientesShowAllBtn) {
  clientesShowAllBtn.addEventListener("click", () => {
    state.clientesShowAll = true;
    loadClientesTable();
  });
}

if (segurosCrmSearch) {
  segurosCrmSearch.addEventListener("input", () => {
    scheduleSave("seguros-crm-search", () => {
      loadSegurosCrm();
    }, 300);
  });
}

if (segurosOfertasSearch) {
  segurosOfertasSearch.addEventListener("input", () => {
    scheduleSave("seguros-ofertas-search", () => {
      loadSegurosOfertas();
    }, 200);
  });
}

if (segurosReferidosSearch) {
  segurosReferidosSearch.addEventListener("input", () => {
    scheduleSave("seguros-referidos-search", () => {
      loadSegurosReferidos();
    }, 200);
  });
}

if (segurosCampanasSearch) {
  segurosCampanasSearch.addEventListener("input", () => {
    scheduleSave("seguros-campanas-search", () => {
      loadSegurosCampanas();
    }, 200);
  });
}

if (segurosComisionesSearch) {
  segurosComisionesSearch.addEventListener("input", () => {
    scheduleSave("seguros-comisiones-search", () => {
      loadSegurosComisiones();
    }, 200);
  });
}

if (segurosCrmClienteOpen) {
  segurosCrmClienteOpen.addEventListener("click", () => {
    const clienteData = resolveClienteFromInput(segurosCrmClienteInput, segurosCrmClienteId);
    if (clienteData.cliente_id) {
      openClienteDetail(clienteData.cliente_id);
    } else if (segurosCrmClienteInput) {
      segurosCrmClienteInput.focus();
    }
  });
}

if (segurosCrmClienteInput) {
  segurosCrmClienteInput.addEventListener("change", () => {
    loadSegurosCrm();
  });
}

if (segurosChecklistPoliza) {
  segurosChecklistPoliza.addEventListener("change", () => {
    loadSegurosChecklist(segurosChecklistPoliza.value);
  });
}

if (segurosChecklistGenerate) {
  segurosChecklistGenerate.addEventListener("click", () => {
    const polizaId = segurosChecklistPoliza ? segurosChecklistPoliza.value : "";
    if (!polizaId) {
      if (segurosChecklistInfo) segurosChecklistInfo.textContent = "Selecciona una póliza.";
      return;
    }
    fetch("/api/seguros_checklist_generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ poliza_id: polizaId }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (segurosChecklistInfo) segurosChecklistInfo.textContent = data.error;
          return;
        }
        loadSegurosChecklist(polizaId);
      })
      .catch(() => {
        if (segurosChecklistInfo) segurosChecklistInfo.textContent = "Error al generar.";
      });
  });
}

if (segurosAiRun) {
  segurosAiRun.addEventListener("click", () => {
    if (segurosAiStatus) segurosAiStatus.textContent = "";
    if (segurosAiOutput) segurosAiOutput.value = "";
    const polizaId = segurosAiPoliza ? segurosAiPoliza.value : "";
    const task = segurosAiTask ? segurosAiTask.value : "resumen";
    if (!polizaId) {
      if (segurosAiStatus) segurosAiStatus.textContent = "Selecciona una póliza.";
      return;
    }
    if (segurosAiStatus) segurosAiStatus.textContent = "Generando...";
    fetch("/api/ai_seguros_copilot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        poliza_id: polizaId,
        task,
        extra: segurosAiExtra ? segurosAiExtra.value.trim() : "",
      }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (segurosAiStatus) segurosAiStatus.textContent = data.error;
          return;
        }
        if (segurosAiStatus) segurosAiStatus.textContent = "Listo.";
        if (segurosAiOutput) segurosAiOutput.value = data.output || "";
      })
      .catch(() => {
        if (segurosAiStatus) segurosAiStatus.textContent = "Error al generar.";
      });
  });
}

if (segurosPreferenciasClienteInput) {
  segurosPreferenciasClienteInput.addEventListener("change", () => {
    const clienteData = resolveClienteFromInput(
      segurosPreferenciasClienteInput,
      segurosPreferenciasClienteId
    );
    if (clienteData.cliente_id) {
      loadSegurosPreferencias(clienteData.cliente_id);
    }
  });
}

if (segurosPreferenciasForm) {
  segurosPreferenciasForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const clienteData = resolveClienteFromInput(
      segurosPreferenciasClienteInput,
      segurosPreferenciasClienteId
    );
    if (!clienteData.cliente_id) {
      if (segurosPreferenciasStatus) {
        segurosPreferenciasStatus.textContent = "Selecciona un cliente.";
      }
      return;
    }
    const formData = new FormData(segurosPreferenciasForm);
    const payload = Object.fromEntries(formData.entries());
    payload.cliente_id = clienteData.cliente_id;
    if (segurosPreferenciasStatus) {
      segurosPreferenciasStatus.textContent = "Guardando...";
    }
    fetch("/api/seguros_preferencias", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (segurosPreferenciasStatus) {
          segurosPreferenciasStatus.textContent = data.error || "Guardado.";
        }
      })
      .catch(() => {
        if (segurosPreferenciasStatus) {
          segurosPreferenciasStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (segurosOfertasForm) {
  segurosOfertasForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const clienteData = resolveClienteFromInput(
      segurosOfertasClienteInput,
      segurosOfertasClienteId
    );
    if (!clienteData.cliente_id) {
      if (segurosOfertasStatus) {
        segurosOfertasStatus.textContent = "Selecciona un cliente.";
      }
      return;
    }
    const formData = new FormData(segurosOfertasForm);
    const payload = Object.fromEntries(formData.entries());
    payload.cliente_id = clienteData.cliente_id;
    if (segurosOfertasStatus) {
      segurosOfertasStatus.textContent = "Guardando...";
    }
    fetch("/api/seguros_ofertas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (segurosOfertasStatus) {
          segurosOfertasStatus.textContent = data.error || "Guardado.";
        }
        if (!data.error) {
          segurosOfertasForm.reset();
          loadSegurosOfertas();
        }
      })
      .catch(() => {
        if (segurosOfertasStatus) {
          segurosOfertasStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (segurosReferidosForm) {
  segurosReferidosForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const clienteData = resolveClienteFromInput(
      segurosReferidosClienteInput,
      segurosReferidosClienteId
    );
    if (!clienteData.cliente_id) {
      if (segurosReferidosStatus) {
        segurosReferidosStatus.textContent = "Selecciona un cliente.";
      }
      return;
    }
    const formData = new FormData(segurosReferidosForm);
    const payload = Object.fromEntries(formData.entries());
    payload.cliente_id = clienteData.cliente_id;
    if (segurosReferidosStatus) {
      segurosReferidosStatus.textContent = "Guardando...";
    }
    fetch("/api/seguros_referidos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (segurosReferidosStatus) {
          segurosReferidosStatus.textContent = data.error || "Guardado.";
        }
        if (!data.error) {
          segurosReferidosForm.reset();
          loadSegurosReferidos();
        }
      })
      .catch(() => {
        if (segurosReferidosStatus) {
          segurosReferidosStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (segurosCampanasForm) {
  segurosCampanasForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const formData = new FormData(segurosCampanasForm);
    const payload = Object.fromEntries(formData.entries());
    if (segurosCampanasStatus) {
      segurosCampanasStatus.textContent = "Guardando...";
    }
    fetch("/api/seguros_campanas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (segurosCampanasStatus) {
          segurosCampanasStatus.textContent = data.error || "Guardado.";
        }
        if (!data.error) {
          segurosCampanasForm.reset();
          loadSegurosCampanas();
        }
      })
      .catch(() => {
        if (segurosCampanasStatus) {
          segurosCampanasStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (segurosComisionesForm) {
  segurosComisionesForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const formData = new FormData(segurosComisionesForm);
    const payload = Object.fromEntries(formData.entries());
    if (segurosComisionesStatus) {
      segurosComisionesStatus.textContent = "Guardando...";
    }
    fetch("/api/seguros_comisiones", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (segurosComisionesStatus) {
          segurosComisionesStatus.textContent = data.error || "Guardado.";
        }
        if (!data.error) {
          segurosComisionesForm.reset();
          loadSegurosComisiones();
        }
      })
      .catch(() => {
        if (segurosComisionesStatus) {
          segurosComisionesStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (finCrmSearch) {
  finCrmSearch.addEventListener("input", () => {
    scheduleSave("fin-crm-search", () => {
      loadFinCrm();
    }, 300);
  });
}

if (finCrmClienteInput) {
  finCrmClienteInput.addEventListener("change", () => {
    loadFinCrm();
  });
}

if (finCrmClienteOpen) {
  finCrmClienteOpen.addEventListener("click", () => {
    const clienteData = resolveClienteFromInput(finCrmClienteInput, finCrmClienteId);
    if (clienteData.cliente_id) {
      openClienteDetail(clienteData.cliente_id);
    } else if (finCrmClienteInput) {
      finCrmClienteInput.focus();
    }
  });
}

let segurosOcrPreviewUrl = "";
if (segurosOcrFile) {
  segurosOcrFile.addEventListener("change", () => {
    if (segurosOcrPreviewUrl) {
      URL.revokeObjectURL(segurosOcrPreviewUrl);
      segurosOcrPreviewUrl = "";
    }
    if (segurosOcrFile.files && segurosOcrFile.files[0]) {
      segurosOcrPreviewUrl = URL.createObjectURL(segurosOcrFile.files[0]);
      if (segurosOcrPreview) {
        segurosOcrPreview.disabled = false;
      }
    } else if (segurosOcrPreview) {
      segurosOcrPreview.disabled = true;
    }
  });
}

if (segurosOcrPreview) {
  segurosOcrPreview.addEventListener("click", () => {
    if (segurosOcrPreviewUrl) {
      window.open(segurosOcrPreviewUrl, "_blank", "noopener");
    }
  });
}

if (segurosOcrButton) {
  segurosOcrButton.addEventListener("click", () => {
    if (segurosOcrStatus) {
      segurosOcrStatus.textContent = "";
    }
    if (segurosOcrSaveStatus) {
      segurosOcrSaveStatus.textContent = "";
    }
    state.segurosOcrClienteId = "";
    if (!segurosOcrFile || !segurosOcrFile.files || !segurosOcrFile.files.length) {
      if (segurosOcrStatus) {
        segurosOcrStatus.textContent = "Selecciona un PDF.";
      }
      return;
    }
    const file = segurosOcrFile.files[0];
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      if (segurosOcrStatus) {
        segurosOcrStatus.textContent = "El archivo debe ser PDF.";
      }
      return;
    }
    if (segurosOcrStatus) {
      segurosOcrStatus.textContent = "Procesando OCR...";
    }
    const reader = new FileReader();
    reader.onload = () => {
      fetch("/api/seguros_ocr", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_base64: reader.result, filename: file.name }),
      })
        .then((res) => res.json())
        .then((data) => {
          if (data.error) {
            if (segurosOcrStatus) {
              segurosOcrStatus.textContent = data.detail
                ? `${data.error} ${data.detail}`
                : data.error;
            }
            state.segurosOcrClienteId = "";
            return;
          }
          state.segurosOcrClienteId = data.cliente_id || "";
          state.segurosOcrQuality = data.ocr_quality || null;
          fillSegurosOcrFields(data.fields || {});
          if (segurosOcrRaw) {
            segurosOcrRaw.value = (data.text || "").trim();
          }
          if (segurosOcrStatus) {
            const lang = data.language ? ` (${data.language})` : "";
            const method = data.method ? ` · ${data.method}` : "";
            const docType = data.doc_type ? ` · ${data.doc_type}` : "";
            const calidad = data.ocr_quality?.calidad ? ` · ${data.ocr_quality.calidad}` : "";
            const fields = data.fields || {};
            const filled = Object.entries(fields)
              .filter(([, value]) => String(value || "").trim().length)
              .map(([key]) => key);
            if (filled.length) {
              segurosOcrStatus.textContent = `Datos extraídos${lang}${method}${docType}${calidad}: ${filled.join(", ")}.`;
            } else {
              segurosOcrStatus.textContent = `No se detectaron campos${lang}${method}${docType}${calidad}.`;
            }
          }
          if (seguroOcrEstado && data.doc_type) {
            if (data.doc_type === "presupuesto") {
              seguroOcrEstado.value = "Presupuesto";
            } else if (data.doc_type === "poliza") {
              seguroOcrEstado.value = "En vigor";
            }
          }
          saveSegurosOcrRecord().catch(() => {});
        })
        .catch(() => {
          if (segurosOcrStatus) {
            segurosOcrStatus.textContent = "No se pudo procesar el PDF.";
          }
          state.segurosOcrClienteId = "";
          state.segurosOcrQuality = null;
        });
    };
    reader.onerror = () => {
      if (segurosOcrStatus) {
        segurosOcrStatus.textContent = "Error al leer el archivo.";
      }
    };
    reader.readAsDataURL(file);
  });
}

if (segurosBdtOcrButton) {
  segurosBdtOcrButton.addEventListener("click", () => {
    if (segurosBdtOcrStatus) segurosBdtOcrStatus.textContent = "";
    state.segurosBdtOcrClienteId = "";
    if (!segurosBdtOcrFile || !segurosBdtOcrFile.files || !segurosBdtOcrFile.files.length) {
      if (segurosBdtOcrStatus) segurosBdtOcrStatus.textContent = "Selecciona un PDF.";
      return;
    }
    const file = segurosBdtOcrFile.files[0];
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      if (segurosBdtOcrStatus) segurosBdtOcrStatus.textContent = "El archivo debe ser PDF.";
      return;
    }
    if (segurosBdtOcrStatus) segurosBdtOcrStatus.textContent = "Procesando OCR...";
    const reader = new FileReader();
    reader.onload = () => {
      fetch("/api/seguros_ocr", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_base64: reader.result, filename: file.name }),
      })
        .then((res) => res.json())
        .then((data) => {
          if (data.error) {
            if (segurosBdtOcrStatus) {
              segurosBdtOcrStatus.textContent = data.detail
                ? `${data.error} ${data.detail}`
                : data.error;
            }
            state.segurosBdtOcrClienteId = "";
            return;
          }
          state.segurosBdtOcrClienteId = data.cliente_id || "";
          fillSegurosBdtOcrFields(data.fields || {});
          if (segurosBdtOcrStatus && (data.doc_type || data.ocr_quality?.calidad)) {
            const docType = data.doc_type ? ` · ${data.doc_type}` : "";
            const calidad = data.ocr_quality?.calidad ? ` · ${data.ocr_quality.calidad}` : "";
            segurosBdtOcrStatus.textContent = `OCR listo${docType}${calidad}.`;
          }
          matchSegurosBdtFromFields().catch(() => {});
        })
        .catch(() => {
          if (segurosBdtOcrStatus) segurosBdtOcrStatus.textContent = "No se pudo procesar el PDF.";
          state.segurosBdtOcrClienteId = "";
        });
    };
    reader.onerror = () => {
      if (segurosBdtOcrStatus) segurosBdtOcrStatus.textContent = "Error al leer el archivo.";
    };
    reader.readAsDataURL(file);
  });
}

if (seguroOcrFechaEfecto) {
  seguroOcrFechaEfecto.addEventListener("change", () => {
    if (!seguroOcrFechaVencimiento) return;
    if (!seguroOcrFechaVencimiento.value) {
      seguroOcrFechaVencimiento.value = addOneYear(seguroOcrFechaEfecto.value);
    }
  });
}

if (segurosBdtOcrFechaEfecto) {
  segurosBdtOcrFechaEfecto.addEventListener("change", () => {
    if (!segurosBdtOcrFechaVencimiento) return;
    if (!segurosBdtOcrFechaVencimiento.value) {
      segurosBdtOcrFechaVencimiento.value = addOneYear(segurosBdtOcrFechaEfecto.value);
    }
  });
}

if (segurosOcrSave) {
  segurosOcrSave.addEventListener("click", async () => {
    const recordId = segurosOcrSave.dataset.recordId;
    if (recordId) {
      const payload = {
        id: recordId,
        estado: "En vigor",
        fecha_efecto: seguroOcrFechaEfecto ? seguroOcrFechaEfecto.value : "",
        fecha_vencimiento: seguroOcrFechaVencimiento ? seguroOcrFechaVencimiento.value : "",
        poliza_numero: seguroOcrPoliza ? seguroOcrPoliza.value.trim() : "",
      };
      const file =
        segurosOcrFile && segurosOcrFile.files && segurosOcrFile.files.length
          ? segurosOcrFile.files[0]
          : null;
      if (file) {
        try {
          const upload = await uploadFileToS3(file, "seguros", segurosOcrSaveStatus);
          if (upload) {
            payload.poliza_key = upload.key || "";
            payload.poliza_url = upload.public_url || "";
          }
        } catch (err) {
          if (segurosOcrSaveStatus) {
            segurosOcrSaveStatus.textContent = `Error al subir: ${err.message}`;
          }
          return;
        }
      }
      fetch("/api/seguros_update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then((res) => res.json())
        .then((data) => {
          if (data.error) {
            if (segurosOcrSaveStatus) {
              segurosOcrSaveStatus.textContent = data.error;
            }
            return;
          }
          if (segurosOcrSaveStatus) {
            segurosOcrSaveStatus.textContent = "Presupuesto convertido.";
          }
          segurosOcrSave.removeAttribute("data-record-id");
          segurosOcrSave.textContent = "Guardar";
          loadSegurosCrm();
        })
        .catch(() => {
          if (segurosOcrSaveStatus) {
            segurosOcrSaveStatus.textContent = "Error al guardar.";
          }
        });
      return;
    }
    saveSegurosOcrRecord().catch(() => {});
  });
}

if (segurosBdtOcrMatchButton) {
  segurosBdtOcrMatchButton.addEventListener("click", () => {
    matchSegurosBdtFromFields().catch(() => {});
  });
}

if (segurosBdtOcrLink) {
  segurosBdtOcrLink.addEventListener("click", async () => {
    if (segurosBdtOcrStatus) segurosBdtOcrStatus.textContent = "";
    const recordId = segurosBdtOcrSelect ? segurosBdtOcrSelect.value : "";
    if (!recordId) {
      if (segurosBdtOcrStatus) segurosBdtOcrStatus.textContent = "Selecciona una póliza.";
      return;
    }
    const fields = getSegurosBdtOcrFields();
    const file =
      segurosBdtOcrFile && segurosBdtOcrFile.files && segurosBdtOcrFile.files.length
        ? segurosBdtOcrFile.files[0]
        : null;
    if (segurosBdtOcrStatus) segurosBdtOcrStatus.textContent = "Vinculando...";
    let upload = null;
    if (file) {
      try {
        upload = await uploadFileToS3(file, "seguros", segurosBdtOcrStatus);
      } catch (err) {
        if (segurosBdtOcrStatus) {
          segurosBdtOcrStatus.textContent = `Error al subir: ${err.message}`;
        }
        return;
      }
    }
    fetch("/api/seguros_enrich", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: recordId, ...fields }),
    })
      .then((res) => res.json())
      .then((resp) => {
        if (resp.error) {
          if (segurosBdtOcrStatus) segurosBdtOcrStatus.textContent = resp.error;
          return;
        }
        if (upload) {
          fetch("/api/seguros_update", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              id: recordId,
              poliza_key: upload.key || "",
              poliza_url: upload.public_url || "",
            }),
          }).catch(() => {});
        }
        if (segurosBdtOcrStatus) segurosBdtOcrStatus.textContent = "Vinculado a BDT.";
        state.segurosBdtOcrClienteId = "";
        state.segurosBdtCache = null;
        loadSegurosCrm();
      })
      .catch(() => {
        if (segurosBdtOcrStatus) segurosBdtOcrStatus.textContent = "Error al vincular.";
      });
  });
}

if (segurosUpdateButton) {
  segurosUpdateButton.addEventListener("click", () => {
    if (segurosUpdateStatus) segurosUpdateStatus.textContent = "";
    const recordId = segurosUpdateSelect ? segurosUpdateSelect.value : "";
    if (!recordId) {
      if (segurosUpdateStatus) segurosUpdateStatus.textContent = "Selecciona una póliza.";
      return;
    }
    if (!segurosUpdateFile || !segurosUpdateFile.files || !segurosUpdateFile.files.length) {
      if (segurosUpdateStatus) segurosUpdateStatus.textContent = "Selecciona un PDF.";
      return;
    }
    const file = segurosUpdateFile.files[0];
    if (file.type !== "application/pdf") {
      if (segurosUpdateStatus) segurosUpdateStatus.textContent = "El archivo debe ser PDF.";
      return;
    }
    if (segurosUpdateStatus) segurosUpdateStatus.textContent = "Procesando OCR...";
    const reader = new FileReader();
    reader.onload = async () => {
      const payload = {
        filename: file.name,
        content: reader.result,
      };
      let upload = null;
      try {
        upload = await uploadFileToS3(file, "seguros", segurosUpdateStatus);
      } catch (err) {
        if (segurosUpdateStatus) {
          segurosUpdateStatus.textContent = `Error al subir: ${err.message}`;
        }
        return;
      }
      fetch("/api/seguros_ocr", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then((res) => res.json())
        .then((data) => {
          if (data.error) {
            if (segurosUpdateStatus) {
              segurosUpdateStatus.textContent = data.detail || data.error;
            }
            return;
          }
          const fields = data.fields || {};
          const enrichPayload = {
            id: recordId,
            tomador: fields.tomador || "",
            nif: fields.dni || "",
            telefono: fields.telefono || "",
            email: fields.email || "",
            direccion: fields.direccion || "",
            fecha_nacimiento: fields.fecha_nacimiento || "",
            compania: fields.compania || "",
            ramo: fields.ramo || "",
            poliza_numero: fields.poliza_numero || "",
            prima_neta: fields.prima_neta || "",
            prima_total: fields.prima_total || "",
            fecha_efecto: fields.fecha_efecto || "",
            fecha_vencimiento: fields.fecha_vencimiento || "",
          };
          if (upload) {
            fetch("/api/seguros_update", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                id: recordId,
                poliza_key: upload.key || "",
                poliza_url: upload.public_url || "",
              }),
            }).catch(() => {});
          }
          fetch("/api/seguros_enrich", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(enrichPayload),
          })
            .then((res) => res.json())
            .then((resp) => {
              if (resp.error) {
                if (segurosUpdateStatus) {
                  segurosUpdateStatus.textContent = resp.error;
                }
                return;
              }
              if (segurosUpdateStatus) {
                segurosUpdateStatus.textContent = "Datos completados.";
              }
              loadSegurosCrm();
            })
            .catch(() => {
              if (segurosUpdateStatus) segurosUpdateStatus.textContent = "Error al completar.";
            });
        })
        .catch(() => {
          if (segurosUpdateStatus) segurosUpdateStatus.textContent = "Error al leer el PDF.";
        });
    };
    reader.readAsDataURL(file);
  });
}

if (finCrmSearch) {
  finCrmSearch.addEventListener("input", () => {
    scheduleSave("fin-crm-search", () => {
      loadFinCrm();
    }, 300);
  });
}

if (holdingBackBtn) {
  holdingBackBtn.addEventListener("click", () => {
    goHome();
  });
}
if (agendaBackBtn) {
  agendaBackBtn.addEventListener("click", () => {
    goHome();
  });
}

if (inmuebleBackBtn) {
  inmuebleBackBtn.addEventListener("click", () => {
    if (inmuebleDetail) {
      inmuebleDetail.classList.add("hidden");
    }
    state.currentInmuebleId = "";
  });
}

if (clienteDetailBack) {
  clienteDetailBack.addEventListener("click", () => {
    closeClienteDetail();
  });
}

if (clienteTabs) {
  clienteTabs.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-tab]");
    if (!btn) return;
    setClienteTab(btn.dataset.tab);
  });
}

if (gestoriaModuleTabs) {
  gestoriaModuleTabs.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-gestoria-module]");
    if (!btn) return;
    setGestoriaClientModuleTab(btn.dataset.gestoriaModule);
  });
}

if (clienteSaveBtn) {
  clienteSaveBtn.addEventListener("click", () => {
    saveClienteForm();
  });
}

if (clienteAssignForm) {
  clienteAssignForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.currentClienteId) {
      if (clienteAssignStatus) {
        clienteAssignStatus.textContent = "Selecciona un cliente.";
      }
      return;
    }
    if (clienteAssignStatus) {
      clienteAssignStatus.textContent = "Vinculando...";
    }
    const formData = new FormData(clienteAssignForm);
    const payload = Object.fromEntries(formData.entries());
    payload.cliente_id = state.currentClienteId;
    fetch("/api/clientes_link", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (clienteAssignStatus) {
            clienteAssignStatus.textContent = data.error;
          }
          return;
        }
        if (clienteAssignStatus) {
          clienteAssignStatus.textContent = "Vinculado.";
        }
        openClienteDetail(state.currentClienteId);
      })
      .catch(() => {
        if (clienteAssignStatus) {
          clienteAssignStatus.textContent = "Error al vincular.";
        }
      });
  });
}

let finAsesorPreviewUrl = "";
if (finAsesorOcrFile) {
  finAsesorOcrFile.addEventListener("change", () => {
    if (finAsesorPreviewUrl) {
      URL.revokeObjectURL(finAsesorPreviewUrl);
      finAsesorPreviewUrl = "";
    }
    if (finAsesorOcrFile.files && finAsesorOcrFile.files[0]) {
      finAsesorPreviewUrl = URL.createObjectURL(finAsesorOcrFile.files[0]);
      if (finAsesorOcrPreview) {
        finAsesorOcrPreview.disabled = false;
      }
    } else if (finAsesorOcrPreview) {
      finAsesorOcrPreview.disabled = true;
    }
  });
}

if (finAsesorOcrPreview) {
  finAsesorOcrPreview.addEventListener("click", () => {
    if (finAsesorPreviewUrl) {
      window.open(finAsesorPreviewUrl, "_blank", "noopener");
    }
  });
}

if (finAsesorOcrExternal) {
  finAsesorOcrExternal.addEventListener("change", () => {
    if (!finAsesorOcrMode) return;
    if (finAsesorOcrExternal.checked) {
      finAsesorOcrMode.value = "handwritten";
    }
  });
}

const readFileAsDataUrl = (file) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });

if (finAsesorOcrButton) {
  finAsesorOcrButton.addEventListener("click", () => {
    if (finAsesorOcrStatus) finAsesorOcrStatus.textContent = "";
    if (!finAsesorOcrFile || !finAsesorOcrFile.files || !finAsesorOcrFile.files.length) {
      if (finAsesorOcrStatus) finAsesorOcrStatus.textContent = "Selecciona un PDF.";
      return;
    }
    const file = finAsesorOcrFile.files[0];
    const isPdf = file.name.toLowerCase().endsWith(".pdf") || file.type === "application/pdf";
    const isImage = file.type.startsWith("image/");
    if (!isPdf && !isImage) {
      if (finAsesorOcrStatus) finAsesorOcrStatus.textContent = "El archivo debe ser PDF o imagen.";
      return;
    }
    if (finAsesorOcrStatus) finAsesorOcrStatus.textContent = "Procesando OCR...";
    const reader = new FileReader();
    reader.onload = () => {
      fetch("/api/fin_asesoramiento_ocr", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          file_base64: reader.result,
          filename: file.name,
          use_external: finAsesorOcrExternal ? finAsesorOcrExternal.checked : false,
          ocr_mode: finAsesorOcrMode ? finAsesorOcrMode.value : "",
        }),
      })
        .then((res) => res.json())
        .then((data) => {
          if (data.error) {
            if (finAsesorOcrStatus) {
              finAsesorOcrStatus.textContent = data.detail
                ? `${data.error} ${data.detail}`
                : data.error;
            }
            return;
          }
          fillFinAsesoramientoOcrFields(data.fields || {});
          if (finAsesorOcrRaw) {
            finAsesorOcrRaw.value = (data.text || "").trim();
          }
          if (finAsesorOcrStatus) {
            const lang = data.language ? ` (${data.language})` : "";
            const method = data.method ? ` · ${data.method}` : "";
            const fields = data.fields || {};
            const filled = Object.values(fields).filter((value) => String(value || "").trim().length).length;
            const extra = data.external_error ? ` (${data.external_error})` : "";
            const quality = data.ocr_quality?.calidad ? ` · ${data.ocr_quality.calidad}` : "";
            finAsesorOcrStatus.textContent = `OCR listo${lang}${method}${quality}. Campos detectados: ${filled}.${extra}`;
          }
          if (finAsesoramientoForm && data.ocr_quality) {
            const qualityInput = finAsesoramientoForm.querySelector("[name='calidad_ocr']");
            const camposInput = finAsesoramientoForm.querySelector("[name='campos_ocr']");
            if (qualityInput) qualityInput.value = data.ocr_quality.calidad || "";
            if (camposInput) camposInput.value = (data.ocr_quality.campos || []).join(",");
          }
        })
        .catch(() => {
          if (finAsesorOcrStatus) finAsesorOcrStatus.textContent = "No se pudo procesar el PDF.";
        });
    };
    reader.readAsDataURL(file);
  });
}

if (finAsesorOcrAutoButton) {
  finAsesorOcrAutoButton.addEventListener("click", () => {
    if (finAsesorOcrStatus) finAsesorOcrStatus.textContent = "";
    if (!finAsesorOcrFile || !finAsesorOcrFile.files || !finAsesorOcrFile.files.length) {
      if (finAsesorOcrStatus) finAsesorOcrStatus.textContent = "Selecciona una imagen.";
      return;
    }
    const file = finAsesorOcrFile.files[0];
    const isImage = file.type.startsWith("image/");
    if (!isImage) {
      if (finAsesorOcrStatus) finAsesorOcrStatus.textContent = "El archivo debe ser imagen.";
      return;
    }
    if (finAsesorOcrStatus) finAsesorOcrStatus.textContent = "Auto-recortando...";
    const reader = new FileReader();
    reader.onload = () => {
      fetch("/api/fin_asesoramiento_ocr_auto", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          file_base64: reader.result,
          filename: file.name,
          use_external: finAsesorOcrExternal ? finAsesorOcrExternal.checked : false,
          ocr_mode: finAsesorOcrMode ? finAsesorOcrMode.value : "",
        }),
      })
        .then((res) => res.json())
        .then((data) => {
          if (data.error) {
            if (finAsesorOcrStatus) {
              finAsesorOcrStatus.textContent = data.detail
                ? `${data.error} ${data.detail}`
                : data.error;
            }
            return;
          }
          fillFinAsesoramientoOcrFields(data.fields || {});
          if (finAsesorOcrRaw) {
            finAsesorOcrRaw.value = (data.text || "").trim();
          }
          if (finAsesorOcrStatus) {
            const lang = data.language ? ` (${data.language})` : "";
            const method = data.method ? ` · ${data.method}` : "";
            const fields = data.fields || {};
            const filled = Object.values(fields).filter((value) => String(value || "").trim().length).length;
            const extra = data.external_error ? ` (${data.external_error})` : "";
            const quality = data.ocr_quality?.calidad ? ` · ${data.ocr_quality.calidad}` : "";
            finAsesorOcrStatus.textContent = `OCR listo${lang}${method}${quality}. Campos detectados: ${filled}.${extra}`;
          }
          if (finAsesoramientoForm && data.ocr_quality) {
            const qualityInput = finAsesoramientoForm.querySelector("[name='calidad_ocr']");
            const camposInput = finAsesoramientoForm.querySelector("[name='campos_ocr']");
            if (qualityInput) qualityInput.value = data.ocr_quality.calidad || "";
            if (camposInput) camposInput.value = (data.ocr_quality.campos || []).join(",");
          }
        })
        .catch(() => {
          if (finAsesorOcrStatus) finAsesorOcrStatus.textContent = "No se pudo auto-recortar.";
        });
    };
    reader.readAsDataURL(file);
  });
}

if (finAsesorOcrGuidedButton) {
  finAsesorOcrGuidedButton.addEventListener("click", () => {
    if (finAsesorOcrGuidedStatus) finAsesorOcrGuidedStatus.textContent = "";
    const sections = {
      header: finAsesorOcrGuidedHeader?.files?.[0],
      cliente1: finAsesorOcrGuidedCliente1?.files?.[0],
      cliente2: finAsesorOcrGuidedCliente2?.files?.[0],
      resumen: finAsesorOcrGuidedResumen?.files?.[0],
    };
    if (!Object.values(sections).some(Boolean)) {
      if (finAsesorOcrGuidedStatus) {
        finAsesorOcrGuidedStatus.textContent = "Sube al menos un recorte.";
      }
      return;
    }
    if (finAsesorOcrGuidedStatus) finAsesorOcrGuidedStatus.textContent = "Procesando recortes...";
    const entries = Object.entries(sections)
      .filter(([, file]) => file)
      .map(([key, file]) => readFileAsDataUrl(file).then((data) => [key, data]));
    Promise.all(entries)
      .then((pairs) => {
        const payloadSections = {};
        pairs.forEach(([key, data]) => {
          payloadSections[key] = data;
        });
        return fetch("/api/fin_asesoramiento_ocr_guided", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sections: payloadSections,
            use_external: finAsesorOcrExternal ? finAsesorOcrExternal.checked : false,
            ocr_mode: finAsesorOcrMode ? finAsesorOcrMode.value : "",
          }),
        });
      })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (finAsesorOcrGuidedStatus) {
            finAsesorOcrGuidedStatus.textContent = data.detail
              ? `${data.error} ${data.detail}`
              : data.error;
          }
          return;
        }
        fillFinAsesoramientoOcrFields(data.fields || {});
        if (finAsesorOcrRaw) {
          finAsesorOcrRaw.value = (data.text || "").trim();
        }
        if (finAsesorOcrGuidedStatus) {
          const fields = data.fields || {};
          const filled = Object.values(fields).filter((value) => String(value || "").trim().length).length;
          const extra = data.external_error ? ` (${data.external_error})` : "";
          const quality = data.ocr_quality?.calidad ? ` · ${data.ocr_quality.calidad}` : "";
          finAsesorOcrGuidedStatus.textContent = `Recortes listos${quality}. Campos detectados: ${filled}.${extra}`;
        }
        if (finAsesoramientoForm && data.ocr_quality) {
          const qualityInput = finAsesoramientoForm.querySelector("[name='calidad_ocr']");
          const camposInput = finAsesoramientoForm.querySelector("[name='campos_ocr']");
          if (qualityInput) qualityInput.value = data.ocr_quality.calidad || "";
          if (camposInput) camposInput.value = (data.ocr_quality.campos || []).join(",");
        }
      })
      .catch(() => {
        if (finAsesorOcrGuidedStatus) {
          finAsesorOcrGuidedStatus.textContent = "No se pudo procesar los recortes.";
        }
      });
  });
}

if (finAsesoramientoForm) {
  finAsesoramientoForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const formData = new FormData(finAsesoramientoForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = FIN_COMPANY;
    payload.cliente1_ingresos = toNumber(payload.cliente1_ingresos);
    payload.cliente2_ingresos = toNumber(payload.cliente2_ingresos);
    payload.ingresos_conjuntos = toNumber(payload.ingresos_conjuntos);
    payload.aportacion_cv = toNumber(payload.aportacion_cv);
    const recordId = payload.id || (finAsesoramientoId ? finAsesoramientoId.value : "");
    if (finAsesoramientoStatus) finAsesoramientoStatus.textContent = "Guardando...";
    const endpoint = recordId ? "/api/fin_asesoramientos_update" : "/api/fin_asesoramientos";
    if (recordId) payload.id = recordId;
    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (finAsesoramientoStatus) {
          let msg = data.error || "Guardado.";
          if (data.duplicate_of) {
            msg = "Duplicado: se actualizó el asesoramiento existente.";
          }
          if (Array.isArray(data.missing) && data.missing.length) {
            msg = `${msg} Faltan: ${data.missing.join(", ")}.`;
          }
          finAsesoramientoStatus.textContent = msg;
        }
        if (!data.error) {
          if (data.id && finAsesoramientoId) {
            finAsesoramientoId.value = data.id;
            if (finAsesoramientoConvert) finAsesoramientoConvert.disabled = false;
            loadFinChecklist(data.id);
          }
          if (!recordId && !data.duplicate_of) {
            finAsesoramientoForm.reset();
            if (finAsesoramientoId) finAsesoramientoId.value = "";
            if (finAsesoramientoConvert) finAsesoramientoConvert.disabled = true;
            loadFinChecklist("");
          }
          loadFinCrm();
        }
      })
      .catch(() => {
        if (finAsesoramientoStatus) finAsesoramientoStatus.textContent = "Error al guardar.";
      });
  });
}

if (finAsesoramientoConvert) {
  finAsesoramientoConvert.disabled = true;
}

if (finAsesoramientoConvert) {
  finAsesoramientoConvert.addEventListener("click", () => {
    const recordId = finAsesoramientoId ? finAsesoramientoId.value : "";
    if (!recordId) {
      if (finAsesoramientoStatus) {
        finAsesoramientoStatus.textContent = "Guarda el asesoramiento antes de convertir.";
      }
      return;
    }
    const ok = window.confirm("¿Convertir este asesoramiento en hipoteca?");
    if (!ok) return;
    fetch("/api/fin_asesoramientos_convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: recordId,
        empresa_nombre: FIN_COMPANY,
      }),
    })
      .then((res) => res.json())
      .then((resp) => {
        if (finAsesoramientoStatus) {
          finAsesoramientoStatus.textContent = resp.error || "Convertido.";
        }
        if (!resp.error) {
          loadFinCrm();
        }
      })
      .catch(() => {
        if (finAsesoramientoStatus) {
          finAsesoramientoStatus.textContent = "Error al convertir.";
        }
      });
  });
}

if (finChecklistGenerate) {
  finChecklistGenerate.addEventListener("click", () => {
    if (finChecklistStatus) finChecklistStatus.textContent = "";
    const recordId = finAsesoramientoId ? finAsesoramientoId.value : "";
    if (!recordId) {
      if (finChecklistStatus) finChecklistStatus.textContent = "Selecciona un asesoramiento.";
      return;
    }
    if (finChecklistStatus) finChecklistStatus.textContent = "Generando checklist...";
    fetch("/api/fin_checklist_generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asesoramiento_id: recordId,
        empresa_nombre: FIN_COMPANY,
      }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (finChecklistStatus) {
          finChecklistStatus.textContent = data.error || "Checklist generado.";
        }
        if (!data.error) {
          loadFinChecklist(recordId);
        }
      })
      .catch(() => {
        if (finChecklistStatus) finChecklistStatus.textContent = "No se pudo generar.";
      });
  });
}

if (finCopilotForm) {
  finCopilotForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (finCopilotStatus) finCopilotStatus.textContent = "";
    const recordId = finAsesoramientoId ? finAsesoramientoId.value : "";
    if (!recordId) {
      if (finCopilotStatus) finCopilotStatus.textContent = "Selecciona un asesoramiento.";
      return;
    }
    const formData = new FormData(finCopilotForm);
    const payload = Object.fromEntries(formData.entries());
    payload.asesoramiento_id = recordId;
    payload.empresa_nombre = FIN_COMPANY;
    if (finCopilotStatus) finCopilotStatus.textContent = "Generando...";
    fetch("/api/ai_fin_copilot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (finCopilotStatus) finCopilotStatus.textContent = data.error || "Listo.";
        if (finCopilotOutput) finCopilotOutput.value = data.output || "";
      })
      .catch(() => {
        if (finCopilotStatus) finCopilotStatus.textContent = "Error al generar.";
      });
  });
}

if (finAsesoramientosSearch) {
  finAsesoramientosSearch.addEventListener("input", () => {
    scheduleSave("fin-asesoramientos-search", () => {
      const empresa = state.empresas.find((e) => e.nombre === FIN_COMPANY);
      if (empresa) loadFinAsesoramientos(empresa.id);
    }, 250);
  });
}

const bindClienteProfesionalForm = (formEl, payloadBuilder) => {
  if (!formEl) return;
  formEl.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.currentClienteId) {
      if (clienteProfesionalStatus) {
        clienteProfesionalStatus.textContent = "Selecciona un cliente.";
      }
      return;
    }
    if (clienteProfesionalStatus) {
      clienteProfesionalStatus.textContent = "Guardando...";
    }
    const formData = new FormData(formEl);
    const payload = Object.fromEntries(formData.entries());
    const extra = payloadBuilder ? payloadBuilder(payload) : payload;
    extra.cliente_id = state.currentClienteId;
    fetch("/api/cliente_profesional", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(extra),
    })
      .then((res) => res.json())
      .then((data) => {
        if (clienteProfesionalStatus) {
          clienteProfesionalStatus.textContent = data.error || "Guardado.";
        }
        if (!data.error) {
          formEl.reset();
          loadClienteProfesional(state.currentClienteId);
        }
      })
      .catch(() => {
        if (clienteProfesionalStatus) {
          clienteProfesionalStatus.textContent = "Error al guardar.";
        }
      });
  });
};

bindClienteProfesionalForm(clienteProfesionalCnaeForm, (payload) => ({
  cnae: payload.cnae,
}));
bindClienteProfesionalForm(clienteProfesionalIaeForm, (payload) => ({
  iae: payload.iae,
}));
bindClienteProfesionalForm(clienteProfesionalActividadForm, (payload) => ({
  actividad: payload.actividad,
}));
bindClienteProfesionalForm(clienteProfesionalIbanForm, (payload) => ({
  iban: payload.iban,
  principal: payload.principal,
}));

if (clienteGestoriaForm) {
  clienteGestoriaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.currentClienteId) {
      if (clienteGestoriaStatus) {
        clienteGestoriaStatus.textContent = "Selecciona un cliente.";
      }
      return;
    }
    if (clienteGestoriaStatus) {
      clienteGestoriaStatus.textContent = "Guardando...";
    }
    const formData = new FormData(clienteGestoriaForm);
    const payload = Object.fromEntries(formData.entries());
    const checkboxFields = [
      "mod_fiscal",
      "mod_laboral",
      "mod_contable",
      "mod_renta",
      "mod_registro",
      "mod_trafico",
      "mod_puntuales",
    ];
    checkboxFields.forEach((field) => {
      payload[field] = clienteGestoriaForm.querySelector(`[name="${field}"]`)?.checked ? 1 : 0;
    });
    payload.cliente_id = state.currentClienteId;
    fetch("/api/cliente_gestoria_update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (clienteGestoriaStatus) {
          clienteGestoriaStatus.textContent = data.error || "Guardado.";
        }
        if (!data.error) {
          updateGestoriaModuleTabsFromForm();
        }
      })
      .catch(() => {
        if (clienteGestoriaStatus) {
          clienteGestoriaStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (gestoriaModeloForm) {
  gestoriaModeloForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.currentClienteId) {
      if (gestoriaModeloStatus) {
        gestoriaModeloStatus.textContent = "Selecciona un cliente.";
      }
      return;
    }
    const modeloValue = gestoriaModeloForm.querySelector('[name="modelo"]')?.value.trim() || "";
    const fechaValue = gestoriaModeloForm.querySelector('[name="proxima_fecha"]')?.value || "";
    if (!modeloValue || !fechaValue) {
      if (gestoriaModeloStatus) {
        gestoriaModeloStatus.textContent = "Indica modelo y próxima presentación.";
      }
      return;
    }
    if (gestoriaModeloStatus) {
      gestoriaModeloStatus.textContent = "Guardando...";
    }
    const formData = new FormData(gestoriaModeloForm);
    const payload = Object.fromEntries(formData.entries());
    payload.usuario = getCurrentUser();
    payload.cliente_id = state.currentClienteId;
    fetch("/api/gestoria_modelos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (gestoriaModeloStatus) {
          gestoriaModeloStatus.textContent = data.error || "Guardado.";
        }
        if (!data.error) {
          gestoriaModeloForm.reset();
          loadGestoriaModelos(state.currentClienteId);
        }
      })
      .catch(() => {
        if (gestoriaModeloStatus) {
          gestoriaModeloStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (gestoriaLaboralForm) {
  gestoriaLaboralForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitGestoriaTrabajoForm(gestoriaLaboralForm, gestoriaLaboralStatus, () => {
      loadGestoriaTrabajosFiltered(
        state.currentClienteId,
        ["Altas/Bajas", "Contratos", "Nóminas", "Seguros sociales", "IT/Bajas médicas", "Finiquitos", "Otros laboral"],
        gestoriaLaboralTable,
        gestoriaLaboralInfo,
        "gestiones laborales"
      );
    });
  });
}

if (gestoriaRentaForm) {
  gestoriaRentaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitGestoriaTrabajoForm(gestoriaRentaForm, gestoriaRentaStatus, () => {
      loadGestoriaTrabajosFiltered(
        state.currentClienteId,
        [
          "Declaración en periodo",
          "Declaración extemporánea",
          "Requerimiento",
          "Complementaria",
          "Rectificativa",
          "Otros renta",
        ],
        gestoriaRentaTable,
        gestoriaRentaInfo,
        "expedientes de renta"
      );
    });
  });
}

if (gestoriaAdminForm) {
  gestoriaAdminForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitGestoriaTrabajoForm(gestoriaAdminForm, gestoriaAdminStatus, () => {
      loadGestoriaTrabajosFiltered(
        state.currentClienteId,
        [
          "Tráfico - Transferencias",
          "Tráfico - Matriculaciones",
          "Herencias",
          "Extinción de condominio",
          "IMV",
          "Becas",
          "Complemento brecha de género",
          "Otros administrativos",
        ],
        gestoriaAdminTable,
        gestoriaAdminInfo,
        "gestiones administrativas"
      );
    });
  });
}

if (gestoriaRentaDetallesForm) {
  gestoriaRentaDetallesForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.currentClienteId) {
      if (gestoriaRentaDetallesStatus) {
        gestoriaRentaDetallesStatus.textContent = "Selecciona un cliente.";
      }
      return;
    }
    if (gestoriaRentaDetallesStatus) {
      gestoriaRentaDetallesStatus.textContent = "Guardando...";
    }
    const formData = new FormData(gestoriaRentaDetallesForm);
    const payload = Object.fromEntries(formData.entries());
    payload.cliente_id = state.currentClienteId;
    fetch("/api/cliente_gestoria_update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (gestoriaRentaDetallesStatus) {
          gestoriaRentaDetallesStatus.textContent = data.error || "Guardado.";
        }
      })
      .catch(() => {
        if (gestoriaRentaDetallesStatus) {
          gestoriaRentaDetallesStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (gestoriaDocsForm) {
  gestoriaDocsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (gestoriaDocsStatus) {
      gestoriaDocsStatus.textContent = "Guardando...";
    }
    const formData = new FormData(gestoriaDocsForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = FINCAS_COMPANY;
    payload.usuario = getCurrentUser();
    const file =
      gestoriaDocsFile && gestoriaDocsFile.files && gestoriaDocsFile.files.length
        ? gestoriaDocsFile.files[0]
        : null;
    if (file) {
      try {
        const upload = await uploadFileToS3(file, "gestoria", gestoriaDocsStatus);
        if (upload) {
          payload.doc_key = upload.key || "";
          payload.doc_url = upload.public_url || "";
        }
      } catch (err) {
        if (gestoriaDocsStatus) {
          gestoriaDocsStatus.textContent = `Error al subir: ${err.message}`;
        }
        return;
      }
    }
    fetch("/api/gestoria_docs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (gestoriaDocsStatus) {
            gestoriaDocsStatus.textContent = data.error;
          }
          return;
        }
        if (gestoriaDocsStatus) {
          gestoriaDocsStatus.textContent = "Guardado.";
        }
        gestoriaDocsForm.reset();
        loadGestoriaDocsRecent();
      })
      .catch(() => {
        if (gestoriaDocsStatus) {
          gestoriaDocsStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (gestoriaClienteDocsForm) {
  gestoriaClienteDocsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.currentClienteId) {
      if (gestoriaClienteDocsStatus) {
        gestoriaClienteDocsStatus.textContent = "Selecciona un cliente.";
      }
      return;
    }
    if (gestoriaClienteDocsStatus) {
      gestoriaClienteDocsStatus.textContent = "Guardando...";
    }
    const formData = new FormData(gestoriaClienteDocsForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = FINCAS_COMPANY;
    payload.usuario = getCurrentUser();
    payload.cliente_id = state.currentClienteId;
    const file =
      gestoriaClienteDocsFile &&
      gestoriaClienteDocsFile.files &&
      gestoriaClienteDocsFile.files.length
        ? gestoriaClienteDocsFile.files[0]
        : null;
    if (file) {
      try {
        const upload = await uploadFileToS3(file, "gestoria", gestoriaClienteDocsStatus);
        if (upload) {
          payload.doc_key = upload.key || "";
          payload.doc_url = upload.public_url || "";
        }
      } catch (err) {
        if (gestoriaClienteDocsStatus) {
          gestoriaClienteDocsStatus.textContent = `Error al subir: ${err.message}`;
        }
        return;
      }
    }
    fetch("/api/gestoria_docs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (gestoriaClienteDocsStatus) {
            gestoriaClienteDocsStatus.textContent = data.error;
          }
          return;
        }
        if (gestoriaClienteDocsStatus) {
          gestoriaClienteDocsStatus.textContent = "Guardado.";
        }
        gestoriaClienteDocsForm.reset();
        loadGestoriaDocs(state.currentClienteId);
        loadGestoriaDocsRecent();
      })
      .catch(() => {
        if (gestoriaClienteDocsStatus) {
          gestoriaClienteDocsStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (adminUserForm) {
  adminUserForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (adminUserStatus) {
      adminUserStatus.textContent = "Guardando...";
    }
    const formData = new FormData(adminUserForm);
    const payload = Object.fromEntries(formData.entries());
    fetch("/api/usuarios", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (adminUserStatus) {
            adminUserStatus.textContent = data.error;
          }
          return;
        }
        if (adminUserStatus) {
          adminUserStatus.textContent = "Usuario creado.";
        }
        adminUserForm.reset();
        loadUsuarios().then(() => {
          renderUsuariosSelect();
          renderUsuariosTable();
          renderCompanyCards();
        });
      })
      .catch(() => {
        if (adminUserStatus) {
          adminUserStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (userSelect) {
  userSelect.addEventListener("change", () => {
    setCurrentUser(userSelect.value);
  });
}

if (adminBackBtn) {
  adminBackBtn.addEventListener("click", () => {
    goHome();
  });
}

if (adminPasswordToggle && adminPasswordInput) {
  adminPasswordToggle.addEventListener("click", () => {
    const isHidden = adminPasswordInput.type === "password";
    adminPasswordInput.type = isHidden ? "text" : "password";
    adminPasswordToggle.textContent = isHidden ? "🙈" : "👁";
  });
}

if (gestoriaDocForm) {
  gestoriaDocForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.currentClienteId) {
      if (gestoriaDocStatus) {
        gestoriaDocStatus.textContent = "Selecciona un cliente.";
      }
      return;
    }
    const nombreDoc = gestoriaDocForm.querySelector('[name="nombre"]')?.value.trim() || "";
    const tipoDoc = gestoriaDocForm.querySelector('[name="tipo"]')?.value.trim() || "";
    if (!nombreDoc || !tipoDoc) {
      if (gestoriaDocStatus) {
        gestoriaDocStatus.textContent = "Indica documento y tipo.";
      }
      return;
    }
    if (gestoriaDocStatus) {
      gestoriaDocStatus.textContent = "Guardando...";
    }
    const formData = new FormData(gestoriaDocForm);
    const payload = Object.fromEntries(formData.entries());
    payload.cliente_id = state.currentClienteId;
    payload.empresa_nombre = FINCAS_COMPANY;
    fetch("/api/gestoria_docs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (gestoriaDocStatus) {
          gestoriaDocStatus.textContent = data.error || "Guardado.";
        }
        if (!data.error) {
          gestoriaDocForm.reset();
          loadGestoriaDocs(state.currentClienteId);
        }
      })
      .catch(() => {
        if (gestoriaDocStatus) {
          gestoriaDocStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (gestoriaClienteAgendaForm) {
  gestoriaClienteAgendaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.currentClienteId) {
      if (gestoriaClienteAgendaStatus) {
        gestoriaClienteAgendaStatus.textContent = "Selecciona un cliente.";
      }
      return;
    }
    if (gestoriaClienteAgendaStatus) {
      gestoriaClienteAgendaStatus.textContent = "Guardando...";
    }
    const formData = new FormData(gestoriaClienteAgendaForm);
    const payload = Object.fromEntries(formData.entries());
    payload.cliente_id = state.currentClienteId;
    payload.empresa_nombre = FINCAS_COMPANY;
    payload.servicio = "gestoria";
    fetch("/api/acciones", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (gestoriaClienteAgendaStatus) {
          gestoriaClienteAgendaStatus.textContent = data.error || "Guardado.";
        }
        if (!data.error) {
          gestoriaClienteAgendaForm.reset();
          loadGestoriaClienteAgenda(state.currentClienteId);
        }
      })
      .catch(() => {
        if (gestoriaClienteAgendaStatus) {
          gestoriaClienteAgendaStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (demandaBackBtn) {
  demandaBackBtn.addEventListener("click", () => {
    if (demandaDetail) {
      demandaDetail.classList.add("hidden");
    }
  });
}

if (inmuebleTabs) {
  inmuebleTabs.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-tab]");
    if (!btn) return;
    setInmuebleTab(btn.dataset.tab);
  });
}

if (inmuebleDemandaForm) {
  inmuebleDemandaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (inmuebleDemandaStatus) {
      inmuebleDemandaStatus.textContent = "Guardando...";
    }
    const formData = new FormData(inmuebleDemandaForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = DASHBOARD_COMPANY;
    fetch("/api/demandas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (inmuebleDemandaStatus) {
            inmuebleDemandaStatus.textContent = data.error;
          }
          return;
        }
        if (inmuebleDemandaStatus) {
          inmuebleDemandaStatus.textContent = "Guardado.";
        }
        inmuebleDemandaForm.reset();
        if (state.currentInmuebleId) {
          loadInmuebleDemandas(state.currentInmuebleId);
        }
        const empresa = state.empresas.find((e) => e.nombre === DASHBOARD_COMPANY);
        loadDemandasList(empresa ? empresa.id : "").then(() => {
          populateDemandasSelect(inmuebleVisitaDemanda);
        });
      })
      .catch(() => {
        if (inmuebleDemandaStatus) {
          inmuebleDemandaStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (inmuebleVisitaForm) {
  inmuebleVisitaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (inmuebleVisitaStatus) {
      inmuebleVisitaStatus.textContent = "Guardando...";
    }
    const formData = new FormData(inmuebleVisitaForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = DASHBOARD_COMPANY;
    payload.inmueble_id = state.currentInmuebleId;
    fetch("/api/visitas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (inmuebleVisitaStatus) {
            inmuebleVisitaStatus.textContent = data.error;
          }
          return;
        }
        if (inmuebleVisitaStatus) {
          inmuebleVisitaStatus.textContent = "Guardada.";
        }
        inmuebleVisitaForm.reset();
        const empresa = state.empresas.find((e) => e.nombre === DASHBOARD_COMPANY);
        if (state.currentInmuebleId && empresa) {
          loadInmuebleVisitas(state.currentInmuebleId, empresa.id);
        }
      })
      .catch(() => {
        if (inmuebleVisitaStatus) {
          inmuebleVisitaStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (inmuebleChecklistBtn) {
  inmuebleChecklistBtn.addEventListener("click", () => {
    const etapa = state.currentInmueble?.estado || "";
    if (!etapa) {
      if (inmuebleChecklistInfo) {
        inmuebleChecklistInfo.textContent = "Selecciona una etapa.";
      }
      return;
    }
    generateInmuebleChecklist(etapa);
  });
}

if (inmuebleActividadForm) {
  inmuebleActividadForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.currentInmuebleId) {
      if (inmuebleActividadStatus) {
        inmuebleActividadStatus.textContent = "Selecciona un inmueble.";
      }
      return;
    }
    if (inmuebleActividadStatus) {
      inmuebleActividadStatus.textContent = "Guardando...";
    }
    const formData = new FormData(inmuebleActividadForm);
    const payload = Object.fromEntries(formData.entries());
    Object.assign(
      payload,
      resolveClienteFromInput(inmuebleActividadClienteInput, inmuebleActividadClienteId)
    );
    payload.empresa_nombre = DASHBOARD_COMPANY;
    payload.servicio = "inmobiliaria";
    payload.inmueble_id = state.currentInmuebleId;
    fetch("/api/acciones", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (inmuebleActividadStatus) {
          inmuebleActividadStatus.textContent = data.error || "Guardado.";
        }
        if (!data.error) {
          inmuebleActividadForm.reset();
          const empresa = state.empresas.find((e) => e.nombre === DASHBOARD_COMPANY);
          if (empresa) {
            loadInmuebleActividad(state.currentInmuebleId, empresa.id);
          }
        }
      })
      .catch(() => {
        if (inmuebleActividadStatus) {
          inmuebleActividadStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (inmuebleDocsForm) {
  inmuebleDocsForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.currentInmuebleId) {
      if (inmuebleDocsStatus) {
        inmuebleDocsStatus.textContent = "Selecciona un inmueble.";
      }
      return;
    }
    if (!inmuebleDocsFile || !inmuebleDocsFile.files || !inmuebleDocsFile.files[0]) {
      if (inmuebleDocsStatus) {
        inmuebleDocsStatus.textContent = "Selecciona un archivo.";
      }
      return;
    }
    if (inmuebleDocsStatus) {
      inmuebleDocsStatus.textContent = "Subiendo...";
    }
    const file = inmuebleDocsFile.files[0];
    const formData = new FormData(inmuebleDocsForm);
    const payload = Object.fromEntries(formData.entries());
    payload.inmueble_id = state.currentInmuebleId;
    payload.empresa_nombre = DASHBOARD_COMPANY;
    payload.nombre = payload.nombre || file.name;
    const reader = new FileReader();
    reader.onload = () => {
      payload.file_base64 = reader.result;
      fetch("/api/inmueble_docs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then((res) => res.json())
        .then((data) => {
          if (inmuebleDocsStatus) {
            inmuebleDocsStatus.textContent = data.error || "Documento subido.";
          }
          if (!data.error) {
            inmuebleDocsForm.reset();
            loadInmuebleDocs(state.currentInmuebleId);
          }
        })
        .catch(() => {
          if (inmuebleDocsStatus) {
            inmuebleDocsStatus.textContent = "Error al subir.";
          }
        });
    };
    reader.onerror = () => {
      if (inmuebleDocsStatus) {
        inmuebleDocsStatus.textContent = "No se pudo leer el archivo.";
      }
    };
    reader.readAsDataURL(file);
  });
}

if (gestoriaCrmForm) {
  gestoriaCrmForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (gestoriaCrmStatus) {
      gestoriaCrmStatus.textContent = "Guardando...";
    }
    const formData = new FormData(gestoriaCrmForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = FINCAS_COMPANY;
    payload.usuario = getCurrentUser();
    fetch("/api/gestoria", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (gestoriaCrmStatus) {
            gestoriaCrmStatus.textContent = data.error;
          }
          return;
        }
        if (gestoriaCrmStatus) {
          gestoriaCrmStatus.textContent = "Asignado.";
        }
        gestoriaCrmForm.reset();
        loadGestoriaCrm();
      })
      .catch(() => {
        if (gestoriaCrmStatus) {
          gestoriaCrmStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (gestoriaTrabajoForm) {
  gestoriaTrabajoForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (gestoriaTrabajoStatus) {
      gestoriaTrabajoStatus.textContent = "Guardando...";
    }
    const formData = new FormData(gestoriaTrabajoForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = FINCAS_COMPANY;
    payload.usuario = getCurrentUser();
    if (!payload.cliente_id && state.currentClienteId) {
      payload.cliente_id = state.currentClienteId;
    }
    fetch("/api/gestoria_trabajos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (gestoriaTrabajoStatus) {
            gestoriaTrabajoStatus.textContent = data.error;
          }
          return;
        }
        if (gestoriaTrabajoStatus) {
          gestoriaTrabajoStatus.textContent = "Guardado.";
        }
    let accionFecha = payload.fecha_fin || payload.fecha_inicio || "";
    if (!payload.fecha_fin && payload.fecha_inicio && payload.sla_dias) {
      const base = new Date(payload.fecha_inicio);
      const days = parseInt(payload.sla_dias, 10);
      if (!Number.isNaN(base.getTime()) && !Number.isNaN(days)) {
        const due = new Date(base.getTime() + days * 86400000);
        accionFecha = due.toISOString().slice(0, 10);
      }
    }
        if (accionFecha) {
          const accionPayload = {
            empresa_nombre: FINCAS_COMPANY,
            cliente_id: payload.cliente_id || "",
            fecha: accionFecha,
            tipo: payload.tipo_trabajo || "Gestión",
            estado: "Pendiente",
            servicio: "gestoria",
          };
          fetch("/api/acciones", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(accionPayload),
          }).catch(() => {});
        }
        gestoriaTrabajoForm.reset();
        loadGestoriaTrabajosOverview();
      })
      .catch(() => {
        if (gestoriaTrabajoStatus) {
          gestoriaTrabajoStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (gestoriaAgendaForm) {
  gestoriaAgendaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (gestoriaAgendaStatus) {
      gestoriaAgendaStatus.textContent = "Guardando...";
    }
    const formData = new FormData(gestoriaAgendaForm);
    const payload = Object.fromEntries(formData.entries());
    Object.assign(
      payload,
      resolveClienteFromInput(gestoriaAgendaClienteInput, gestoriaAgendaClienteId)
    );
    payload.empresa_nombre = FINCAS_COMPANY;
    payload.servicio = "gestoria";
    fetch("/api/acciones", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (gestoriaAgendaStatus) {
            gestoriaAgendaStatus.textContent = data.error;
          }
          return;
        }
        if (gestoriaAgendaStatus) {
          gestoriaAgendaStatus.textContent = "Guardado.";
        }
        gestoriaAgendaForm.reset();
        const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
        if (empresa) {
          loadAcciones("gestoria", empresa.id, gestoriaAgendaTable, gestoriaAgendaInfo);
        }
      })
      .catch(() => {
        if (gestoriaAgendaStatus) {
          gestoriaAgendaStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (gestoriaContabilidadForm) {
  gestoriaContabilidadForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (gestoriaContabilidadStatus) {
      gestoriaContabilidadStatus.textContent = "Guardando...";
    }
    const formData = new FormData(gestoriaContabilidadForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = FINCAS_COMPANY;
    fetch("/api/gestoria_contabilidad", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (gestoriaContabilidadStatus) {
          gestoriaContabilidadStatus.textContent = data.error || "Guardado.";
        }
        if (!data.error) {
          gestoriaContabilidadForm.reset();
          loadGestoriaContabilidad();
        }
      })
      .catch(() => {
        if (gestoriaContabilidadStatus) {
          gestoriaContabilidadStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (gestoriaContaConfigForm) {
  gestoriaContaConfigForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.currentClienteId) {
      if (gestoriaContaConfigStatus) {
        gestoriaContaConfigStatus.textContent = "Selecciona un cliente.";
      }
      return;
    }
    if (gestoriaContaConfigStatus) {
      gestoriaContaConfigStatus.textContent = "Guardando...";
    }
    const formData = new FormData(gestoriaContaConfigForm);
    const payload = Object.fromEntries(formData.entries());
    payload.cliente_id = state.currentClienteId;
    fetch("/api/gestoria_conta_config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (gestoriaContaConfigStatus) {
          gestoriaContaConfigStatus.textContent = data.error || "Guardado.";
        }
        if (!data.error) {
          loadGestoriaContaConfig(state.currentClienteId);
        }
      })
      .catch(() => {
        if (gestoriaContaConfigStatus) {
          gestoriaContaConfigStatus.textContent = "Error al guardar.";
        }
      });
  });
  const periodoSelect = gestoriaContaConfigForm.querySelector('[name="periodo"]');
  if (periodoSelect) {
    periodoSelect.addEventListener("change", () => {
      if (state.currentClienteId) {
        loadGestoriaContaTasks(state.currentClienteId, periodoSelect.value);
      }
    });
  }
}

if (gestoriaContaTasksBtn) {
  gestoriaContaTasksBtn.addEventListener("click", () => {
    createGestoriaContaChecklist();
  });
}

if (gestoriaContaQueueBtn) {
  gestoriaContaQueueBtn.addEventListener("click", () => {
    openCompany(FINCAS_COMPANY);
    setTab("gestoria-conta");
    loadGestoriaContabilidad();
    loadGestoriaContaQueue();
  });
}

if (gestoriaContaQueueFilter) {
  gestoriaContaQueueFilter.addEventListener("change", () => {
    loadGestoriaContaQueue();
  });
}


if (segurosAgendaForm) {
  segurosAgendaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (segurosAgendaStatus) {
      segurosAgendaStatus.textContent = "Guardando...";
    }
    const formData = new FormData(segurosAgendaForm);
    const payload = Object.fromEntries(formData.entries());
    Object.assign(
      payload,
      resolveClienteFromInput(segurosAgendaClienteInput, segurosAgendaClienteId)
    );
    payload.empresa_nombre = FINCAS_COMPANY;
    payload.servicio = "seguros";
    fetch("/api/acciones", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (segurosAgendaStatus) {
            segurosAgendaStatus.textContent = data.error;
          }
          return;
        }
        if (segurosAgendaStatus) {
          segurosAgendaStatus.textContent = "Guardado.";
        }
        segurosAgendaForm.reset();
        const empresa = state.empresas.find((e) => e.nombre === FINCAS_COMPANY);
        if (empresa) {
          loadAcciones("seguros", empresa.id, segurosAgendaTable, segurosAgendaInfo);
        }
      })
      .catch(() => {
        if (segurosAgendaStatus) {
          segurosAgendaStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (finAgendaForm) {
  finAgendaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (finAgendaStatus) {
      finAgendaStatus.textContent = "Guardando...";
    }
    const formData = new FormData(finAgendaForm);
    const payload = Object.fromEntries(formData.entries());
    Object.assign(
      payload,
      resolveClienteFromInput(finAgendaClienteInput, finAgendaClienteId)
    );
    payload.empresa_nombre = FIN_COMPANY;
    payload.servicio = "financiaciones";
    fetch("/api/acciones", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (finAgendaStatus) {
            finAgendaStatus.textContent = data.error;
          }
          return;
        }
        if (finAgendaStatus) {
          finAgendaStatus.textContent = "Guardado.";
        }
        finAgendaForm.reset();
        const empresa = state.empresas.find((e) => e.nombre === FIN_COMPANY);
        if (empresa) {
          loadAcciones("financiaciones", empresa.id, finAgendaTable, finAgendaInfo);
        }
      })
      .catch(() => {
        if (finAgendaStatus) {
          finAgendaStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (empresaSelect) {
  empresaSelect.addEventListener("change", () => {
    if (state.currentModule === "clientes") {
      loadClientesTable();
      return;
    }
    const empresaName = state.empresas.find((e) => e.id === empresaSelect.value)?.nombre || "";
    state.currentEmpresaId = empresaSelect.value;
    state.currentEmpresaName = empresaName;
    updateExplorerHeader(empresaName);
    populateTables();
    ensureOperativaTable();
    updateTableVisibility();
    loadTable();
    if (empresaName === FINCAS_COMPANY && currentTab === "gestoria-crm") {
      loadGestoriaCrm();
    }
  });
}

init();

populateGestoriaSubtipos("");

if (yearSelect) {
  yearSelect.addEventListener("change", () => {
    const selectedYear = yearSelect.value;
    loadHomeFincasStats(selectedYear).then(() => renderCompanyCards());
    if (state.currentEmpresaName === FINCAS_COMPANY && currentTab === "seguros-crm") {
      renderFincasDashboard(state.currentEmpresaId);
    }
    updateCompanySummary(state.currentEmpresaName || (state.currentModule === "clientes" ? "Clientes" : ""));
  });
}

window.addEventListener("popstate", () => {
  handleRoute();
});

if (bdtForm) {
  bdtForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (bdtFormStatus) {
      bdtFormStatus.textContent = "Guardando...";
    }
    const formData = new FormData(bdtForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = DASHBOARD_COMPANY;
    fetch("/api/movimientos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (bdtFormStatus) {
            bdtFormStatus.textContent = data.error;
          }
          return;
        }
        if (bdtFormStatus) {
          bdtFormStatus.textContent = "Guardado.";
        }
        bdtForm.reset();
        const now = new Date();
        if (bdtForm.anio) {
          bdtForm.anio.value = now.getFullYear();
        }
        if (bdtForm.mes) {
          bdtForm.mes.value = now.toLocaleString("es-ES", { month: "long" });
        }
        if (bdtForm.sl) {
          bdtForm.sl.value = "Estudio Velazquez";
        }
        // refresh dashboard without changing tabs
        const empresa = state.empresas.find(
          (item) => item.nombre === DASHBOARD_COMPANY
        );
        if (empresa) {
          renderDashboard(empresa.nombre, empresa.id);
        }
      })
      .catch(() => {
        if (bdtFormStatus) {
          bdtFormStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (captacionForm) {
  bindPostalLookup(captacionForm);
  captacionForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (captacionFormStatus) {
      captacionFormStatus.textContent = "Guardando...";
    }
    const formData = new FormData(captacionForm);
    const payload = Object.fromEntries(formData.entries());
    if (captacionPropietarios) {
      payload.propietarios = Array.from(captacionPropietarios.selectedOptions).map(
        (option) => option.value
      );
    }
    payload.empresa_nombre = DASHBOARD_COMPANY;
    fetch("/api/captaciones", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (captacionFormStatus) {
            captacionFormStatus.textContent = data.error;
          }
          return;
        }
        if (captacionFormStatus) {
          captacionFormStatus.textContent = "Guardado.";
        }
        captacionForm.reset();
        loadCrmCaptaciones();
        loadCrmInmuebles();
      })
      .catch(() => {
        if (captacionFormStatus) {
          captacionFormStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (demandaForm) {
  demandaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (demandaFormStatus) {
      demandaFormStatus.textContent = "Guardando...";
    }
    const formData = new FormData(demandaForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = DASHBOARD_COMPANY;
    fetch("/api/demandas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (demandaFormStatus) {
            demandaFormStatus.textContent = data.error;
          }
          return;
        }
        if (demandaFormStatus) {
          demandaFormStatus.textContent = "Guardado.";
        }
        demandaForm.reset();
        loadCrmDemandas();
        const empresa = state.empresas.find((e) => e.nombre === DASHBOARD_COMPANY);
        loadDemandasList(empresa ? empresa.id : "").then(() => {
          populateDemandasSelect(inmuebleVisitaDemanda);
          if (state.currentInmuebleId) {
            loadInmuebleDemandas(state.currentInmuebleId);
          }
        });
      })
      .catch(() => {
        if (demandaFormStatus) {
          demandaFormStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (visitaForm) {
  visitaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (visitaFormStatus) {
      visitaFormStatus.textContent = "Guardando...";
    }
    const formData = new FormData(visitaForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = DASHBOARD_COMPANY;
    fetch("/api/visitas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (visitaFormStatus) {
            visitaFormStatus.textContent = data.error;
          }
          return;
        }
        if (visitaFormStatus) {
          visitaFormStatus.textContent = "Guardada.";
        }
        visitaForm.reset();
        loadCrmVisitas();
      })
      .catch(() => {
        if (visitaFormStatus) {
          visitaFormStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (fincasBdtForm) {
  fincasBdtForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (fincasBdtFormStatus) {
      fincasBdtFormStatus.textContent = "Guardando...";
    }
    const formData = new FormData(fincasBdtForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = FINCAS_COMPANY;
    fetch("/api/movimientos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (fincasBdtFormStatus) {
            fincasBdtFormStatus.textContent = data.error;
          }
          return;
        }
        if (fincasBdtFormStatus) {
          fincasBdtFormStatus.textContent = "Guardado.";
        }
        fincasBdtForm.reset();
        const now = new Date();
        if (fincasBdtForm.anio) {
          fincasBdtForm.anio.value = now.getFullYear();
        }
        if (fincasBdtForm.mes) {
          fincasBdtForm.mes.value = now.toLocaleString("es-ES", { month: "long" });
        }
        if (fincasBdtForm.sl) {
          fincasBdtForm.sl.value = "Fincas Velazquez";
        }
      })
      .catch(() => {
        if (fincasBdtFormStatus) {
          fincasBdtFormStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (gestoriaAltaForm) {
  bindPostalLookup(gestoriaAltaForm);
  const updateGestoriaAltaPersona = () => {
    if (!gestoriaAltaTipoPersona || !gestoriaAltaPersonaFields.length) {
      return;
    }
    const isJuridica =
      String(gestoriaAltaTipoPersona.value || "").toLowerCase() === "jurídica";
    gestoriaAltaPersonaFields.forEach((field) => {
      field.classList.toggle("hidden", isJuridica);
    });
  };
  updateGestoriaAltaPersona();
  if (gestoriaAltaTipoPersona) {
    gestoriaAltaTipoPersona.addEventListener("change", updateGestoriaAltaPersona);
  }
  gestoriaAltaForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (gestoriaAltaStatus) {
      gestoriaAltaStatus.textContent = "Guardando...";
    }
    const formData = new FormData(gestoriaAltaForm);
    const payload = Object.fromEntries(formData.entries());
    const fincas = state.empresas.find((empresa) => empresa.nombre === FINCAS_COMPANY);
    if (!fincas) {
      if (gestoriaAltaStatus) {
        gestoriaAltaStatus.textContent = "Empresa gestoría no encontrada.";
      }
      return;
    }
    const clienteId = randomId();
    const clientePayload = {
      id: clienteId,
      tipo_persona: payload.tipo_persona || "Física",
      apellido1: payload.apellido1 || "",
      apellido2: payload.apellido2 || "",
      nombre: payload.nombre || "",
      nif: payload.nif || "",
      telefono: payload.telefono || "",
      email: payload.email || "",
      direccion: payload.direccion || "",
      codigo_postal: payload.codigo_postal || "",
      poblacion: payload.poblacion || "",
      provincia: payload.provincia || "",
    };
    if (!String(clientePayload.nombre).trim()) {
      if (gestoriaAltaStatus) {
        gestoriaAltaStatus.textContent = "Indica el nombre o razón social.";
      }
      return;
    }
    try {
      const clienteRes = await fetch("/api/clientes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(clientePayload),
      });
      const clienteData = await clienteRes.json();
      if (clienteData.error) {
        if (gestoriaAltaStatus) gestoriaAltaStatus.textContent = clienteData.error;
        return;
      }
      await fetch("/api/clientes_link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cliente_id: clienteId,
          empresa_id: fincas.id,
          servicio: "Gestoría",
          estado: payload.estado || "Alta",
          fecha_inicio: payload.fecha || "",
          fecha_fin: payload.fecha_baja || "",
        }),
      });
      await fetch("/api/gestoria", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          empresa_nombre: FINCAS_COMPANY,
          cliente: buildDisplayName(clientePayload),
          fecha: payload.fecha || "",
          cuota: payload.cuota || "",
          precio: payload.precio || "",
          tipo: payload.tipo || "",
          perfil: payload.perfil || "",
          estado: payload.estado || "",
          fecha_baja: payload.fecha_baja || "",
        }),
      });
      if (gestoriaAltaStatus) {
        gestoriaAltaStatus.textContent = "Cliente creado y asignado.";
      }
      gestoriaAltaForm.reset();
      updateGestoriaAltaPersona();
      loadGestoriaCrm();
      loadClientesList();
    } catch (error) {
      if (gestoriaAltaStatus) {
        gestoriaAltaStatus.textContent = "Error al guardar.";
      }
    }
  });
}

if (fincasSegurosForm) {
  fincasSegurosForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (fincasSegurosFormStatus) {
      fincasSegurosFormStatus.textContent = "Guardando...";
    }
    const formData = new FormData(fincasSegurosForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = FINCAS_COMPANY;
    fetch("/api/seguros", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (fincasSegurosFormStatus) {
            fincasSegurosFormStatus.textContent = data.error;
          }
          return;
        }
        if (fincasSegurosFormStatus) {
          fincasSegurosFormStatus.textContent = "Guardado.";
        }
        fincasSegurosForm.reset();
        const now = new Date();
        if (fincasSegurosForm.mes_creacion) {
          fincasSegurosForm.mes_creacion.value = now.toLocaleString("es-ES", { month: "long" });
        }
        loadFincasRenewalAlert();
      })
      .catch(() => {
        if (fincasSegurosFormStatus) {
          fincasSegurosFormStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (clientesForm) {
  bindPostalLookup(clientesForm);
  clientesForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (clientesFormStatus) {
      clientesFormStatus.textContent = "Guardando...";
    }
    const formData = new FormData(clientesForm);
    const payload = Object.fromEntries(formData.entries());
    const tipoPersona = payload.tipo_persona || "Física";
    const nombreBase = String(payload.nombre || "").trim();
    const apellido1 = String(payload.apellido1 || "").trim();
    const apellido2 = String(payload.apellido2 || "").trim();
    if (String(tipoPersona).toLowerCase() === "jurídica") {
      if (!nombreBase) {
        if (clientesFormStatus) {
          clientesFormStatus.textContent = "Indica la razón social.";
        }
        return;
      }
    } else {
      if (!apellido1 || !nombreBase) {
        if (clientesFormStatus) {
          clientesFormStatus.textContent = "Indica apellido 1 y nombre.";
        }
        return;
      }
    }
    if (payload.nif) {
      const nif = normalizeDocumento(payload.nif);
      if (!isValidDocumento(nif)) {
        if (clientesFormStatus) {
          clientesFormStatus.textContent = "DNI/NIF/CIF no válido.";
        }
        return;
      }
      payload.nif = nif;
    }
    if (String(tipoPersona).toLowerCase() === "jurídica") {
      payload.nombre = nombreBase;
    } else {
      const apellidos = [apellido1, apellido2].filter(Boolean).join(" ").trim();
      payload.nombre = apellidos || nombreBase
        ? `${apellidos}${apellidos && nombreBase ? ", " : ""}${nombreBase}`.trim()
        : "";
    }
    delete payload.apellido1;
    delete payload.apellido2;
    const newClienteId = randomId();
    payload.id = newClienteId;
    fetch("/api/clientes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (clientesFormStatus) {
            clientesFormStatus.textContent = data.error;
          }
          return;
        }
        if (clientesFormStatus) {
          clientesFormStatus.textContent = "Guardado. Vincula servicios abajo si aplica.";
        }
        state.lastCreatedClientId = data.id || newClienteId;
        clientesForm.reset();
        updateClienteAltaPersona();
        Promise.all([loadClientesStats(), loadClientesList()]).then(([_, list]) => {
          renderClientesSelects(list);
          renderCompanyCards();
          if (state.currentModule === "clientes") {
            loadClientesTable();
          }
        });
      })
      .catch(() => {
        if (clientesFormStatus) {
          clientesFormStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (clienteTipoPersona) {
  clienteTipoPersona.addEventListener("change", updateClienteAltaPersona);
  updateClienteAltaPersona();
}

if (clientesLinkAdd) {
  clientesLinkAdd.addEventListener("click", () => {
    buildClientesLinkRow();
  });
}

if (clientesLinkForm) {
  clientesLinkForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (clientesLinkFormStatus) {
      clientesLinkFormStatus.textContent = "Guardando...";
    }
    const clienteId = clientesSelect && clientesSelect.value
      ? clientesSelect.value
      : (state.currentClienteId || state.lastCreatedClientId || "");
    if (!clienteId) {
      if (clientesLinkFormStatus) {
        clientesLinkFormStatus.textContent = "Guarda el cliente primero.";
      }
      return;
    }
    const rows = Array.from(
      clientesLinkRows ? clientesLinkRows.querySelectorAll(".link-row") : []
    )
      .map((row) => {
        const getVal = (field) => row.querySelector(`[data-field="${field}"]`)?.value || "";
        return {
          empresa_id: getVal("empresa_id"),
          servicio: getVal("servicio"),
          estado: getVal("estado") || "Activo",
          fecha_inicio: getVal("fecha_inicio"),
          fecha_fin: getVal("fecha_fin"),
        };
      })
      .filter((row) => row.empresa_id && row.servicio);

    if (!rows.length) {
      if (clientesLinkFormStatus) {
        clientesLinkFormStatus.textContent = "Añade al menos un servicio válido.";
      }
      return;
    }
    Promise.all(
      rows.map((row) =>
        fetch("/api/clientes_link", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            cliente_id: clienteId,
            ...row,
          }),
        }).then((res) => res.json())
      )
    )
      .then((results) => {
        const error = results.find((r) => r && r.error);
        if (error) {
          if (clientesLinkFormStatus) {
            clientesLinkFormStatus.textContent = error.error;
          }
          return;
        }
        if (clientesLinkFormStatus) {
          clientesLinkFormStatus.textContent = "Servicios vinculados.";
        }
        if (clientesLinkRows) {
          clientesLinkRows.innerHTML = "";
        }
        buildClientesLinkRow();
        if (state.lastCreatedClientId === clienteId) {
          state.lastCreatedClientId = "";
        }
        loadClientesTable();
      })
      .catch(() => {
        if (clientesLinkFormStatus) {
          clientesLinkFormStatus.textContent = "Error al vincular.";
        }
      });
  });
}

if (clientesServicioSelect) {
  clientesServicioSelect.addEventListener("change", () => {
    syncEmpresaFromServicio(clientesServicioSelect.value);
  });
}

if (clienteAssignServicio) {
  clienteAssignServicio.addEventListener("change", () => {
    syncAssignEmpresaFromServicio(clienteAssignServicio.value);
  });
}

if (aieForm) {
  aieForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (aieFormStatus) {
      aieFormStatus.textContent = "Guardando...";
    }
    const formData = new FormData(aieForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = AIE_COMPANY;
    payload.tipo = "Gasto";
    payload.sl = "Inmovere Gestión AIE";
    const year = Number(payload.anio);
    const monthIndex = [
      "enero",
      "febrero",
      "marzo",
      "abril",
      "mayo",
      "junio",
      "julio",
      "agosto",
      "septiembre",
      "octubre",
      "noviembre",
      "diciembre",
    ].indexOf(String(payload.mes).toLowerCase());
    if (Number.isNaN(year) || year < 2026 || (year === 2026 && monthIndex < 1)) {
      if (aieFormStatus) {
        aieFormStatus.textContent = "Solo desde Febrero 2026.";
      }
      return;
    }
    fetch("/api/movimientos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (aieFormStatus) {
            aieFormStatus.textContent = data.error;
          }
          return;
        }
        if (aieFormStatus) {
          aieFormStatus.textContent = "Guardado.";
        }
        aieForm.reset();
      })
      .catch(() => {
        if (aieFormStatus) {
          aieFormStatus.textContent = "Error al guardar.";
        }
      });
  });
}

if (hipotecaForm) {
  const comisionInput = hipotecaForm.querySelector("input[name='comision']");
  const comisionJuanInput = hipotecaForm.querySelector("input[name='comision_juan']");
  const comisionModerniaInput = hipotecaForm.querySelector("input[name='comision_modernia']");
  const cesionInput = hipotecaForm.querySelector("input[name='cesion']");
  const oficinaInput = hipotecaForm.querySelector("input[name='oficina']");
  const precioInput = hipotecaForm.querySelector("input[name='precio']");
  const hipotecaInput = hipotecaForm.querySelector("input[name='importe_hipoteca']");
  const porcentajeInput = hipotecaForm.querySelector("input[name='porcentaje']");
  const entradaInput = hipotecaForm.querySelector("input[name='entrada']");
  const groupOffices = new Set([
    "malaga norte",
    "málaga norte",
    "malaga centro",
    "málaga centro",
    "malaga oeste",
    "málaga oeste",
    "malaga valle del guadalhorce",
    "málaga valle del guadalhorce",
  ]);

  const normalizeText = (value) =>
    String(value || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .trim();

  const updateCommissions = () => {
    if (!comisionInput) return;
    const total = Number(comisionInput.value);
    if (Number.isNaN(total)) {
      return;
    }
    if (comisionJuanInput) {
      comisionJuanInput.value = (total * 0.2).toFixed(2);
    }
    const oficina = normalizeText(oficinaInput?.value || "");
    const cesionRate = groupOffices.has(oficina) ? 0.25 : 0.2;
    if (cesionInput) {
      cesionInput.value = (total * cesionRate).toFixed(2);
    }
    if (comisionModerniaInput) {
      const juan = total * 0.2;
      const cesion = total * cesionRate;
      const modernia = Math.max(total - juan - cesion, 0);
      comisionModerniaInput.value = modernia.toFixed(2);
    }
  };

  const updateFinanciacion = () => {
    const precio = Number(precioInput?.value);
    const hipoteca = Number(hipotecaInput?.value);
    if (!Number.isNaN(precio) && precio > 0 && !Number.isNaN(hipoteca)) {
      if (porcentajeInput) {
        porcentajeInput.value = ((hipoteca / precio) * 100).toFixed(2);
      }
      if (entradaInput) {
        entradaInput.value = (precio - hipoteca).toFixed(2);
      }
    }
  };

  if (comisionInput && comisionJuanInput) {
    comisionInput.addEventListener("input", updateCommissions);
  }
  if (oficinaInput) {
    oficinaInput.addEventListener("input", updateCommissions);
  }
  if (precioInput) {
    precioInput.addEventListener("input", updateFinanciacion);
  }
  if (hipotecaInput) {
    hipotecaInput.addEventListener("input", updateFinanciacion);
  }
  hipotecaForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (hipotecaFormStatus) {
      hipotecaFormStatus.textContent = "Guardando...";
    }
    const formData = new FormData(hipotecaForm);
    const payload = Object.fromEntries(formData.entries());
    payload.empresa_nombre = FIN_COMPANY;
    if (!payload.anio && payload.fecha_firma) {
      payload.anio = String(payload.fecha_firma).slice(0, 4);
    }
    fetch("/api/hipotecas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          if (hipotecaFormStatus) {
            hipotecaFormStatus.textContent = data.error;
          }
          return;
        }
        if (hipotecaFormStatus) {
          hipotecaFormStatus.textContent = "Guardado.";
        }
        hipotecaForm.reset();
        loadHomeHipotecaStats().then(() => renderCompanyCards());
      })
      .catch(() => {
        if (hipotecaFormStatus) {
          hipotecaFormStatus.textContent = "Error al guardar.";
        }
      });
  });
}

window.addEventListener("resize", () => {
  if (lastDashboardData && dashboardSection && !dashboardSection.classList.contains("hidden")) {
    const ventasYears = buildYearIndex([lastDashboardData.ventas]);
    const facturadoYears = buildYearIndex([lastDashboardData.ingresos, lastDashboardData.gastos]);
    const alquilerYears = buildYearIndex([lastDashboardData.alquileres]);
    drawBarChart(
      ventasChart,
      ventasYears,
      [
        {
          label: "Ventas",
          values: alignSeries(ventasYears, lastDashboardData.ventas),
          color: "#824c45",
          format: (value) => numberFormatter.format(value),
        },
      ],
      { legend: false, showValues: true }
    );
    drawBarChart(
      facturadoChart,
      facturadoYears,
      [
        {
          label: "Facturado",
          values: alignSeries(facturadoYears, lastDashboardData.ingresos),
          color: "#d7b04c",
          format: (value) => euroFormatter.format(value),
        },
        {
          label: "Gastos",
          values: alignSeries(facturadoYears, lastDashboardData.gastos),
          color: "#7e8878",
          format: (value) => euroFormatter.format(value),
        },
      ],
      { legend: true, showValues: true }
    );
    drawBarChart(
      alquileresChart,
      alquilerYears,
      [
        {
          label: "Alquileres",
          values: alignSeries(alquilerYears, lastDashboardData.alquileres),
          color: "#cca33c",
          format: (value) => numberFormatter.format(value),
        },
      ],
      { legend: false, showValues: true }
    );
    const ventasVar = computeVariations(lastDashboardData.ventas);
    const alquilerVar = computeVariations(lastDashboardData.alquileres);
    const facturadoVar = computeVariations(lastDashboardData.ingresos);
    drawSignedBarChart(
      ventasVarChart,
      ventasVar.map((item) => item.year),
      ventasVar.map((item) => item.total),
      "#824c45"
    );
    drawSignedBarChart(
      alquileresVarChart,
      alquilerVar.map((item) => item.year),
      alquilerVar.map((item) => item.total),
      "#cca33c"
    );
    drawSignedBarChart(
      facturadoVarChart,
      facturadoVar.map((item) => item.year),
      facturadoVar.map((item) => item.total),
      "#d7b04c"
    );
  }
});
