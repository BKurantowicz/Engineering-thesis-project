"""Invoice rendering and persisted per-parcel SMTP outcomes."""
import json
import os
import smtplib
import ssl
import time
from contextlib import closing
from email.message import EmailMessage
from html import escape
from pathlib import Path
from tempfile import NamedTemporaryFile

from PySide6.QtGui import QTextDocument, QPdfWriter, QPageSize

from controllers.inventory_controller import connect


def invoice_pdf(db_path, invoice_id, directory, translator):
    with closing(connect(db_path)) as db:
        row = db.execute("SELECT document FROM invoices WHERE invoice_id=?", (invoice_id,)).fetchone()
    if not row or not row[0]:
        raise ValueError("no_invoice")
    data = json.loads(row[0])
    t = translator.t
    def html(v):
        return escape(str(v or ""))
    def party(title, values):
        return "<h3>"+html(title)+"</h3><p>"+"<br>".join(html(v) for v in values if v)+"</p>"
    seller,recipient,billing = data["seller"],data["recipient"],data["billing"]
    parts = ["<h1>"+html(t("invoice"))+" "+html(data["number"])+"</h1>",
             f"<p>ORD-{data['order_id']:05d} · {html(data['date'])}</p>",
             party(t("seller"),[seller.get(k) for k in ("name","street","postal_code","city","tax_id","bank","bdo")]),
             party(t("billing"),[billing.get("billing_name") or (recipient["first_name"]+" "+recipient["last_name"]),
                                  billing.get("billing_street") or recipient["street"],billing.get("billing_postal_code") or recipient["postal_code"],
                                  billing.get("billing_city") or recipient["city"],billing.get("billing_country") or recipient["country"],billing.get("tax_id")])]
    parts.append("<table border='1' cellpadding='5'><tr>"+"".join("<th>"+html(t(k,k))+"</th>" for k in
                 ("product","quantity","price","vat_rate","net","vat","gross"))+"</tr>")
    lines = [*data["lines"],dict(data["delivery"],name_en=t("delivery"),name_pl=t("delivery"))]
    for line in lines:
        values = (line["name_"+translator.lang_code],line["quantity"],line["unit"],line["vat"],
                  *(f"{line[k]/100:.2f}" for k in ("net_cents","vat_cents","gross_cents")))
        parts.append("<tr>"+"".join("<td>"+escape(str(v))+"</td>" for v in values)+"</tr>")
    parts.append("</table><p>"+" · ".join(f"{html(t(k))} {sum(i[k+'_cents'] for i in lines)/100:.2f} PLN" for k in ("net","vat","gross"))+"</p>")
    directory = Path(directory)
    directory.mkdir(exist_ok=True,parents=True)
    path = directory/(data["number"].replace("/","-")+".pdf")
    with NamedTemporaryFile(suffix=".pdf",dir=directory,delete=False) as f:
        temporary = Path(f.name)
    try:
        pdf = QPdfWriter(str(temporary))
        pdf.setPageSize(QPageSize(QPageSize.A4))
        pdf.setTitle(data["number"])
        doc = QTextDocument()
        doc.setHtml("".join(parts))
        doc.print_(pdf)
        del pdf
        if not temporary.read_bytes().startswith(b"%PDF-"):
            raise OSError(str(path))
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def mail_text(message, translator):
    return translator.t("tracking_message").format(**message)


class DispatchMail:
    def __init__(self, db_path):
        self.db_path = db_path

    def get(self,shipment_id):
        with closing(connect(self.db_path)) as db:
            row = db.execute("SELECT * FROM dispatch_mail WHERE shipment_id=?",(shipment_id,)).fetchone()
            return dict(row) if row else None

    def invoice_for(self,order_id):
        with closing(connect(self.db_path)) as db:
            row = db.execute("SELECT invoice_id FROM invoices WHERE order_id=? AND document IS NOT NULL",(order_id,)).fetchone()
            return row[0] if row else None

    def send(self,shipment_id,config,translator,allow_uncertain=False):
        states = ("pending","failed","uncertain") if allow_uncertain else ("pending","failed")
        with closing(connect(self.db_path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute("SELECT * FROM dispatch_mail WHERE shipment_id=?",(shipment_id,)).fetchone()
            if job and job["state"]=="sending":
                if (job["claimed_at"] or 0) > time.time()-900:
                    return "sending"
                db.execute("UPDATE dispatch_mail SET state='uncertain' WHERE shipment_id=?", (shipment_id,))
                return "uncertain"
            if not job or job["state"] not in states:
                return job["state"] if job else "no_email"
            # A process interrupted after claiming the job leaves an explicit uncertain result.
            db.execute("UPDATE dispatch_mail SET state='sending',claimed_at=?,detail=NULL WHERE shipment_id=?",(int(time.time()),shipment_id))
        smtp=None
        submitted=False
        try:
            settings=config.get("email_smtp",{})
            host=settings.get("host","").strip()
            sender=settings.get("sender") or config.get("company_info",{}).get("email")
            mode=settings.get("security","")
            if not host or not sender or mode not in ("TLS","STARTTLS","LOCAL"):
                raise ValueError("smtp_setup")
            if mode=="LOCAL" and host not in ("127.0.0.1","localhost","::1"):
                raise ValueError("smtp_setup")
            msg=EmailMessage()
            message=json.loads(job["message"])
            msg["Subject"]=translator.t("dispatch_subject")+" "+message["order"]
            msg["From"],msg["To"]=sender,job["recipient"]
            msg.set_content(mail_text(message,translator))
            if job["invoice_id"]:
                path=invoice_pdf(self.db_path,job["invoice_id"],config["paths"].get("exports_invoices") or "Invoices",translator)
                msg.add_attachment(path.read_bytes(),maintype="application",subtype="pdf",filename=path.name)
            port=int(settings.get("port") or (465 if mode=="TLS" else 587))
            if mode=="TLS":
                smtp=smtplib.SMTP_SSL(host,port,timeout=15,context=ssl.create_default_context())
            else:
                smtp=smtplib.SMTP(host,port,timeout=15)
                if mode=="STARTTLS":
                    smtp.starttls(context=ssl.create_default_context())
            if mode!="LOCAL":
                from utils.smtp_secret import load_password
                password=load_password(settings["credential_id"]) if settings.get("credential_id") else os.environ.get("WMS_SMTP_PASSWORD")
                if not settings.get("username") or not password:
                    raise ValueError("smtp_setup")
                smtp.login(settings["username"],password)
            submitted=True
            smtp.send_message(msg)
            state,detail="sent",None
        except (OSError,smtplib.SMTPException,ValueError,KeyError) as error:
            state = "uncertain" if submitted and not isinstance(error,(smtplib.SMTPResponseException,smtplib.SMTPRecipientsRefused)) else "failed"
            detail=type(error).__name__
        finally:
            if smtp:
                smtp.close()
        with closing(connect(self.db_path)) as db,db:
            db.execute("UPDATE dispatch_mail SET state=?,detail=? WHERE shipment_id=?",(state,detail,shipment_id))
        return state
