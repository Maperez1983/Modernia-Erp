(function () {
  const API_TIMEOUT_MS = 90000;
  const APP_SW_VERSION = "v372";
  const DEFAULT_TENANT_WORKSPACE_SLUG = "verifika2";
  const LEGACY_TENANT_WORKSPACE_SLUGS = new Set(["modernia", "grupomodernia", "grupo-modernia"]);
  const DEFAULT_TENANT_WORKSPACE_NAME = "Verifika²";

  const normalizeSlugLike = (value) =>
    String(value || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, "-")
      .replace(/[^a-z0-9\-]+/g, "")
      .replace(/\-+/g, "-")
      .replace(/^\-+|\-+$/g, "");

  const normalizeTenantWorkspaceSlug = (value, fallback = DEFAULT_TENANT_WORKSPACE_SLUG) => {
    const raw = String(value || "").trim();
    if (!raw) return fallback;
    const normalized = normalizeSlugLike(raw);
    if (LEGACY_TENANT_WORKSPACE_SLUGS.has(normalized)) {
      try {
        const candidates = [];
        const currentState = window.state || null;
        if (Array.isArray(currentState?.workspaces)) candidates.push(...currentState.workspaces);
        if (Array.isArray(currentState?.homeWorkspacesRows)) candidates.push(...currentState.homeWorkspacesRows);
        const exists = candidates.some((row) => normalizeSlugLike(row?.slug || row?.nombre || row?.name || "") === normalized);
        if (!exists) return fallback;
      } catch {
        return fallback;
      }
    }
    return normalized || fallback;
  };

  const fetchWithTimeout = async (input, init = {}, timeoutMs = API_TIMEOUT_MS) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), Math.max(1000, Number(timeoutMs) || API_TIMEOUT_MS));
    try {
      return await fetch(input, { ...(init || {}), signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
  };

  const setUiToast = (title, detail = "") => {
    const toast = document.getElementById("uiErrorToast");
    if (!toast) return;
    toast.classList.remove("hidden");
    toast.innerHTML = "";
    const strong = document.createElement("strong");
    strong.textContent = title || "";
    toast.appendChild(strong);
    if (detail) {
      const pre = document.createElement("pre");
      pre.textContent = String(detail).slice(0, 2000);
      toast.appendChild(pre);
    }
  };

  const hideUiToast = () => {
    const toast = document.getElementById("uiErrorToast");
    if (!toast) return;
    toast.classList.add("hidden");
    toast.innerHTML = "";
  };

  const probeDbHealth = async () => {
    try {
      const res = await fetchWithTimeout(
        "/api/health",
        { cache: "no-store", credentials: "same-origin" },
        4500
      );
      const body = await res.text().catch(() => "");
      return { ok: res.ok, status: res.status, body: String(body || "").trim() };
    } catch (err) {
      const msg = err?.name === "AbortError" ? "Tiempo de espera agotado." : "No se pudo conectar con el servidor.";
      return { ok: false, status: 0, body: msg };
    }
  };

  const sanitizeApiUrl = (value) => {
    const raw = String(value || "");
    if (!raw) return raw;
    const scrubKeys = new Set(["token", "password", "activar_token", "portal_token", "firma_inmo"]);
    const scrubParams = (query = "") => {
      if (!query) return "";
      const params = new URLSearchParams(query);
      for (const key of scrubKeys) {
        if (params.has(key)) params.set(key, "***");
      }
      return params.toString();
    };
    try {
      const url = new URL(raw, window.location.origin);
      const search = scrubParams(url.search.replace(/^\?/, ""));
      url.search = search ? `?${search}` : "";
      if (url.hash && url.hash.includes("=")) {
        const hashParams = new URLSearchParams(url.hash.slice(1));
        for (const key of scrubKeys) {
          if (hashParams.has(key)) hashParams.set(key, "***");
        }
        url.hash = hashParams.toString() ? `#${hashParams.toString()}` : "";
      }
      return url.toString();
    } catch {
      const [base, query] = raw.split("?", 2);
      if (!query) return base;
      const parts = query
        .split("&")
        .filter(Boolean)
        .map((part) => {
          const [k, v = ""] = part.split("=", 2);
          const key = String(k || "").trim();
          if (!key) return "";
          if (scrubKeys.has(key)) return `${key}=***`;
          return `${key}=${v}`;
        })
        .filter(Boolean);
      return parts.length ? `${base}?${parts.join("&")}` : base;
    }
  };

  const getDeepLinkParams = () => {
    try {
      if (window.CRMDeepLink && typeof window.CRMDeepLink.getParams === "function") {
        return window.CRMDeepLink.getParams();
      }
    } catch {}
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

  const getDeepLinkToken = (name) => {
    const params = getDeepLinkParams();
    return String(params.get(name) || "").trim();
  };

  const safeUrlValue = (value, { allowDataImage = false, allowBlob = false } = {}) => {
    const raw = String(value || "").trim();
    if (!raw) return "";
    if (allowDataImage && raw.startsWith("data:image/")) return raw;
    if (allowBlob && raw.startsWith("blob:")) return raw;
    if (/^(javascript|vbscript):/i.test(raw)) return "";
    if (/^data:/i.test(raw) && !(allowDataImage && raw.startsWith("data:image/"))) return "";
    try {
      const url = new URL(raw, window.location.origin);
      if (!["http:", "https:"].includes(url.protocol)) return "";
      return url.toString();
    } catch {
      return "";
    }
  };

  const safeHrefUrl = (value) => safeUrlValue(value, { allowBlob: true });
  const safeImageUrl = (value) => safeUrlValue(value, { allowDataImage: true, allowBlob: true });
  const safeOpenUrl = (value) => safeUrlValue(value, { allowBlob: true });

  const openBlobInNewTab = (blob, filename = "archivo") => {
    if (!(blob instanceof Blob)) return false;
    const url = URL.createObjectURL(blob);
    let opened = null;
    try {
      opened = window.open(url, "_blank", "noopener,noreferrer");
    } catch {
      opened = null;
    }
    if (!opened) {
      const a = document.createElement("a");
      a.href = url;
      a.download = filename || "archivo";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }
    setTimeout(() => {
      try {
        URL.revokeObjectURL(url);
      } catch {}
    }, 60000);
    return true;
  };

  const fetchBlobFromGet = async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    const timeoutMs = Number(options.timeoutMs || API_TIMEOUT_MS) || API_TIMEOUT_MS;
    const res = await fetchWithTimeout(
      path,
      {
        cache: "no-store",
        credentials: "same-origin",
        headers,
      },
      timeoutMs
    );
    if (!res.ok) {
      let detail = "";
      try {
        detail = await res.text();
      } catch {
        detail = "";
      }
      let message = detail || `HTTP ${res.status}`;
      try {
        const parsed = detail ? JSON.parse(detail) : null;
        if (parsed && parsed.error) {
          message = parsed.detail ? `${parsed.error} · ${parsed.detail}` : parsed.error;
        }
      } catch {}
      const error = new Error(message);
      error.status = res.status;
      throw error;
    }
    const blob = await res.blob();
    const disposition = String(res.headers.get("Content-Disposition") || "");
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match && match[1] ? match[1] : String(options.filenameFallback || "archivo").trim() || "archivo";
    return { blob, filename };
  };

  window.CRMAppShared = window.CRMAppShared || {};
  Object.assign(window.CRMAppShared, {
    API_TIMEOUT_MS,
    APP_SW_VERSION,
    DEFAULT_TENANT_WORKSPACE_SLUG,
    LEGACY_TENANT_WORKSPACE_SLUGS,
    DEFAULT_TENANT_WORKSPACE_NAME,
    normalizeSlugLike,
    normalizeTenantWorkspaceSlug,
    fetchWithTimeout,
    setUiToast,
    hideUiToast,
    probeDbHealth,
    sanitizeApiUrl,
    getDeepLinkParams,
    getDeepLinkToken,
    safeUrlValue,
    safeHrefUrl,
    safeImageUrl,
    safeOpenUrl,
    openBlobInNewTab,
    fetchBlobFromGet,
  });
})();
