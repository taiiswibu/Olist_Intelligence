import hashlib
import base64
import csv
import io
import json
import os
import secrets
import uuid
from datetime import timedelta

import requests
from markupsafe import Markup, escape

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import html2plaintext


LABELS = {"overdue_activity": "Có công việc quá hạn", "expired_quotation": "Báo giá đã hết hạn",
          "expiring_quotation": "Báo giá hết hạn trong ba ngày tới", "no_activity": "Chưa có lịch chăm sóc", "waiting": "Đang chờ xử lý"}


class SaleOrder(models.Model):
    _inherit = "sale.order"

    olist_ai_reason = fields.Char("Lý do cần xem", compute="_compute_olist_ai")
    olist_ai_demo = fields.Boolean(compute="_compute_olist_ai")

    def _compute_olist_ai(self):
        today = fields.Date.context_today(self)
        for order in self:
            order.olist_ai_demo = bool((order.origin or "").startswith("OLIST-") and
                (order.partner_id.ref or "").startswith("OLIST-DEMO:") and order.state in ("draft", "sent"))
            codes = []
            if any(a.date_deadline < today for a in order.activity_ids):
                codes.append("overdue_activity")
            if order.validity_date:
                if order.validity_date < today:
                    codes.append("expired_quotation")
                elif order.validity_date <= today + timedelta(days=3):
                    codes.append("expiring_quotation")
            if not order.activity_ids:
                codes.append("no_activity")
            order.olist_ai_reason = " · ".join(LABELS[c] for c in codes) or LABELS["waiting"]

    @api.model
    def _olist_scope_domain(self):
        if not self.env.user.has_group("sales_team.group_sale_salesman"):
            raise AccessError("Cần quyền nhân viên bán hàng.")
        domain = [("company_id", "=", self.env.company.id), ("origin", "=like", "OLIST-%"),
                  ("partner_id.ref", "=like", "OLIST-DEMO:%"), ("state", "in", ["draft", "sent"])]
        if self.env.user.has_group("sales_team.group_sale_manager"):
            teams = self.env["crm.team"].search([("user_id", "=", self.env.uid),
                ("company_id", "in", [False, self.env.company.id])])
            domain += ["|", ("user_id", "=", self.env.uid), ("team_id", "in", teams.ids)]
        else:
            domain += [("user_id", "=", self.env.uid)]
        return domain

    def _olist_check_scope(self):
        self.check_access("read")
        if set(self.search(self._olist_scope_domain() + [("id", "in", self.ids)]).ids) != set(self.ids):
            raise AccessError("Báo giá không thuộc phạm vi DEMO, nhóm hoặc công ty hiện tại.")

    @api.model
    def olist_ai_queue_action(self):
        return {"type": "ir.actions.act_window", "name": "Khách cần chăm sóc", "res_model": "sale.order",
                "views": [(self.env.ref("olist_sales_ai.queue_list").id, "list"), (False, "form")],
                "domain": self._olist_scope_domain(), "context": {**self.env.context, "olist_ai_queue": True},
                "help": "Chọn báo giá và bấm Phân tích AI để xem đề xuất chờ duyệt."}

    def _olist_priority(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        if any(a.date_deadline < today for a in self.activity_ids):
            return 0
        if self.validity_date and self.validity_date <= today + timedelta(days=3):
            return 1
        return 2 if not self.activity_ids else 3

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        if self.env.context.get("olist_ai_queue"):
            # Use deterministic priority ordering only for our queue, retaining all ORM access rules.
            domain = list(domain) + self._olist_scope_domain()
            ids = self.search(domain).sorted(key=lambda o: (o._olist_priority(), o.date_order, o.id))
            selected = ids[offset:offset + limit] if limit else ids[offset:]
            return {"length": len(ids), "records": selected.web_read(specification)}
        return super().web_search_read(domain, specification, offset=offset, limit=limit, order=order, count_limit=count_limit)

    def action_olist_ai_analyze(self):
        if not self or len(self) > 20:
            raise UserError("Chọn từ một đến hai mươi báo giá mỗi lượt.")
        self._olist_check_scope()
        reviews = self.env["olist.ai.followup.review"].create([{"order_id": order.id} for order in self])
        reviews.action_start()
        return {"type": "ir.actions.act_window", "name": "Đề xuất chờ duyệt", "res_model": reviews._name,
                "view_mode": "list,form" if len(reviews) > 1 else "form", "res_id": reviews.id if len(reviews) == 1 else False,
                "domain": [("id", "in", reviews.ids)]}

    def action_olist_measure(self):
        """One explicit, timed task; rotate methods without silently selecting successes."""
        self.ensure_one()
        self._olist_check_scope()
        self.env.cr.execute("SELECT id FROM res_users WHERE id=%s FOR UPDATE", (self.env.uid,))
        model = self.env["olist.ai.followup.review"]
        domain = [("owner_id", "=", self.env.uid), ("company_id", "=", self.env.company.id),
                  ("trial_started_at", "!=", False)]
        active = model.search(domain + [("trial_finished_at", "=", False)], limit=1)
        if active:
            if active.order_id != self:
                raise UserError("Hoàn tất hoặc bỏ qua lượt đo đang mở trước khi bắt đầu lượt khác.")
            review = active
        else:
            previous = model.search(domain, order="id desc", limit=1)
            sequence = model.search_count(domain) + 1
            method = ("manual", "rules", "ai")[(sequence - 1 + self.env.uid) % 3]
            peer = model.search(domain + [("order_id", "=", self.id)], order="id desc", limit=1)
            review = model.create({"order_id": self.id})
            review._set_internal({"trial_method": method, "trial_sequence": sequence,
                "trial_participant": previous.trial_participant or "P_" + secrets.token_hex(6),
                "trial_case": peer.trial_case if peer and peer.source_hash == review.source_hash else "T_" + secrets.token_hex(6),
                "trial_started_at": fields.Datetime.now()})
            if method == "manual":
                review._set_internal({"state": "ready", "trace": json.dumps({"strategy": "manual"}),
                    "evidence": review._source_evidence(), "explanation": "Soạn tay từ dữ liệu đối chiếu. Chưa gọi model."})
            else:
                review.action_start()
        return {"type": "ir.actions.act_window", "name": "Đo thao tác chăm sóc", "res_model": review._name,
                "view_mode": "form", "res_id": review.id, "target": "current"}


class FollowupReview(models.Model):
    _name = "olist.ai.followup.review"
    _description = "Đề xuất chăm sóc khách"
    _order = "create_date desc,id desc"
    _rec_name = "order_id"

    order_id = fields.Many2one("sale.order", string="Báo giá", required=True, readonly=True, ondelete="restrict", index=True)
    company_id = fields.Many2one("res.company", string="Công ty", required=True, readonly=True, index=True)
    owner_id = fields.Many2one("res.users", string="Người lập đề xuất", required=True, readonly=True)
    state = fields.Selection([("pending", "Đang phân tích"), ("ready", "Chờ duyệt"), ("approved", "Đã giao việc"),
                              ("failed", "Chưa hoàn tất"), ("cancelled", "Đã bỏ qua")], default="pending", readonly=True, required=True)
    request_key = fields.Char(readonly=True, copy=False)
    snapshot_json = fields.Text(readonly=True)
    source_hash = fields.Char(readonly=True)
    snapshot_date = fields.Date(readonly=True)
    job_started = fields.Boolean(readonly=True, default=False)
    error = fields.Text("Thông báo", readonly=True)
    explanation = fields.Text("AI giải thích", readonly=True)
    evidence = fields.Text("Dữ liệu đối chiếu", readonly=True)
    trace = fields.Text("Model và skill đã dùng", readonly=True)
    model_details = fields.Text("Model và skill đã dùng", compute="_compute_model_details")
    summary = fields.Char("Tên công việc", size=120)
    note = fields.Text("Nội dung chăm sóc (bản nháp)")
    activity_type = fields.Selection([("call", "Gọi điện"), ("todo", "Việc cần làm")], string="Loại việc", default="todo", required=True)
    assigned_id = fields.Many2one("res.users", string="Người phụ trách", required=True)
    deadline = fields.Date("Ngày hẹn", required=True)
    approval_checked = fields.Boolean("Tôi đã kiểm tra nội dung, người phụ trách và ngày hẹn.", default=False)
    activity_id = fields.Many2one("mail.activity", readonly=True, ondelete="set null")
    approved_by = fields.Many2one("res.users", string="Người duyệt", readonly=True)
    approved_at = fields.Datetime("Thời điểm duyệt", readonly=True)
    approved_payload = fields.Text("Nội dung đã duyệt", readonly=True)
    allowed_user_ids = fields.Many2many("res.users", compute="_compute_allowed_users")
    trial_method = fields.Selection([("manual", "Soạn tay"), ("rules", "Mẫu quy tắc"), ("ai", "AI theo cấu hình")],
                                    string="Cách chuẩn bị", readonly=True, copy=False)
    trial_sequence = fields.Integer("Thứ tự lượt đo", readonly=True, copy=False)
    trial_participant = fields.Char("Mã người tham gia", readonly=True, copy=False)
    trial_case = fields.Char("Mã tình huống", readonly=True, copy=False)
    trial_started_at = fields.Datetime("Bắt đầu lượt đo", readonly=True, copy=False)
    trial_ready_at = fields.Datetime("Có bản nháp", readonly=True, copy=False)
    trial_finished_at = fields.Datetime("Kết thúc lượt đo", readonly=True, copy=False)
    trial_outcome = fields.Selection([("approved", "Đã duyệt"), ("failed", "Lỗi"), ("cancelled", "Bỏ qua")],
                                     string="Kết quả lượt đo", readonly=True, copy=False)
    trial_rating = fields.Selection([("usable", "Dùng được"), ("needs_edit", "Cần sửa"), ("reject", "Không dùng được")],
                                    string="Tự đánh giá", readonly=True, copy=False)
    trial_rated_by = fields.Many2one("res.users", string="Người tự đánh giá", readonly=True, copy=False)
    trial_rated_at = fields.Datetime("Thời điểm tự đánh giá", readonly=True, copy=False)
    trial_elapsed = fields.Float("Tổng thời gian (giây)", compute="_compute_trial_elapsed", digits=(16, 1))

    @api.depends("trial_started_at", "trial_finished_at")
    def _compute_trial_elapsed(self):
        for review in self:
            review.trial_elapsed = ((review.trial_finished_at - review.trial_started_at).total_seconds()
                                    if review.trial_started_at and review.trial_finished_at else 0)

    @api.depends("trace")
    def _compute_model_details(self):
        for review in self:
            detail = json.loads(review.trace or "{}")
            review.model_details = "\n".join(f"{item['provider']} · {item['model']}" for item in detail.get("trace", [])) + (
                "\nKỹ năng: " + ", ".join(item["label"] for item in detail.get("skills", [])) if detail.get("skills") else "")
            if detail.get("privacy_version"):
                review.model_details += "\nChế độ: " + ("Quy tắc local, không gọi API model." if detail.get("strategy") == "rules" else
                    "Chỉ gửi mã tạm, trạng thái và dấu hiệu nghiệp vụ; giữ tên khách, giá và ghi chú tại máy.")

    def _allowed_users(self):
        self.ensure_one()
        users = self.env.user
        if self.env.user.has_group("sales_team.group_sale_manager"):
            teams = self.env["crm.team"].search([("user_id", "=", self.env.uid),
                ("company_id", "in", [False, self.env.company.id])])
            users |= teams.member_ids | teams.user_id
        return users.filtered(lambda u: u.active and not u.share and self.env.company in u.company_ids)

    def _compute_allowed_users(self):
        for review in self:
            review.allowed_user_ids = review._allowed_users()

    def _check_scope(self, operation="read"):
        self.check_access(operation)
        self.order_id._olist_check_scope()

    def _set_internal(self, values):
        for review in self:
            update = dict(values)
            if update.get("trial_started_at") or review.trial_started_at:
                if update.get("state") == "ready" and not review.trial_ready_at:
                    update["trial_ready_at"] = fields.Datetime.now()
                if update.get("state") in {"approved", "failed", "cancelled"} and not review.trial_finished_at:
                    update["trial_finished_at"] = fields.Datetime.now()
                    update["trial_outcome"] = update["state"]
            super(FollowupReview, review).write(update)
        return True

    def _source_evidence(self):
        self.ensure_one()
        evidence = json.loads(self.snapshot_json)
        return (f"{evidence['name']} · {evidence['partner_name']}\nTổng: {evidence['total']} {evidence['currency']}\n"
                f"Trạng thái: {evidence['state']}\nHạn báo giá: {evidence['validity_date'] or 'Chưa có'}\n" + self.order_id.olist_ai_reason)

    def action_export_trials(self):
        if not self or any(not r.trial_started_at for r in self):
            raise UserError("Chọn các lượt đo cần xuất, gồm cả lượt lỗi hoặc bị bỏ qua.")
        for review in self:
            review._check_scope("read")
        stream = io.StringIO(newline="")
        columns = ["schema_version", "trial_id", "participant", "case", "sequence", "assignment_version", "method", "actual_strategy", "outcome",
                   "started_at_utc", "ready_at_utc", "finished_at_utc", "total_seconds", "after_ready_seconds", "quotation_state", "has_activity",
                   "self_rating", "rated_at_utc", "rating_source"]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for review in self.sorted("id"):
            detail = json.loads(review.trace or "{}")
            snapshot = json.loads(review.snapshot_json)
            finished = review.trial_finished_at
            writer.writerow({"schema_version": "followup-task-times-v2", "trial_id": review.request_key, "participant": review.trial_participant,
                "case": review.trial_case, "sequence": review.trial_sequence, "assignment_version": "cyclic-v1",
                "method": review.trial_method, "actual_strategy": detail.get("strategy", "unknown"),
                "outcome": review.trial_outcome if finished else "unfinished",
                "started_at_utc": fields.Datetime.to_string(review.trial_started_at),
                "ready_at_utc": fields.Datetime.to_string(review.trial_ready_at) if review.trial_ready_at else "",
                "finished_at_utc": fields.Datetime.to_string(finished) if finished else "",
                "total_seconds": (finished - review.trial_started_at).total_seconds() if finished else "",
                "after_ready_seconds": (finished - review.trial_ready_at).total_seconds() if finished and review.trial_ready_at else "",
                "quotation_state": snapshot["state"], "has_activity": bool(snapshot["activities"]),
                "self_rating": review.trial_rating or "", "rated_at_utc": fields.Datetime.to_string(review.trial_rated_at) if review.trial_rated_at else "",
                "rating_source": "self" if review.trial_rated_at else ""})
        attachment = self.env["ir.attachment"].create({"name": "olist-luot-do.csv", "type": "binary",
            "datas": base64.b64encode(("\ufeff" + stream.getvalue()).encode("utf-8")), "mimetype": "text/csv",
            "public": False})  # Unlinked: only the exporter and administrators may read it.
        return {"type": "ir.actions.act_url", "url": f"/web/content/{attachment.id}?download=true", "target": "self"}

    def _rate_trial(self, rating):
        self.ensure_one()
        self._check_scope("write")
        self.env.cr.execute("SELECT id FROM olist_ai_followup_review WHERE id=%s FOR UPDATE", (self.id,))
        self.invalidate_recordset()
        if self.owner_id != self.env.user or not self.trial_finished_at:
            raise UserError("Chỉ người thực hiện tự đánh giá sau khi lượt đo kết thúc.")
        if self.trial_rated_at:
            if self.trial_rating != rating:
                raise UserError("Đã ghi tự đánh giá đầu tiên; không ghi đè kết quả cũ.")
            return {"type": "ir.actions.client", "tag": "reload"}
        if rating != "reject" and (not self.trial_ready_at or not self.summary or not self.note):
            raise UserError("Lượt chưa có nội dung chỉ có thể đánh dấu không dùng được.")
        self._set_internal({"trial_rating": rating, "trial_rated_by": self.env.uid, "trial_rated_at": fields.Datetime.now()})
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_trial_usable(self):
        return self._rate_trial("usable")

    def action_trial_needs_edit(self):
        return self._rate_trial("needs_edit")

    def action_trial_reject(self):
        return self._rate_trial("reject")

    @api.model
    def _snapshot(self, order):
        order._olist_check_scope()
        if len(order.activity_ids) > 100:
            raise UserError("Báo giá có quá nhiều công việc để đối soát đầy đủ.")
        notes = self.env["mail.message"].search([("model", "=", "sale.order"), ("res_id", "=", order.id),
            ("message_type", "=", "comment"), ("subtype_id", "=", self.env.ref("mail.mt_note").id)], order="date desc,id desc", limit=5)
        return {"id": order.id, "name": order.name, "partner_id": order.partner_id.id, "partner_name": order.partner_id.name,
                "salesperson_id": order.user_id.id or None, "state": order.state, "currency": order.currency_id.name,
                "total": str(order.amount_total), "ordered_at": fields.Datetime.to_string(order.date_order),
                "validity_date": fields.Date.to_string(order.validity_date) if order.validity_date else None,
                "write_date": fields.Datetime.to_string(order.write_date),
                "activities": [{"id": a.id, "deadline": fields.Date.to_string(a.date_deadline), "user_id": a.user_id.id,
                    "type_id": a.activity_type_id.id, "summary": (a.summary or "")[:500]} for a in order.activity_ids.sorted("id")],
                "notes": [html2plaintext(n.body or "")[:1000] for n in notes]}

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for values in vals_list:
            if set(values) != {"order_id"}:
                raise AccessError("Chỉ tạo đề xuất từ báo giá; thông tin đối soát do server lập.")
            order = self.env["sale.order"].browse(values["order_id"])
            order._olist_check_scope()
            snapshot = json.dumps(self._snapshot(order), ensure_ascii=False, sort_keys=True)
            prepared.append({**values, "company_id": order.company_id.id, "owner_id": self.env.uid,
                "assigned_id": self.env.uid, "deadline": fields.Date.context_today(self) + timedelta(days=1),
                "snapshot_json": snapshot, "source_hash": hashlib.sha256(snapshot.encode()).hexdigest(),
                "snapshot_date": fields.Date.context_today(self), "request_key": uuid.uuid4().hex})
        return super().create(prepared)

    def write(self, values):
        allowed = {"summary", "note", "activity_type", "assigned_id", "deadline", "approval_checked"}
        if not set(values) <= allowed:
            raise AccessError("Không được sửa dữ liệu đối soát hoặc lịch sử duyệt.")
        for review in self:
            review._check_scope("write")
            if review.state != "ready":
                raise UserError("Chỉ sửa nội dung khi đề xuất đang chờ duyệt.")
        if any(k != "approval_checked" for k in values) and "approval_checked" not in values:
            values = {**values, "approval_checked": False}
        return super().write(values)

    @api.onchange("summary", "note", "activity_type", "assigned_id", "deadline")
    def _onchange_approval(self):
        self.approval_checked = False

    def copy(self, default=None):
        raise UserError("Chọn báo giá để tạo bản đối soát mới.")

    def _bridge(self, method, path, payload=None):
        token = os.getenv("ODOO_AI_BRIDGE_TOKEN", "")
        if len(token) < 32:
            raise UserError("Chưa cấu hình ODOO_AI_BRIDGE_TOKEN trên Odoo server.")
        base = os.getenv("ODOO_AI_BACKEND_URL", "http://host.docker.internal:8000").rstrip("/")
        # No user-controlled URL, cookies or redirects; credentials never reach the browser.
        if base not in {"http://host.docker.internal:8000", "http://127.0.0.1:8000", "http://host.docker.internal:8011"}:
            raise UserError("Địa chỉ backend AI chưa được hỗ trợ.")
        try:
            response = requests.request(method, base + path, json=payload if method == "POST" else None,
                params=payload if method == "GET" else None, headers={"X-Odoo-Bridge-Token": token}, timeout=8, allow_redirects=False)
            response.raise_for_status()
            return response.json()
        except Exception:
            raise UserError("Chưa kết nối được backend AI. Kiểm tra ứng dụng local và cấu hình kết nối.") from None

    def action_start(self):
        self._check_scope("write")
        if not self or len(self) > 20 or any(r.state != "pending" for r in self):
            raise UserError("Đề xuất đã được xử lý. Tạo bản đối soát mới nếu cần.")
        if any(self.mapped("job_started")):
            return True
        if len(self.owner_id) != 1 or len(self.company_id) != 1 or len(set(self.mapped("snapshot_date"))) != 1:
            raise UserError("Mỗi lượt phân tích chỉ dùng một người, công ty và ngày đối soát.")
        key = self[0].request_key
        self._set_internal({"request_key": key, "job_started": True})
        payload = {"request_id": key, "database": self.env.cr.dbname, "user_id": self.owner_id.id,
            "company_id": self.company_id.id, "today": fields.Date.to_string(self[0].snapshot_date),
            "orders": [json.loads(r.snapshot_json) for r in self]}
        if any(r.trial_method == "rules" for r in self):
            if any(r.trial_method != "rules" for r in self):
                raise UserError("Không trộn lượt dùng mẫu với lượt AI trong một yêu cầu.")
            payload["mode"] = "rules_only"
        try:
            self._bridge("POST", "/odoo-ai/analyses", payload)
        except UserError as exc:
            self._set_internal({"error": str(exc) + " Đang giữ mã lượt để lấy lại kết quả."})
        return True

    def poll_state(self):
        self.ensure_one()
        self._check_scope("write")
        if self.state != "pending":
            return self.state
        try:
            result = self._bridge("GET", "/odoo-ai/analyses/" + self.request_key,
                {"database": self.env.cr.dbname, "user_id": self.owner_id.id, "company_id": self.company_id.id})
        except UserError:
            if (fields.Datetime.now() - self.create_date).total_seconds() > 150:
                self._set_internal({"state": "failed", "error": "Chưa lấy được kết quả. Kiểm tra backend rồi tạo đề xuất mới."})
                return self.state
            return "pending"  # Keep the same request ID; a temporary outage does not repeat models.
        self.env.cr.execute("SELECT id FROM olist_ai_followup_review WHERE id=%s FOR UPDATE", (self.id,))
        self.invalidate_recordset()
        if self.state != "pending":
            return self.state
        if result.get("state") == "complete":
            items = result.get("items", [])
            matching = [item for item in items if item.get("order_id") == self.order_id.id]
            if result.get("request_id") != self.request_key or len(matching) != 1:
                self._set_internal({"state": "failed", "error": "Kết quả AI không khớp báo giá."})
                return self.state
            item = matching[0]
            evidence = json.loads(self.snapshot_json)
            self._set_internal({"state": "ready", "summary": item["summary"], "note": item["note"],
                "activity_type": item["activity_type"], "explanation": item["explanation"],
                "evidence": f"{evidence['name']} · {evidence['partner_name']}\nTổng: {evidence['total']} {evidence['currency']}\n"
                    f"Hạn báo giá: {evidence['validity_date'] or 'Chưa có'}\n" + " · ".join(LABELS[c] for c in item["reason_codes"]),
                "trace": json.dumps({k: result.get(k, []) for k in ("trace", "skills", "privacy_version", "grounding_version", "request_policy", "strategy")}, ensure_ascii=False)})
        elif result.get("state") in {"failed", "interrupted"}:
            self._set_internal({"state": "failed", "error": result.get("error", "Chưa hoàn tất phân tích."),
                "trace": json.dumps({"trace": result.get("trace", [])}, ensure_ascii=False)})
        return self.state

    def action_poll(self):
        self.poll_state()
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_cancel(self):
        self._check_scope("write")
        if any(r.state == "approved" for r in self):
            raise UserError("Công việc đã giao; xử lý ở Activities của báo giá.")
        self._set_internal({"state": "cancelled"})

    def action_approve(self):
        self.ensure_one()
        self._check_scope("write")
        self.env.cr.execute("SELECT id FROM olist_ai_followup_review WHERE id=%s FOR UPDATE", (self.id,))
        self.invalidate_recordset()
        if self.state == "approved":
            return {"type": "ir.actions.act_window", "res_model": "sale.order", "res_id": self.order_id.id, "view_mode": "form"}
        if self.state != "ready" or not self.approval_checked:
            raise UserError("Kiểm tra nội dung và đánh dấu đồng ý trước khi duyệt giao việc.")
        self.env.cr.execute("SELECT id FROM sale_order WHERE id=%s FOR UPDATE", (self.order_id.id,))
        self.order_id.invalidate_recordset()
        fresh = json.dumps(self._snapshot(self.order_id), ensure_ascii=False, sort_keys=True)
        if hashlib.sha256(fresh.encode()).hexdigest() != self.source_hash:
            raise UserError("Dữ liệu Odoo đã đổi. Bỏ qua đề xuất này và phân tích lại trước khi duyệt.")
        if self.assigned_id not in self._allowed_users():
            raise AccessError("Chỉ giao việc cho người trong phạm vi được quản lý.")
        if not self.summary or not self.summary.strip() or not self.note or not self.note.strip() or len(self.note) > 2000:
            raise ValidationError("Nhập tên việc và nội dung chăm sóc, tối đa hai nghìn ký tự.")
        if self.deadline < fields.Date.context_today(self):
            raise ValidationError("Ngày hẹn không được ở quá khứ.")
        activity_type = self.env.ref("mail.mail_activity_data_call" if self.activity_type == "call" else "mail.mail_activity_data_todo")
        model_id = self.env["ir.model"]._get_id("sale.order")
        if self.env["mail.activity"].search_count([("res_model_id", "=", model_id), ("res_id", "=", self.order_id.id),
            ("user_id", "=", self.assigned_id.id), ("activity_type_id", "=", activity_type.id)]):
            raise UserError("Đã có công việc cùng loại cho người này. Kiểm tra Activities trước khi tạo thêm.")
        values = {"res_model_id": model_id, "res_id": self.order_id.id, "activity_type_id": activity_type.id,
            "user_id": self.assigned_id.id, "date_deadline": self.deadline, "summary": self.summary.strip(),
            "note": Markup("<p>%s</p>") % escape(self.note).replace("\n", Markup("<br/>"))}
        activity = self.env["mail.activity"].create(values)
        self._set_internal({"state": "approved", "activity_id": activity.id, "approved_by": self.env.uid,
            "approved_at": fields.Datetime.now(), "approved_payload": json.dumps({
                "summary": self.summary, "note": self.note, "user_id": self.assigned_id.id,
                "deadline": fields.Date.to_string(self.deadline), "activity_type": self.activity_type}, ensure_ascii=False)})
        return {"type": "ir.actions.act_window", "res_model": "sale.order", "res_id": self.order_id.id, "view_mode": "form"}
