from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged("post_install", "-at_install")
class TestFollowup(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        context = {"no_reset_password": True, "mail_create_nosubscribe": True}
        cls.manager = new_test_user(cls.env, login="ai_manager", groups="sales_team.group_sale_manager", context=context)
        cls.staff = new_test_user(cls.env, login="ai_staff", groups="sales_team.group_sale_salesman", context=context)
        cls.other = new_test_user(cls.env, login="ai_other", groups="sales_team.group_sale_salesman", context=context)
        cls.team = cls.env["crm.team"].create({"name": "AI test team", "user_id": cls.manager.id,
            "member_ids": [Command.set([cls.staff.id])], "company_id": cls.env.company.id})
        cls.team_other = cls.env["crm.team"].create({"name": "Other team", "user_id": cls.env.user.id,
            "member_ids": [Command.set([cls.other.id])], "company_id": cls.env.company.id})
        partner = cls.env["res.partner"].create({"name": "Fixture client", "ref": "OLIST-DEMO:fixture"})
        product = cls.env["product.product"].create({"name": "Fixture service", "type": "service"})
        cls.quote = cls.env["sale.order"].create({"partner_id": partner.id, "user_id": cls.staff.id,
            "team_id": cls.team.id, "origin": "OLIST-TEST:fixture", "order_line": [Command.create({
                "product_id": product.id, "product_uom_qty": 1, "price_unit": 100, "tax_ids": [Command.clear()]})]})
        cls.other_quote = cls.quote.copy({"user_id": cls.other.id, "team_id": cls.team_other.id})
        cls.private_quote = cls.quote.copy({"origin": "NOT-DEMO"})

    def ready(self, user=None):
        user = user or self.staff
        review = self.env["olist.ai.followup.review"].with_user(user).create({"order_id": self.quote.id})
        review._set_internal({"state": "ready", "summary": "Liên hệ khách", "note": "Trao đổi nhu cầu với khách."})
        return review

    def test_staff_and_manager_scope(self):
        own = self.quote.with_user(self.staff)
        own._olist_check_scope()
        self.quote.with_user(self.manager)._olist_check_scope()
        for order, user in [(self.other_quote, self.staff), (self.other_quote, self.manager),
                            (self.private_quote, self.staff)]:
            with self.assertRaises(AccessError):
                order.with_user(user)._olist_check_scope()
        review = self.ready()
        review.with_user(self.manager).check_access("read")
        with self.assertRaises(AccessError):
            review.with_user(self.other).read(["summary"])
        action = self.env["sale.order"].with_user(self.manager).olist_ai_queue_action()
        records = self.env["sale.order"].with_user(self.manager).search(action["domain"])
        self.assertIn(self.quote, records)
        self.assertNotIn(self.other_quote, records)

    def test_cannot_forge_review_or_change_audit(self):
        model = self.env["olist.ai.followup.review"].with_user(self.staff)
        with self.assertRaises(AccessError):
            model.create({"order_id": self.quote.id, "state": "approved"})
        review = self.ready()
        with self.assertRaises(AccessError):
            review.write({"state": "approved"})
        with self.assertRaises(AccessError):
            review.write({"order_id": self.other_quote.id})
        with self.assertRaises(AccessError):
            review.unlink()

    def test_explicit_approval_creates_once_and_native_activity_completes(self):
        review = self.ready()
        with self.assertRaises(UserError):
            review.action_approve()
        review.write({"approval_checked": True})
        review.action_approve()
        activity = review.activity_id
        self.assertTrue(activity)
        self.assertEqual(activity.user_id, self.staff)
        self.assertEqual(review.approved_by, self.staff)
        self.assertTrue(review.approved_payload)
        review.action_approve()
        self.assertEqual(review.activity_id, activity)
        activity.action_feedback(feedback="Đã xử lý trong fixture.")
        review.action_approve()
        self.assertFalse(activity.active)
        self.assertEqual(self.quote.state, "draft")

    def test_stale_source_and_outside_assignee_block_write(self):
        review = self.ready()
        review.write({"assigned_id": self.other.id, "approval_checked": True})
        with self.assertRaises(AccessError):
            review.action_approve()
        review.write({"assigned_id": self.staff.id, "approval_checked": True})
        self.quote.validity_date = fields.Date.today() + timedelta(days=10)
        with self.assertRaises(UserError):
            review.action_approve()
        self.assertFalse(review.activity_id)

    def test_edit_invalidates_approval_and_manager_can_assign_team(self):
        review = self.ready(self.manager)
        review.write({"approval_checked": True})
        review.write({"summary": "Việc được sửa"})
        self.assertFalse(review.approval_checked)
        review.write({"assigned_id": self.staff.id, "approval_checked": True})
        review.action_approve()
        self.assertEqual(review.activity_id.user_id, self.staff)

    def test_multi_company_and_duplicate_activity(self):
        other_company = self.env["res.company"].create({"name": "AI fixture company"})
        self.manager.company_ids = [Command.link(other_company.id)]
        with self.assertRaises(AccessError):
            self.quote.with_user(self.manager).with_company(other_company)._olist_check_scope()
        first = self.ready()
        first.write({"approval_checked": True})
        first.action_approve()
        second = self.ready()
        second.write({"approval_checked": True})
        with self.assertRaises(UserError):
            second.action_approve()
        self.assertFalse(second.activity_id)

    def test_batch_analysis_uses_one_job_and_no_activity_before_approval(self):
        extra = self.quote.copy()
        reviews = self.env["olist.ai.followup.review"].with_user(self.staff).create([
            {"order_id": self.quote.id}, {"order_id": extra.id}])
        requests = []

        def bridge(record, method, path, payload=None):
            requests.append((method, payload))
            if method == "POST":
                return {"request_id": record[0].request_key, "state": "pending"}
            return {"request_id": record.request_key, "state": "complete", "items": [{
                "order_id": r.order_id.id, "summary": "Liên hệ khách", "note": "Nháp trao đổi.", "activity_type": "todo",
                "explanation": "Chưa có lịch chăm sóc.", "reason_codes": ["no_activity"]} for r in reviews]}

        with patch.object(type(reviews), "_bridge", bridge):
            reviews.action_start()
            reviews.action_start()
            self.assertEqual(len(requests), 1)
            self.assertEqual(len(requests[0][1]["orders"]), 2)
            self.assertEqual(len(set(reviews.mapped("request_key"))), 1)
            for review in reviews:
                self.assertEqual(review.poll_state(), "ready")
        self.assertFalse(reviews.activity_id)
        self.assertFalse(any(reviews.mapped("approval_checked")))

    def test_queue_priority_is_current_and_applied_before_pagination(self):
        expired = self.quote.copy({"validity_date": fields.Date.today() - timedelta(days=1)})
        overdue = self.quote.copy()
        self.env["mail.activity"].create({"res_model_id": self.env["ir.model"]._get_id("sale.order"),
            "res_id": overdue.id, "user_id": self.staff.id, "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
            "date_deadline": fields.Date.today() - timedelta(days=1), "summary": "Fixture overdue"})
        orders = self.env["sale.order"].with_user(self.staff).with_context(olist_ai_queue=True)
        page = orders.web_search_read([], {"name": {}, "olist_ai_reason": {}}, limit=1)
        self.assertEqual(page["records"][0]["id"], overdue.id)
        overdue.activity_ids.action_feedback()
        page = orders.web_search_read([], {"name": {}}, limit=1)
        self.assertEqual(page["records"][0]["id"], expired.id)

    def test_lost_post_response_keeps_job_and_cancel_does_not_restart_it(self):
        review = self.env["olist.ai.followup.review"].with_user(self.staff).create({"order_id": self.quote.id})
        calls = []
        def bridge(record, method, path, payload=None):
            calls.append(method)
            if method == "POST":
                raise UserError("Fixture response lost")
            return {"request_id": record.request_key, "state": "complete", "items": [{"order_id": self.quote.id,
                "summary": "Rà soát báo giá", "note": "Nháp chăm sóc khách.", "activity_type": "todo",
                "explanation": "Chưa có lịch chăm sóc.", "reason_codes": ["no_activity"]}]}
        with patch.object(type(review), "_bridge", bridge):
            review.action_start()
            review.action_start()
            self.assertEqual(calls, ["POST"])
            self.assertEqual(review.poll_state(), "ready")
            review.action_cancel()
            self.assertEqual(review.poll_state(), "cancelled")
            self.assertEqual(calls, ["POST", "GET"])
        self.assertFalse(review.activity_id)
