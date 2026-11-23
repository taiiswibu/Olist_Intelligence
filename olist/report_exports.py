"""PDF and Excel exports of a saved report snapshot. No model or ERP calls."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from .reporting import DIMENSIONS, KINDS, LABELS, formatted, series


def warnings(report):
    notes = []
    if not report["snapshot"]["kpis"]["values"]["orders"]:
        notes.append("Không có đơn hàng trong phạm vi đã chọn. Không diễn giải các số không là doanh thu hiện tại.")
    source = report.get("source")
    if source and source["status"] != "complete":
        notes.append("Chat nguồn chưa hoàn tất. Số liệu dưới đây được truy vấn lại; nhận xét cần rà soát.")
    if source and source.get("filters") != report["filters"]:
        notes.append("Bộ lọc khác cuộc chat nguồn; cần kiểm tra lại nhận xét trước khi sử dụng.")
    return notes


def excel(report):
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = Workbook()
    overview = workbook.active
    overview.title = "Bao cao"
    scope = report["filters"]
    overview.append([report["title"]])
    for row in [("Từ ngày", scope["start"]), ("Đến ngày", scope["end"]), ("Bang", scope.get("state") or "Tất cả"),
                ("Chụp số liệu (UTC)", report["snapshot"]["generated_at"]), ("Bản lưu", report["version"]),
                ("Nhận xét có thể chỉnh sửa", report["notes"])]:
        overview.append(row)
    for text in warnings(report):
        overview.append(["Cần rà soát", text])
    overview.append([])
    overview.append(["KPI", "Giá trị", "Đơn vị"])
    for key, value in report["snapshot"]["kpis"]["values"].items():
        overview.append([LABELS.get(key, key), value, "BRL" if key in {"product_gmv", "freight", "product_aov"} else "Tỷ lệ" if "rate" in key else "Đơn"])
        overview.cell(overview.max_row, 2).number_format = '0.00%' if "rate" in key else '#,##0.00' if key in {"product_gmv", "freight", "product_aov"} else '#,##0'

    for index, spec in enumerate(report["charts"], 1):
        sheet = workbook.create_sheet(f"Bieu do {index}")
        sheet.append([spec["title"]])
        sheet.append([LABELS[DIMENSIONS[spec["kind"]]], LABELS[spec["metric"]]])
        points = series(report, spec)
        for label, value in points:
            sheet.append([label, value])
            sheet.cell(sheet.max_row, 2).number_format = '0.00%' if "rate" in spec["metric"] else '#,##0.00' if spec["metric"] == "product_gmv" else '#,##0'
        if points and any(value is not None for _, value in points):
            chart = LineChart() if spec["chart_type"] == "line" else BarChart()
            chart.title, chart.y_axis.title = spec["title"], LABELS[spec["metric"]]
            chart.legend = None
            chart.add_data(Reference(sheet, min_col=2, min_row=2, max_row=2 + len(points)), titles_from_data=True)
            chart.set_categories(Reference(sheet, min_col=1, min_row=3, max_row=2 + len(points)))
            chart.display_blanks = "gap"
            if "rate" in spec["metric"]:
                chart.y_axis.numFmt = '0.0%'
            chart.width, chart.height = 24, 13
            sheet.add_chart(chart, "E2")
        else:
            sheet.append(["Chưa đủ dữ liệu để vẽ biểu đồ."])
        if report["include_tables"] and points:
            sheet.append([])
            rows = report["snapshot"]["datasets"][spec["kind"]]["rows"]
            keys = list(rows[0])
            sheet.append([LABELS.get(key, key) for key in keys])
            for row in rows:
                sheet.append([row[key] for key in keys])

    sources = workbook.create_sheet("Nguon")
    sources.append(["Nguồn", "Nội dung"])
    for text in report["limits"]:
        sources.append(["Phạm vi / giới hạn", text])
    sources.append(["Định nghĩa", report["snapshot"]["kpis"]["definition"]])
    sources.append(["Bộ lọc", str(scope)])
    for name, data in [("KPI", report["snapshot"]["kpis"]), *report["snapshot"]["datasets"].items()]:
        sources.append([f"SQL {name}", data["sql"]])
    if report.get("source"):
        source = report["source"]
        sources.append(["Câu hỏi gốc", source["question"]])
        sources.append(["Trạng thái chat gốc", source["status"]])
        sources.append(["Bộ lọc chat gốc", str(source["filters"])])
        for doc in source["documents"]:
            sources.append([f"{doc['source']} · {doc['id']}", doc["text"]])
    for sheet in workbook:
        sheet.freeze_panes = "A3"
        sheet.column_dimensions["A"].width = 42
        sheet.column_dimensions["B"].width = 70 if sheet.title == "Nguon" else 35
        sheet.row_dimensions[1].height = 28
        for row in sheet:
            for cell in row:
                # All text, including '='-prefixed notes, stays text rather than an Excel formula.
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.font = Font(name="Calibri", size=11, color="173E34")
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for cell in sheet[1]:
            cell.fill = PatternFill("solid", fgColor="173E34")
            cell.font = Font(name="Calibri", size=12, bold=True, color="FFFFFF")
        if sheet.title == "Bao cao":
            sheet.row_dimensions[7].height = 105
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


@lru_cache(maxsize=1)
def pdf_font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    candidates = [Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                  Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf")]
    for path in candidates:
        if path.is_file():
            pdfmetrics.registerFont(TTFont("OlistReport", str(path)))
            return "OlistReport"
    raise ValueError("Chưa có font tiếng Việt cho PDF. Cần Arial hoặc DejaVu Sans trên máy chạy ứng dụng.")


def pdf(report):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
    from reportlab.graphics.shapes import Drawing, Line, Rect, String, Circle

    font = pdf_font()
    ink, green = colors.HexColor("#173E34"), colors.HexColor("#427759")
    normal = ParagraphStyle("report", fontName=font, fontSize=9, leading=14, textColor=ink, spaceAfter=7, splitLongWords=True)
    heading = ParagraphStyle("heading", parent=normal, fontSize=15, leading=21, spaceBefore=14, spaceAfter=10, keepWithNext=True)
    small = ParagraphStyle("small", parent=normal, fontSize=7, leading=10)
    def text(value, style=normal):
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), style)
    def table(rows, widths=None):
        grid = Table([[text(v, small) for v in row] for row in rows], colWidths=widths, repeatRows=1, hAlign="LEFT")
        grid.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF1E7")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("LINEBELOW", (0, 0), (-1, -1), .3, colors.HexColor("#DCE6DA"))]))
        return grid

    content = [text("OLIST INTELLIGENCE", small), text(report["title"], heading)]
    scope = report["filters"]
    content += [text(f"{scope['start']} — {scope['end']} · Bang: {scope.get('state') or 'Tất cả'} · BRL"),
                text(f"Số liệu chụp lúc {report['snapshot']['generated_at']} (UTC) · Bản lưu {report['version']}", small)]
    content += [text(note) for note in warnings(report)]
    kpis = report["snapshot"]["kpis"]
    content += [text("Chỉ số chính", heading), table([["Chỉ tiêu", "Giá trị"], *[
        [LABELS.get(key, key), formatted(value, key)] for key, value in kpis["values"].items()]], [280, 235])]
    if report["notes"]:
        content.append(text("Nhận xét có thể chỉnh sửa", heading))
        content += [text(part) for part in report["notes"].split("\n") if part.strip()]
    for spec in report["charts"]:
        points = series(report, spec)
        numeric = [v for _, v in points if v is not None]
        section = [text(spec["title"], heading), text(f"{KINDS[spec['kind']]} · {LABELS[spec['metric']]}", small)]
        if numeric:
            width, height, left, bottom = 515, 230, 70, 50
            drawing = Drawing(width, height)
            maximum = max(max(numeric), 1e-9) * 1.15
            plot_w, plot_h = width-left-15, height-bottom-20
            def x(i): return left + (i + .5) / len(points) * plot_w
            def y(v): return bottom + v / maximum * plot_h
            for tick in range(5):
                value = maximum * tick / 4
                drawing.add(Line(left, y(value), width-10, y(value), strokeColor=colors.HexColor("#E1E9DF"), strokeWidth=.5))
                label = f"{value*100:.1f}%" if "rate" in spec["metric"] else f"{value:,.0f}"
                drawing.add(String(left-5, y(value)-3, label, textAnchor="end", fontName=font, fontSize=7, fillColor=ink))
            previous = None
            for index, (label, value) in enumerate(points):
                if value is None:
                    previous = None
                    continue
                if spec["chart_type"] == "bar":
                    bar_w = plot_w/len(points)*.7
                    drawing.add(Rect(x(index)-bar_w/2, bottom, bar_w, y(value)-bottom, fillColor=green, strokeColor=None))
                else:
                    if previous:
                        drawing.add(Line(*previous, x(index), y(value), strokeColor=green, strokeWidth=2))
                    drawing.add(Circle(x(index), y(value), 2.5, fillColor=green, strokeColor=None))
                    previous = (x(index), y(value))
                if index % max(1, (len(points)+5)//6) == 0:
                    drawing.add(String(x(index), bottom-17, label[:16], textAnchor="middle", fontName=font, fontSize=6, fillColor=ink))
            section += [drawing, text("Giá trị thiếu không được thay bằng số không. Nhãn dài được rút gọn; xem bảng số liệu.", small)]
        else:
            section.append(text("Chưa đủ dữ liệu để vẽ biểu đồ."))
        content.append(KeepTogether(section))
        if report["include_tables"] and points:
            rows = report["snapshot"]["datasets"][spec["kind"]]["rows"]
            keys = list(rows[0])
            content.append(table([[LABELS.get(key,key) for key in keys], *[[formatted(row[key], key) for key in keys] for row in rows]], [515/len(keys)]*len(keys)))
        content.append(Spacer(1, 8))
    content.append(text("Nguồn và giới hạn", heading))
    content += [text(limit) for limit in report["limits"]]
    content.append(text(kpis["definition"]))
    if report.get("source"):
        source = report["source"]
        content += [text("Câu hỏi nguồn: " + source["question"]), text("Trạng thái chat nguồn: " + source["status"])]
        for doc in source["documents"]:
            content += [text(f"{doc['source']} · {doc['section']} · {doc['id']}", small), text(doc["text"], small)]
    for name, data in [("KPI", kpis), *report["snapshot"]["datasets"].items()]:
        content += [text("Truy vấn " + name, small), text(data["sql"], small), text(str(data["filters"]), small)]
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=38, bottomMargin=38, title=report["title"], author="Olist Intelligence")
    def footer(canvas, doc):
        canvas.setFont(font, 7)
        canvas.setFillColor(ink)
        canvas.drawString(40, 22, "Olist · Dữ liệu lịch sử · CC BY-NC-SA 4.0")
        canvas.drawRightString(A4[0]-40, 22, f"Trang {doc.page}")
    document.build(content, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
