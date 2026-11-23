from copy import deepcopy
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from test_sales import adapter, client
from test_sales_pricing import financial, body
from olist.api import app
from olist import erp


@pytest.fixture
def quotation(client, financial):
    action = client.post("/actions", json=body()).json()
    assert client.post(f"/actions/{action['id']}/approve").status_code == 200
    financial.calls.clear()
    return financial.orders[99]


def pdf_text(response):
    assert response.status_code == 200, response.text if response.status_code != 200 else ""
    assert response.content.startswith(b"%PDF-")
    reader = PdfReader(BytesIO(response.content))
    return reader, "\n".join(page.extract_text() for page in reader.pages)


def test_pdf_reads_native_discount_tax_totals_and_vietnamese_without_writes(client, financial, quotation):
    before = erp.list_actions()
    response = client.get("/erp/quotations/99/pdf")
    _, text = pdf_text(response)
    for expected in ["BÁO GIÁ S00099", "DEMO Khách", "90.00 BRL", "9.00 BRL", "99.00 BRL", "10.00", "Tax 101"]:
        assert expected in text
    assert response.headers["content-disposition"] == 'attachment; filename="bao_gia_99.pdf"'
    assert response.headers["cache-control"] == "no-store"
    assert erp.list_actions() == before
    assert all(method in {"search_read"} for _, method, _, _ in financial.calls)
    assert quotation["state"] == "draft"


def test_pdf_paginates_long_quotes_escapes_text_and_preserves_document_rounding(client, financial, quotation):
    line = deepcopy(quotation["lines"][0])
    line["name"] = "Dịch vụ <b>chưa định dạng</b> & kiểm tra tiếng Việt " * 3
    quotation["lines"] = [deepcopy(line) for _ in range(90)]
    quotation.update(amount_untaxed=8100, amount_tax=810.01, amount_total=8910.01)
    reader, text = pdf_text(client.get("/erp/quotations/99/pdf"))
    assert len(reader.pages) > 2
    assert "<b>chưa định dạng</b>" in text
    assert "8,910.01 BRL" in text and "Chênh lệch làm tròn tổng theo Odoo: 0.01 BRL" in text
    assert all("Sản phẩm / dịch vụ" in page.extract_text() for page in reader.pages[:-1])


@pytest.mark.parametrize("state", ["sale", "cancel"])
def test_pdf_rejects_non_quotation_states(client, quotation, state):
    quotation["state"] = state
    assert client.get("/erp/quotations/99/pdf").status_code == 422


def test_pdf_auth_scope_and_truncated_lines(client, financial, quotation):
    assert TestClient(app).get("/erp/quotations/99/pdf").status_code == 401
    assert client.get("/erp/quotations/100/pdf").status_code == 422
    assert client.get("/erp/quotations/0/pdf").status_code == 422
    quotation["lines"] *= 501
    assert client.get("/erp/quotations/99/pdf").status_code == 422

