(function () {
  async function waitForHealth(deps, options) {
    const maxMs = Math.max(5000, Number(options?.maxMs || 45000) || 45000);
    const started = Date.now();
    let attempt = 0;
    let lastDetail = "";
    while (Date.now() - started < maxMs) {
      attempt += 1;
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 5000);
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
              deps.authLoginStatus.textContent = `Base de datos no disponible. ${lastDetail}`;
            }
          }
        } finally {
          clearTimeout(timer);
        }
      } catch {}
      const delay = Math.min(6000, 250 * Math.pow(1.8, attempt));
      if (deps?.authLoginStatus) {
        deps.authLoginStatus.textContent = attempt <= 2 ? "Arrancando servidor..." : `Arrancando servidor... (${Math.round(delay)}ms)`;
      }
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
    return false;
  }

  async function fetchCurrentSessionUser() {
    try {
      const res = await fetch("/api/me", { cache: "no-store", credentials: "same-origin" });
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
    const healthy = await waitForHealth(deps, { maxMs: 45000 });
    if (!healthy) {
      const detail = String(deps?._lastHealthDetail || "").trim();
      deps.showAuthOverlay(detail ? `Base de datos no disponible. ${detail}` : "Servidor no disponible. Espera unos segundos y recarga.");
      try { document.body.classList.remove("auth-pending"); } catch {}
      return;
    }
    const params = new URLSearchParams(window.location.search);
    const activateToken = (params.get("activar_token") || "").trim();
    const portalToken = (params.get("portal_token") || "").trim();
    if (activateToken) {
      await deps.prepareActivationFlow(activateToken);
      try { document.body.classList.remove("auth-pending"); } catch {}
      return;
    }
    if (portalToken) {
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
      deps.showAuthOverlay("");
      try { document.body.classList.remove("auth-pending"); } catch {}
      return;
    }
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
      const data = await deps.api(`/api/auth_invite_status?token=${encodeURIComponent(token)}`);
      if (!data?.valid) {
        if (deps.authActivateStatus) {
          deps.authActivateStatus.textContent = data?.expired ? "La invitación ha caducado." : "Invitación no válida.";
        }
        return;
      }
      const user = data.user || {};
      const label = [user.nombre, user.apellido].filter(Boolean).join(" ").trim() || user.usuario || user.email || "usuario";
      if (deps.authActivateIntro) {
        deps.authActivateIntro.textContent = `Activa el acceso de ${label} y define tu contraseña.`;
      }
    } catch (error) {
      if (deps.authActivateStatus) {
        deps.authActivateStatus.textContent = error?.message || "No se pudo validar la invitación.";
      }
    }
  }

  async function submitActivationPassword(deps) {
    const params = new URLSearchParams(window.location.search);
    const token = (params.get("activar_token") || "").trim();
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
    const usuario = deps.authLoginUser?.value?.trim() || "";
    const password = deps.authLoginPass?.value || "";
    if (!usuario || !password) {
      if (deps.authLoginStatus) deps.authLoginStatus.textContent = "Introduce usuario/email y contraseña.";
      return;
    }
    if (deps.authLoginStatus) deps.authLoginStatus.textContent = "Accediendo...";
    await waitForHealth(deps, { maxMs: 30000 });
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ usuario, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) {
        if (deps.authLoginStatus) deps.authLoginStatus.textContent = data?.error || "No se pudo iniciar sesión.";
        return;
      }
      if (deps.authLoginPass) deps.authLoginPass.value = "";
      if (deps.authLoginStatus) {
        deps.authLoginStatus.textContent = data?.first_password_set
          ? "Contraseña inicial guardada. Acceso correcto."
          : "Acceso correcto.";
      }
      deps.setAuthUi(data?.user || null);
      deps.hideAuthOverlay();
      if (!deps.state.appInitialized) {
        await deps.init();
        deps.state.appInitialized = true;
      }
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
        if (!navigate({ holding: "1", mode: "tenant", workspace: "modernia", view: "overview" })) {
          window.location.assign("?holding=1&mode=tenant&workspace=modernia&view=overview");
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
