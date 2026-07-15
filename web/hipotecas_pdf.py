#!/usr/bin/env python3
import json
import importlib
from io import BytesIO
from types import ModuleType
from typing import Any

_pypdf: ModuleType | None
try:
    _pypdf = importlib.import_module("pypdf")
except Exception:  # pragma: no cover
    _pypdf = None

PdfReader: Any | None = getattr(_pypdf, "PdfReader", None) if _pypdf is not None else None
PdfWriter: Any | None = getattr(_pypdf, "PdfWriter", None) if _pypdf is not None else None

try:
    from . import pdf_utils as runtime_pdf_utils
except ImportError:  # pragma: no cover
    import pdf_utils as runtime_pdf_utils  # type: ignore[no-redef]


normalize_lookup_text = runtime_pdf_utils._normalize_lookup_text
build_hipoteca_bank_logo_meta = runtime_pdf_utils.build_hipoteca_bank_logo_meta
normalize_hipoteca_pdf_sort_order = runtime_pdf_utils.normalize_hipoteca_pdf_sort_order


_DEPENDENCIES: dict[str, Any] = {}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def configure_dependencies(**deps):
    for key, value in deps.items():
        if value is not None:
            _DEPENDENCIES[key] = value


def _dep(name):
    if name not in _DEPENDENCIES:
        raise RuntimeError(f"hipotecas_pdf dependency not configured: {name}")
    return _DEPENDENCIES[name]


def _hipoteca_ficha_bool_text(value):
    raw = str(value or "").strip()
    if not raw:
        return "—"
    normalized = normalize_lookup_text(raw)
    if normalized in {"SI", "S", "TRUE", "1", "YES", "Y"}:
        return "Sí"
    if normalized in {"NO", "FALSE", "0", "N"}:
        return "No"
    return raw


def _hipoteca_ficha_money(value, default="—"):
    if value in (None, ""):
        return default
    try:
        amount = _dep("parse_money_value")(value)
    except Exception:
        amount = None
    if amount is None:
        text = str(value or "").strip()
        return text or default
    return _dep("format_eur")(amount)


def _hipoteca_ficha_num(value, decimals=2, default="—"):
    if value in (None, ""):
        return default
    parsed = _dep("parse_optional_float")(value)
    if parsed is None:
        text = str(value or "").strip()
        return text or default
    try:
        amount = float(parsed)
    except Exception:
        text = str(value or "").strip()
        return text or default
    raw = f"{amount:,.{int(decimals)}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if int(decimals) > 0:
        raw = raw.rstrip("0").rstrip(",")
    return raw


def _hipoteca_ficha_json_lines(raw_value):
    text = str(raw_value or "").strip()
    if not text:
        return ["{}"]
    try:
        parsed = json.loads(text)
    except Exception:
        return text.splitlines() or [text]
    try:
        return json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    except Exception:
        return text.splitlines() or [text]


def _hipoteca_ficha_intervinientes_text(cliente_inmueble):
    intervinientes = _dep("_get_nested")(cliente_inmueble or {}, "intervinientes", [])
    if not isinstance(intervinientes, list):
        return "—"
    parts = []
    for item in intervinientes:
        if not isinstance(item, dict):
            continue
        rol = str(item.get("rol") or item.get("tipo") or "Interviniente").strip()
        nombre = str(item.get("nombre") or item.get("name") or "").strip()
        nif = str(item.get("nif") or item.get("dni") or "").strip()
        chunk = " · ".join([part for part in [rol, nombre, nif] if part])
        if chunk:
            parts.append(chunk)
    return " | ".join(parts) if parts else "—"


def build_hipotecas_bdt_listado_card_items(item):
    item = item or {}

    def text(value, default="—"):
        raw = str(value or "").strip()
        return raw or default

    def money(value):
        return _dep("format_export_money")(value)

    def date_text(value):
        return _dep("format_export_date")(value) or "—"

    return [
        {"label": "Nombre y apellidos cliente", "value": text(item.get("cliente")), "accent": True},
        {"label": "Banco", "value": text(item.get("banco"))},
        {"label": "Fecha de encargo", "value": date_text(item.get("fecha_encargo"))},
        {"label": "Fecha de firma", "value": date_text(item.get("fecha_firma"))},
        {"label": "Valor compra inmueble", "value": money(item.get("precio")), "accent": True},
        {"label": "Entrada", "value": money(item.get("entrada"))},
        {"label": "Hipoteca", "value": money(item.get("importe_hipoteca")), "accent": True},
        {"label": "Comisión cobrada", "value": money(item.get("honorarios")), "accent": True},
    ]


def build_hipoteca_ficha_pdf(payload, section=None):
    payload = payload or {}
    liq_payload = _dict_or_empty(payload.get("liquidacion_print"))
    if not liq_payload:
        liq_payload = _dict_or_empty(
            _dep("compute_hipoteca_liquidacion_print_data")(
                payload,
                _dep("_safe_json_object")(payload.get("liquidacion_json") or "{}"),
            )
        )
    liq = _dict_or_empty(liq_payload.get("liq"))
    flags = _dict_or_empty(liq_payload.get("flags"))

    cliente_inmueble = _dict_or_empty(_dep("_safe_json_object")(payload.get("cliente_inmueble_json") or "{}"))
    hipoteca_detalle = _dict_or_empty(_dep("_safe_json_object")(payload.get("hipoteca_detalle_json") or "{}"))

    comprador = _dict_or_empty(liq.get("comprador"))
    gastos_cv = _dict_or_empty(comprador.get("gastos_compraventa"))
    hip = _dict_or_empty(comprador.get("hipoteca"))
    entregas = _dict_or_empty(comprador.get("entregas"))
    prestamo = _dict_or_empty(liq.get("prestamo"))
    vendedor = _dict_or_empty(liq.get("vendedor"))
    vendedor_ded = _dict_or_empty(vendedor.get("deducciones"))
    vendedor_vendedores = _dict_or_empty(vendedor.get("vendedores"))
    vend_v1 = _dict_or_empty(vendedor_vendedores.get("v1"))
    vend_v2 = _dict_or_empty(vendedor_vendedores.get("v2"))
    cuadre = _dict_or_empty(liq.get("cuadre"))
    cuadre_cheq1 = _dict_or_empty(cuadre.get("cheque1"))
    cuadre_cheq2 = _dict_or_empty(cuadre.get("cheque2"))
    cuadre_gastos = _dict_or_empty(cuadre.get("gastos_escrituras"))
    notaria = _dict_or_empty(liq.get("notaria"))

    def text(value, default="—"):
        raw = str(value or "").strip()
        return raw if raw else default

    def money(value, default="—"):
        return _hipoteca_ficha_money(value, default=default)

    def num(value, decimals=2, default="—"):
        return _hipoteca_ficha_num(value, decimals=decimals, default=default)

    def pct(value, decimals=2, default="—"):
        raw = _hipoteca_ficha_num(value, decimals=decimals, default=default)
        if raw == default:
            return default
        return f"{raw} %"

    def date_text(value):
        parsed = _dep("parse_iso_date")(value)
        if parsed:
            return parsed.strftime("%d/%m/%Y")
        return text(value)

    def nested(obj, path, default="—"):
        raw = _dep("_get_nested")(obj or {}, path, default)
        if raw in (None, ""):
            return default
        if isinstance(raw, (dict, list)):
            return default
        return str(raw).strip() or default

    def amount_value(raw):
        try:
            return float(_dep("parse_money_value")(raw or 0) or 0.0)
        except Exception:
            return 0.0

    coste_asociado = round(
        sum(
            [
                amount_value(payload.get("honorarios")),
                amount_value(payload.get("cesion")),
                amount_value(payload.get("comision_juan")),
                amount_value(payload.get("comision_modernia")),
                amount_value(nested(hip, "notaria_impuestos_gestoria")),
                amount_value(nested(hip, "comision_apertura")),
                amount_value(nested(hip, "cuota_socio")),
                amount_value(nested(hip, "comision_cheques")),
                amount_value(nested(hip, "seguro_proteccion_pago")),
                amount_value(nested(hip, "seguro_hogar")),
                amount_value(nested(hip, "seguro_vida")),
            ]
        ),
        2,
    )

    hero_card = {
        "kind": "feature_card",
        "layout": "hero",
        "eyebrow": "Presentación comercial",
        "title": text(payload.get("cliente")),
        "subtitle": " · ".join(
            [
                part
                for part in [
                    text(payload.get("banco")),
                    text(payload.get("oficina")),
                    text(payload.get("asesor")),
                ]
                if part and part != "—"
            ]
        ),
        "badge": text(payload.get("estado")),
        "chips": [
            text(payload.get("banco")),
            text(payload.get("oficina")),
            f"Encargo {text(payload.get('encargo'))}",
            f"Firma {date_text(payload.get('fecha_firma'))}",
        ],
        "items": [
            {"label": "Tipo hipoteca", "value": text(payload.get("tipo_hipoteca")), "accent": True},
            {"label": "Importe hipoteca", "value": money(payload.get("importe_hipoteca")), "accent": True},
            {"label": "% financiación", "value": pct(payload.get("porcentaje")), "accent": True},
        ],
        "note": "Ficha interna para presentar la operación de forma clara, rápida y comercial.",
    }

    resumen_cards = {
        "kind": "kpi_cards",
        "columns": 3,
        "items": [
            {"label": "Importe hipoteca", "value": money(payload.get("importe_hipoteca")), "accent": True},
            {"label": "% financiación", "value": pct(payload.get("porcentaje")), "accent": True},
            {"label": "Cuota estimada", "value": money(nested(prestamo, "cuota_inicial")), "accent": True},
            {"label": "Precio compra", "value": money(payload.get("precio"))},
            {"label": "Entrada", "value": money(payload.get("entrada"))},
            {"label": "Total necesario", "value": money(nested(hip, "total_necesario"))},
        ],
    }

    operativa_cards = {
        "kind": "kpi_cards",
        "columns": 3,
        "items": [
            {"label": "Cliente", "value": text(payload.get("cliente")), "accent": True},
            {"label": "Banco", "value": text(payload.get("banco"))},
            {"label": "Oficina", "value": text(payload.get("oficina"))},
            {"label": "Asesor", "value": text(payload.get("asesor"))},
            {"label": "Estado", "value": text(payload.get("estado")), "accent": True},
            {"label": "Fecha firma", "value": date_text(payload.get("fecha_firma"))},
        ],
    }

    trazabilidad_lines = [
        ("ID operación", text(payload.get("id"))),
        ("Empresa ID", text(payload.get("empresa_id"))),
        ("Cliente ID", text(payload.get("cliente_id"))),
        ("Creado", text(payload.get("created_at"))),
        ("Actualizado", text(payload.get("updated_at"))),
    ]

    cliente_lines = [
        ("Inmueble · Dirección", nested(cliente_inmueble, "inmueble.direccion")),
        ("Inmueble · Localidad", nested(cliente_inmueble, "inmueble.localidad")),
        ("Inmueble · Provincia", nested(cliente_inmueble, "inmueble.provincia")),
        ("Intervinientes", _hipoteca_ficha_intervinientes_text(cliente_inmueble)),
        ("C1 · Nombre", nested(cliente_inmueble, "comprador.c1.nombre")),
        ("C1 · NIF/NIE", nested(cliente_inmueble, "comprador.c1.nif")),
        ("C1 · Email", nested(cliente_inmueble, "comprador.c1.email")),
        ("C1 · Teléfono", nested(cliente_inmueble, "comprador.c1.telefono")),
        ("C1 · Domicilio", nested(cliente_inmueble, "comprador.c1.domicilio")),
        ("C2 · Nombre", nested(cliente_inmueble, "comprador.c2.nombre")),
        ("C2 · NIF/NIE", nested(cliente_inmueble, "comprador.c2.nif")),
        ("C2 · Email", nested(cliente_inmueble, "comprador.c2.email")),
        ("C2 · Teléfono", nested(cliente_inmueble, "comprador.c2.telefono")),
        ("C2 · Domicilio", nested(cliente_inmueble, "comprador.c2.domicilio")),
        ("C2 · Mismo domicilio", _hipoteca_ficha_bool_text(nested(cliente_inmueble, "comprador.c2.mismo_domicilio"))),
        ("Prestatario 1 · Fuente", nested(cliente_inmueble, "prestataria.p1.source")),
        ("Prestatario 1 · Nombre", nested(cliente_inmueble, "prestataria.p1.nombre")),
        ("Prestatario 1 · NIF/NIE", nested(cliente_inmueble, "prestataria.p1.nif")),
        ("Prestatario 2 · Fuente", nested(cliente_inmueble, "prestataria.p2.source")),
        ("Prestatario 2 · Nombre", nested(cliente_inmueble, "prestataria.p2.nombre")),
        ("Prestatario 2 · NIF/NIE", nested(cliente_inmueble, "prestataria.p2.nif")),
    ]

    hipoteca_lines = [
        ("Condiciones · Interés", num(nested(hipoteca_detalle, "condiciones.interes"), 4)),
        ("Condiciones · Cuota", money(nested(hipoteca_detalle, "condiciones.cuota"))),
        ("Preferencias · Plazo amortización (años)", num(nested(hipoteca_detalle, "preferencias.plazo_anos"), 0)),
        ("Preferencias · Tipo interés", nested(hipoteca_detalle, "preferencias.tipo_interes")),
        ("Preferencias · Garantía vivienda habitual", _hipoteca_ficha_bool_text(nested(hipoteca_detalle, "preferencias.garantia_vivienda_habitual"))),
        ("Preferencias · Comisión apertura máx.", money(nested(hipoteca_detalle, "preferencias.comision_apertura_max"))),
        ("Preferencias · Otras", nested(hipoteca_detalle, "preferencias.otras")),
        ("Precontractual · Registro", nested(hipoteca_detalle, "precontractual.registro")),
        ("Precontractual · Seguro RC", nested(hipoteca_detalle, "precontractual.seguro_rc")),
        ("Comentarios", nested(hipoteca_detalle, "comentarios")),
    ]

    comprador = _dict_or_empty(liq.get("comprador"))
    vendedor = _dict_or_empty(liq.get("vendedor"))
    vendedor_ded = _dict_or_empty(vendedor.get("deducciones"))
    vendedor_vendedores = _dict_or_empty(vendedor.get("vendedores"))
    vend_v1 = _dict_or_empty(vendedor_vendedores.get("v1"))
    vend_v2 = _dict_or_empty(vendedor_vendedores.get("v2"))
    cuadre = _dict_or_empty(liq.get("cuadre"))
    cuadre_cheq1 = _dict_or_empty(cuadre.get("cheque1"))
    cuadre_cheq2 = _dict_or_empty(cuadre.get("cheque2"))
    cuadre_gastos = _dict_or_empty(cuadre.get("gastos_escrituras"))

    comprador_lines = [
        ("Cliente", text(nested(comprador, "cliente", payload.get("cliente")))),
        ("Vivienda", nested(comprador, "vivienda")),
        ("Localidad", nested(comprador, "localidad")),
        ("Provincia", nested(comprador, "provincia")),
        ("Precio compra vivienda", money(nested(comprador, "precio_compra"))),
        ("Escriturado", money(nested(comprador, "escriturado"))),
        ("Notaría (compraventa)", money(nested(gastos_cv, "notaria"))),
        ("Registro propiedad", money(nested(gastos_cv, "registro"))),
        ("Impuesto transmisiones", money(nested(gastos_cv, "itp"))),
        ("Gestoría", money(nested(gastos_cv, "gestoria"))),
        ("Total gastos compraventa", money(nested(gastos_cv, "total"))),
        ("Notaría, impuestos y gestoría (hipoteca)", money(nested(hip, "notaria_impuestos_gestoria"))),
        ("Comisión apertura", money(nested(hip, "comision_apertura"))),
        ("Cuota socio caja", money(nested(hip, "cuota_socio"))),
        ("Comisión cheques/OMF", money(nested(hip, "comision_cheques"))),
        ("Seguro protección de pago", money(nested(hip, "seguro_proteccion_pago"))),
        ("Seguro hogar", money(nested(hip, "seguro_hogar"))),
        ("Seguro vida", money(nested(hip, "seguro_vida"))),
        ("Total gastos bloque", money(nested(hip, "total_bloque"))),
        ("Total necesario", money(nested(hip, "total_necesario"))),
        ("Gestión inmobiliaria", money(nested(comprador, "gestion_inmobiliaria"))),
        ("Gestión financiación", money(nested(comprador, "gestion_financiacion"))),
        ("Suma total necesaria", money(nested(comprador, "suma_total_necesaria"))),
        ("Señal", money(nested(entregas, "senal"))),
        ("Transf. a Modernia", money(nested(entregas, "transf_modernia"))),
        ("A ingresar en banco", money(nested(entregas, "ingresar_banco"))),
        ("Préstamo concedido", money(nested(entregas, "prestamo_concedido"))),
        ("Suma total entregada", money(nested(comprador, "suma_total_entregada"))),
        ("Sobran en cuenta", money(nested(comprador, "sobran_en_cuenta"))),
        ("Protección financiada", _hipoteca_ficha_bool_text(flags.get("proteccion_financiado"))),
        ("Hogar financiado", _hipoteca_ficha_bool_text(flags.get("hogar_financiado"))),
        ("Vida financiada", _hipoteca_ficha_bool_text(flags.get("vida_financiado"))),
    ]

    vendedor_lines = [
        ("Cliente", text(nested(vendedor, "cliente", payload.get("cliente")))),
        ("Dirección", nested(vendedor, "direccion")),
        ("Localidad", nested(vendedor, "localidad")),
        ("Precio vivienda", money(nested(vendedor, "precio_vivienda"))),
        ("Deducciones (texto)", nested(vendedor, "deducciones_nota")),
        ("Señal", money(nested(vendedor_ded, "senal"))),
        ("Cancelación económica préstamo", money(nested(vendedor_ded, "cancelacion_economica"))),
        ("Cancelación registral préstamo", money(nested(vendedor_ded, "cancelacion_registral"))),
        ("Deuda IBI", money(nested(vendedor_ded, "deuda_ibi"))),
        ("Plusvalía municipal", money(nested(vendedor_ded, "plusvalia"))),
        ("Retención 3% no residente", money(nested(vendedor_ded, "retencion_no_residente"))),
        ("Gestión no residente", money(nested(vendedor_ded, "gestion_no_residente"))),
        ("Subtotal pte. percibir", money(nested(vendedor, "subtotal_pte_percibir"))),
        ("Total a percibir", money(nested(vendedor, "total_a_percibir"))),
        ("Vendedor 1", " · ".join([part for part in [text(nested(vend_v1, "nombre")), text(nested(vend_v1, "nif"))] if part and part != "—"]) or "—"),
        ("Vendedor 2", " · ".join([part for part in [text(nested(vend_v2, "nombre")), text(nested(vend_v2, "nif"))] if part and part != "—"]) or "—"),
        ("Registro", nested(vendedor, "registro")),
        ("Finca", nested(vendedor, "finca")),
        ("Notas", nested(vendedor, "notas")),
    ]

    cheques_lines = [
        ("Préstamo concedido", money(nested(cuadre, "prestamo_concedido"))),
        ("Ingreso en cuenta", money(nested(cuadre, "ingreso_en_cuenta"))),
        ("Seguros", money(nested(cuadre, "seguros"))),
        ("Cheque 1 · Beneficiario", nested(cuadre_cheq1, "beneficiario")),
        ("Cheque 1 · Importe", money(nested(cuadre_cheq1, "importe"))),
        ("Cheque 2 · Beneficiario", nested(cuadre_cheq2, "beneficiario")),
        ("Cheque 2 · Importe", money(nested(cuadre_cheq2, "importe"))),
        ("Cancelación económica préstamo", money(nested(cuadre, "cancelacion_economica"))),
        ("Retención cancelación registral", money(nested(cuadre, "retencion_cancelacion_registral"))),
        ("Retención deuda IBI", money(nested(cuadre, "retencion_ibi"))),
        ("Retención 3% no residente", money(nested(cuadre, "retencion_no_residente"))),
        ("Gestión no residente", money(nested(cuadre, "gestion_no_residente"))),
        ("Gastos escrituras · Compraventa", money(nested(cuadre_gastos, "compraventa"))),
        ("Gastos escrituras · Hipoteca", money(nested(cuadre_gastos, "hipoteca"))),
        ("Gastos escrituras · Com. apertura", money(nested(cuadre_gastos, "com_apertura"))),
        ("Comisión cheques/OMF", money(nested(cuadre, "comision_cheques"))),
        ("Cuota socio caja", money(nested(cuadre, "cuota_socio"))),
        ("Total salidas", money(nested(cuadre, "total_salidas"))),
        ("Total medios de pago", money(nested(cuadre, "total_medios_pago"))),
        ("Diferencia vs escriturado", money(nested(cuadre, "diferencia_medios_pago"))),
        ("Sobran en cuenta (auto)", money(nested(cuadre, "sobran_en_cuenta"))),
        ("Cuadre sobrante OK", _hipoteca_ficha_bool_text(flags.get("cuadre_sobrante_ok"))),
        ("Δ sobrante", _hipoteca_ficha_num(flags.get("cuadre_sobrante_delta"), 2)),
    ]

    notaria_lines = [
        ("Notaría", nested(notaria, "nombre")),
        ("Contacto", nested(notaria, "contacto")),
        ("Atención", nested(notaria, "atencion")),
        ("Entidad hipoteca", nested(notaria, "entidad")),
        ("Op. referencia", nested(notaria, "op_referencia")),
        ("Fecha y hora firma", nested(notaria, "fecha_hora_firma")),
        ("Forma de pago", nested(notaria, "forma_pago")),
        ("Observaciones", nested(notaria, "observaciones")),
        ("Tipo salida", nested(prestamo, "tipo_salida")),
        ("Revisión", _hipoteca_ficha_num(nested(prestamo, "revision"), 4)),
        ("Interés", _hipoteca_ficha_num(nested(prestamo, "interes"), 6)),
        ("Plazo (años)", _hipoteca_ficha_num(nested(prestamo, "plazo_anos"), 0)),
        ("Nº cuotas", _hipoteca_ficha_num(nested(prestamo, "numero_cuotas"), 0)),
        ("Cuota inicial", money(nested(prestamo, "cuota_inicial"))),
        ("Apertura", _hipoteca_ficha_num(nested(prestamo, "apertura"), 4)),
        ("Ca. parcial", _hipoteca_ficha_num(nested(prestamo, "cancelacion_parcial"), 4)),
        ("Cancelación", _hipoteca_ficha_num(nested(prestamo, "cancelacion"), 4)),
    ]

    structure_bar = {
        "kind": "split_bar",
        "label": "Estructura de fondos",
        "items": [
            {"label": "Hipoteca", "value": amount_value(payload.get("importe_hipoteca"))},
            {"label": "Entrada", "value": amount_value(payload.get("entrada"))},
            {"label": "Costes asociados", "value": coste_asociado},
        ],
    }
    bank_logo_meta = build_hipoteca_bank_logo_meta(payload.get("banco"))

    sections = [
        ("Resumen comercial", {**hero_card, **bank_logo_meta}),
        ("Importes clave", resumen_cards),
        ("Estructura de fondos", structure_bar),
        ("Datos operativos", operativa_cards),
        ("Cliente e inmueble", cliente_lines),
        ("Hipoteca y condiciones", hipoteca_lines),
        ("Liquidación comprador", comprador_lines),
        ("Liquidación vendedor", vendedor_lines),
        ("Cuadre de cheques", cheques_lines),
        ("Notaría y préstamo", notaria_lines),
        ("Trazabilidad", trazabilidad_lines),
        ("JSON · cliente e inmueble", _hipoteca_ficha_json_lines(payload.get("cliente_inmueble_json") or "{}")),
        ("JSON · hipoteca detalle", _hipoteca_ficha_json_lines(payload.get("hipoteca_detalle_json") or "{}")),
        ("JSON · liquidación", _hipoteca_ficha_json_lines(payload.get("liquidacion_json") or "{}")),
    ]

    section_key = normalize_lookup_text(section or "")
    if section_key in {"COMPRADOR", "VENDEDOR", "CHEQUES", "NOTARIA"}:
        keep_map = {
            "COMPRADOR": {"Resumen comercial", "Importes clave", "Estructura de fondos", "Datos operativos", "Liquidación comprador"},
            "VENDEDOR": {"Resumen comercial", "Importes clave", "Estructura de fondos", "Datos operativos", "Liquidación vendedor"},
            "CHEQUES": {"Resumen comercial", "Importes clave", "Estructura de fondos", "Datos operativos", "Cuadre de cheques"},
            "NOTARIA": {"Resumen comercial", "Importes clave", "Estructura de fondos", "Datos operativos", "Notaría y préstamo"},
        }
        sections = [item for item in sections if item[0] in keep_map[section_key]]

    subtitle_parts = [text(payload.get("cliente")), text(payload.get("banco")), text(payload.get("estado"))]
    fecha_firma_text = date_text(payload.get("fecha_firma"))
    if fecha_firma_text and fecha_firma_text != "—":
        subtitle_parts.append(f"Firma {fecha_firma_text}")
    subtitle = " · ".join([part for part in subtitle_parts if part and part != "—"])
    subtitle = subtitle or text(payload.get("id"))
    footer = [
        "Documento comercial interno generado por el CRM Financiaciones.",
        "Revisar la liquidación y los datos técnicos antes de usarlo fuera del expediente.",
    ]
    return _dep("build_modernia_branded_document_pdf")(
        "FICHA COMERCIAL DE HIPOTECA",
        subtitle,
        sections,
        footer_lines=footer,
        company={},
        brand_logo_url="/assets/grupo_modernia_logo.png",
    )


def build_hipoteca_ficha_compact_pdf(payload):
    payload = payload or {}

    def text(value, default="—"):
        raw = str(value or "").strip()
        return raw if raw else default

    def money(value, default="—"):
        raw = str(value or "").strip()
        if not raw and value not in (0, 0.0):
            return default
        return _dep("format_export_money")(value)

    def pct(value, decimals=2, default="—"):
        raw = _dep("parse_optional_float")(value)
        if raw is None:
            text_value = str(value or "").strip()
            return text_value or default
        try:
            amount = float(raw)
        except Exception:
            text_value = str(value or "").strip()
            return text_value or default
        if 0 <= amount <= 1:
            amount *= 100
        value_text = f"{amount:,.{int(decimals)}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if int(decimals) > 0:
            value_text = value_text.rstrip("0").rstrip(",")
        return f"{value_text} %"

    def date_text(value):
        parsed = _dep("parse_iso_date")(value)
        if parsed:
            return parsed.strftime("%d/%m/%Y")
        return text(value)

    def total_associated():
        return round(
            sum(
                [
                    float(_dep("parse_money_value")(payload.get("honorarios") or 0) or 0.0),
                    float(_dep("parse_money_value")(payload.get("cesion") or 0) or 0.0),
                    float(_dep("parse_money_value")(payload.get("comision_juan") or 0) or 0.0),
                    float(_dep("parse_money_value")(payload.get("comision_modernia") or 0) or 0.0),
                ]
            ),
            2,
        )

    bank_logo_meta = build_hipoteca_bank_logo_meta(payload.get("banco"))
    cliente = text(payload.get("cliente"))
    banco = text(payload.get("banco"))
    oficina = text(payload.get("oficina") or payload.get("inmobiliaria"))
    asesor = text(payload.get("asesor"))
    estado = text(payload.get("estado"))
    tipo_hipoteca = text(payload.get("tipo_hipoteca"))
    fecha_encargo = date_text(payload.get("fecha_encargo"))
    fecha_firma = date_text(payload.get("fecha_firma"))

    subtitle_parts = [part for part in [banco, oficina, asesor] if part and part != "—"]
    subtitle = " · ".join(subtitle_parts) or text(payload.get("id"))
    hero_card = {
        "kind": "feature_card",
        "layout": "hero",
        "eyebrow": "Ficha comercial resumida",
        "title": cliente,
        "subtitle": subtitle,
        "badge": estado,
        "chips": [
            value
            for value in [
                banco if banco != "—" else "",
                oficina if oficina != "—" else "",
                f"Encargo {fecha_encargo}" if fecha_encargo != "—" else "",
                f"Firma {fecha_firma}" if fecha_firma != "—" else "",
            ]
            if value
        ],
        "items": [
            {"label": "Importe hipoteca", "value": money(payload.get("importe_hipoteca")), "accent": True},
            {"label": "Precio compra", "value": money(payload.get("precio")), "accent": True},
            {"label": "% financiación", "value": pct(payload.get("porcentaje")), "accent": True},
        ],
        "note": "Ficha resumida de una sola hoja.",
    }

    operativa_cards = {
        "kind": "kpi_cards",
        "columns": 4,
        "items": [
            {"label": "Cliente", "value": cliente, "accent": True},
            {"label": "Banco", "value": banco},
            {"label": "Oficina", "value": oficina},
            {"label": "Asesor", "value": asesor},
            {"label": "Estado", "value": estado, "accent": True},
            {"label": "Tipo hipoteca", "value": tipo_hipoteca},
            {"label": "Fecha encargo", "value": fecha_encargo},
            {"label": "Fecha firma", "value": fecha_firma},
        ],
    }

    importes_cards = {
        "kind": "kpi_cards",
        "columns": 4,
        "items": [
            {"label": "Entrada", "value": money(payload.get("entrada")), "accent": True},
            {"label": "Comisión cliente", "value": money(payload.get("honorarios")), "accent": True},
            {"label": "Cesión banco", "value": money(payload.get("cesion"))},
            {"label": "Comisión Juan", "value": money(payload.get("comision_juan"))},
            {"label": "Comisión Modernia", "value": money(payload.get("comision_modernia"))},
            {"label": "Total asociado", "value": money(total_associated()), "accent": True},
        ],
    }

    footer_lines = [
        "Ficha resumida de una sola hoja para impresión rápida.",
        "La ficha completa sigue disponible en la descarga individual.",
    ]
    return _dep("build_modernia_branded_document_pdf")(
        "FICHA COMERCIAL RESUMIDA",
        subtitle,
        [
            ("Resumen comercial", {**hero_card, **bank_logo_meta}),
            ("Datos operativos", operativa_cards),
            ("Importes clave", importes_cards),
        ],
        footer_lines=footer_lines,
        company={},
        brand_logo_url="/assets/grupo_modernia_logo.png",
    )


def build_hipotecas_bdt_listado_pdf(conn, rows, filters=None):
    rows = [row for row in (rows or []) if row is not None]
    if not rows:
        return b""

    items = [_dep("build_hipoteca_export_row")(conn, row) for row in rows]
    filters = filters if isinstance(filters, dict) else {}

    year = str(filters.get("year") or "").strip()
    estado = str(filters.get("estado") or "").strip()
    query = str(filters.get("query") or "").strip()
    order = normalize_hipoteca_pdf_sort_order(filters.get("order") or filters.get("sort_order") or "desc")
    ordered_items = sorted(items, key=_dep("hipoteca_export_sort_key"), reverse=order != "asc")
    total = len(ordered_items)
    filter_parts = []
    if year:
        filter_parts.append(f"Año {year}")
    if estado:
        filter_parts.append(f"Estado {estado}")
    if query:
        filter_parts.append(f'Búsqueda "{query}"')
    filter_parts.append("Orden ascendente" if order == "asc" else "Orden descendente")
    if not (year or estado or query):
        filter_parts.insert(0, f"{total} operación(es)")
    subtitle = " · ".join(filter_parts) if filter_parts else f"{total} operación(es)"
    money = _dep("format_export_money")

    total_precio = sum(float(item.get("precio") or 0) for item in ordered_items)
    total_entrada = sum(float(item.get("entrada") or 0) for item in ordered_items)
    total_hipoteca = sum(float(item.get("importe_hipoteca") or 0) for item in ordered_items)
    total_comision = sum(float(item.get("honorarios") or 0) for item in ordered_items)

    summary = {
        "kind": "kpi_cards",
        "columns": 3,
        "items": [
            {"label": "Operaciones", "value": str(total), "accent": True},
            {"label": "Compra total", "value": money(total_precio), "accent": True},
            {"label": "Entrada total", "value": money(total_entrada)},
            {"label": "Hipoteca total", "value": money(total_hipoteca), "accent": True},
            {"label": "Comisión cobrada", "value": money(total_comision), "accent": True},
        ],
    }

    sections = [("Resumen", summary), ("__PAGE_BREAK__", [])]
    for idx, item in enumerate(ordered_items, start=1):
        bank_logo_meta = build_hipoteca_bank_logo_meta(item.get("banco"))
        sections.append(
            (
                f"Operación {idx:02d}",
                {
                    "kind": "feature_card",
                    "layout": "hero",
                    "eyebrow": f"Operación {idx}/{total}",
                    "title": str(item.get("cliente") or "").strip() or f"Hipoteca {idx}",
                    "subtitle": " · ".join(
                        [
                            part
                            for part in [
                                str(item.get("banco") or "").strip(),
                                str(item.get("oficina") or item.get("inmobiliaria") or "").strip(),
                                str(item.get("asesor") or "").strip(),
                            ]
                            if part
                        ]
                    ),
                    "badge": str(item.get("estado") or "").strip(),
                    "chips": [
                        part
                        for part in [
                            str(item.get("banco") or "").strip(),
                            _dep("format_export_date")(item.get("fecha_encargo")) or "",
                            _dep("format_export_date")(item.get("fecha_firma")) or "",
                        ]
                        if part
                    ],
                    **bank_logo_meta,
                    "items": [
                        {"label": "Nombre y apellidos cliente", "value": str(item.get("cliente") or "").strip() or "—", "accent": True},
                        {"label": "Banco", "value": str(item.get("banco") or "").strip() or "—"},
                        {"label": "Fecha de encargo", "value": _dep("format_export_date")(item.get("fecha_encargo"))},
                        {"label": "Fecha de firma", "value": _dep("format_export_date")(item.get("fecha_firma"))},
                        {"label": "Valor compra inmueble", "value": _dep("format_export_money")(item.get("precio")), "accent": True},
                        {"label": "Entrada", "value": _dep("format_export_money")(item.get("entrada"))},
                        {"label": "Hipoteca", "value": _dep("format_export_money")(item.get("importe_hipoteca")), "accent": True},
                        {"label": "Comisión cobrada", "value": _dep("format_export_money")(item.get("honorarios") or item.get("comision")), "accent": True},
                    ],
                    "note": "Ficha comercial resumida del listado.",
                },
            )
        )
        sections.append(
            (
                f"Datos operativos {idx}",
                {
                    "kind": "kpi_cards",
                    "columns": 2,
                    "items": build_hipotecas_bdt_listado_card_items(item),
                },
            )
        )
        if idx < total:
            sections.append(("__PAGE_BREAK__", []))
    footer_lines = [
        "Listado interno generado por el CRM Financiaciones.",
        "Cada operación se presenta con un orden fijo para facilitar la revisión comercial.",
    ]
    return _dep("build_modernia_branded_document_pdf")(
        "LISTADO DE HIPOTECAS",
        subtitle,
        sections,
        footer_lines=footer_lines,
        company={},
        brand_logo_url="/assets/grupo_modernia_logo.png",
    )


def build_hipotecas_listado_pdf(conn, rows, section=None, filters=None):
    rows = [row for row in (rows or []) if row is not None]
    if not rows:
        return b""

    filters = filters if isinstance(filters, dict) else {}
    order = normalize_hipoteca_pdf_sort_order(filters.get("order") or filters.get("sort_order") or "desc")

    if PdfReader is not None and PdfWriter is not None:
        writer = PdfWriter()
        page_count = 0
        for row in _dep("sort_hipoteca_export_rows")(rows, order=order):
            payload = _dep("build_hipoteca_ficha_payload")(conn, row)
            pdf_bytes = build_hipoteca_ficha_compact_pdf(payload)
            if not pdf_bytes:
                continue
            reader = PdfReader(BytesIO(pdf_bytes))
            for page in reader.pages:
                writer.add_page(page)
                page_count += 1
        if not page_count:
            return b""
        buffer = BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    def money_or_dash(value):
        raw = str(value or "").strip()
        if not raw and value not in (0, 0.0):
            return "—"
        return _dep("format_export_money")(value)

    def percent_or_dash(value):
        raw = str(value or "").strip()
        if not raw and value not in (0, 0.0):
            return "—"
        amount = _dep("parse_money_value")(value)
        if amount is None:
            return "—"
        if 0 <= amount <= 1:
            amount *= 100
        return f"{amount:.2f} %"

    payloads = [_dep("build_hipoteca_ficha_payload")(conn, row) for row in _dep("sort_hipoteca_export_rows")(rows, order=order)]
    total = len(payloads)
    filter_parts = []
    if isinstance(filters, dict):
        year = str(filters.get("year") or "").strip()
        estado = str(filters.get("estado") or "").strip()
        query = str(filters.get("query") or "").strip()
        if year:
            filter_parts.append(f"Año {year}")
        if estado:
            filter_parts.append(f"Estado {estado}")
        if query:
            filter_parts.append(f'Búsqueda "{query}"')
        filter_parts.append("Orden ascendente" if order == "asc" else "Orden descendente")
        if not (year or estado or query):
            filter_parts.insert(0, f"{total} operación(es)")
    subtitle = " · ".join(filter_parts) if filter_parts else f"{total} operación(es)"

    sections: list[tuple[str, Any]] = []
    for idx, payload in enumerate(payloads, start=1):
        cliente = str(payload.get("cliente") or "").strip() or f"Hipoteca {idx}"
        banco = str(payload.get("banco") or "").strip() or "-"
        oficina = str(payload.get("oficina") or payload.get("inmobiliaria") or "").strip() or "-"
        asesor = str(payload.get("asesor") or "").strip() or "-"
        estado = str(payload.get("estado") or "").strip() or "-"
        fecha_encargo = _dep("format_export_date")(payload.get("fecha_encargo")) or "—"
        fecha_firma = _dep("format_export_date")(payload.get("fecha_firma")) or "—"
        bank_logo_meta = build_hipoteca_bank_logo_meta(payload.get("banco"))
        summary_chips = [
            value
            for value in [
                banco,
                oficina,
                asesor,
                f"Encargo {fecha_encargo}" if fecha_encargo != "—" else "",
                f"Firma {fecha_firma}" if fecha_firma != "—" else "",
            ]
            if value and value != "—"
        ]

        sections.append(
            (
                f"Ficha {idx}/{total}",
                {
                    "kind": "feature_card",
                    "layout": "hero",
                    "eyebrow": "Presentación comercial",
                    "title": cliente,
                    "subtitle": " · ".join(summary_chips),
                    "badge": estado,
                    "chips": summary_chips,
                    **bank_logo_meta,
                    "items": [
                        {"label": "Importe hipoteca", "value": money_or_dash(payload.get("importe_hipoteca")), "accent": True},
                        {"label": "Precio compra", "value": money_or_dash(payload.get("precio")), "accent": True},
                        {"label": "% financiación", "value": percent_or_dash(payload.get("porcentaje")), "accent": True},
                    ],
                    "note": "Ficha comercial resumida para impresión masiva de operaciones.",
                },
            )
        )

        sections.append(
            (
                f"Datos operativos {idx}",
                {
                    "kind": "kpi_cards",
                    "columns": 3,
                    "items": [
                        {"label": "Cliente", "value": cliente, "accent": True},
                        {"label": "Banco", "value": banco},
                        {"label": "Oficina", "value": oficina},
                        {"label": "Asesor", "value": asesor},
                        {"label": "Estado", "value": estado, "accent": True},
                        {"label": "Fecha encargo", "value": fecha_encargo},
                        {"label": "Fecha firma", "value": fecha_firma},
                        {"label": "Tipo hipoteca", "value": str(payload.get("tipo_hipoteca") or "").strip() or "—"},
                    ],
                },
            )
        )

        sections.append(
            (
                f"Importes {idx}",
                {
                    "kind": "kpi_cards",
                    "columns": 3,
                    "items": [
                        {"label": "Entrada", "value": money_or_dash(payload.get("entrada")), "accent": True},
                        {"label": "Comisión", "value": money_or_dash(payload.get("honorarios") or payload.get("comision")), "accent": True},
                        {"label": "Cesión", "value": money_or_dash(payload.get("cesion"))},
                        {"label": "Comisión Juan", "value": money_or_dash(payload.get("comision_juan"))},
                        {"label": "Comisión Modernia", "value": money_or_dash(payload.get("comision_modernia"))},
                        {"label": "Importe hipoteca", "value": money_or_dash(payload.get("importe_hipoteca")), "accent": True},
                    ],
                },
            )
        )
        if idx < total:
            sections.append(("__PAGE_BREAK__", []))

    footer_lines = [
        "Documento comercial interno generado por el CRM Financiaciones.",
        "Cada ficha resume la operación en formato de presentación para impresión masiva.",
    ]
    return _dep("build_modernia_branded_document_pdf")(
        "FICHAS DE HIPOTECAS",
        subtitle,
        sections,
        footer_lines=footer_lines,
        company={},
        brand_logo_url="/assets/grupo_modernia_logo.png",
    )


build_hipotecas_fichas_pdf = build_hipotecas_listado_pdf
