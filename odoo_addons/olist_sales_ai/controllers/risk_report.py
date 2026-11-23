from odoo import http
from odoo.http import content_disposition, request
from odoo.exceptions import AccessError, MissingError, UserError
from werkzeug.exceptions import BadRequest, NotFound


class RiskReportController(http.Controller):
    @http.route("/olist-sales-ai/risk/<int:review_id>/xlsx", type="http", auth="user", methods=["GET"], readonly=True)
    def download(self, review_id, **kwargs):
        try:
            review = request.env["olist.ai.quote.risk.review"].browse(review_id).exists()
            if not review: raise NotFound()
            content = review._risk_xlsx_bytes()
        except (AccessError, MissingError):
            raise NotFound() from None
        except UserError as exc:
            raise BadRequest(str(exc)) from None
        return request.make_response(content, headers=[
            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Disposition", content_disposition(f"olist-rui-ro-{review.id}.xlsx")),
            ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")])
