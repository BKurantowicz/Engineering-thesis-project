"""Escaped document presentation with editable, non-executable HTML templates.

Templates use {{token}} placeholders. Renderers supply escaped data and generated
table fragments; template files cannot execute Python or fetch external assets.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
import re


BUNDLED_DIR = Path(__file__).resolve().parents[1] / "templates"
DEFAULTS = {kind: f"{kind}-standard.html" for kind in ("invoice", "email", "pick")}
CONFIG_KEYS = {"invoice": "invoice", "email": "email", "pick": "pick_list"}
TOKENS = {"lang", "title", "reference", "date", "intro", "parties", "table_head", "rows", "summary", "footer", "tracking"}
REQUIRED = {
    "invoice": {"title", "reference", "parties", "table_head", "rows", "summary"},
    "email": {"title", "reference", "tracking", "parties", "table_head", "rows", "summary", "footer"},
    "pick": {"title", "reference", "date", "table_head", "rows", "summary"},
}
TOKEN = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
UNSAFE = re.compile(r"<(?:script|iframe|object|embed|link|base|form)\b|\bon\w+\s*=|\b(?:src|href)\s*=|@import|url\s*\(", re.I)

# Keep the packaged standards available if an operator deletes a selected file
# while the app is running. The emergency shell also works after accidental
# removal of the entire templates directory before startup.
_EMERGENCY = '''<!DOCTYPE html><html lang="{{lang}}"><head><meta charset="UTF-8"><title>{{title}}</title>
<style>@page { size:A4; margin:12mm; } @media print { body { background:#fff; } } tr { page-break-inside:avoid; }</style></head>
<body style="margin:0;padding:24px;background:#f4f6f8;color:#1e293b;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:600px;margin:auto;padding:24px;background:#fff;border:1px solid #e2e8f0;border-top:5px solid #2563eb;border-radius:8px;">
<h1 style="font-size:24px;">{{title}}</h1><p>{{reference}} · {{date}}</p><p>{{intro}}</p>{{tracking}}{{parties}}
<table width="100%" style="width:100%;border-collapse:collapse;"><thead>{{table_head}}</thead><tbody>{{rows}}</tbody></table>
<p>{{summary}}</p><p style="font-size:11px;color:#64748b;">{{footer}}</p></div></body></html>'''
_BUNDLED_STANDARDS = {}
for _kind, _filename in DEFAULTS.items():
    try:
        _BUNDLED_STANDARDS[_kind] = (BUNDLED_DIR / _filename).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        _BUNDLED_STANDARDS[_kind] = _EMERGENCY


class _Html(str):
    """Only fragments created by this module bypass escaping."""


def template_config(config):
    value = (config or {}).get("paths", {}).get("templates", {})
    return value if isinstance(value, dict) else {}


def template_directory(config):
    folder = template_config(config).get("base_dir", "")
    return Path(folder).expanduser() if isinstance(folder, str) and folder.strip() else BUNDLED_DIR


def list_templates(config, kind):
    if kind not in DEFAULTS:
        raise ValueError("template_kind")
    try:
        return sorted((p.name for p in template_directory(config).iterdir()
                       if p.is_file() and p.name.startswith(kind + "-") and p.suffix.lower() == ".html"), key=str.casefold)
    except OSError:
        return []


def _label(translator, key):
    return translator.t("doc_" + key, key.replace("_", " ").title())


def _validate(source, kind):
    tokens = set(TOKEN.findall(source))
    remainder = TOKEN.sub("", source)
    if not REQUIRED[kind].issubset(tokens) or tokens - TOKENS or "{{" in remainder or "}}" in remainder:
        raise ValueError("template_tokens")
    if UNSAFE.search(source) or re.search(r"\bborder\s*=\s*['\"]?1\b", source, re.I):
        raise ValueError("template_content")


def render_document(kind, context, config, translator):
    """Render escaped context with the selected template; return a fallback warning."""
    if kind not in DEFAULTS:
        raise ValueError("template_kind")
    settings = template_config(config)
    name = settings.get(CONFIG_KEYS[kind]) or DEFAULTS[kind]
    warning = ""
    try:
        if not isinstance(name, str) or Path(name).name != name or not name.startswith(kind + "-") or Path(name).suffix.lower() != ".html":
            raise ValueError("template_name")
        folder = template_directory(config).resolve()
        path = (folder / name).resolve()
        if path.parent != folder:
            raise ValueError("template_location")
        source = path.read_text(encoding="utf-8-sig")
        _validate(source, kind)
    except (OSError, UnicodeError, ValueError):
        source = _BUNDLED_STANDARDS[kind]
        try:
            _validate(source, kind)
        except ValueError:
            source = _EMERGENCY
        warning = translator.t("doc_template_fallback", "The selected template is missing or invalid. The built-in Standard template was used.")
    values = {key: value if isinstance(value, _Html) else escape(str(value if value is not None else ""), quote=True)
              for key, value in context.items()}
    # Replace only original placeholders, never tokens embedded in customer data.
    return TOKEN.sub(lambda match: values.get(match[1], ""), source), warning


def money(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("document_amount")
        return f"{number:.2f}"
    except (InvalidOperation, TypeError):
        raise ValueError("document_amount") from None


def date_text(value, translator):
    try:
        stamp = datetime.fromisoformat(str(value))
        return stamp.strftime("%Y-%m-%d, ") + ("godz. " if translator.lang_code == "pl" else "") + stamp.strftime("%H:%M")
    except (ValueError, TypeError):
        return str(value or "—")


def _e(value):
    return escape(str(value if value is not None else ""), quote=True)


def _party(values):
    return "<br>".join(_e(value) for value in values if value)


def _person(person):
    return _party((" ".join(filter(None, (person.get("first_name"), person.get("last_name")))),
                   person.get("street"), " ".join(filter(None, (person.get("postal_code"), person.get("city")))),
                   person.get("country")))


def _header(labels, numeric=()):
    return _Html("<tr>" + "".join(f'<th style="padding:10px 8px;text-align:{"right" if i in numeric else "left"};'
        f'border-bottom:2px solid #cbd5e1;color:#334155;background-color:#f1f5f9;">{_e(label)}</th>'
        for i, label in enumerate(labels)) + "</tr>")


def _cells(values, row, numeric=(), background=None):
    color = background or ("#f8fafc" if row % 2 else "#ffffff")
    return "<tr>" + "".join(f'<td style="padding:10px 8px;text-align:{"right" if i in numeric else "left"};'
        f'border-bottom:1px solid #e2e8f0;background-color:{color};">{_e(value)}</td>'
        for i, value in enumerate(values)) + "</tr>"


def _totals(lines, translator):
    rows = []
    for key in ("net", "vat", "gross"):
        cents = sum(int(line[key + "_cents"]) for line in lines)
        amount = money(Decimal(cents) / 100) + " PLN"
        final = key == "gross"
        style = "font-size:12pt;font-weight:bold;color:#0f172a;" if final else "font-size:10pt;color:#475569;"
        label = _label(translator, "total") if final else _label(translator, key)
        rows.append(f'<tr><td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;"><p style="margin:0;{style}">{_e(label)}</p></td>'
                    f'<td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;text-align:right;"><p style="margin:0;text-align:right;{style}">{amount}</p></td></tr>')
    return _Html('<table width="100%" style="width:100%;border-collapse:collapse;"><tr><td width="55%"></td>'
                 '<td width="45%"><table width="100%" style="width:100%;border-collapse:collapse;background-color:#f8fafc;">'
                 + "".join(rows) + "</table></td></tr></table>")


def _context(translator):
    return dict.fromkeys(TOKENS, "") | {"lang": translator.lang_code}


def invoice_html(document, config, translator):
    context = _context(translator)
    seller, recipient, billing = document["seller"], document["recipient"], document.get("billing", {})
    seller_html = _party(seller.get(k) for k in ("name", "street", "postal_code", "city", "country", "tax_id", "bank", "bdo"))
    buyer_html = _party((billing.get("billing_name") or " ".join(filter(None, (recipient.get("first_name"), recipient.get("last_name")))),
        billing.get("billing_street") or recipient.get("street"), billing.get("billing_postal_code") or recipient.get("postal_code"),
        billing.get("billing_city") or recipient.get("city"), billing.get("billing_country") or recipient.get("country"), billing.get("tax_id")))
    parties = '<table width="100%" style="width:100%;border-collapse:collapse;"><tr>'
    for label, content in (("seller", seller_html), ("buyer", buyer_html)):
        parties += f'<td width="50%" valign="top" style="padding:12px 12px 18px 0;vertical-align:top;"><h3 style="font-size:11pt;color:#64748b;margin:0 0 8px 0;">{_e(_label(translator,label))}</h3><p style="margin:0;">{content}</p></td>'
    parties += '</tr></table>'
    lines = [*document["lines"], dict(document["delivery"], name_pl=_label(translator,"delivery"), name_en=_label(translator,"delivery"))]
    rows = []
    for index, line in enumerate(lines):
        values = (line.get("name_" + translator.lang_code) or line.get("sku", ""), line["quantity"], money(line["unit"]),
                  line["vat"], *(money(Decimal(int(line[k])) / 100) for k in ("net_cents", "vat_cents", "gross_cents")))
        rows.append(_cells(values, index, range(1,7)))
    context.update(title=_label(translator,"invoice") + " " + str(document["number"]), reference=f"ORD-{int(document['order_id']):05d}",
        date=date_text(document["date"],translator), parties=_Html(parties),
        table_head=_header([_label(translator,key) for key in ("product","quantity","unit_gross","rate","net","vat","gross")],range(1,7)),
        rows=_Html("".join(rows)), summary=_totals(lines,translator), footer=_label(translator,"generated"))
    return render_document("invoice",context,config,translator)


def email_html(data, config, translator):
    context = _context(translator)
    lines = list(data.get("lines") or [])
    delivery = data.get("delivery")
    rows = []
    for index, line in enumerate(lines):
        rows.append(_cells((line.get("name_" + translator.lang_code) or line.get("sku", ""),
            line["quantity"], money(line["unit"]) + " PLN", money(Decimal(int(line["gross_cents"]))/100) + " PLN"),index,(1,2,3)))
    if delivery:
        rows.append(_cells((_label(translator,"delivery"),1,money(delivery["unit"])+" PLN",money(Decimal(int(delivery["gross_cents"]))/100)+" PLN"),len(lines),(1,2,3)))
    seller = data.get("seller",{})
    tracking = '<div style="padding:16px;background-color:#eff6ff;border:1px solid #dbeafe;border-radius:6px;">'
    tracking += f'<strong>{_e(_label(translator,"carrier"))}:</strong> {_e(data.get("carrier"))}<br>'
    tracking += f'<strong>{_e(_label(translator,"tracking"))}:</strong> {_e(data.get("tracking"))}</div>'
    notice = _label(translator,"invoice_attached") if data.get("invoice_number") else _label(translator,"invoice_later")
    footer = _party((seller.get("name"),seller.get("email"),seller.get("phone"),_label(translator,"generated")))
    context.update(title=_label(translator,"shipped" if data.get("final") else "parcel_shipped"), reference=data.get("order",""),
        intro=_label(translator,"mail_intro") + " " + notice, tracking=_Html(tracking),
        parties=_Html(f'<h3 style="font-size:14px;margin:24px 0 8px;color:#334155;">{_e(_label(translator,"destination"))}</h3><p style="margin:0;line-height:1.6;">{_person(data.get("recipient",{}))}</p>'),
        table_head=_header([_label(translator,key) for key in ("product","quantity","unit_gross","gross")],(1,2,3)),
        rows=_Html("".join(rows)), summary=_totals(lines+([delivery] if delivery else []),translator), footer=_Html(footer))
    return render_document("email",context,config,translator)


def pick_html(data, config, translator):
    context = _context(translator)
    rows, units, skus = [], 0, set()
    for index,line in enumerate(data.get("lines",[])):
        cancelled = bool(line.get("cancelled")) or line.get("order_status")=="CANCELLED"
        quantity = int(line["quantity"])
        picked = int(line.get("picked_quantity",0))
        complete = not cancelled and quantity > 0 and picked >= quantity
        if not cancelled:
            units += max(0,quantity-picked)
            skus.add(line["sku"])
        state = _label(translator,"resolved" if cancelled else "picked" if complete else "open")
        check = "—" if cancelled else "☑" if complete else "□"
        background = "#f1f5f9" if cancelled else "#ecfdf5" if complete else "#f8fafc" if index%2 else "#ffffff"
        values = (line["order_id"],line["sku"],line.get("name_"+translator.lang_code,""),line["location_code"],quantity,picked,state,check)
        cells=[]
        for col,value in enumerate(values):
            style = "text-align:center;font-weight:bold;font-size:13px;" if col in (3,4,7) else "text-align:left;"
            if col==7:
                style += "font-family:'Segoe UI Symbol','DejaVu Sans',sans-serif;font-size:19px;"
            cells.append(f'<td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;background-color:{background};{style}">{_e(value)}</td>')
        rows.append("<tr>"+"".join(cells)+"</tr>")
    if not rows:
        rows.append('<tr><td colspan="8" style="padding:16px;">'+_e(_label(translator,"missing_allocations"))+"</td></tr>")
    context.update(title=_label(translator,"pick_list"),reference=f"#{data['pick_list_id']}",date=date_text(data.get("generated_at",data.get("created_at")),translator),
        table_head=_header([_label(translator,k) for k in ("order","sku","product","rack","allocated","picked","status","check")]),
        rows=_Html("".join(rows)),summary=f"{_label(translator,'sku_count')}: {len(skus)} · {_label(translator,'remaining_units')}: {units}",
        footer=_label(translator,"pick_note"))
    return render_document("pick",context,config,translator)
