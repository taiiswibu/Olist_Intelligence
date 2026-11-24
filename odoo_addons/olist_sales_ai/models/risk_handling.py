"""Local, append-only human dispositions; never included in model requests or chatter."""
import json

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from .risk import CATALOG, DECISIONS

CODES = [(code, value["label"]) for code, value in CATALOG.items()]


def clean_context(record):
    return record.with_context({k: v for k, v in record.env.context.items() if not k.startswith("default_")})


class RiskDecision(models.Model):
    _name = "olist.ai.quote.risk.decision"
    _description = "Lịch sử ghi nhận cảnh báo"
    _order = "id desc"

    review_id = fields.Many2one("olist.ai.quote.risk.review", required=True, readonly=True, ondelete="restrict", index=True)
    order_id = fields.Many2one(related="review_id.order_id", store=True, readonly=True)
    company_id = fields.Many2one(related="review_id.company_id", store=True, readonly=True)
    code = fields.Selection(CODES, string="Cảnh báo", required=True, readonly=True)
    decision = fields.Selection(DECISIONS, string="Ghi nhận", required=True, readonly=True)
    reason = fields.Text("Lý do", required=True, readonly=True)
    actor_id = fields.Many2one("res.users", string="Người ghi", required=True, readonly=True)
    recorded_at = fields.Datetime("Thời điểm", required=True, readonly=True)

    @api.model_create_multi
    def create(self, values_list):
        result = self.browse()
        for item in values_list:
            if set(item) != {"review_id", "code", "decision", "reason"}:
                raise AccessError("Chỉ ghi lựa chọn và lý do; thông tin lịch sử do server lập.")
            review = self.env["olist.ai.quote.risk.review"].browse(item["review_id"])
            review._check_scope()
            self.env.cr.execute("SELECT id FROM olist_ai_quote_risk_review WHERE id=%s FOR UPDATE", (review.id,))
            review.invalidate_recordset(["stale", "decision_ids"])
            if review.stale:
                raise UserError("Dữ liệu đã đổi; kiểm tra lại trước khi ghi nhận xử lý.")
            codes = {r["code"] for r in json.loads(review.findings_json)}
            reason = item["reason"].strip() if isinstance(item["reason"], str) else ""
            if item["code"] not in codes or item["decision"] not in dict(DECISIONS):
                raise UserError("Lựa chọn phải thuộc cảnh báo của bản kiểm tra này.")
            if not reason or len(reason) > 1000:
                raise UserError("Nhập lý do từ một đến một nghìn ký tự.")
            last = review._latest_decisions().get(item["code"])
            if last and last.decision == item["decision"] and last.reason == reason:
                result += last
                continue
            result += super(RiskDecision, clean_context(self)).create({**item, "reason": reason,
                "actor_id": self.env.uid, "recorded_at": fields.Datetime.now()})
        return result

    def write(self, values):
        raise AccessError("Lịch sử đã lưu không được sửa; hãy ghi nhận lần mới.")

    def unlink(self):
        raise AccessError("Không xóa lịch sử ghi nhận.")


class RiskHandle(models.TransientModel):
    _name = "olist.ai.quote.risk.handle"
    _description = "Ghi nhận xử lý cảnh báo"

    review_id = fields.Many2one("olist.ai.quote.risk.review", string="Bản kiểm tra", required=True, readonly=True)
    line_ids = fields.One2many("olist.ai.quote.risk.handle.line", "wizard_id", string="Cảnh báo")
    saved = fields.Boolean(readonly=True)

    @api.model_create_multi
    def create(self, values_list):
        result = self.browse()
        for item in values_list:
            if set(item) != {"review_id"}:
                raise AccessError("Mở cửa sổ từ bản kiểm tra; danh sách cờ do server lập.")
            review = self.env["olist.ai.quote.risk.review"].browse(item["review_id"])
            review._check_scope()
            review.invalidate_recordset(["stale"])
            if review.stale:
                raise UserError("Dữ liệu đã đổi; hãy kiểm tra lại.")
            wizard = super(RiskHandle, clean_context(self)).create(item)
            latest = review._latest_decisions()
            values = []
            for finding in json.loads(review.findings_json):
                last = latest.get(finding["code"])
                values.append({"wizard_id": wizard.id, "code": finding["code"], "evidence": "; ".join(finding["evidence"]),
                    "decision": last.decision if last else False, "reason": last.reason if last else False,
                    "base_decision_id": last.id if last else False})
            self.env["olist.ai.quote.risk.handle.line"]._seed(values)
            result += wizard
        return result

    def write(self, values):
        if set(values) - {"line_ids"}:
            raise AccessError("Chỉ sửa lựa chọn và lý do trong cửa sổ xử lý.")
        for command in values.get("line_ids", []):
            if command[0] != 1 or command[1] not in self.line_ids.ids:
                raise AccessError("Không thay danh sách cảnh báo do server lập.")
        return super().write(values)

    def action_save(self):
        self.ensure_one(); self.check_access("write")
        self.review_id._check_scope()
        self.env.cr.execute("SELECT id FROM olist_ai_quote_risk_handle WHERE id=%s FOR UPDATE", (self.id,))
        self.invalidate_recordset(["saved"])
        if self.saved:
            return self.review_id._open_action()
        review = self.review_id
        self.env.cr.execute("SELECT id FROM olist_ai_quote_risk_review WHERE id=%s FOR UPDATE", (review.id,))
        review.invalidate_recordset(["stale", "decision_ids"])
        if review.stale:
            raise UserError("Dữ liệu đã đổi; kiểm tra lại trước khi lưu ghi nhận.")
        codes = {r["code"] for r in json.loads(review.findings_json)}
        if len(self.line_ids) != len(codes) or set(self.line_ids.mapped("code")) != codes:
            raise AccessError("Danh sách cảnh báo không khớp bản kiểm tra.")
        latest = review._latest_decisions()
        for line in self.line_ids:
            base = line.base_decision_id
            reason = (line.reason or "").strip()
            if line.decision == (base.decision if base else False) and reason == (base.reason if base else ""):
                continue
            current = latest.get(line.code)
            if (current.id if current else False) != base.id:
                raise UserError("Có ghi nhận mới trong lúc bạn đang nhập; mở lại cửa sổ để đối chiếu.")
            self.env["olist.ai.quote.risk.decision"].create({"review_id": review.id, "code": line.code,
                "decision": line.decision, "reason": reason})
        super().write({"saved": True})
        return review._open_action()


class RiskHandleLine(models.TransientModel):
    _name = "olist.ai.quote.risk.handle.line"
    _description = "Dòng ghi nhận cảnh báo"
    _order = "id"

    wizard_id = fields.Many2one("olist.ai.quote.risk.handle", required=True, readonly=True, ondelete="cascade")
    code = fields.Selection(CODES, string="Cảnh báo", required=True, readonly=True)
    evidence = fields.Text("Bằng chứng", readonly=True)
    decision = fields.Selection(DECISIONS, string="Ghi nhận")
    reason = fields.Text("Lý do")
    base_decision_id = fields.Many2one("olist.ai.quote.risk.decision", readonly=True)

    @api.model_create_multi
    def create(self, values_list):
        raise AccessError("Dòng cảnh báo do server lập.")

    def _seed(self, values):
        return super(RiskHandleLine, clean_context(self)).create(values)

    def write(self, values):
        if set(values) - {"decision", "reason"}:
            raise AccessError("Chỉ sửa lựa chọn và lý do.")
        if any(line.wizard_id.saved for line in self):
            raise AccessError("Cửa sổ đã lưu; mở lại để ghi nhận lần mới.")
        return super().write(values)
