"""Invoice rendering and persisted per-parcel SMTP outcomes."""
import json
import os
import smtplib
import ssl
import time
from contextlib import closing
from email.message import EmailMessage
from pathlib import Path
from tempfile import NamedTemporaryFile

from PySide6.QtGui import QTextDocument, QPdfWriter, QPageSize, QFont

from controllers.inventory_controller import connect


def invoice_pdf(db_path, invoice_id, directory, translator, config=None, on_warning=None):
    with closing(connect(db_path)) as db:
        row = db.execute("SELECT document FROM invoices WHERE invoice_id=?", (invoice_id,)).fetchone()
    if not row or not row[0]:
        raise ValueError("no_invoice")
    data = json.loads(row[0])
    from utils.document_templates import invoice_html
    if config is None:
        from controllers.settings_controller import SettingsController
        config = SettingsController().get_config()
    document, warning = invoice_html(data, config, translator)
    if warning and on_warning:
        on_warning(warning)
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
        doc.setDefaultFont(QFont("Segoe UI", 10))
        doc.setHtml(document)
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

    def preview(self, shipment_id, config, translator):
        """Render the same HTML included in the SMTP message, without sending."""
        from utils.document_templates import email_html
        job = self.get(shipment_id)
        if not job:
            raise ValueError("not_ready")
        message = json.loads(job["message"])
        with closing(connect(self.db_path)) as db:
            order = db.execute("""SELECT o.* FROM orders o JOIN order_shipments s USING(order_id)
                                  WHERE s.shipment_id=?""", (shipment_id,)).fetchone()
            header = json.loads(order["sales_snapshot"])
            lines = [json.loads(row[0]) for row in db.execute(
                "SELECT sale_snapshot FROM order_items WHERE order_id=? ORDER BY item_id", (order["order_id"],))]
            invoice = db.execute("SELECT document FROM invoices WHERE invoice_id=?", (job["invoice_id"],)).fetchone()
        document = json.loads(invoice[0]) if invoice else {}
        context = dict(message, recipient=header["recipient"], lines=lines, delivery=header["delivery_line"],
                       seller=document.get("seller", message.get("seller", config.get("company_info", {}))),
                       invoice_number=document.get("number"), final=bool(job["invoice_id"]))
        return email_html(context, config, translator)

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
        warning=None
        try:
            settings=config.get("email_smtp",{})
            host=settings.get("host","").strip()
            sender=settings.get("sender") or config.get("company_info",{}).get("email")
            mode=settings.get("security","")
            if not host or not sender or mode not in ("TLS","STARTTLS","LOCAL"):
                raise ValueError("smtp_setup")
            if mode=="LOCAL" and host not in ("127.0.0.1","localhost","::1"):
                raise ValueError("smtp_setup")
            password = None
            if mode != "LOCAL":
                from utils.smtp_secret import load_password
                try:
                    password = load_password(settings["credential_id"]) if settings.get("credential_id") else os.environ.get("WMS_SMTP_PASSWORD")
                except OSError:
                    raise ValueError("smtp_setup") from None
                if not settings.get("username") or not password:
                    raise ValueError("smtp_setup")
            try:
                port=int(settings.get("port") or (465 if mode=="TLS" else 587))
                if not 0 < port <= 65535:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError("smtp_setup") from None
            msg=EmailMessage()
            message=json.loads(job["message"])
            msg["Subject"]=translator.t("dispatch_subject")+" "+message["order"]
            msg["From"],msg["To"]=sender,job["recipient"]
            msg.set_content(mail_text(message,translator))
            document, warning = self.preview(shipment_id, config, translator)
            msg.add_alternative(document, subtype="html")
            if job["invoice_id"]:
                try:
                    notices = []
                    path=invoice_pdf(self.db_path,job["invoice_id"],config["paths"].get("exports_invoices") or "Invoices",translator,config,notices.append)
                    warning = warning or (notices[0] if notices else None)
                    attachment=path.read_bytes()
                except OSError:
                    raise ValueError("document_error") from None
                msg.add_attachment(attachment,maintype="application",subtype="pdf",filename=path.name)
            if mode=="TLS":
                smtp=smtplib.SMTP_SSL(host,port,timeout=15,context=ssl.create_default_context())
            else:
                smtp=smtplib.SMTP(host,port,timeout=15)
                if mode=="STARTTLS":
                    smtp.starttls(context=ssl.create_default_context())
            if mode!="LOCAL":
                smtp.login(settings["username"],password)
            submitted=True
            smtp.send_message(msg)
            state,detail="sent",("template_fallback" if warning else None)
        except (OSError,smtplib.SMTPException,ValueError,KeyError) as error:
            state = "uncertain" if submitted and not isinstance(error,(smtplib.SMTPResponseException,smtplib.SMTPRecipientsRefused)) else "failed"
            if isinstance(error, ValueError) and str(error) in ("smtp_setup", "document_error"):
                detail = str(error)
            elif isinstance(error, smtplib.SMTPAuthenticationError):
                detail = "smtp_auth"
            elif isinstance(error, smtplib.SMTPRecipientsRefused):
                detail = "smtp_recipient"
            elif isinstance(error, (OSError, smtplib.SMTPException)):
                detail = "smtp_connection"
            else:
                detail = "notification_error"
        finally:
            if smtp:
                smtp.close()
        with closing(connect(self.db_path)) as db,db:
            db.execute("UPDATE dispatch_mail SET state=?,detail=? WHERE shipment_id=?",(state,detail,shipment_id))
        return state
