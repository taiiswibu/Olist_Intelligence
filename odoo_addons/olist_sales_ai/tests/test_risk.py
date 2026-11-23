import json
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
