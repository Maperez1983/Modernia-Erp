(function () {
  function handleRoute(deps) {
    const params = new URLSearchParams(window.location.search);
    if (params.has("firma_inmo")) {
      deps.openInmuebleSignaturePublic?.(params.get("firma_inmo") || "");
      deps.ui?.refreshContext(deps.state);
      return;
    }
    if (params.has("portal_inmo")) {
      deps.openInmobiliariaPortalPublic?.(params.get("id") || "");
      deps.ui?.refreshContext(deps.state);
      return;
    }
    if (params.has("portal_token")) {
      deps.openWorkspacePortalPublic(params.get("portal_token") || "");
      deps.ui?.refreshContext(deps.state);
      return;
    }
    if (params.has("agenda")) {
      deps.openAgenda();
      deps.ui?.refreshContext(deps.state);
      return;
    }
    if (params.has("admin")) {
      deps.openAdmin();
      deps.ui?.refreshContext(deps.state);
      return;
    }
    if (params.has("clientes")) {
      deps.openClientesModule();
      deps.ui?.refreshContext(deps.state);
      return;
    }
    const slug = params.get("empresa");
    if (slug && !params.has("crm") && (params.has("holding") || params.has("workspace") || params.has("conta")) && typeof deps.openWorkspaceCompanyFicha === "function") {
      const pools = [
        ...(Array.isArray(deps.state?.currentWorkspaceDetail?.companies) ? deps.state.currentWorkspaceDetail.companies : []),
        ...(Array.isArray(deps.state?.currentWorkspaceDetail?.companies_v2) ? deps.state.currentWorkspaceDetail.companies_v2 : []),
        ...(Array.isArray(deps.state?.empresas) ? deps.state.empresas : []),
      ];
      const empresa = pools.find((item) => deps.slugify(String(item?.nombre || item?.razon_social || item?.name || "")) === slug) || null;
      deps.openWorkspaceCompanyFicha(String(empresa?.id || empresa?.legacy_empresa_id || slug).trim(), params.get("conta") || "dashboard");
      deps.ui?.refreshContext(deps.state);
      return;
    }
    if (slug) {
      const pools = [
        ...(Array.isArray(deps.state?.currentWorkspaceDetail?.companies) ? deps.state.currentWorkspaceDetail.companies : []),
        ...(Array.isArray(deps.state?.currentWorkspaceDetail?.companies_v2) ? deps.state.currentWorkspaceDetail.companies_v2 : []),
        ...(Array.isArray(deps.state?.empresas) ? deps.state.empresas : []),
      ];
      const empresa = pools.find((item) => deps.slugify(String(item?.nombre || item?.razon_social || item?.name || "")) === slug) || null;
      if (empresa && typeof deps.openCompany === "function") {
        deps.openCompany(String(empresa.nombre || empresa.razon_social || slug).trim());
        deps.ui?.refreshContext(deps.state);
        return;
      }
    }
    if (params.has("holding")) {
      const mode = (params.get("mode") || "platform").toLowerCase() === "tenant" ? "tenant" : "platform";
      const requestedView = (params.get("view") || "").trim();
      const requestedEngine = (params.get("engine") || "").trim();
      const requestedRrhh = (params.get("rrhh") || "").trim();
      const requestedPersona = (params.get("persona") || "").trim();
      deps.openHolding({
        mode,
        workspace: params.get("workspace") || "",
        // Allow deep links inside tenant mode (e.g. Motores/Registro horario).
        view: requestedView || (mode === "tenant" ? "overview" : "overview"),
        engine: requestedEngine || "",
        rrhh: requestedRrhh || "",
        persona: requestedPersona || "",
      });
      deps.ui?.refreshContext(deps.state);
      return;
    }
    if (params.has("crm")) {
      const crm = params.get("crm");
      if (crm === "inmo") {
        deps.openCrmInmobiliario();
        const inmuebleId = (params.get("inmueble") || "").trim();
        const captacionId = (params.get("captacion") || "").trim();
        if (inmuebleId && typeof deps.openInmuebleDetail === "function") {
          setTimeout(() => {
            deps.openInmuebleDetail(inmuebleId, "resumen");
            deps.ui?.refreshContext(deps.state);
          }, 250);
          return;
        }
        if (captacionId && typeof deps.openInmuebleFromCaptacion === "function") {
          setTimeout(() => {
            deps.openInmuebleFromCaptacion(captacionId, "captaciones");
            deps.ui?.refreshContext(deps.state);
          }, 250);
          return;
        }
        deps.ui?.refreshContext(deps.state);
        return;
      }
      if (crm === "gestoria") {
        const requestedTab = (params.get("tab") || "").trim();
        if (requestedTab && typeof deps.openGestoriaServiceTab === "function") {
          deps.openGestoriaServiceTab(requestedTab);
          deps.ui?.refreshContext(deps.state);
          return;
        }
        deps.openGestoriaCrm();
        deps.ui?.refreshContext(deps.state);
        return;
      }
      if (crm === "seguros") {
        deps.openSegurosCrm();
        deps.ui?.refreshContext(deps.state);
        return;
      }
      if (crm === "fin") {
        const requestedTab = (params.get("tab") || "").trim();
        if (requestedTab && typeof deps.openFinServiceTab === "function") {
          deps.openFinServiceTab(requestedTab);
          deps.ui?.refreshContext(deps.state);
          return;
        }
        deps.openFinCrm();
        deps.ui?.refreshContext(deps.state);
        return;
      }
    }
    if (params.has("cliente")) {
      const id = params.get("cliente");
      if (params.has("poliza")) {
        const polizaId = params.get("poliza");
        deps.openClientesModule();
        deps.openClienteDetail(id);
        setTimeout(() => {
          deps.openSeguroById(polizaId, id);
          deps.ui?.refreshContext(deps.state);
        }, 250);
        return;
      }
      deps.openClientesModule();
      deps.openClienteDetail(id);
      deps.ui?.refreshContext(deps.state);
      return;
    }
    if (params.has("poliza")) {
      const polizaId = params.get("poliza");
      deps.openSegurosCrm();
      setTimeout(() => {
        deps.openSeguroById(polizaId);
        deps.ui?.refreshContext(deps.state);
      }, 250);
      return;
    }
    deps.goHome();
    deps.ui?.refreshContext(deps.state);
  }

  window.CRMAppRouting = {
    handleRoute,
  };
})();
