"""Read UTF-8 semicolon CSV or JSON records and validate one marketplace order at a time."""
import csv
import json
from io import StringIO
from pathlib import Path


def read_groups(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        records = json.loads(text)
        if isinstance(records,dict):
            records = [records]
    elif path.suffix.lower() == ".csv":
        records = list(csv.DictReader(StringIO(text),delimiter=";",strict=True))
    else:
        raise ValueError("file_format")
    if not isinstance(records,list) or not records or any(not isinstance(r,dict) for r in records):
        raise ValueError("file_format")
    groups = {}
    for record in records:
        row = {str(k):"" if v is None else str(v).strip() for k,v in record.items()}
        key = (row.get("Platforma","").casefold(),row.get("Nr_Zewnetrzny","").casefold())
        groups.setdefault(key,[]).append(row)
    return groups


def import_group(sales, rows, choices, blank_choice=None):
    first = rows[0]
    line_keys = {"SKU","Ilosc","Cena_Sztuka","Cena_Netto","VAT"}
    if any({k:v for k,v in r.items() if k not in line_keys} !=
           {k:v for k,v in first.items() if k not in line_keys} for r in rows[1:]):
        raise ValueError("conflicting_headers")

    def match(table,key,name,*columns):
        value = first.get(name,"").casefold()
        matches = [r[key] for r in choices[table] if value and any(str(r[c]).casefold()==value for c in columns)]
        if len(matches)!=1:
            raise ValueError(name)
        return matches[0]

    recipient = dict(first_name=first.get("Imie",""),last_name=first.get("Nazwisko",""),
                     street=" ".join(filter(None,(first.get("Ulica"),first.get("Nr_Domu")))),
                     postal_code=first.get("Kod_Pocztowy",""),city=first.get("Miasto",""),
                     country=first.get("Kraj",""),email=first.get("Email",""),phone=first.get("Telefon",""))
    if not recipient["email"] and blank_choice is None:
        raise ValueError("customer_id")
    header = dict(channel=first.get("Platforma",""),external_ref=first.get("Nr_Zewnetrzny",""),
                  customer_id=blank_choice,recipient=recipient,
                  billing={k:first.get(src,"") for k,src in (("billing_name","Firma"),("tax_id","NIP"),
                    ("billing_street","Faktura_Ulica"),("billing_city","Faktura_Miasto"),
                    ("billing_postal_code","Faktura_Kod"),("billing_country","Faktura_Kraj"))},
                  payment=match("payments","id","Platnosc","id","name_pl","name_en"),
                  carrier=match("carriers","shipping_id","Kurier","shipping_id","carrier_name","service_name_pl","service_name_en"),
                  package_type=match("types","package_code","Typ_Wysylki","package_code","name_pl","name_en"),
                  delivery=first.get("Koszt_Wysylki","0"),delivery_vat=first.get("VAT_Wysylki","0"))
    items = []
    for r in rows:
        products = [p for p in choices["products"] if p["sku"].casefold()==r.get("SKU","").casefold()]
        if len(products)!=1:
            raise ValueError("SKU")
        items.append(dict(product_id=products[0]["product_id"],unit=r.get("Cena_Sztuka",""),
                          quantity=r.get("Ilosc",""),vat=r.get("VAT","")))
    return sales.save(header,items,new_customer=recipient if recipient["email"] or blank_choice=="new" else None,importing=True)
