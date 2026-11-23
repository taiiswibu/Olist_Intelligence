"""Download a quotation using live Odoo reads only; no attachments or ERP writes."""
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from . import sales
from .report_exports import pdf_font


def _quotation(client, order_id):
    order = sales.order_detail(client, order_id)
    if order["state"] not in {"draft", "sent"}:
        raise ValueError("Chỉ tải báo giá nháp hoặc đã gửi. Đọc lại trạng thái trên Odoo.")
    if order["lines_truncated"]:
        raise ValueError("Báo giá quá 500 dòng; chưa thể xuất đầy đủ trong bản local.")
    return order


def document(client, order_id):
    order = _quotation(client, order_id)
    return {"order_id": order["id"], "name": order["name"], "state": order["state"],
            "currency": order["currency_id"][1], "subtotal": order["amount_untaxed"],
            "tax": order["amount_tax"], "total": order["amount_total"],
            "download_path": f"/erp/quotations/{order['id']}/pdf"}


def pdf(client, order_id):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle, KeepTogether

    order = _quotation(client, order_id)
    partner = sales.record(client, "partners", order["partner_id"][0])
    currency = order["currency_id"][1]
    font = pdf_font()
    text = ParagraphStyle("Quote", fontName=font, fontSize=9, leading=13, textColor=colors.HexColor("#173E34"))
    title = ParagraphStyle("Title", parent=text, fontSize=22, leading=28, spaceAfter=12)
    right = ParagraphStyle("Right", parent=text, alignment=TA_RIGHT)
    small = ParagraphStyle("Small", parent=text, fontSize=8, leading=11)

    def paragraph(value, style=text):
        return Paragraph(escape(str(value or "")).replace("\n", "<br/>"), style)

    def money(value):
        return f"{sales.amount(value):,.2f} {currency}"

    company = order.get("company_id")
    story = [paragraph("BÁO GIÁ " + order["name"], title),
             paragraph((company[1] + " · " if company else "") + ("Nháp" if order["state"] == "draft" else "Đã gửi")),
             paragraph("Ngày trên Odoo: " + str(order.get("date_order") or "—") + " · Tiền tệ: " + currency),
             Spacer(1, 14), paragraph("Khách hàng: " + partner["name"]),
             paragraph("Mã khách: " + str(partner.get("ref") or "—"))]
    for label, key in [("Địa chỉ", "street"), ("Thành phố", "city"), ("Email", "email"), ("Điện thoại", "phone")]:
        if partner.get(key):
            story.append(paragraph(label + ": " + str(partner[key])))
    story.append(Spacer(1, 16))
    headers = ["Sản phẩm / dịch vụ", "SL", "Đơn giá", "Giảm %", "Thuế", "Trước thuế", "Tiền thuế", "Tổng dòng"]
    data = [[paragraph(h, small) for h in headers]]
    for line in order["lines"]:
        values = [line["name"], format(Decimal(str(line["product_uom_qty"])).normalize(), "f"), money(line["price_unit"]),
                  f"{Decimal(str(line['discount'])):.2f}", ", ".join(line.get("tax_names", [])) or "Không áp thuế",
                  money(line["price_subtotal"]), money(line["price_tax"]), money(line["price_total"])]
        data.append([paragraph(value, small if i in {0, 4} else right) for i, value in enumerate(values)])
    table = LongTable(data, colWidths=[205, 35, 80, 45, 100, 95, 95, 110], repeatRows=1, splitInRow=1, hAlign="LEFT")
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9F1E3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LINEBELOW", (0, 0), (-1, 0), .6, colors.HexColor("#9FB89B")),
        ("LINEBELOW", (0, 1), (-1, -1), .25, colors.HexColor("#DCE6D8"))]))
    story.append(table)
    totals = [paragraph("Sau giảm, trước thuế: " + money(order["amount_untaxed"]), right),
              paragraph("Thuế: " + money(order["amount_tax"]), right),
              paragraph("TỔNG THANH TOÁN: " + money(order["amount_total"]), right)]
    adjustment = sales.amount(order["amount_total"]) - sum((sales.amount(l["price_total"]) for l in order["lines"]), Decimal(0))
    if adjustment:
        totals.append(paragraph("Chênh lệch làm tròn tổng theo Odoo: " + money(adjustment), right))
    story += [Spacer(1, 14), KeepTogether(totals), Spacer(1, 16),
              paragraph("Đơn giá và thuế theo cấu hình Odoo; số tiền trước thuế đã trừ chiết khấu. "
                        "Tổng chứng từ có thể khác tổng từng dòng do làm tròn thuế.", small),
              paragraph("Bản đọc từ Odoo DEMO tại lúc tải.", small)]
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), leftMargin=36, rightMargin=36,
                           topMargin=32, bottomMargin=35, title="Báo giá " + order["name"], author="Olist Intelligence")

    def footer(canvas, document):
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#71816F"))
        canvas.drawString(36, 18, "Olist Intelligence · Báo giá DEMO · " + order["name"])
        canvas.drawRightString(landscape(A4)[0]-36, 18, f"Trang {document.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
