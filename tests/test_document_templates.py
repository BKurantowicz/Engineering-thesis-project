"""Document data remains escaped and consistent across external template choices."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from utils.document_templates import BUNDLED_DIR, invoice_html, email_html, pick_html, list_templates
from utils.translations import translator


class DocumentTemplateTests(unittest.TestCase):
    def setUp(self):
        self.t = translator("pl", str(Path(__file__).resolve().parents[1] / "utils"))
        self.person = dict(first_name="Łucja",last_name="Żółć <script>",street="Długa 1",postal_code="80-001",city="Gdańsk",country="PL")
        self.line = dict(product_id=1,sku="SKU-1",name_pl="Ładowarka {{title}}",name_en="Charger",quantity=2,
                         unit="139.9",vat="23",net_cents=22748,vat_cents=5232,gross_cents=27980)
        self.delivery = dict(quantity=1,unit="10.8",vat="8",net_cents=1000,vat_cents=80,gross_cents=1080)
        self.document = dict(number="FV/2026/11/1",date="2026-11-05T21:53:00",order_id=1,seller={"name":"Test & Co"},
                             recipient=self.person,billing={},lines=[self.line],delivery=self.delivery)

    def test_invoice_preserves_data_formats_money_and_escapes_only_once(self):
        before = copy.deepcopy(self.document)
        html,warning = invoice_html(self.document,{},self.t)
        self.assertFalse(warning)
        self.assertEqual(self.document,before)
        for expected in ("Nabywca", "139.90", "10.80", "290.60 PLN", "2026-11-05, godz. 21:53", "Żółć &lt;script&gt;", "Test &amp; Co", "Ładowarka {{title}}"):
            self.assertIn(expected,html)
        self.assertNotIn("Separate billing details",html)
        self.assertNotIn("<script>",html)
        self.assertNotIn('border="1"',html)
        self.assertIn("text-align:right",html)

    def test_external_variants_and_invalid_selection_fall_back_without_external_code(self):
        with tempfile.TemporaryDirectory() as folder:
            template=Path(folder)/"invoice-custom.html"
            template.write_text((BUNDLED_DIR/"invoice-compact.html").read_text(encoding="utf-8").replace("</h1>"," Custom</h1>"),encoding="utf-8")
            config={"paths":{"templates":{"base_dir":folder,"invoice":template.name}}}
            self.assertEqual(list_templates(config,"invoice"),[template.name])
            html,warning=invoice_html(self.document,config,self.t)
            self.assertFalse(warning)
            self.assertIn("Custom</h1>",html)
            for invalid in ("<html>{{title}}</html>", template.read_text(encoding="utf-8")+"<script>alert(1)</script>", "{{unknown}}"):
                template.write_text(invalid,encoding="utf-8")
                html,warning=invoice_html(self.document,config,self.t)
                self.assertTrue(warning)
                self.assertIn("Nabywca",html)
                self.assertNotIn("<script>",html)
            template.unlink()
            self.assertTrue(invoice_html(self.document,config,self.t)[1])
            config["paths"]["templates"]["invoice"]="../invoice-standard.html"
            self.assertTrue(invoice_html(self.document,config,self.t)[1])
            config["paths"]["templates"]["base_dir"]=str(Path(folder)/"missing")
            self.assertEqual(list_templates(config,"invoice"),[])
            self.assertTrue(invoice_html(self.document,config,self.t)[1])

    def test_cached_standard_handles_deleted_bundled_files(self):
        with patch("utils.document_templates.Path.read_text",side_effect=FileNotFoundError):
            html,warning=invoice_html(self.document,{},self.t)
        self.assertTrue(warning)
        self.assertIn("290.60 PLN",html)

    def test_invalid_cached_standard_uses_safe_emergency_layout(self):
        from utils import document_templates as templates
        with patch.dict(templates._BUNDLED_STANDARDS, {"invoice": "<script>bad()</script>{{title}}"}):
            with patch("utils.document_templates.Path.read_text", side_effect=FileNotFoundError):
                html, warning = invoice_html(self.document, {}, self.t)
        self.assertTrue(warning)
        self.assertNotIn("<script>", html)
        self.assertIn("290.60 PLN", html)
        self.assertIn("<table", html)

    def test_pick_marks_completed_and_cancelled_lines_without_false_checks(self):
        base=dict(order_id=1,sku="A",name_pl="Żarówka",name_en="Bulb",location_code="A-01",quantity=3,
                  picked_quantity=0,cancelled=0,order_status="IN_PROGRESS")
        data=dict(pick_list_id=179,created_at="2026-11-05T21:53",lines=[base,dict(base,sku="B",picked_quantity=3),
                  dict(base,sku="C",picked_quantity=3,cancelled=1),dict(base,sku="D",picked_quantity=3,order_status="CANCELLED")])
        html,warning=pick_html(data,{},self.t)
        self.assertFalse(warning)
        self.assertEqual(html.count("☑"),1)
        self.assertEqual(html.count("□"),1)
        self.assertIn("Liczba SKU: 2",html)
        self.assertIn("Pozostało sztuk do zebrania: 3",html)
        self.assertIn("background-color:#ecfdf5",html)
        self.assertIn("@media print",html)
        self.assertIn("2026-11-05, godz. 21:53",html)
        empty,_=pick_html(dict(data,lines=[]),{},self.t)
        self.assertIn("Brak zapisanych przydziałów",empty)

    def test_email_has_whole_order_summary_and_final_invoice_notice(self):
        data=dict(order="ORD-00001",carrier="InPost",tracking="TRACK<&>",recipient=self.person,seller={"name":"Demo","email":"test@example.test"},
                  lines=[self.line],delivery=self.delivery,final=False)
        html,warning=email_html(data,{},self.t)
        self.assertFalse(warning)
        for value in ("max-width:600px", "background-color:#f4f6f8", "139.90 PLN", "290.60 PLN", "TRACK&lt;&amp;&gt;", "Adres dostawy", "ostatniej paczki"):
            self.assertIn(value,html)
        data.update(final=True,invoice_number="FV/2026/11/1")
        html,_=email_html(data,{},self.t)
        self.assertIn("załączniku PDF",html)
        self.assertNotIn("ostatniej paczki",html)

    def test_all_six_variants_render_in_both_languages_and_handle_many_rows(self):
        for lang in ("pl","en"):
            t=translator(lang,str(Path(__file__).resolve().parents[1]/"utils"))
            for kind,renderer,data in (("invoice",invoice_html,self.document),
                ("email",email_html,dict(order="ORD-00001",recipient=self.person,lines=[self.line],delivery=self.delivery)),
                ("pick",pick_html,dict(pick_list_id=1,created_at="2026-11-05T21:53",lines=[]))):
                self.assertEqual(len(list_templates({},kind)),2)
                for variant in ("standard","compact"):
                    key="pick_list" if kind=="pick" else kind
                    html,warning=renderer(data,{"paths":{"templates":{key:f"{kind}-{variant}.html"}}},t)
                    self.assertFalse(warning,(lang,kind,variant))
                    self.assertIn('charset="UTF-8"',html)
            large=copy.deepcopy(self.document)
            large["lines"]=[dict(self.line,name_pl=f"Pozycja {n}") for n in range(100)]
            html,_=invoice_html(large,{},t)
            self.assertEqual(html.count("139.90"),100)


if __name__=="__main__":
    unittest.main()
