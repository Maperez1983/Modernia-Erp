(function () {
  const dirtyForms = new Set();
  const touchedForms = new Set();
  const focusedModalState = new WeakMap();
  let contextBar = null;
  let contextTitle = null;
  let contextMeta = null;
  let contextDrafts = null;
  let contextBackBtn = null;
  let observer = null;
  let refreshTimer = null;

  const CONTROL_PERSIST_RE = /(search|filter|select|year|view|sort|density|empresa|tabla|crm|agenda|tab)/i;
  const DRAFT_SKIP_RE = /(auth|login|activate|password|upload)/i;

  const isVisible = (el) => {
    if (!el) return false;
    if (el.hidden) return false;
    if (el.classList?.contains("hidden")) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const storageKey = (prefix, id) => `crm_ui_${prefix}_${id}`;

  const resolveControlStorageKey = (el) => {
    const key = getElementKey(el);
    if (!key) return "";
    const form = el?.closest ? el.closest("form[id]") : null;
    if (form?.id) return storageKey("control", `${form.id}__${key}`);
    return storageKey("control", key);
  };

  const getElementKey = (el) => {
    if (!el) return "";
    return String(el.id || el.name || "").trim();
  };

  const isPersistableControl = (el) => {
    if (!el || !getElementKey(el)) return false;
    const form = el.closest && el.closest("form");
    if (form && String(form.dataset.uiPersist || "") === "0") return false;
    if (String(el.dataset?.uiPersist || "") === "0") return false;
    if (el.type && /password|file|hidden/.test(el.type)) return false;
    // Un formulario con campo oculto `id` es la ficha de un registro, no un panel de
    // filtros: lo que hay dentro son datos de ese expediente. Marcarlos uno a uno se
    // olvida en el siguiente que se escriba, así que se reconoce por la forma. Había
    // 8 así solo en index.html, la mayoría por un `select` de empresa_id.
    if (form && form.querySelector && form.querySelector('input[type="hidden"][name="id"]')) return false;
    // Antes cualquier select o textarea se recordaba, sin más. Recordar un filtro es
    // útil; recordar un campo de una ficha es grave: al abrir otro registro se repone
    // el valor guardado encima del real. Visto en producción el 2026-08-04, una
    // hipoteca "Pendiente" se mostraba como "Firmada" —el estado de la ficha anterior—
    // y guardar el formulario lo habría escrito en la base.
    //
    // Se aplica el mismo criterio que al resto: solo se recuerda lo que parece un
    // filtro o una preferencia de vista.
    return CONTROL_PERSIST_RE.test(getElementKey(el));
  };

  const getEligibleForms = (root = document) =>
    Array.from(root.querySelectorAll("form[id]")).filter((form) => {
      if (!form || !form.id) return false;
      if (String(form.dataset.uiDraft || "") === "0") return false;
      return !DRAFT_SKIP_RE.test(form.id);
    });

  const getDraftControls = (form) =>
    Array.from(form.elements || []).filter((el) => {
      const tag = String(el.tagName || "").toLowerCase();
      if (!["input", "select", "textarea"].includes(tag)) return false;
      if (!getElementKey(el)) return false;
      if (el.disabled) return false;
      if (el.type && /password|file|hidden|submit|button|reset/.test(el.type)) return false;
      return true;
    });

  const getStatusTarget = (form) => {
    if (!form) return null;
    return (
      form.querySelector('[id$="Status"]') ||
      form.closest(".form-card, .card, .dashboard-card, .data-card")?.querySelector('[id$="Status"]') ||
      null
    );
  };

  const styleStatusNode = (node) => {
    if (!node || node.nodeType !== 1) return;
    const text = String(node.textContent || "").trim().toLowerCase();
    node.classList.remove("ui-status", "is-success", "is-error", "is-pending", "is-empty");
    node.setAttribute("aria-live", "polite");
    const isStatusNode =
      /Status$/i.test(node.id || "") ||
      ["dbStatus", "authLoginStatus", "authActivateStatus"].includes(node.id || "");
    if (!isStatusNode) return;
    node.classList.add("ui-status");
    if (!text) return;
    if (/guardando|cargando|accediendo|validando|subiendo|optimizando/.test(text)) {
      node.classList.add("is-pending");
      return;
    }
    if (/error|incorrect|inv[aá]lid|caduc|no se pudo|no v[aá]lid|requerid|sin empresa|no encontrada/.test(text)) {
      node.classList.add("is-error");
      return;
    }
    if (/guardad|activad|correcto|vinculad|cread|hecho|completad|restaurad/.test(text)) {
      node.classList.add("is-success");
      return;
    }
    if (/sin |no hay|usa b[uú]squeda/.test(text)) {
      node.classList.add("is-empty");
    }
  };

  const renderFieldError = (field, message) => {
    if (!field || !getElementKey(field)) return;
    const errorId = `${getElementKey(field)}__ui_error`;
    const escapedId = window.CSS?.escape ? window.CSS.escape(errorId) : errorId;
    let error = field.parentElement?.querySelector(`#${escapedId}`);
    if (!message) {
      field.removeAttribute("aria-invalid");
      field.removeAttribute("aria-describedby");
      if (error) error.remove();
      return;
    }
    field.setAttribute("aria-invalid", "true");
    field.setAttribute("aria-describedby", errorId);
    if (!error) {
      error = document.createElement("div");
      error.id = errorId;
      error.className = "ui-field-error";
      field.parentElement?.appendChild(error);
    }
    error.textContent = message;
  };

  const validateField = (field) => {
    if (!field || field.disabled) return true;
    const tag = String(field.tagName || "").toLowerCase();
    if (!["input", "select", "textarea"].includes(tag)) return true;
    const value = String(field.value || "").trim();
    let message = "";
    if (field.required && !value) {
      message = "Campo obligatorio.";
    } else if (field.type === "email" && value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
      message = "Email no válido.";
    } else if (field.type === "password" && value && value.length < 8) {
      message = "Mínimo 8 caracteres.";
    }
    renderFieldError(field, message);
    return !message;
  };

  const saveControlState = (el) => {
    if (!isPersistableControl(el)) return;
    try {
      const key = resolveControlStorageKey(el);
      if (!key) return;
      localStorage.setItem(key, String(el.value ?? ""));
    } catch {}
  };

  const restoreControlState = (root = document) => {
    Array.from(root.querySelectorAll("input, select, textarea")).forEach((el) => {
      if (!isPersistableControl(el)) return;
      const key = resolveControlStorageKey(el);
      if (!key) return;
      let saved = "";
      try {
        saved = localStorage.getItem(key) || "";
      } catch {}
      if (!saved) return;
      if (String(el.value || "") === saved) return;
      el.value = saved;
      el.dispatchEvent(new Event("change", { bubbles: true }));
    });
  };

  // A qué registro pertenece lo que hay ahora mismo en el formulario.
  //
  // El borrador se guarda con el id del formulario, no con el del expediente. Sin
  // esto, dejar a medias la ficha de una hipoteca y abrir otra restauraba encima los
  // valores de la primera: el mismo fallo que el de los controles recordados, pero
  // por otra puerta. Guardando el ámbito solo se restaura lo que es de ese registro.
  const getFormScope = (form) => {
    if (!form) return "";
    try {
      const campoId = form.querySelector('input[name="id"]');
      const porCampo = String(campoId?.value || "").trim();
      if (porCampo) return porCampo;
      const contenedor = form.closest("[data-record-id]");
      return String(contenedor?.dataset?.recordId || "").trim();
    } catch {
      return "";
    }
  };

  const serializeFormDraft = (form) => {
    const payload = { __scope: getFormScope(form) };
    getDraftControls(form).forEach((el) => {
      const key = getElementKey(el);
      if (!key) return;
      if (el.type === "checkbox") {
        payload[key] = !!el.checked;
      } else if (el.type === "radio") {
        if (el.checked) payload[key] = el.value;
      } else {
        payload[key] = el.value;
      }
    });
    return payload;
  };

  const saveFormDraft = (form) => {
    if (!form?.id) return;
    try {
      localStorage.setItem(storageKey("draft", form.id), JSON.stringify(serializeFormDraft(form)));
    } catch {}
  };

  const clearFormDraft = (form) => {
    if (!form?.id) return;
    try {
      localStorage.removeItem(storageKey("draft", form.id));
    } catch {}
    dirtyForms.delete(form.id);
    touchedForms.delete(form.id);
    form.classList.remove("is-dirty");
    syncContextBar();
  };

  const restoreFormDraft = (form) => {
    if (!form?.id) return;
    let draft = null;
    try {
      draft = JSON.parse(localStorage.getItem(storageKey("draft", form.id)) || "null");
    } catch {
      draft = null;
    }
    if (!draft || typeof draft !== "object") return;
    // Un borrador solo vuelve al expediente del que salió. Si es de otro, se tira:
    // restaurarlo pondría datos de una hipoteca encima de otra, y quien guardara
    // después los estaría escribiendo en el registro equivocado.
    if (String(draft.__scope || "") !== getFormScope(form)) {
      clearFormDraft(form);
      return;
    }
    let restored = 0;
    getDraftControls(form).forEach((el) => {
      const key = getElementKey(el);
      if (key === "__scope" || !(key in draft)) return;
      const value = draft[key];
      if (el.type === "checkbox") {
        el.checked = !!value;
      } else if (el.type === "radio") {
        el.checked = String(value) === String(el.value);
      } else {
        el.value = value ?? "";
      }
      restored += 1;
    });
    if (!restored) return;
    const status = getStatusTarget(form);
    if (status && !String(status.textContent || "").trim()) {
      status.textContent = "Borrador restaurado.";
      styleStatusNode(status);
    }
    dirtyForms.add(form.id);
    form.classList.add("is-dirty");
    syncContextBar();
  };

  const enhanceForm = (form) => {
    if (!form || form.dataset.uiManaged === "1") return;
    form.dataset.uiManaged = "1";
    form.classList.add("ui-form-managed");
    restoreFormDraft(form);
    const controls = getDraftControls(form);
    controls.forEach((field) => {
      const handleFieldChange = (event) => {
        validateField(field);
        // Solo cuenta como "tocado" lo que ha tocado una persona. La aplicación
        // rellena los formularios y dispara `change` para que los filtros reaccionen
        // —al abrir una ficha, al sincronizar el año, al cargar una lista—, y eso
        // marcaba el formulario como sucio sin que nadie hubiera escrito nada. El
        // aviso de "cambios sin guardar" saltaba en cada navegación, así que dejaba
        // de significar algo. Los eventos que dispara el código llevan isTrusted en
        // false; los de teclado y ratón, en true.
        if (event && event.isTrusted === false) return;
        dirtyForms.add(form.id);
        touchedForms.add(form.id);
        form.classList.add("is-dirty");
        saveFormDraft(form);
        syncContextBar();
      };
      field.addEventListener("input", handleFieldChange);
      field.addEventListener("change", handleFieldChange);
      field.addEventListener("blur", () => validateField(field));
    });
    form.addEventListener(
      "submit",
      (event) => {
        const invalid = controls.find((field) => !validateField(field));
        if (invalid) {
          event.preventDefault();
          invalid.focus();
          return;
        }
        const status = getStatusTarget(form);
        if (status && !String(status.textContent || "").trim()) {
          status.textContent = "Guardando...";
          styleStatusNode(status);
        }
      },
      true
    );
    form.addEventListener("reset", () => {
      window.setTimeout(() => {
        clearFormDraft(form);
        controls.forEach((field) => renderFieldError(field, ""));
      }, 0);
    });
  };

  const enhanceFieldPersistence = (root = document) => {
    Array.from(root.querySelectorAll("input, select, textarea")).forEach((el) => {
      if (!isPersistableControl(el) || el.dataset.uiPersistManaged === "1") return;
      el.dataset.uiPersistManaged = "1";
      const persist = () => saveControlState(el);
      el.addEventListener("change", persist);
      if (String(el.tagName || "").toLowerCase() !== "select") {
        el.addEventListener("input", persist);
      }
    });
  };

  const enhanceTabs = (root = document) => {
    Array.from(root.querySelectorAll(".tabs")).forEach((tablist) => {
      if (tablist.dataset.uiTabsManaged === "1") return;
      tablist.dataset.uiTabsManaged = "1";
      tablist.setAttribute("role", "tablist");
      const tabs = Array.from(tablist.querySelectorAll(".tab"));
      tabs.forEach((tab, index) => {
        tab.setAttribute("role", "tab");
        tab.setAttribute("tabindex", tab.classList.contains("active") ? "0" : "-1");
        tab.setAttribute("aria-selected", tab.classList.contains("active") ? "true" : "false");
        tab.addEventListener("keydown", (event) => {
          if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const visibleTabs = tabs.filter((item) => !item.classList.contains("hidden"));
          const current = visibleTabs.indexOf(tab);
          if (current < 0) return;
          let nextIndex = current;
          if (event.key === "ArrowRight") nextIndex = (current + 1) % visibleTabs.length;
          if (event.key === "ArrowLeft") nextIndex = (current - 1 + visibleTabs.length) % visibleTabs.length;
          if (event.key === "Home") nextIndex = 0;
          if (event.key === "End") nextIndex = visibleTabs.length - 1;
          visibleTabs[nextIndex]?.focus();
          visibleTabs[nextIndex]?.click();
        });
        if (!tab.id) {
          tab.id = `ui-tab-${index}-${Math.random().toString(36).slice(2, 7)}`;
        }
      });
    });
    Array.from(root.querySelectorAll(".tabs .tab")).forEach((tab) => {
      tab.setAttribute("aria-selected", tab.classList.contains("active") ? "true" : "false");
      tab.setAttribute("tabindex", tab.classList.contains("active") ? "0" : "-1");
    });
  };

  const getSortableCellValue = (tr, idx) => {
    const cell = tr.children[idx];
    if (!cell) return "";
    const text = String(cell.textContent || "").trim();
    const numeric = text
      .replace(/\s/g, "")
      .replace(/\.(?=\d{3}\b)/g, "")
      .replace(",", ".")
      .replace(/[€%]/g, "");
    const num = Number(numeric);
    return Number.isFinite(num) && numeric ? num : text.toLowerCase();
  };

  const makeTableSortable = (table) => {
    const headerRows = Array.from(table.tHead?.rows || []);
    if (headerRows.length !== 1) return;
    const headCells = Array.from(headerRows[0].cells || []);
    if (!headCells.length || headCells.some((cell) => cell.querySelector("input, select, button"))) return;
    headCells.forEach((th, idx) => {
      if (th.dataset.uiSortable === "1") return;
      th.dataset.uiSortable = "1";
      th.classList.add("ui-sortable");
      th.tabIndex = 0;
      const sortByColumn = () => {
        const tbody = table.tBodies[0];
        if (!tbody) return;
        const currentDir = th.dataset.sortDir === "asc" ? "desc" : "asc";
        headCells.forEach((cell) => {
          cell.dataset.sortDir = "";
          cell.classList.remove("sort-asc", "sort-desc");
        });
        th.dataset.sortDir = currentDir;
        th.classList.add(currentDir === "asc" ? "sort-asc" : "sort-desc");
        const rows = Array.from(tbody.rows);
        rows.sort((a, b) => {
          const av = getSortableCellValue(a, idx);
          const bv = getSortableCellValue(b, idx);
          if (typeof av === "number" && typeof bv === "number") {
            return currentDir === "asc" ? av - bv : bv - av;
          }
          return currentDir === "asc"
            ? String(av).localeCompare(String(bv), "es", { sensitivity: "base" })
            : String(bv).localeCompare(String(av), "es", { sensitivity: "base" });
        });
        rows.forEach((row) => tbody.appendChild(row));
      };
      th.addEventListener("click", sortByColumn);
      th.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          sortByColumn();
        }
      });
    });
  };

  const enhanceTable = (table) => {
    if (!table || table.dataset.uiManaged === "1") return;
    table.dataset.uiManaged = "1";
    table.classList.add("ui-table");
    const headerRows = Array.from(table.tHead?.rows || []);
    const labels = headerRows[headerRows.length - 1]
      ? Array.from(headerRows[headerRows.length - 1].cells || []).map((cell) => String(cell.textContent || "").trim())
      : [];
    Array.from(table.tBodies || []).forEach((tbody) => {
      Array.from(tbody.rows || []).forEach((tr) => {
        Array.from(tr.cells || []).forEach((td, idx) => {
          td.dataset.label = labels[idx] || `Columna ${idx + 1}`;
        });
      });
    });
    let shell = table.closest(".ui-table-shell");
    if (!shell) {
      shell = document.createElement("div");
      shell.className = "ui-table-shell";
      const info = document.createElement("div");
      info.className = "ui-table-meta";
      const scroll = document.createElement("div");
      scroll.className = "ui-table-scroll";
      table.parentNode?.insertBefore(shell, table);
      shell.appendChild(info);
      shell.appendChild(scroll);
      scroll.appendChild(table);
    }
    const tbody = table.tBodies[0];
    const rowCount = tbody ? Array.from(tbody.rows).filter((row) => row.style.display !== "none").length : 0;
    const totalCount = tbody ? tbody.rows.length : 0;
    const meta = shell.querySelector(".ui-table-meta");
    if (meta) {
      meta.textContent = totalCount ? `${rowCount} filas visibles · pulsa cabeceras para ordenar.` : "Sin filas.";
    }
    makeTableSortable(table);
  };

  const enhanceTables = (root = document) => {
    Array.from(root.querySelectorAll("table")).forEach(enhanceTable);
    Array.from(root.querySelectorAll("p.muted")).forEach((node) => {
      const text = String(node.textContent || "").trim().toLowerCase();
      if (/^(sin |no hay|usa b[uú]squeda)/.test(text)) {
        node.classList.add("ui-empty-state");
      }
    });
  };

  const trapModalFocus = (modal) => {
    if (!modal || !isVisible(modal) || !modal.classList.contains("open")) return;
    const focusables = Array.from(
      modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
    ).filter((el) => !el.disabled && isVisible(el));
    if (!focusables.length) return;
    if (!focusedModalState.get(modal)) {
      focusedModalState.set(modal, document.activeElement);
      focusables[0].focus();
    }
  };

  const releaseModalFocus = (modal) => {
    const previous = focusedModalState.get(modal);
    if (previous && typeof previous.focus === "function") {
      previous.focus();
    }
    focusedModalState.delete(modal);
  };

  const enhanceModals = () => {
    Array.from(document.querySelectorAll(".modal")).forEach((modal) => {
      if (modal.dataset.uiManaged === "1") {
        if (!isVisible(modal) || modal.classList.contains("hidden")) {
          releaseModalFocus(modal);
        } else {
          trapModalFocus(modal);
        }
        return;
      }
      modal.dataset.uiManaged = "1";
      modal.setAttribute("role", "dialog");
      modal.setAttribute("aria-modal", "true");
      if (isVisible(modal) && !modal.classList.contains("hidden")) {
        trapModalFocus(modal);
      }
    });
  };

  const handleGlobalKeydown = (event) => {
    const activeTag = String(document.activeElement?.tagName || "").toLowerCase();
    const typing = ["input", "textarea", "select"].includes(activeTag);
    if (event.key === "/" && !typing) {
      event.preventDefault();
      // La búsqueda global vive en app.js, que es quien sabe del workspace. Si está
      // disponible, manda ella; si no, se cae al comportamiento de siempre: enfocar
      // la caja de búsqueda que haya en pantalla (y no hacer nada si no hay).
      if (window.abrirBusquedaGlobal?.()) return;
      const target = Array.from(
        document.querySelectorAll('input[type="search"], input[id*="Search"], input[placeholder*="Buscar"], input[placeholder*="buscar"]')
      ).find(isVisible);
      target?.focus();
      target?.select?.();
      return;
    }
    if (event.key === "Escape") {
      const modal = Array.from(document.querySelectorAll(".modal.open, .modal:not(.hidden)")).find(isVisible);
      if (!modal) return;
      const closeBtn =
        modal.querySelector('[data-close], [data-ocr-close], [data-cliente-ocr-close], [data-close-cliente-seguro], .modal-header button, .secondary');
      closeBtn?.click();
      return;
    }
    if (event.key === "Tab") {
      const modal = Array.from(document.querySelectorAll(".modal.open, .modal:not(.hidden)")).find(isVisible);
      if (!modal) return;
      const focusables = Array.from(
        modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
      ).filter((el) => !el.disabled && isVisible(el));
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  };

  const ensureContextBar = () => {
    if (contextBar && contextBar.isConnected) return contextBar;
    contextBar = document.getElementById("uiContextBar");
    const header = document.querySelector("header");
    if (!contextBar && header) {
      contextBar = document.createElement("div");
      contextBar.id = "uiContextBar";
      contextBar.className = "ui-context-bar";
      contextBar.innerHTML = `
        <div class="ui-context-copy">
          <strong id="uiContextTitle">Inicio</strong>
          <span id="uiContextMeta">Atajos: / buscar · Esc cerrar modal</span>
        </div>
        <div class="ui-context-actions">
          <span id="uiContextDrafts" class="pill hidden"></span>
          <button id="uiContextBackBtn" type="button" class="secondary ghost hidden" data-ui-action="holding-back">Volver al panel</button>
          <button type="button" class="secondary ghost" data-ui-action="focus-search">Buscar</button>
        </div>
      `;
      header.insertAdjacentElement("afterend", contextBar);
    }
    if (!contextBar) return null;
    contextTitle = contextBar.querySelector("#uiContextTitle");
    contextMeta = contextBar.querySelector("#uiContextMeta");
    contextDrafts = contextBar.querySelector("#uiContextDrafts");
    contextBackBtn = contextBar.querySelector("#uiContextBackBtn");
    if (contextBar.dataset.uiBound !== "1") {
      contextBar.addEventListener("click", (event) => {
        const action = event.target.closest("[data-ui-action]")?.dataset.uiAction;
        if (action === "focus-search") {
          // Igual que el atajo "/": si hay búsqueda global, manda ella.
          if (window.abrirBusquedaGlobal?.()) return;
          const target = Array.from(
            document.querySelectorAll('input[type="search"], input[id*="Search"], input[placeholder*="Buscar"], input[placeholder*="buscar"]')
          ).find(isVisible);
          target?.focus();
        }
        // Se mantiene el manejador aunque ya no haya botón: la barra se genera en
        // varios sitios y alguno podría seguir pidiéndolo. Lo que se quitó es el
        // botón visible, que solo movía el foco y parecía un comando.
        if (action === "focus-primary") {
          const target = Array.from(document.querySelectorAll("button, .btn")).find(
            (el) => isVisible(el) && !el.classList.contains("secondary") && !el.classList.contains("ghost")
          );
          target?.focus();
        }
        if (action === "holding-back") {
          const btn = document.getElementById("holdingBackBtn");
          if (isVisible(btn)) {
            btn.click();
          }
        }
      });
      contextBar.dataset.uiBound = "1";
    }
    return contextBar;
  };

		  const syncContextBar = (state) => {
		    ensureContextBar();
		    if (!contextBar || !contextTitle || !contextMeta || !contextDrafts || !contextBackBtn) return;
		    const visibleSection = Array.from(document.querySelectorAll("main > section")).find(isVisible);
	    const title =
	      visibleSection?.querySelector("h2, .section-head h2, .modal-header h3")?.textContent?.trim() ||
	      state?.currentEmpresaName ||
	      "Inicio";
    const activeTab = Array.from(document.querySelectorAll(".tab.active")).find(isVisible)?.textContent?.trim() || "";
    const visibleSearch = Array.from(
      document.querySelectorAll('input[type="search"], input[id*="Search"], input[placeholder*="Buscar"], input[placeholder*="buscar"]')
    ).find(isVisible);
		    contextTitle.textContent = title || "Inicio";
		    contextMeta.textContent = [state?.currentEmpresaName || "", activeTab, visibleSearch ? "Búsqueda disponible" : ""]
		      .filter(Boolean)
		      .join(" · ") || "Atajos: / buscar · Esc cerrar modal";

        // Evita parpadeos: el botón "Volver" se mantiene dentro de la vista (holdingSection)
        // y no se mueve dinámicamente a la barra de contexto.
        contextBackBtn.classList.add("hidden");
        document.body.classList.remove("ui-context-holding-back");

		    const visibleDirtyCount = Array.from(dirtyForms).reduce((acc, formId) => {
		      const form = document.getElementById(formId);
		      if (!form) return acc;
		      if (!isVisible(form)) return acc;
	      return acc + 1;
	    }, 0);
	    if (visibleDirtyCount) {
	      contextDrafts.textContent = `${visibleDirtyCount} borrador${visibleDirtyCount === 1 ? "" : "es"}`;
	      contextDrafts.classList.remove("hidden");
	    } else {
	      contextDrafts.textContent = "";
	      contextDrafts.classList.add("hidden");
	    }
	  };

  const enhanceStatusNodes = (root = document) => {
    Array.from(root.querySelectorAll('[id$="Status"], #dbStatus, #authLoginStatus, #authActivateStatus')).forEach(styleStatusNode);
  };

  const enhance = (root = document) => {
    enhanceFieldPersistence(root);
    getEligibleForms(root).forEach(enhanceForm);
    enhanceTabs(root);
    enhanceTables(root);
    enhanceStatusNodes(root);
    enhanceModals();
    restoreControlState(root);
    syncContextBar(window.crmState || null);
  };

  const queueRefresh = () => {
    window.clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(() => enhance(document), 20);
  };

  const boot = (appState) => {
    window.crmState = appState || window.crmState || null;
    ensureContextBar();
    enhance(document);
    if (!observer) {
      observer = new MutationObserver(() => queueRefresh());
      observer.observe(document.body, {
        subtree: true,
        childList: true,
        characterData: true,
        attributes: true,
        attributeFilter: ["class", "hidden", "aria-selected"],
      });
    }
  };

  window.addEventListener("beforeunload", (event) => {
    if (!touchedForms.size) return;
    event.preventDefault();
    event.returnValue = "";
  });
  document.addEventListener("keydown", handleGlobalKeydown);

  // Cuatro raíles de navegación —Admin, Portal cliente, Ficha de póliza y Agenda—
  // tenían su marcado y ningún manejador en ningún fichero: pulsar el icono no hacía
  // absolutamente nada. Los otros tres raíles de la misma familia (`cliente-tab`,
  // `explorer-tab`, `workspace-view-tab`) sí tienen el suyo y no se tocan aquí.
  //
  // Cada uno de estos cuatro rotula la sección que tiene al lado, así que el clic la
  // marca como activa y trae su contenido a la vista, que es lo que espera quien
  // pulsa un raíl. Hoy llevan un solo ítem y el efecto es modesto —el raíl es sobre
  // todo un rótulo—; en cuanto se le añada un segundo, funciona sin tocar nada más.
  const RAILES_SIN_MANEJADOR = ["admin-view", "portal-public-view", "seguro-view", "agenda-view"];
  document.addEventListener("click", (event) => {
    const selector = RAILES_SIN_MANEJADOR.map((attr) => `[data-${attr}]`).join(",");
    const item = event.target?.closest?.(selector);
    if (!item) return;
    const rail = item.closest(".app-lightning-sidebar");
    if (!rail) return;
    rail.querySelectorAll(".app-side-item").forEach((btn) => {
      const esteEs = btn === item;
      btn.classList.toggle("active", esteEs);
      // Un raíl es navegación: quien va con lector de pantalla necesita saber en cuál está.
      btn.setAttribute("aria-current", esteEs ? "page" : "false");
    });
    const principal = rail.parentElement?.querySelector(".app-lightning-main");
    const destino = principal?.querySelector("h2, h3") || principal;
    if (!destino) return;
    try {
      destino.scrollIntoView({ behavior: "smooth", block: "start" });
      if (!destino.hasAttribute("tabindex")) destino.setAttribute("tabindex", "-1");
      destino.focus({ preventScroll: true });
    } catch (e) {}
  });

  window.CRMUI = {
    boot,
    enhanceFragment: enhance,
    enhanceTables,
    enhanceForms: (root = document) => getEligibleForms(root).forEach(enhanceForm),
    refreshContext: syncContextBar,
    clearDraft(formId) {
      const form = document.getElementById(formId);
      if (form) clearFormDraft(form);
    },
  };
})();
