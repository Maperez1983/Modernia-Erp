(function () {
  const DEEP_LINK_KEYS = ["activar_token", "portal_token", "firma_inmo", "token"];
  const SESSION_STATE_ENDPOINT = "/api/session_state";
  let authLoginBusy = false;
  let authRecoveryBusy = false;

  const getDeepLinkParams = () => {
    const params = new URLSearchParams(window.location.search || "");
    const hash = String(window.location.hash || "").replace(/^#/, "");
    if (hash) {
      const hashParams = new URLSearchParams(hash);
      hashParams.forEach((value, key) => {
        if (!params.has(key)) {
          params.set(key, value);
        }
      });
    }
    return params;
  };

  const getDeepLinkParam = (name) => {
    const params = getDeepLinkParams();
    return String(params.get(name) || "").trim();
  };

  window.CRMDeepLink = window.CRMDeepLink || {};
  Object.assign(window.CRMDeepLink, {
    getParams: getDeepLinkParams,
    getParam: getDeepLinkParam,
    keys: DEEP_LINK_KEYS.slice(),
  });

  function getLoginSubmitButton(deps) {
    return deps?.authLoginForm?.querySelector?.('button[type="submit"]') || null;
  }

  function setLoginBusyState(deps, busy) {
    authLoginBusy = Boolean(busy);
    const submitBtn = getLoginSubmitButton(deps);
    if (submitBtn) {
      submitBtn.disabled = authLoginBusy;
      submitBtn.setAttribute("aria-busy", authLoginBusy ? "true" : "false");
    }
    if (deps?.authLoginForm) {
      deps.authLoginForm.dataset.busy = authLoginBusy ? "1" : "";
    }
  }

  function setRecoveryBusyState(btn, busy) {
    if (!btn) return;
    const baseLabel = String(btn.dataset.baseLabel || btn.textContent || "Recuperar acceso").trim() || "Recuperar acceso";
    btn.dataset.baseLabel = baseLabel;
    btn.disabled = Boolean(busy);
    btn.setAttribute("aria-busy", busy ? "true" : "false");
    btn.textContent = busy ? "Preparando..." : baseLabel;
  }

  function ensureRecoveryButton(deps) {
    if (deps.authRecoveryBtn && deps.authRecoveryBtn.isConnected) return deps.authRecoveryBtn;
    const status = deps.authLoginStatus;
    if (!status || !status.parentElement) return null;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "secondary-btn";
    btn.textContent = "Recuperar acceso";
    btn.dataset.baseLabel = btn.textContent;
    btn.style.display = "none";
    btn.style.marginLeft = "8px";
    btn.addEventListener("click", async () => {
      if (authRecoveryBusy || btn.disabled) return;
      const login = String(btn.dataset.login || "").trim();
      if (!login) return;
      authRecoveryBusy = true;
      setRecoveryBusyState(btn, true);
      if (deps.authLoginStatus) deps.authLoginStatus.textContent = "Preparando recuperación de acceso...";
      try {
        const res = await fetch("/api/auth_request_access_recovery", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ login }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data?.error) {
          if (deps.authLoginStatus) deps.authLoginStatus.textContent = data?.error || "No se pudo preparar la recuperación.";
          return;
        }
        if (deps.authLoginStatus) {
          const main = String(data?.message || "Recuperación preparada.").trim();
          const hint = String(data?.recovery_message || "").trim();
          deps.authLoginStatus.textContent = `${main} ${hint}`.trim();
        }
      } catch {
        if (deps.authLoginStatus) deps.authLoginStatus.textContent = "Error de conexión al preparar la recuperación.";
      } finally {
        authRecoveryBusy = false;
        setRecoveryBusyState(btn, false);
      }
    });
    status.parentElement.appendChild(btn);
    deps.authRecoveryBtn = btn;
    return btn;
  }

  function hideRecoveryButton(deps) {
    const btn = deps.authRecoveryBtn;
    if (!btn) return;
    btn.style.display = "none";
    btn.dataset.login = "";
    setRecoveryBusyState(btn, false);
  }

  function showRecoveryButton(deps, login) {
    const btn = ensureRecoveryButton(deps);
    if (!btn) return;
    if (!btn.dataset.baseLabel) {
      btn.dataset.baseLabel = btn.textContent || "Recuperar acceso";
    }
    btn.dataset.login = String(login || "").trim();
    btn.style.display = btn.dataset.login ? "" : "none";
    setRecoveryBusyState(btn, false);
  }

  async function waitForHealth(deps, options) {
    const maxMs = Math.max(5000, Number(options?.maxMs || 120000) || 120000);
    const reqTimeoutMs = Math.max(1500, Number(options?.requestTimeoutMs || 10000) || 10000);
    const started = Date.now();
    let attempt = 0;
    let lastDetail = "";
    while (Date.now() - started < maxMs) {
      attempt += 1;
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), reqTimeoutMs);
        try {
          const res = await fetch("/api/health", { cache: "no-store", credentials: "same-origin", signal: controller.signal });
          if (res && res.ok) {
            try { deps._lastHealthDetail = ""; } catch {}
            return true;
          }
          if (res && res.status === 503) {
            try {
              lastDetail = (await res.text()) || "";
            } catch {
              lastDetail = "";
            }
            try { deps._lastHealthDetail = lastDetail; } catch {}
            if (deps?.authLoginStatus && lastDetail) {
              const clean = String(lastDetail || "").trim();
              if (clean.toLowerCase().startsWith("bootstrapping")) {
                deps.authLoginStatus.textContent = `Arrancando base de datos… ${clean}`;
              } else {
                deps.authLoginStatus.textContent = `Base de datos no disponible. ${clean}`;
              }
            }
          }
        } finally {
          clearTimeout(timer);
        }
      } catch {}
      const delay = Math.min(7000, 250 * Math.pow(1.8, attempt));
      if (deps?.authLoginStatus) {
        const remaining = Math.max(0, maxMs - (Date.now() - started));
        const remainingLabel = remaining ? `${Math.ceil(remaining / 1000)}s` : "";
        deps.authLoginStatus.textContent = attempt <= 2
          ? "Arrancando servidor... (Render puede tardar 1-2 min)"
          : `Arrancando servidor... reintento en ${Math.round(delay / 1000)}s · queda ${remainingLabel}`;
      }
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
    return false;
  }

  async function fetchCurrentSessionUser() {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 4500);
      let res;
      try {
        res = await fetch(SESSION_STATE_ENDPOINT, {
          cache: "no-store",
          credentials: "same-origin",
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timer);
      }
      let data = null;
      try {
        data = await res.json();
      } catch {
        data = null;
      }
      if (!res.ok) {
        return null;
      }
      return data?.user || null;
    } catch {
      return null;
    }
  }

  async function ensureAuthAndBoot(deps) {
    const params = getDeepLinkParams();
    const activateToken = (params.get("activar_token") || "").trim();
    const portalToken = (params.get("portal_token") || "").trim();
    if (activateToken) {
      const healthy = await waitForHealth(deps, { maxMs: 120000, requestTimeoutMs: 12000 });
      if (!healthy) {
        const detail = String(deps?._lastHealthDetail || "").trim();
        deps.showActivationOverlay("Servidor arrancando…");
        if (deps.authActivateStatus) {
          deps.authActivateStatus.textContent = detail
            ? `Base de datos no disponible. ${detail}`
            : "Servidor arrancando (Render puede tardar 1-2 min). Espera unos segundos y recarga.";
        }
        try { document.body.classList.remove("auth-pending"); } catch {}
        return;
      }
      await deps.prepareActivationFlow(activateToken);
      try { document.body.classList.remove("auth-pending"); } catch {}
      return;
    }
    if (portalToken) {
      const healthy = await waitForHealth(deps, { maxMs: 120000, requestTimeoutMs: 12000 });
      if (!healthy) {
        const detail = String(deps?._lastHealthDetail || "").trim();
        deps.showAuthOverlay(detail
          ? `Base de datos no disponible. ${detail}`
          : "Servidor arrancando (Render puede tardar 1-2 min). Espera unos segundos y recarga si no avanza.");
        try { document.body.classList.remove("auth-pending"); } catch {}
        return;
      }
      deps.setAuthUi(null);
      deps.hideAuthOverlay();
      if (!deps.state.appInitialized) {
        await deps.init();
        deps.state.appInitialized = true;
      } else if (typeof deps.openPublicPortal === "function") {
        await deps.openPublicPortal(portalToken);
      }
      try { document.body.classList.remove("auth-pending"); } catch {}
      return;
    }
    const user = await fetchCurrentSessionUser();
    if (!user) {
      try { deps.state.authSessionResolved = true; } catch {}
      // No bloqueamos la UI esperando el cold start: mostramos login y dejamos el health probe en background.
      deps.showAuthOverlay("Arrancando servidor... (Render puede tardar 1-2 min)");
      try {
        await fetch("/health", { cache: "no-store", credentials: "same-origin" });
      } catch {}
      const userReady = await fetchCurrentSessionUser();
      if (!userReady) {
        if (deps?.authLoginStatus) deps.authLoginStatus.textContent = "";
        return;
      }
      deps.setAuthUi(userReady);
      deps.hideAuthOverlay();
      if (!deps.state.appInitialized) {
        await deps.init();
        deps.state.appInitialized = true;
      }
      try { document.body.classList.remove("auth-pending"); } catch {}
      return;
    }
    try { deps.state.authSessionResolved = true; } catch {}
    deps.setAuthUi(user);
    deps.hideAuthOverlay();
    if (!deps.state.appInitialized) {
      await deps.init();
      deps.state.appInitialized = true;
    }
    try { document.body.classList.remove("auth-pending"); } catch {}
  }

  function handleAuthExpired(deps) {
    if (!deps.state.appInitialized && deps.authLoginOverlay && !deps.authLoginOverlay.classList.contains("hidden")) {
      return;
    }
    deps.showAuthOverlay("La sesión ha caducado. Inicia sesión de nuevo.");
  }

  async function prepareActivationFlow(deps, token) {
    deps.showActivationOverlay("Validando invitación...");
    try {
      const data = await deps.api("/api/auth_invite_status", {
        headers: { "X-Access-Token": token },
      });
      if (!data?.valid) {
        if (deps.authActivateStatus) {
          deps.authActivateStatus.textContent = data?.expired ? "La invitación ha caducado." : "Invitación no válida.";
        }
        return;
      }
      const user = data.user || {};
      const label = [user.nombre, user.apellido].filter(Boolean).join(" ").trim() || user.usuario || user.email || "usuario";
      const mode = String(data?.mode || "").trim().toLowerCase();
      if (deps.authActivateIntro) {
        deps.authActivateIntro.textContent = mode === "recovery"
          ? `Restablece el acceso de ${label} y define una nueva contraseña.`
          : `Activa el acceso de ${label} y define tu contraseña.`;
      }
    } catch (error) {
      if (deps.authActivateStatus) {
        deps.authActivateStatus.textContent = error?.message || "No se pudo validar la invitación.";
      }
    }
  }

  async function submitActivationPassword(deps) {
    const token = getDeepLinkParam("activar_token");
    const p1 = deps.authActivatePass1?.value || "";
    const p2 = deps.authActivatePass2?.value || "";
    if (!token) {
      if (deps.authActivateStatus) deps.authActivateStatus.textContent = "Token de activación no disponible.";
      return;
    }
    if (!p1 || p1.length < 8) {
      if (deps.authActivateStatus) deps.authActivateStatus.textContent = "La contraseña debe tener al menos 8 caracteres.";
      return;
    }
    if (p1 !== p2) {
      if (deps.authActivateStatus) deps.authActivateStatus.textContent = "Las contraseñas no coinciden.";
      return;
    }
    if (deps.authActivateStatus) deps.authActivateStatus.textContent = "Activando cuenta...";
    try {
      const res = await fetch("/api/auth_set_password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ token, password: p1 }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) {
        if (deps.authActivateStatus) deps.authActivateStatus.textContent = data?.error || "No se pudo activar la cuenta.";
        return;
      }
      if (deps.authActivateStatus) {
        deps.authActivateStatus.textContent = "Cuenta activada. Ya puedes iniciar sesión.";
        deps.authActivateStatus.classList.add("success");
      }
      if (deps.authActivatePass1) deps.authActivatePass1.value = "";
      if (deps.authActivatePass2) deps.authActivatePass2.value = "";
      history.replaceState({}, "", window.location.pathname);
      setTimeout(() => {
        if (deps.authActivateStatus) deps.authActivateStatus.classList.remove("success");
        deps.showAuthOverlay("Cuenta activada. Inicia sesión.");
      }, 700);
    } catch {
      if (deps.authActivateStatus) deps.authActivateStatus.textContent = "Error de conexión al activar la cuenta.";
    }
  }

  async function submitAuthLogin(deps) {
    if (authLoginBusy) return;
    const usuario = deps.authLoginUser?.value?.trim() || "";
    const password = deps.authLoginPass?.value || "";
    if (!usuario || !password) {
      hideRecoveryButton(deps);
      if (deps.authLoginStatus) deps.authLoginStatus.textContent = "Introduce usuario/email y contraseña.";
      return;
    }
    authLoginBusy = true;
    setLoginBusyState(deps, true);
    hideRecoveryButton(deps);
    if (deps.authLoginStatus) deps.authLoginStatus.textContent = "Accediendo...";
    try {
      await waitForHealth(deps, { maxMs: 90000, requestTimeoutMs: 12000 });
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ usuario, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) {
        const baseMessage = data?.error || "No se pudo iniciar sesión.";
        const recoveryAvailable = Boolean(data?.recovery_available && (data?.recovery_login || usuario));
        const recoveryHint = String(data?.recovery_message || "").trim();
        if (deps.authLoginStatus) {
          deps.authLoginStatus.textContent = recoveryAvailable
            ? `${baseMessage} ${recoveryHint || "Puedes recuperar el acceso."}`.trim()
            : baseMessage;
        }
        if (recoveryAvailable) showRecoveryButton(deps, data?.recovery_login || usuario);
        return;
      }
      hideRecoveryButton(deps);
      if (deps.authLoginPass) deps.authLoginPass.value = "";
      if (deps.authLoginStatus) {
        const successMessage = data?.first_password_set
          ? "Contraseña inicial guardada. Acceso correcto."
          : "Acceso correcto.";
        deps.authLoginStatus.textContent = data?.access_warning_message
          ? `${successMessage} ${String(data.access_warning_message).trim()}`.trim()
          : successMessage;
      }
      const postLoginWarning = String(data?.access_warning_message || "").trim();
      deps.setAuthUi(data?.user || null);
      if (postLoginWarning) {
        try {
          sessionStorage.setItem("crm.postLoginNotice", postLoginWarning);
          sessionStorage.setItem(
            "crm.postLoginAccessWarning",
            JSON.stringify({
              reason: String(data?.access_warning_reason || "").trim(),
              message: postLoginWarning,
            })
          );
        } catch {}
      }
      deps.hideAuthOverlay();
      try { document.body.classList.remove("auth-pending"); } catch {}
      try {
        const current = getDeepLinkParams();
        const hasDeepLink =
          current.has("holding") ||
          current.has("crm") ||
          current.has("clientes") ||
          current.has("cliente") ||
          current.has("poliza") ||
          current.has("empresa") ||
          current.has("agenda") ||
          current.has("admin") ||
          current.has("portal_token") ||
          current.has("portal_inmo") ||
          current.has("firma_inmo") ||
          current.has("activar_token");
        const returnUrl = String(deps.state?.postAuthReturnUrl || "").trim();
        if (!returnUrl && !hasDeepLink) {
          const targetUser = String(data?.user?.usuario || "").trim().toLowerCase();
          const targetRole = String(data?.user?.rol || "").trim().toLowerCase();
          const targetService = String(data?.user?.servicio || "").trim().toLowerCase();
          const params = new URLSearchParams();
          if (targetUser === "workspace") {
            params.set("holding", "1");
            params.set("mode", "tenant");
            params.set("workspace", "verifika2");
            params.set("view", "overview");
          } else if (targetRole === "administrador" || targetService === "administración" || targetService === "administracion") {
            params.set("holding", "1");
            params.set("mode", "platform");
            params.set("view", "overview");
            try {
              const workspaceId = String(localStorage.getItem("crm.currentWorkspaceId") || "").trim();
              if (workspaceId) params.set("workspace", workspaceId);
            } catch {}
          }
          if (params.toString()) {
            const url = new URL(window.location.href);
            url.search = params.toString();
            history.replaceState({}, "", url.toString());
          }
        }
      } catch {}
      if (!deps.state.appInitialized) {
        await deps.init();
        deps.state.appInitialized = true;
      }
      // Si venimos de una sesión expirada, reabrimos la URL exacta que el usuario intentaba abrir
      // (p.ej. un workspace tenant). Esto evita que, tras re-login, se quede en Home.
      try {
        const returnUrl = String(deps.state?.postAuthReturnUrl || "").trim();
        deps.state.postAuthReturnUrl = "";
        if (returnUrl && returnUrl !== window.location.href) {
          // Si el returnUrl es de otro subdominio (app.verifika2.com vs crm.verifika2.com),
          // normalizamos al host actual para evitar perder cookies host-only y entrar en bucle de login.
          try {
            const url = new URL(returnUrl, window.location.href);
            const cur = new URL(window.location.href);
            const sameSite =
              url.hostname === cur.hostname ||
              (url.hostname.endsWith(".verifika2.com") && cur.hostname.endsWith(".verifika2.com"));
            if (sameSite && url.hostname !== cur.hostname) {
              url.protocol = cur.protocol;
              url.host = cur.host;
            }
            window.location.assign(url.toString());
          } catch {
            window.location.assign(returnUrl);
          }
          return;
        }
      } catch {}
      // Si el usuario venía por un deep-link (p.ej. `?holding=1&mode=tenant&workspace=...`),
      // no lo pisamos con la navegación "por rol" (admin/workspace). Esto evita que al entrar
      // desde una card del Home, tras re-login se pierda el destino.
      try {
        const current = getDeepLinkParams();
        const hasDeepLink =
          current.has("holding") ||
          current.has("crm") ||
          current.has("clientes") ||
          current.has("cliente") ||
          current.has("poliza") ||
          current.has("empresa") ||
          current.has("agenda") ||
          current.has("admin") ||
          current.has("portal_token") ||
          current.has("portal_inmo") ||
          current.has("firma_inmo") ||
          current.has("activar_token");
        if (hasDeepLink) {
          // Re-aplica el routing con la URL actual (en apps ya inicializadas, no se re-ejecuta `init()`).
          const query = {};
          current.forEach((value, key) => {
            if (value === null || value === undefined) return;
            const v = String(value);
            if (!v) return;
            query[key] = v;
          });
          if (Object.keys(query).length && typeof deps.navigate === "function") {
            try {
              deps.navigate(query);
              return;
            } catch {}
          }
          // Fallback: recarga completa al mismo deep-link.
          try {
            window.location.assign(window.location.href);
          } catch {}
          return;
        }
      } catch {}
      const targetUser = String(data?.user?.usuario || "").trim().toLowerCase();
      const targetRole = String(data?.user?.rol || "").trim().toLowerCase();
      const targetService = String(data?.user?.servicio || "").trim().toLowerCase();
      const navigate = (query) => {
        if (typeof deps.navigate === "function") {
          try {
            deps.navigate(query || {});
            return true;
          } catch {}
        }
        return false;
      };
      if (targetUser === "workspace") {
        if (!navigate({ holding: "1", mode: "tenant", workspace: "verifika2", view: "overview" })) {
          window.location.assign("?holding=1&mode=tenant&workspace=verifika2&view=overview");
        }
        return;
      }
      if (targetRole === "administrador" || targetService === "administración" || targetService === "administracion") {
        if (!navigate({ holding: "1", mode: "platform" })) {
          window.location.assign("?holding=1&mode=platform");
        }
        return;
      }
    } catch {
      if (deps.authLoginStatus) deps.authLoginStatus.textContent = "Error de conexión al iniciar sesión.";
    } finally {
      authLoginBusy = false;
      setLoginBusyState(deps, false);
    }
  }

  async function logoutAuthSession(deps) {
    try {
      await fetch("/api/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: "{}",
      });
    } catch {}
    deps.showAuthOverlay("Sesión cerrada.");
  }

  window.CRMAppAuth = {
    fetchCurrentSessionUser,
    ensureAuthAndBoot,
    handleAuthExpired,
    prepareActivationFlow,
    submitActivationPassword,
    submitAuthLogin,
    logoutAuthSession,
  };
})();
