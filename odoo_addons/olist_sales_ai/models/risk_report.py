"""Read-only report projection shared by QWeb PDF and in-memory XLSX exports."""
import io
import json
from math import ceil

import xlsxwriter
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from .risk import DECISIONS

LEVELS = {"high": "Cần xem kỹ", "attention": "Cần đối chiếu", "info": "Thông tin"}
NOTICE = "Các cờ dùng để đối chiếu dữ liệu và nghiệp vụ. Đúng chủ đích là ghi nhận của người bán, chưa thay phê duyệt chứng từ."


class RiskReportExport(models.Model):
    _inherit = "olist.ai.quote.risk.review"

    def _risk_report_data(self):
        self.ensure_one(); self._check_scope()
        previous = self.previous_review_id
        if previous:
            previous._check_scope()
            if previous.order_id != self.order_id or previous.company_id != self.company_id:
                raise AccessError("Bản trước không thuộc cùng báo giá và công ty.")
        try:
            self.invalidate_recordset(["stale"])
            stale = self.stale
        except UserError:
            stale = True  # Source now exceeds the check's line limit; export the saved evidence.
        def timestamp(value):
            return fields.Datetime.context_timestamp(self, value).strftime("%Y-%m-%d %H:%M:%S") if value else ""
        before = {r["code"]: r for r in json.loads(previous.findings_json or "[]")}
        current = {r["code"]: r for r in json.loads(self.findings_json or "[]")}
        latest = self._latest_decisions()
        previous_latest = previous._latest_decisions() if previous else {}
        rows = []
        for code in sorted(before.keys() | current.keys()):
            finding = current.get(code) or before[code]
            event, old_event = latest.get(code), previous_latest.get(code)
            change = ("Chưa có bản trước" if not previous else "Vẫn xuất hiện" if code in before and code in current
                else "Mới xuất hiện" if code in current else "Không còn xuất hiện")
            rows.append({"code": code, "label": finding["label"], "level": LEVELS[finding["level"]], "change": change,
                "before": "; ".join(before[code]["evidence"]) if code in before else "Không có cờ này" if previous else "Chưa có bản trước",
                "after": "; ".join(current[code]["evidence"]) if code in current else "Không có cờ này",
                "current": code in current, "decision": dict(DECISIONS)[event.decision] if event else "Chưa ghi nhận" if code in current else "Không áp dụng",
                "reason": event.reason if event else "", "actor": event.actor_id.name if event else "", "recorded_at": timestamp(event.recorded_at) if event else "",
                "previous_decision": dict(DECISIONS)[old_event.decision] if old_event else "Chưa ghi nhận" if code in before else "Không áp dụng",
                "previous_reason": old_event.reason if old_event else "",
                "needs_attention": code in current and (not event or event.decision != "intentional")})
        events = self.env["olist.ai.quote.risk.decision"].search([("review_id", "in", (self | previous).ids)], order="id", limit=1001)
        if len(events) > 1000:
            raise UserError("Báo cáo hỗ trợ tối đa một nghìn ghi nhận của hai bản; chưa xuất một phần lịch sử.")
        labels = {r["code"]: r["label"] for r in rows}
        return {"quote": self.order_id.name, "review_id": self.id, "previous_id": previous.id or "",
            "checked_at": timestamp(self.checked_at), "previous_checked_at": timestamp(previous.checked_at) if previous else "",
            "exported_at": timestamp(fields.Datetime.now()), "exported_by": self.env.user.name, "owner": self.owner_id.name,
            "timezone": self.env.context.get("tz") or self.env.user.tz or "UTC", "stale": stale, "notice": NOTICE,
            "source_notice": "Nguồn đã đổi hoặc chưa đối chiếu được hiện tại; file giữ bằng chứng tại thời điểm kiểm tra." if stale else "Nguồn hiện tại khớp bản kiểm tra khi xuất file.",
            "current_count": len(current), "attention_count": sum(r["needs_attention"] for r in rows), "rows": rows,
            "ai_state": dict(self._fields["state"].selection)[self.state], "ai_explanation": self.explanation or "", "ai_error": self.error or "",
            "history": [{"review_id": e.review_id.id, "code": e.code, "label": labels[e.code], "decision": dict(DECISIONS)[e.decision],
                "reason": e.reason, "actor": e.actor_id.name, "recorded_at": timestamp(e.recorded_at)} for e in events]}

    def action_risk_pdf(self):
        self.ensure_one(); self._check_scope()
        return self.env.ref("olist_sales_ai.risk_report_action").report_action(self)

    def action_risk_xlsx(self):
        self.ensure_one(); self._check_scope()
        return {"type": "ir.actions.act_url", "url": f"/olist-sales-ai/risk/{self.id}/xlsx", "target": "self"}

    def _risk_xlsx_bytes(self):
        report = self._risk_report_data()
        stream = io.BytesIO()
        with xlsxwriter.Workbook(stream, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False}) as book:
            header = book.add_format({"bold": True, "bg_color": "#E8EDF4", "text_wrap": True, "valign": "top"})
            text = book.add_format({"text_wrap": True, "valign": "top"})
            def sheet(name, columns, rows):
                ws = book.add_worksheet(name)
                ws.freeze_panes(1, 0)
                widths = [100 if title == "Giá trị" else 40 if title == "Thông tin" else
                    60 if title.startswith(("Bằng chứng", "Lý do")) else 28 for title in columns]
                ws.set_row(0, 32)
                for col, title in enumerate(columns):
                    ws.write_string(0, col, title, header)
                    ws.set_column(col, col, widths[col])
                for row, values in enumerate(rows, 1):
                    for col, value in enumerate(values):
                        ws.write_string(row, col, str(value), text)
                    lines = max(sum(max(1, ceil(len(part)/widths[col])) for part in str(value).split("\n")) for col, value in enumerate(values))
                    ws.set_row(row, min(400, 15*lines+6))
                if rows: ws.autofilter(0, 0, len(rows), len(columns)-1)
                ws.set_landscape(); ws.fit_to_pages(1, 0); ws.repeat_rows(0)
                return ws
            sheet("Tổng quan", ["Thông tin", "Giá trị"], [
                ["Báo giá", report["quote"]], ["Bản kiểm tra", report["review_id"]], ["Thời điểm kiểm tra", report["checked_at"]],
                ["Người kiểm tra", report["owner"]], ["Bản trước", report["previous_id"]], ["Thời điểm bản trước", report["previous_checked_at"]],
                ["Thời điểm xuất", report["exported_at"]], ["Người xuất", report["exported_by"]], ["Múi giờ", report["timezone"]],
                ["Nguồn tại lúc xuất", report["source_notice"]], ["Số mã cờ trong bản này", report["current_count"]],
                ["Chưa ghi nhận / cần sửa / cần quản lý xem", report["attention_count"]],
                ["Cách đếm", "Theo mã cảnh báo; cùng mã ở nhiều dòng chỉ tính một cờ."],
                ["Trạng thái diễn giải AI", report["ai_state"]], ["Diễn giải AI đã lưu", report["ai_explanation"]], ["Thông báo AI", report["ai_error"]],
                ["Phạm vi lịch sử", "Bản đang xuất và bản trước được liên kết; nhận xét hai bản được giữ riêng."], ["Giới hạn", report["notice"]]])
            keys = ["code", "label", "level", "change", "before", "after", "previous_decision", "previous_reason", "decision", "reason", "actor", "recorded_at"]
            sheet("Đối chiếu", ["Mã cờ", "Cảnh báo", "Mức cần xem", "Trước/sau", "Bằng chứng trước", "Bằng chứng bản này", "Ghi nhận bản trước", "Lý do bản trước", "Ghi nhận bản này", "Lý do bản này", "Người ghi bản này", "Thời điểm bản này"],
                [[row[k] for k in keys] for row in report["rows"]])
            sheet("Lịch sử", ["Bản kiểm tra", "Mã cờ", "Cảnh báo", "Ghi nhận", "Lý do", "Người ghi", "Thời điểm"],
                [[event[k] for k in ("review_id", "code", "label", "decision", "reason", "actor", "recorded_at")] for event in report["history"]])
        return stream.getvalue()


class RiskPdfReport(models.AbstractModel):
    _name = "report.olist_sales_ai.risk_report_document"
    _description = "Báo cáo đối chiếu rủi ro báo giá"

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["olist.ai.quote.risk.review"].browse(docids)
        docs.ensure_one()
        return {"doc_ids": docs.ids, "doc_model": docs._name, "docs": docs, "report": docs._risk_report_data()}
