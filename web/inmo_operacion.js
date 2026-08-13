/* Panel de la operación: de la oferta al estudio de hipoteca, en la ficha del inmueble.
 *
 * Va en un fichero aparte y no dentro de `app.js` por dos razones. La primera es
 * de convivencia: `app.js` pasa de las cincuenta mil líneas y lo tocan varias
 * manos a la vez; meter aquí quinientas más era pedir un conflicto. La segunda es
 * que todo esto cuelga de un solo sitio —la ficha de un inmueble— y no necesita
 * nada del resto de la aplicación: se monta solo cuando aparece esa ficha en el
 * DOM y se apaga cuando desaparece.
 *
 * Ninguno de estos botones hace nada por su cuenta. Presentar una oferta al
 * propietario, pedir la señal, preparar las arras o vincular al comprador con
 * Financiaciones son decisiones de una persona: aquí sólo se pulsa.
 */
(function () {
  "use strict";

  /* El estilo viaja con el módulo y no en `styles.css`: son ocho reglas que sólo
   * usa este panel, y meterlas en la hoja común obliga a tocar un fichero que
   * comparten todas las pantallas. Se apoya en las variables del tema, así que
   * sigue al modo claro y al oscuro sin decir un color propio. */
  const ESTILO = `
    .op-panel { display: grid; gap: 12px; }
    .op-titulo { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .op-titulo h3 { margin: 0; font-size: 15px; }
    .op-cuerpo { display: grid; gap: 10px; }
    .op-oferta { border: 1px solid var(--border, #e2e8f0); border-radius: 12px; padding: 12px;
      display: grid; gap: 6px; }
    .op-cabecera { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
    .op-estado { font-size: 12px; opacity: .75; }
    .op-cifra { font-size: 20px; font-weight: 600; }
    .op-nota { font-size: 12.5px; opacity: .75; }
    .op-mediacion { font-size: 12.5px; font-weight: 600; }
    .op-alerta { font-size: 12.5px; font-weight: 600; padding: 6px 10px; border-radius: 8px;
      background: #fef3c7; color: #b45309; }
    .op-botones { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px; }`;

  function pintaEstilo() {
    if (document.getElementById("op-estilo")) return;
    const hoja = document.createElement("style");
    hoja.id = "op-estilo";
    hoja.textContent = ESTILO;
    document.head.appendChild(hoja);
  }

  const RUTA = {
    ofertas: "/api/inmueble_ofertas",
    responder: "/api/inmueble_oferta_responder",
    presentar: "/api/inmueble_oferta_presentar",
    verificar: "/api/inmueble_oferta_verificar",
    arras: "/api/inmueble_arras_preparar",
    encargo: "/api/inmueble_encargo_firma",
    financiar: "/api/inmueble_oferta_financiacion",
    fase: "/api/inmueble_oferta_financiacion_fase",
    cerrarFinanciacion: "/api/inmueble_oferta_financiacion_cerrar",
  };

  const eur = (n) =>
    (Number(n) || 0).toLocaleString("es-ES", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });

  const esc = (s) =>
    String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function pide(ruta, cuerpo) {
    const r = await fetch(ruta, cuerpo
      ? { method: "POST", headers: { "Content-Type": "application/json" },
          credentials: "same-origin", body: JSON.stringify(cuerpo) }
      : { credentials: "same-origin" });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || "No se ha podido completar la operación");
    return d;
  }

  /* Un `prompt` por dato, no un formulario: son acciones puntuales de un asesor
   * que ya sabe la cifra, y montar un modal para tres campos añade una pantalla
   * que hay que mantener. Devuelve null si cancela. */
  function pregunta(texto, porDefecto) {
    const v = window.prompt(texto, porDefecto == null ? "" : String(porDefecto));
    return v === null ? null : v.trim();
  }

  function tarjetaDeOferta(o) {
    const lineas = [];
    lineas.push(`<div class="op-cabecera">
      <strong>${esc(o.comprador || "Interesado")}</strong>
      <span class="op-estado">${esc(o.titulo || o.estado || "")}</span>
    </div>`);
    lineas.push(`<div class="op-cifra">${eur(o.importe)}${
      o.financiacion ? ' <span class="op-nota">con financiación</span>' : ""}</div>`);
    const detalles = [];
    if (o.plazo_escritura) detalles.push(`escritura en ${o.plazo_escritura} días`);
    if (o.vigencia) detalles.push(`la mantiene hasta el ${o.vigencia}`);
    if (o.contraoferta) detalles.push(`contraoferta: ${eur(o.contraoferta)}`);
    if (o.senal) detalles.push(`señal ${eur(o.senal)}`);
    if (detalles.length) lineas.push(`<div class="op-nota">${esc(detalles.join(" · "))}</div>`);
    if (o.comentario) lineas.push(`<div class="op-nota">«${esc(o.comentario)}»</div>`);

    if (o.mediacion) {
      const dicho = {
        presentada_al_propietario: "Presentada al propietario",
        propietario_acepta: "El propietario ACEPTA",
        propietario_rechaza: "El propietario RECHAZA",
      }[o.mediacion] || o.mediacion;
      lineas.push(`<div class="op-mediacion">${esc(dicho)}${
        o.mediacion_at ? " · " + esc(o.mediacion_at) : ""}</div>`);
    }

    /* La alerta de vinculación. Él dijo que necesitaba financiación, está
     * reservado y todavía no se ha vinculado: es un aviso, no un automatismo. */
    if (o.sugerir_financiacion) {
      lineas.push(`<div class="op-alerta">Pidió financiación · ¿lo vinculamos con Financiaciones?</div>`);
    }
    if (o.financiacion_estado === "estudio") {
      lineas.push(`<div class="op-mediacion">Estudio de hipoteca en marcha</div>`);
    }

    const botones = [];
    const b = (accion, texto, clase) =>
      botones.push(`<button type="button" class="${clase || "secondary ghost"} button-inline op-btn"
        data-accion="${accion}" data-id="${esc(o.id)}">${esc(texto)}</button>`);

    if (o.estado === "presentada") {
      if (o.puede_presentar) b("presentar", "Presentar al propietario", "primary");
      b("contraoferta", "Contraofertar");
      b("aceptar", "Aceptar y pedir señal");
      b("rechazar", "Rechazar");
    } else if (o.estado === "reserva_justificada") {
      b("verificar", "Dar por buena la señal", "primary");
    } else if (o.estado === "reservada") {
      b("arras", "Preparar contrato de arras", "primary");
    }
    if (o.sugerir_financiacion) b("financiar", "Vincular con Financiaciones", "primary");
    if (o.financiacion_estado === "estudio") {
      b("fase", "Mover la fase de la hipoteca");
      b("cerrarFinanciacion", "Cerrar el estudio");
    }
    if (botones.length) lineas.push(`<div class="op-botones">${botones.join("")}</div>`);
    return `<article class="op-oferta" data-oferta="${esc(o.id)}">${lineas.join("")}</article>`;
  }

  async function ejecuta(accion, oferta, fases) {
    const id = oferta.id;
    if (accion === "presentar") {
      const nota = pregunta(
        "¿Qué le contamos al propietario? (esta nota es lo que él va a leer)", "");
      if (nota === null) return false;
      if (!window.confirm(`Se le enseñará la oferta de ${eur(oferta.importe)}. ¿Seguimos?`)) return false;
      await pide(RUTA.presentar, { oferta_id: id, nota });
      return true;
    }
    if (accion === "contraoferta") {
      const importe = pregunta("Importe de la contraoferta (€)", oferta.importe);
      if (!importe) return false;
      const nota = pregunta("Nota para el comprador (opcional)", "") || "";
      await pide(RUTA.responder, { oferta_id: id, decision: "contraoferta", importe, nota });
      return true;
    }
    if (accion === "rechazar") {
      const nota = pregunta("Motivo (opcional, lo verá el comprador)", "");
      if (nota === null) return false;
      await pide(RUTA.responder, { oferta_id: id, decision: "rechazar", nota });
      return true;
    }
    if (accion === "aceptar") {
      const senal = pregunta("Importe de la señal para reservar (€)", "");
      if (!senal) return false;
      const iban = pregunta("Cuenta donde ingresarla (vacío = la de la empresa)", "") || "";
      const limite = pregunta("Fecha límite para el ingreso (AAAA-MM-DD, opcional)", "") || "";
      const nota = pregunta("Nota para el comprador (opcional)", "") || "";
      await pide(RUTA.responder, { oferta_id: id, decision: "aceptar", senal, iban, limite, nota });
      return true;
    }
    if (accion === "verificar") {
      if (!window.confirm("¿Confirmas que el ingreso está en la cuenta? El inmueble quedará reservado."))
        return false;
      await pide(RUTA.verificar, { oferta_id: id });
      return true;
    }
    if (accion === "arras") {
      const arras = pregunta("Importe de las arras (€)", "");
      if (!arras) return false;
      const fechaEscritura = pregunta("Fecha límite para escriturar (AAAA-MM-DD)", "");
      if (!fechaEscritura) return false;
      const fechaFirma = pregunta("Fecha del contrato (AAAA-MM-DD, vacío = hoy)", "") || "";
      const notaria = pregunta("Notaría (opcional)", "") || "";
      const nota = pregunta("Cláusula añadida (opcional)", "") || "";
      const r = await pide(RUTA.arras, {
        oferta_id: id, arras, fecha_escritura: fechaEscritura, fecha_firma: fechaFirma, notaria, nota,
      });
      window.alert(`Contrato generado. Pendiente de ${r.firmas} firma(s).`);
      return true;
    }
    if (accion === "financiar") {
      if (!window.confirm(
        "Se vinculará este cliente con Financiaciones y se dará de alta el estudio. " +
        "Es la misma ficha de cliente, no una nueva. ¿Seguimos?")) return false;
      const importe = pregunta("Importe a financiar (€, vacío = precio menos entrada)", "") || "";
      const banco = pregunta("Banco (opcional)", "") || "";
      await pide(RUTA.financiar, { oferta_id: id, importe, banco });
      return true;
    }
    if (accion === "fase") {
      const opciones = (fases || []).map((f) => `${f.clave} = ${f.etiqueta}`).join("\n");
      const fase = pregunta("¿En qué fase está la hipoteca?\n\n" + opciones, "");
      if (!fase) return false;
      const nota = pregunta("Nota interna (no la ve el cliente)", "") || "";
      await pide(RUTA.fase, { oferta_id: id, fase, nota });
      return true;
    }
    if (accion === "cerrarFinanciacion") {
      const motivo = pregunta("¿Cómo se cierra? denegada / no_interesa / firmada", "");
      if (!motivo) return false;
      await pide(RUTA.cerrarFinanciacion, { oferta_id: id, motivo });
      return true;
    }
    return false;
  }

  async function pinta(panel, inmuebleId) {
    const cuerpo = panel.querySelector(".op-cuerpo");
    let datos;
    try {
      datos = await pide(RUTA.ofertas + "?inmueble_id=" + encodeURIComponent(inmuebleId));
    } catch (e) {
      cuerpo.innerHTML = `<div class="op-nota">${esc(e.message)}</div>`;
      return;
    }
    const ofertas = datos.ofertas || [];
    cuerpo.innerHTML = ofertas.length
      ? ofertas.map(tarjetaDeOferta).join("")
      : `<div class="op-nota">Todavía no hay ofertas sobre este inmueble.</div>`;

    cuerpo.querySelectorAll(".op-btn").forEach((boton) => {
      boton.addEventListener("click", async () => {
        const oferta = ofertas.find((o) => o.id === boton.dataset.id);
        if (!oferta) return;
        boton.disabled = true;
        try {
          if (await ejecuta(boton.dataset.accion, oferta, oferta.fases)) await pinta(panel, inmuebleId);
          else boton.disabled = false;
        } catch (e) {
          window.alert(e.message);
          boton.disabled = false;
        }
      });
    });
  }

  function construye(inmuebleId) {
    pintaEstilo();
    const panel = document.createElement("section");
    panel.className = "card op-panel";
    panel.dataset.inmueble = inmuebleId;
    panel.innerHTML = `
      <div class="op-titulo">
        <h3>Operación</h3>
        <button type="button" class="secondary ghost button-inline" data-accion="encargo">
          Mandar la nota de encargo a firmar
        </button>
      </div>
      <div class="op-cuerpo"><div class="op-nota">Cargando…</div></div>`;
    panel.querySelector('[data-accion="encargo"]').addEventListener("click", async (ev) => {
      const boton = ev.currentTarget;
      if (!window.confirm("Se generará la nota de encargo y se le mandará al propietario para firmarla."))
        return;
      boton.disabled = true;
      try {
        const r = await pide(RUTA.encargo, { inmueble_id: inmuebleId });
        window.alert(`Enviada. Pendiente de ${r.firmas} firma(s).`);
      } catch (e) {
        window.alert(e.message);
      }
      boton.disabled = false;
    });
    return panel;
  }

  /* Se engancha a la ficha del inmueble sin que `app.js` tenga que saber que
   * existimos: se busca el contenedor y, cuando cambia de inmueble, se repinta.
   * Si algún día la ficha se llama de otra forma, esto no rompe nada: no se monta
   * y ya está. */
  const SELECTORES = ["#inmuebleSummaryCard", "[data-inmueble-id]", "#inmuebleDetalle"];

  function inmuebleVisible() {
    for (const selector of SELECTORES) {
      const nodo = document.querySelector(selector);
      if (!nodo) continue;
      const id = nodo.dataset.inmuebleId || nodo.dataset.id || "";
      if (id) return { nodo, id };
    }
    return null;
  }

  let montado = "";
  function revisa() {
    const ficha = inmuebleVisible();
    const panel = document.querySelector(".op-panel");
    if (!ficha) {
      if (panel) panel.remove();
      montado = "";
      return;
    }
    if (montado === ficha.id && panel) return;
    if (panel) panel.remove();
    const nuevo = construye(ficha.id);
    ficha.nodo.parentNode.insertBefore(nuevo, ficha.nodo.nextSibling);
    montado = ficha.id;
    pinta(nuevo, ficha.id);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", revisa);
  } else {
    revisa();
  }
  new MutationObserver(() => revisa()).observe(document.documentElement, {
    childList: true, subtree: true,
  });

  window.InmoOperacion = { pinta, tarjetaDeOferta, ejecuta, revisa };
})();
