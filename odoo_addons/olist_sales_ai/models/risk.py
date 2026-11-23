import hashlib
import json
import uuid
from datetime import timedelta
from pathlib import Path

from markupsafe import Markup, escape
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

CATALOG = json.loads((Path(__file__).resolve().parents[1] / "data/risk_catalog.json").read_text(encoding="utf-8"))


class SaleOrderRisk(models.Model):
    _inherit = "sale.order"

    def _olist_risk_snapshot(self):
        self.ensure_one()
        self._olist_check_scope()
        lines = self.order_line.filtered(lambda line: not line.display_type)
        if len(lines) > 100:
            raise UserError("Bản kiểm tra local hỗ trợ tối đa một trăm dòng sản phẩm; chưa kiểm tra một phần.")
        return {"today": fields.Date.to_string(fields.Date.context_today(self)), "write_date": fields.Datetime.to_string(self.write_date),
            "state": self.state, "validity": fields.Date.to_string(self.validity_date) if self.validity_date else None,
            "payment_term": self.payment_term_id.id or None,
            "lines": [{"id": line.id, "quantity": line.product_uom_qty, "price": line.price_unit,
                       "discount": line.discount, "taxes": line.tax_ids.ids, "product_active": line.product_id.active}
                      for line in lines.sorted(lambda line: (line.sequence, line.id))]}

    def action_olist_check_risks(self):
        self.ensure_one()
        self._olist_check_scope()
        review = self.env["olist.ai.quote.risk.review"].create({"order_id": self.id})
        return {"type": "ir.actions.act_window", "name": "Kiểm tra rủi ro báo giá", "res_model": review._name,
                "view_mode": "form", "res_id": review.id, "target": "current"}


class QuoteRiskReview(models.Model):
    _name = "olist.ai.quote.risk.review"
    _description = "Điểm cần đối chiếu trên báo giá"
    _rec_name = "order_id"
    _order = "create_date desc,id desc"

    order_id = fields.Many2one("sale.order", string="Báo giá", required=True, readonly=True, ondelete="restrict")
    owner_id = fields.Many2one("res.users", string="Người kiểm tra", required=True, readonly=True)
    company_id = fields.Many2one("res.company", required=True, readonly=True)
    checked_at = fields.Datetime("Thời điểm kiểm tra", readonly=True)
    snapshot_json = fields.Text(readonly=True)
    source_hash = fields.Char(readonly=True)
    findings_json = fields.Text(readonly=True)
    findings_html = fields.Html("Điểm cần đối chiếu", compute="_compute_findings")
    stale = fields.Boolean("Nguồn đã thay đổi", compute="_compute_stale")
    state = fields.Selection([("checked", "Đã kiểm tra quy tắc"), ("pending", "Đang diễn giải"),
        ("explained", "Đã diễn giải"), ("failed", "Chưa có diễn giải")], default="checked", readonly=True)
    explanation = fields.Text("Câu hỏi đối chiếu", readonly=True)
    error = fields.Text("Thông báo", readonly=True)
    trace = fields.Text("Lịch sử model", readonly=True)
    request_key = fields.Char(readonly=True, copy=False)
    job_started = fields.Boolean(readonly=True)
    explanation_started_at = fields.Datetime(readonly=True)

    @api.depends("order_id.write_date", "snapshot_json")
    def _compute_stale(self):
        for review in self:
            try:
                current = json.dumps(review.order_id._olist_risk_snapshot(), sort_keys=True)
                review.stale = hashlib.sha256(current.encode()).hexdigest() != review.source_hash
            except AccessError:
                review.stale = True

    @api.depends("findings_json")
    def _compute_findings(self):
        levels = {"high": "Cần xem kỹ", "attention": "Cần đối chiếu", "info": "Thông tin"}
        for review in self:
            rows = json.loads(review.findings_json or "[]")
            review.findings_html = Markup("<ul>%s</ul>") % Markup("").join(
                Markup("<li><strong>%s · %s</strong><br/>%s</li>") % (escape(levels[r["level"]]), escape(r["label"]), escape("; ".join(r["evidence"]))) for r in rows)
            if not rows:
                review.findings_html = "Trong phạm vi kiểm tra này chưa thấy cờ cần xem. Chưa thay cho duyệt nghiệp vụ hoặc kiểm toán thuế."

    @api.model
    def _findings(self, snapshot):
        findings = {}
        def flag(code, evidence):
            findings.setdefault(code, {"code": code, **CATALOG[code], "evidence": []})["evidence"].append(evidence)
        today = fields.Date.to_date(snapshot["today"])
        expiry = fields.Date.to_date(snapshot["validity"]) if snapshot["validity"] else None
        if expiry is None: flag("missing_validity", "Chưa chọn hạn hiệu lực trên chứng từ.")
        elif expiry < today: flag("expired", "Hạn hiệu lực: " + snapshot["validity"])
        elif expiry <= today + timedelta(days=3): flag("expiring", "Hạn hiệu lực: " + snapshot["validity"])
        if not snapshot["payment_term"]: flag("missing_payment_term", "Chưa chọn điều khoản thanh toán; cần xác minh chủ đích.")
        if not snapshot["lines"]: flag("empty_lines", "Không có dòng sản phẩm; dòng ghi chú/tiêu đề không thay thế dòng hàng.")
        for index, line in enumerate(snapshot["lines"], 1):
            prefix = f"Dòng {index}: "
            if line["quantity"] <= 0: flag("nonpositive_quantity", prefix + "số lượng " + str(line["quantity"]))
            if line["price"] < 0: flag("negative_price", prefix + "đơn giá âm, cần kiểm tra dòng giảm trừ có chủ đích.")
            elif line["price"] == 0: flag("zero_price", prefix + "đơn giá bằng không, có thể là miễn phí có chủ đích.")
            if not 0 <= line["discount"] <= 100: flag("invalid_discount", prefix + "chiết khấu " + str(line["discount"]) + "%; khoảng đối chiếu kỹ thuật là 0–100%, không thay chính sách công ty.")
            elif line["discount"] > 0: flag("discount_present", prefix + "chiết khấu " + str(line["discount"]) + "%; chưa có chính sách phê duyệt để kết luận sai.")
            if not line["taxes"]: flag("missing_tax", prefix + "chưa chọn thuế; không tự kết luận sai hoặc vi phạm thuế.")
            if not line["product_active"]: flag("inactive_product", prefix + "sản phẩm đã được lưu trữ.")
        priority = {"high": 0, "attention": 1, "info": 2}
        return sorted(findings.values(), key=lambda r: (priority[r["level"]], r["code"]))

    @api.model_create_multi
    def create(self, values_list):
        values = []
        for item in values_list:
            if set(item) != {"order_id"}: raise AccessError("Chỉ chọn báo giá; kết quả do server đối chiếu.")
            order = self.env["sale.order"].browse(item["order_id"])
            snapshot = order._olist_risk_snapshot()
            serialized = json.dumps(snapshot, sort_keys=True)
            values.append({"order_id": order.id, "owner_id": self.env.uid, "company_id": order.company_id.id,
                "checked_at": fields.Datetime.now(), "snapshot_json": serialized, "source_hash": hashlib.sha256(serialized.encode()).hexdigest(),
                "findings_json": json.dumps(self._findings(snapshot), ensure_ascii=False), "request_key": uuid.uuid4().hex})
        clean_context = {k: v for k, v in self.env.context.items() if not k.startswith("default_")}
        return super(QuoteRiskReview, self.with_context(clean_context)).create(values)

    def write(self, values):
        raise AccessError("Không sửa kết quả đối chiếu; kiểm tra lại để có bản mới.")

    def _check_scope(self):
        self.check_access("read")
        self.order_id._olist_check_scope()

    def _bridge(self, method, path, payload=None):
        return self.env["olist.ai.followup.review"]._bridge(method, path, payload)

    def action_explain(self):
        self.ensure_one(); self._check_scope()
        self.env.cr.execute("SELECT id FROM olist_ai_quote_risk_review WHERE id=%s FOR UPDATE", (self.id,))
        self.invalidate_recordset()
        if self.stale: raise UserError("Dữ liệu đã đổi; kiểm tra lại trước khi yêu cầu diễn giải.")
        if self.job_started: return True
        codes = [r["code"] for r in json.loads(self.findings_json)]
        super().write({"state": "pending", "job_started": True, "explanation_started_at": fields.Datetime.now()})
        payload = {"request_id": self.request_key, "database": self.env.cr.dbname, "user_id": self.owner_id.id,
            "company_id": self.company_id.id, "today": json.loads(self.snapshot_json)["today"], "purpose": "risk", "risk_codes": codes,
            "orders": [self.env["olist.ai.followup.review"]._snapshot(self.order_id)]}
        try: self._bridge("POST", "/odoo-ai/analyses", payload)
        except UserError: super().write({"error": "Chưa nhận được phản hồi; đang giữ mã lượt để lấy lại kết quả."})
        return True

    def poll_state(self):
        self.ensure_one(); self._check_scope()
        if self.state != "pending": return self.state
        try:
            result = self._bridge("GET", "/odoo-ai/analyses/"+self.request_key,
                {"database": self.env.cr.dbname, "user_id": self.owner_id.id, "company_id": self.company_id.id})
        except UserError: result = {"state": "pending"}
        self.env.cr.execute("SELECT id FROM olist_ai_quote_risk_review WHERE id=%s FOR UPDATE", (self.id,))
        self.invalidate_recordset()
        if self.state != "pending": return self.state
        if result.get("state") == "complete":
            expected = {r["code"] for r in json.loads(self.findings_json)}
            items = result.get("items", [])
            valid_items = isinstance(items, list) and all(isinstance(r, dict) and
                isinstance(r.get("code"), str) and isinstance(r.get("question"), str) and
                0 < len(r["question"]) <= 400 for r in items)
            if (result.get("request_id") != self.request_key or result.get("purpose") != "risk" or
                not valid_items or len(items) != len(expected) or {r["code"] for r in items} != expected):
                super().write({"state": "failed", "error": "Kết quả không khớp các cờ đã kiểm tra."})
            else:
                text = "\n\n".join(CATALOG[r["code"]]["label"]+": "+r["question"] for r in items) or "Chưa có cờ cần diễn giải trong phạm vi kiểm tra."
                super().write({"state": "explained", "explanation": text, "trace": json.dumps({k:result.get(k) for k in ("trace", "skills", "strategy", "privacy_version")}, ensure_ascii=False), "error": False})
        elif result.get("state") in {"failed", "interrupted"} or fields.Datetime.now() - self.explanation_started_at > timedelta(seconds=150):
            super().write({"state": "failed", "error": result.get("error") or "Lượt diễn giải hết thời gian chờ; các cờ kiểm tra local vẫn được giữ."})
        return self.state

    def action_poll(self):
        self.poll_state()
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_recheck(self):
        self.ensure_one(); self._check_scope()
        return self.order_id.action_olist_check_risks()
