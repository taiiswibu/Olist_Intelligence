import hashlib
import json
import os
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
        return super(FollowupReview, self).write(values)

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
                "trace": json.dumps({k: result.get(k, []) for k in ("trace", "skills", "privacy_version", "strategy")}, ensure_ascii=False)})
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
