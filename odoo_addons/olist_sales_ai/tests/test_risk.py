import json
import io
import zipfile
from xml.etree import ElementTree as ET
from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestRisk(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        context = {"no_reset_password": True, "mail_create_nosubscribe": True}
        cls.staff = new_test_user(cls.env, login="risk_staff", groups="sales_team.group_sale_salesman", context=context)
        cls.other = new_test_user(cls.env, login="risk_other", groups="sales_team.group_sale_salesman", context=context)
        cls.manager = new_test_user(cls.env, login="risk_manager", groups="sales_team.group_sale_manager", context=context)
        team = cls.env["crm.team"].create({"name": "Risk fixture team", "user_id": cls.manager.id, "member_ids": [Command.set([cls.staff.id])]})
        partner = cls.env["res.partner"].create({"name": "Risk fixture", "ref": "OLIST-DEMO:risk-fixture"})
        cls.product = cls.env["product.product"].create({"name": "Risk fixture service", "type": "service"})
        cls.quote = cls.env["sale.order"].create({"partner_id": partner.id, "user_id": cls.staff.id, "team_id": team.id,
            "origin": "OLIST-TEST:risk-fixture", "validity_date": fields.Date.today()-timedelta(days=1), "payment_term_id": False,
            "order_line": [Command.create({"product_id": cls.product.id, "product_uom_qty": 1, "price_unit": 100, "tax_ids": [Command.clear()]})]})

    def review(self):
        return self.env["olist.ai.quote.risk.review"].with_user(self.staff).create({"order_id": self.quote.id})

    def codes(self, review):
        return {r["code"] for r in json.loads(review.findings_json)}

    def decision(self, review, code="missing_tax", decision="intentional", reason="Fixture: đã đối chiếu cấu hình."):
        return self.env["olist.ai.quote.risk.decision"].with_user(self.staff).create({
            "review_id": review.id, "code": code, "decision": decision, "reason": reason})

    def test_flags_evidence_and_no_business_writes(self):
        before = self.quote.read(["state", "amount_total", "write_date", "activity_ids", "invoice_ids"])
        review = self.review()
        self.assertEqual(self.codes(review), {"expired", "missing_tax", "missing_payment_term"})
        self.assertIn(str(self.quote.validity_date), str(review.findings_html))
        self.assertEqual(self.quote.read(["state", "amount_total", "write_date", "activity_ids", "invoice_ids"]), before)
        self.assertFalse(review.stale)

    def test_line_anomalies_and_archived_product(self):
        self.quote.order_line.write({"product_uom_qty": 0, "price_unit": -10, "discount": 120})
        self.product.active = False
        self.assertTrue({"nonpositive_quantity", "negative_price", "invalid_discount", "inactive_product"} <= self.codes(self.review()))
        self.quote.order_line.write({"price_unit": 0, "discount": 5})
        codes = self.codes(self.review())
        self.assertTrue({"zero_price", "discount_present"} <= codes)
        self.assertNotIn("negative_price", codes); self.assertNotIn("invalid_discount", codes)

    def test_expiry_boundaries_and_section_only_quote(self):
        today = fields.Date.today()
        for days, expected in [(-1, "expired"), (0, "expiring"), (3, "expiring"), (4, None)]:
            self.quote.validity_date = today+timedelta(days=days)
            codes = self.codes(self.review())
            self.assertEqual(codes & {"expired", "expiring"}, {expected} if expected else set())
        self.quote.write({"validity_date": False, "order_line": [Command.clear(), Command.create({"display_type": "line_section", "name": "Fixture section"})]})
        self.assertTrue({"missing_validity", "empty_lines"} <= self.codes(self.review()))

    def test_stale_blocks_ai_and_recheck_keeps_original(self):
        review = self.review()
        original = review.findings_json
        self.quote.order_line.discount = 7
        review.invalidate_recordset()
        self.assertTrue(review.stale)
        with self.assertRaises(UserError): review.action_explain()
        new = self.env[review._name].browse(review.action_recheck()["res_id"])
        self.assertNotEqual(new, review)
        self.assertIn("discount_present", self.codes(new))
        self.assertEqual(review.findings_json, original)

    def test_immutable_result_and_staff_team_company_scope(self):
        review = self.review()
        forged = review.with_context(default_state="explained", default_explanation="Forged", default_job_started=True).create({"order_id": self.quote.id})
        self.assertEqual(forged.state, "checked")
        self.assertFalse(forged.explanation)
        self.assertFalse(forged.job_started)
        with self.assertRaises(AccessError): review.write({"state": "explained"})
        with self.assertRaises(AccessError): review.unlink()
        with self.assertRaises(AccessError): review.create({"order_id": self.quote.id, "findings_json": "[]"})
        with self.assertRaises(AccessError): review.with_user(self.other).read(["findings_json"])
        self.assertTrue(review.with_user(self.manager).read(["findings_json"]))
        for changed in [{"origin": "NOT-DEMO"}, {"user_id": self.other.id, "team_id": False}]:
            outside = self.quote.copy(changed)
            with self.assertRaises(AccessError): review.create({"order_id": outside.id})
        company = self.env["res.company"].create({"name": "Risk fixture other company"})
        self.manager.company_ids = [Command.link(company.id)]
        with self.assertRaises(AccessError): review.with_user(self.manager).with_company(company).action_explain()

    def test_lost_post_response_recovers_once_without_quote_writes(self):
        review = self.review(); calls = []
        before = self.quote.write_date
        def bridge(record, method, path, payload=None):
            calls.append((method, payload))
            if method == "POST": raise UserError("Fixture response lost")
            return {"state": "complete", "request_id": record.request_key, "purpose": "risk",
                "items": [{"code": c, "question": "Có cần đối chiếu lại không?"} for c in self.codes(record)]}
        with patch.object(type(review), "_bridge", bridge):
            review.action_explain(); review.action_explain()
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1]["purpose"], "risk")
            self.assertEqual(set(calls[0][1]["risk_codes"]), self.codes(review))
            self.assertEqual(review.poll_state(), "explained")
        self.assertEqual(self.quote.write_date, before)
        self.assertFalse(self.quote.activity_ids)
        self.assertFalse(self.quote.invoice_ids)

    def test_wrong_result_and_deadline_preserve_local_findings(self):
        for changed in [{"request_id": "wrong"}, {"purpose": "followup"}, {"items": []}, {"items": [None]}]:
            review = self.review()
            def bridge(record, method, path, payload=None):
                return {"state": "complete", "request_id": record.request_key, "purpose": "risk",
                    "items": [{"code": c, "question": "Có cần xem lại không?"} for c in self.codes(record)], **changed}
            with patch.object(type(review), "_bridge", bridge):
                review.action_explain()
                self.assertEqual(review.poll_state(), "failed")
            self.assertTrue(self.codes(review))
        review = self.review()
        with patch.object(type(review), "_bridge", return_value={"state": "pending"}):
            review.action_explain()
            review.flush_recordset(["explanation_started_at"])
            self.env.cr.execute("UPDATE olist_ai_quote_risk_review SET explanation_started_at=%s WHERE id=%s",
                (fields.Datetime.now()-timedelta(minutes=3), review.id))
            review.invalidate_recordset()
            self.assertEqual(review.poll_state(), "failed")
        self.assertTrue(review.findings_html)

    def test_decisions_append_deduplicate_and_keep_business_source(self):
        review = self.review()
        original = (review.snapshot_json, review.findings_json, review.source_hash, self.quote.write_date)
        event = self.decision(review, reason="  Fixture: tự ghi nhận.  ")
        self.assertEqual(event.reason, "Fixture: tự ghi nhận.")
        self.assertEqual(event.actor_id, self.staff)
        self.assertTrue(event.recorded_at)
        self.assertEqual(self.decision(review, reason=event.reason), event)
        self.assertEqual(len(review.decision_ids), 1)
        self.assertIn("Đúng chủ đích", str(review.findings_html))
        self.assertIn("Có dòng chưa chọn thuế", str(review.findings_html))
        self.decision(review, decision="manager")
        self.assertTrue(review.needs_manager)
        model = self.env[review._name].with_user(self.manager)
        self.assertIn(review, model.search([("needs_manager", "=", True)]))
        self.decision(review, decision="fix")
        self.assertFalse(review.needs_manager)
        self.assertNotIn(review, model.search([("needs_manager", "=", True)]))
        self.assertEqual(len(review.decision_ids), 3)
        self.assertEqual((review.snapshot_json, review.findings_json, review.source_hash, self.quote.write_date), original)
        self.assertFalse(self.quote.activity_ids)
        self.assertFalse(self.quote.invoice_ids)
        with self.assertRaises(AccessError): event.write({"reason": "forged"})
        with self.assertRaises(AccessError): event.unlink()

    def test_decisions_validate_input_scope_and_server_metadata(self):
        review = self.review()
        for changes in [{"reason": "  "}, {"reason": "a"*1001}, {"code": "discount_present"}, {"decision": "approved"}]:
            with self.assertRaises(UserError): self.decision(review, **changes)
        base = {"review_id": review.id, "code": "missing_tax", "decision": "fix", "reason": "Fixture reason"}
        model = self.env["olist.ai.quote.risk.decision"].with_user(self.staff)
        with self.assertRaises(AccessError): model.create({**base, "actor_id": self.manager.id})
        event = model.with_context(default_actor_id=self.manager.id, default_recorded_at="2000-01-01", default_reason="forged").create(base)
        self.assertEqual(event.actor_id, self.staff)
        self.assertEqual(event.reason, base["reason"])
        event.with_user(self.manager).read(["reason"])
        with self.assertRaises(AccessError): event.with_user(self.other).read(["reason"])
        with self.assertRaises(AccessError): model.with_user(self.other).create(base)
        company = self.env["res.company"].create({"name": "Disposition fixture company"})
        self.manager.company_ids = [Command.link(company.id)]
        with self.assertRaises(AccessError): model.with_user(self.manager).with_company(company).create(base)

    def test_wizard_partial_save_prefill_noop_and_double_click(self):
        review = self.review()
        wizard = self.env["olist.ai.quote.risk.handle"].with_user(self.staff).browse(review.action_handle()["res_id"])
        self.assertFalse(review.decision_ids)
        self.assertEqual(set(wizard.line_ids.mapped("code")), self.codes(review))
        line = wizard.line_ids.filtered(lambda r: r.code == "missing_tax")
        line.write({"decision": "intentional", "reason": "Fixture: exception checked"})
        wizard.action_save(); wizard.action_save()
        self.assertEqual(len(review.decision_ids), 1)
        with self.assertRaises(AccessError): line.write({"reason": "late edit"})
        next_wizard = wizard.create({"review_id": review.id})
        next_line = next_wizard.line_ids.filtered(lambda r: r.code == "missing_tax")
        self.assertEqual(next_line.reason, line.reason)
        self.assertEqual(next_line.decision, line.decision)
        next_wizard.action_save()
        self.assertEqual(len(review.decision_ids), 1)
        self.assertIn("Chưa ghi nhận", str(review.findings_html))

    def test_wizard_rejects_blank_reason_tampering_and_other_users(self):
        review = self.review()
        wizard = self.env["olist.ai.quote.risk.handle"].with_user(self.staff).create({"review_id": review.id})
        line = wizard.line_ids[0]
        line.decision = "fix"
        with self.assertRaises(UserError): wizard.action_save()
        self.assertFalse(review.decision_ids)
        for changes in [{"review_id": review.id}, {"saved": True}]:
            with self.assertRaises(AccessError): wizard.write(changes)
        for changes in [{"code": "expired"}, {"base_decision_id": False}, {"evidence": "forged"}]:
            with self.assertRaises(AccessError): line.write(changes)
        with self.assertRaises(AccessError): wizard.write({"line_ids": [Command.clear()]})
        with self.assertRaises(AccessError): line.create({"wizard_id": wizard.id, "code": "expired"})
        with self.assertRaises(AccessError): wizard.with_user(self.other).action_save()
        with self.assertRaises(AccessError): wizard.create({"review_id": review.id, "saved": True})

    def test_stale_and_concurrent_dispositions_do_not_overwrite(self):
        review = self.review()
        wizard = self.env["olist.ai.quote.risk.handle"].with_user(self.staff).create({"review_id": review.id})
        line = wizard.line_ids.filtered(lambda r: r.code == "missing_tax")
        line.write({"decision": "fix", "reason": "Fixture: original edit"})
        self.decision(review, decision="manager")
        with self.assertRaises(UserError): wizard.action_save()
        self.assertEqual(len(review.decision_ids), 1)
        self.assertEqual(review.decision_ids.decision, "manager")
        self.quote.order_line.discount = 12
        with self.assertRaises(UserError): wizard.action_save()
        with self.assertRaises(UserError): review.action_handle()
        with self.assertRaises(UserError): self.decision(review)

    def test_recheck_compares_partial_fixes_and_resets_dispositions(self):
        self.quote.order_line.copy({"order_id": self.quote.id})
        review = self.review()
        self.decision(review, decision="manager")
        original = review.findings_json
        tax = self.env["account.tax"].create({"name": "Fixture comparison tax", "amount": 0, "type_tax_use": "sale"})
        term = self.env["account.payment.term"].create({"name": "Fixture comparison term"})
        self.quote.order_line[0].tax_ids = [Command.set(tax.ids)]
        self.quote.write({"payment_term_id": term.id, "validity_date": False})
        new = self.env[review._name].with_user(self.staff).browse(review.action_recheck()["res_id"])
        self.assertEqual(new.previous_review_id, review)
        self.assertEqual(self.codes(new), {"missing_tax", "missing_validity"})
        self.assertFalse(new.decision_ids)
        self.assertFalse(new.needs_manager)
        self.assertIn("Chưa ghi nhận", str(new.findings_html))
        comparison = str(new.comparison_html)
        for status in ["Vẫn xuất hiện", "Mới xuất hiện", "Không còn xuất hiện", "Dòng 1", "Dòng 2"]:
            self.assertIn(status, comparison)
        self.assertEqual(review.findings_json, original)
        latest = self.review()
        self.assertEqual(latest.previous_review_id, new)
        self.assertIn("Vẫn xuất hiện", str(latest.comparison_html))
        self.assertNotIn("Không còn xuất hiện", str(latest.comparison_html))
        with self.assertRaises(AccessError): latest.create({"order_id": self.quote.id, "previous_review_id": review.id})

    def test_local_reason_is_escaped_and_excluded_from_ai_requests(self):
        review = self.review()
        reason = "LOCAL_REASON_CANARY <script>alert('fixture')</script>"
        self.decision(review, reason=reason)
        self.assertNotIn("<script>", str(review.findings_html))
        calls = []
        def bridge(record, method, path, payload=None):
            calls.append(payload)
            return {"state": "pending"}
        with patch.object(type(review), "_bridge", bridge): review.action_explain()
        self.assertEqual(len(calls), 1)
        self.assertNotIn("LOCAL_REASON_CANARY", json.dumps(calls))
        self.assertEqual(calls[0]["purpose"], "risk")
        self.assertEqual(set(calls[0]["risk_codes"]), self.codes(review))

    def test_export_projection_uses_saved_source_and_separate_dispositions(self):
        review = self.review()
        self.decision(review, decision="intentional", reason="Fixture: đã kiểm tra ngoại lệ")
        before = review._risk_report_data()
        self.assertEqual(before["current_count"], 3)
        self.assertEqual(before["attention_count"], 2)
        self.assertFalse(before["stale"])
        self.assertTrue(all(r["change"] == "Chưa có bản trước" for r in before["rows"]))
        original = review.findings_json
        self.quote.order_line.discount = 7
        stale = review._risk_report_data()
        self.assertTrue(stale["stale"])
        self.assertNotIn("discount_present", {r["code"] for r in stale["rows"]})
        new = self.env[review._name].with_user(self.staff).browse(review.action_recheck()["res_id"])
        self.decision(new, code="discount_present", decision="manager")
        report = new._risk_report_data()
        tax = next(r for r in report["rows"] if r["code"] == "missing_tax")
        self.assertEqual(tax["previous_decision"], "Đúng chủ đích")
        self.assertEqual(tax["decision"], "Chưa ghi nhận")
        self.assertEqual(tax["reason"], "")
        self.assertEqual(report["attention_count"], 4)
        self.assertEqual({r["review_id"] for r in report["history"]}, {review.id, new.id})
        self.assertEqual(review.findings_json, original)

    def test_xlsx_keeps_user_text_literal_and_does_not_mutate_quote(self):
        review = self.review()
        reason = '=HYPERLINK("https://example.invalid", "Fixture: chỉ là chữ")'
        self.decision(review, reason=reason)
        before = self.quote.read(["state", "write_date", "activity_ids", "invoice_ids", "amount_total"])
        with patch.object(type(review), "_bridge", side_effect=AssertionError("Export must not call AI")):
            content = review._risk_xlsx_bytes()
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            self.assertEqual([e.attrib["name"] for e in workbook.findall("s:sheets/s:sheet", ns)], ["Tổng quan", "Đối chiếu", "Lịch sử"])
            strings = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            values = ["".join(e.itertext()) for e in strings]
            self.assertIn(reason, values)
            self.assertIn("Đúng chủ đích", values)
            for name in archive.namelist():
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                    sheet = ET.fromstring(archive.read(name))
                    self.assertFalse(sheet.findall(".//s:f", ns))
                    self.assertFalse(sheet.findall(".//s:hyperlink", ns))
        self.assertEqual(self.quote.read(["state", "write_date", "activity_ids", "invoice_ids", "amount_total"]), before)
        action = review.action_risk_xlsx()
        self.assertEqual(action["url"], f"/olist-sales-ai/risk/{review.id}/xlsx")

    def test_pdf_html_escapes_notes_and_rechecks_scope_at_render(self):
        review = self.review()
        self.decision(review, reason="<script>EXPORT_PRIVATE_CANARY</script>")
        engine = self.env["ir.actions.report"].with_user(self.staff)
        content, kind = engine._render_qweb_html("olist_sales_ai.risk_report_action", review.ids)
        html = content.decode()
        self.assertEqual(kind, "html")
        for text in ["Báo cáo xử lý rủi ro", "EXPORT_PRIVATE_CANARY", "Lịch sử ghi nhận", "Điểm cần đối chiếu tiếp"]:
            self.assertIn(text, html)
        self.assertNotIn("<script>EXPORT_PRIVATE_CANARY</script>", html)
        self.assertFalse(self.env.ref("olist_sales_ai.risk_report_action").attachment_use)
        self.assertEqual(review.action_risk_pdf()["report_type"], "qweb-pdf")
        self.staff.write({"group_ids": [Command.link(self.env.ref("base.group_system").id)]})
        self.env.company.external_report_layout_id = False
        self.assertEqual(review.action_risk_pdf()["report_type"], "qweb-pdf")
        with self.assertRaises(AccessError):
            engine.with_user(self.other)._render_qweb_html("olist_sales_ai.risk_report_action", review.ids)

    def test_export_empty_findings_and_staff_team_company_access(self):
        term = self.env["account.payment.term"].create({"name": "Fixture export term"})
        tax = self.env["account.tax"].create({"name": "Fixture export tax", "amount": 0, "type_tax_use": "sale"})
        self.quote.write({"payment_term_id": term.id, "validity_date": fields.Date.today()+timedelta(days=7)})
        self.quote.order_line.tax_ids = [Command.set(tax.ids)]
        review = self.review()
        data = review._risk_report_data()
        self.assertEqual(data["current_count"], 0)
        self.assertEqual(data["attention_count"], 0)
        self.assertEqual(data["rows"], [])
        review.with_user(self.manager)._risk_xlsx_bytes()
        for method in ["_risk_report_data", "_risk_xlsx_bytes", "action_risk_pdf", "action_risk_xlsx"]:
            with self.assertRaises(AccessError): getattr(review.with_user(self.other), method)()
        company = self.env["res.company"].create({"name": "Fixture export company"})
        self.manager.company_ids = [Command.link(company.id)]
        with self.assertRaises(AccessError): review.with_user(self.manager).with_company(company)._risk_report_data()
