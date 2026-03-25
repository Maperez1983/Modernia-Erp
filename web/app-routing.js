(function () {
  function handleRoute(deps) {
    const params = new URLSearchParams(window.location.search);
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
    if (params.has("holding")) {
      deps.openHolding();
      deps.ui?.refreshContext(deps.state);
      return;
    }
    if (params.has("clientes")) {
      deps.openClientesModule();
      deps.ui?.refreshContext(deps.state);
      return;
    }
    if (params.has("crm")) {
      const crm = params.get("crm");
      if (crm === "inmo") {
        deps.openCrmInmobiliario();
        deps.ui?.refreshContext(deps.state);
        return;
      }
      if (crm === "gestoria") {
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
    const slug = params.get("empresa");
    if (slug) {
      const empresa = deps.state.empresas.find((item) => deps.slugify(item.nombre) === slug);
      if (empresa) {
        deps.openCompany(empresa.nombre);
        deps.ui?.refreshContext(deps.state);
        return;
      }
    }
    deps.goHome();
    deps.ui?.refreshContext(deps.state);
  }

  window.CRMAppRouting = {
    handleRoute,
  };
})();
