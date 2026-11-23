from datetime import timedelta
import base64
import csv
import io
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

    def test_trial_methods_rotate_and_templates_are_explicit(self):
        requests, methods = [], []
        model = self.env["olist.ai.followup.review"].with_user(self.staff)
        def bridge(record, method, path, payload=None):
            requests.append((record.trial_method, method, payload))
            if method == "POST":
                return {"state": "pending"}
            return {"request_id": record.request_key, "state": "complete", "strategy": "rules" if record.trial_method == "rules" else "pipeline",
                "items": [{"order_id": record.order_id.id, "summary": "Rà soát báo giá", "note": "Kiểm tra nội dung trước khi gửi.",
                    "activity_type": "todo", "explanation": "Bản nháp.", "reason_codes": ["no_activity"]}]}
        with patch.object(type(model), "_bridge", bridge):
            for _ in range(3):
                action = self.quote.with_user(self.staff).action_olist_measure()
                review = model.browse(action["res_id"])
                methods.append(review.trial_method)
                self.assertEqual(review.trial_sequence, len(methods))
                self.assertTrue(review.trial_started_at)
                if review.trial_method == "manual":
                    self.assertEqual(review.state, "ready")
                    self.assertFalse(review.note)
                    self.assertFalse(review.summary)
                    self.assertIn("draft", review.evidence)
                else:
                    review.poll_state()
                self.assertTrue(review.trial_ready_at)
                self.assertFalse(review.activity_id)
                review.action_cancel()
                self.assertTrue(review.trial_finished_at)
        self.assertEqual(set(methods), {"manual", "rules", "ai"})
        posts = [r for r in requests if r[1] == "POST"]
        self.assertEqual(len(posts), 2)
        self.assertEqual(next(r[2]["mode"] for r in posts if r[0] == "rules"), "rules_only")
        self.assertNotIn("mode", next(r[2] for r in posts if r[0] == "ai"))
        trials = model.search([("owner_id", "=", self.staff.id), ("trial_started_at", "!=", False)])
        self.assertEqual(len(set(trials.mapped("trial_participant"))), 1)
        self.assertEqual(len(set(trials.mapped("trial_case"))), 1)
        self.assertFalse(self.quote.activity_ids)

    def test_trial_double_click_resumes_and_parallel_task_is_blocked(self):
        model = self.env["olist.ai.followup.review"].with_user(self.staff)
        with patch.object(type(model), "_bridge", return_value={"state": "pending"}) as bridge:
            first = self.quote.with_user(self.staff).action_olist_measure()
            again = self.quote.with_user(self.staff).action_olist_measure()
            self.assertEqual(first["res_id"], again["res_id"])
            self.assertLessEqual(bridge.call_count, 1)
            other = self.quote.copy()
            with self.assertRaises(UserError):
                other.with_user(self.staff).action_olist_measure()
            review = model.browse(first["res_id"])
            with self.assertRaises(AccessError):
                review.write({"trial_started_at": fields.Datetime.now()})
            with self.assertRaises(AccessError):
                model.create({"order_id": self.quote.id, "trial_method": "manual"})
            with self.assertRaises(AccessError):
                self.quote.with_user(self.other).action_olist_measure()

    def test_trial_timer_ends_once_on_explicit_approval(self):
        review = self.ready()
        start = fields.Datetime.now() - timedelta(seconds=40)
        ready = start + timedelta(seconds=10)
        review._set_internal({"trial_method": "manual", "trial_sequence": 1,
            "trial_participant": "P_fixture", "trial_case": "T_fixture", "trial_started_at": start,
            "trial_ready_at": ready})
        review.write({"approval_checked": True})
        review.action_approve()
        finished = review.trial_finished_at
        self.assertTrue(finished)
        self.assertGreaterEqual(review.trial_elapsed, 40)
        self.assertTrue(review.activity_id)
        review.action_approve()
        self.assertEqual(review.trial_finished_at, finished)

    def test_trial_csv_keeps_failures_and_is_private_without_customer_text(self):
        model = self.env["olist.ai.followup.review"].with_user(self.staff)
        reviews = model.create([{"order_id": self.quote.id}, {"order_id": self.quote.id}])
        start = fields.Datetime.now() - timedelta(seconds=30)
        for index, review in enumerate(reviews):
            review._set_internal({"trial_method": "rules" if index else "ai", "trial_sequence": index+1,
                "trial_participant": "P_fixture", "trial_case": "T_fixture", "trial_started_at": start})
        reviews[0]._set_internal({"state": "failed"})
        reviews[1]._set_internal({"state": "ready"})
        action = reviews.with_user(self.manager).action_export_trials()
        attachment_id = int(action["url"].split("/")[-1].split("?")[0])
        attachment = self.env["ir.attachment"].with_user(self.manager).browse(attachment_id)
        content = base64.b64decode(attachment.datas).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(content)))
        self.assertEqual([r["outcome"] for r in rows], ["failed", "unfinished"])
        self.assertNotEqual(rows[0]["total_seconds"], "")
        self.assertEqual(rows[0]["after_ready_seconds"], "")
        self.assertEqual(rows[1]["total_seconds"], "")
        self.assertEqual(rows[0]["actual_strategy"], "unknown")
        self.assertNotIn("Fixture client", content)
        self.assertNotIn(self.quote.name, content)
        self.assertNotIn(self.staff.login, content)
        with self.assertRaises(AccessError):
            attachment.with_user(self.staff).check_access("read")
        with self.assertRaises(AccessError):
            reviews.with_user(self.other).action_export_trials()

    def test_failed_trial_finishes_without_rewriting_old_timestamp(self):
        review = self.ready()
        review._set_internal({"trial_started_at": fields.Datetime.now() - timedelta(seconds=10), "state": "pending"})
        result = {"state": "failed", "error": "HTTP 503", "trace": []}
        with patch.object(type(review), "_bridge", return_value=result):
            self.assertEqual(review.poll_state(), "failed")
        finished = review.trial_finished_at
        self.assertTrue(finished)
        self.assertFalse(review.activity_id)
        review.action_cancel()
        self.assertEqual(review.trial_finished_at, finished)
        self.assertEqual(review.trial_outcome, "failed")

    def test_self_rating_is_explicit_owned_and_keeps_first_judgment(self):
        review = self.ready()
        review._set_internal({"trial_started_at": fields.Datetime.now() - timedelta(seconds=10), "state": "ready"})
        with self.assertRaises(UserError):
            review.action_trial_usable()
        review.action_cancel()
        finished = review.trial_finished_at
        with self.assertRaises(UserError):
            review.with_user(self.manager).action_trial_usable()
        with self.assertRaises(AccessError):
            review.write({"trial_rating": "usable"})
        review.action_trial_usable()
        rated = review.trial_rated_at
        self.assertEqual(review.trial_rating, "usable")
        self.assertEqual(review.trial_rated_by, self.staff)
        review.action_trial_usable()
        self.assertEqual(review.trial_rated_at, rated)
        self.assertEqual(review.trial_finished_at, finished)
        with self.assertRaises(UserError):
            review.action_trial_reject()

    def test_trial_without_draft_cannot_receive_positive_rating(self):
        review = self.env["olist.ai.followup.review"].with_user(self.staff).create({"order_id": self.quote.id})
        review._set_internal({"trial_started_at": fields.Datetime.now(), "state": "failed"})
        with self.assertRaises(UserError):
            review.action_trial_usable()
        review.action_trial_reject()
        self.assertEqual(review.trial_rating, "reject")
