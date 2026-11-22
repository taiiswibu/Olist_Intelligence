from io import BytesIO
import json
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader

from olist import analytics, database, erp, reporting
from olist.api import app


@pytest.fixture
def client(db, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Reports must not call Odoo or cloud models")
    monkeypatch.setattr(erp, "Odoo", forbidden)
    from olist import llm
    monkeypatch.setattr(llm, "complete", forbidden)
    return TestClient(app, headers={"X-App-Token": "local-test-token"})


def create(client, **changes):
    payload = {"title": "Báo cáo thử nghiệm", "filters": {"start": "2018-01-01", "end": "2018-01-31"}, **changes}
    response = client.post("/report-drafts", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def definition(report, **changes):
    return {**{k: report[k] for k in ("title", "filters", "notes", "charts", "include_tables", "version")}, **changes}


def test_draft_uses_tools_and_preserves_snapshot_on_note_edit(client, monkeypatch):
    report = create(client)
    assert report["snapshot"]["kpis"]["values"]["product_gmv"] == 70
    assert report["snapshot"]["kpis"]["values"]["late_delivery_rate"] == .5
    original = report["snapshot"]
    monkeypatch.setattr(analytics, "kpis", lambda *a: pytest.fail("Note edits must not silently refresh figures"))
    response = client.put("/report-drafts/" + report["id"], json=definition(report, notes="Nhận xét đã sửa"))
    assert response.status_code == 200
    saved = response.json()
    assert saved["version"] == 2 and saved["snapshot"] == original
    assert client.get("/report-drafts/" + report["id"]).json() == saved
    assert client.get("/report-drafts").json()[0]["title"] == report["title"]
    assert erp.list_actions() == []


def test_change_filters_requeries_but_stale_update_is_rejected(client):
    report = create(client)
    payload = definition(report, filters={"start": "2018-01-01", "end": "2018-01-31", "state": "RJ"})
    response = client.put("/report-drafts/"+report["id"], json=payload)
    assert response.status_code == 200
    saved = response.json()
    assert saved["snapshot"]["kpis"]["values"]["orders"] == 1
    assert saved["snapshot"]["kpis"]["values"]["product_gmv"] == 0
    assert saved["snapshot"]["kpis"]["values"]["late_delivery_rate"] is None
    assert client.put("/report-drafts/"+report["id"], json=payload).status_code == 409
    assert client.get("/report-drafts/"+report["id"]).json()["version"] == 2


def test_exports_are_real_files_with_charts_unicode_and_literal_notes(client, monkeypatch):
    report = create(client, title="Báo cáo giao trễ Việt Nam", notes='=HYPERLINK("https://example.test")\n<script>Nhận xét</script>')
    monkeypatch.setattr(analytics, "kpis", lambda *a: pytest.fail("Downloads must use the saved snapshot"))
    excel = client.get(f"/report-drafts/{report['id']}/export/xlsx")
    assert excel.status_code == 200 and "attachment" in excel.headers["content-disposition"]
    workbook = load_workbook(BytesIO(excel.content))
    assert workbook["Bao cao"]["A1"].value == report["title"]
    notes = workbook["Bao cao"]["B7"]
    assert notes.value == report["notes"] and notes.data_type == "s"
    assert workbook["Bieu do 1"]["B3"].value == 70
    with ZipFile(BytesIO(excel.content)) as archive:
        assert len([n for n in archive.namelist() if n.startswith("xl/charts/chart") and n.endswith(".xml")]) == 2
        assert b"<f>HYPERLINK" not in archive.read("xl/worksheets/sheet1.xml")
    pdf = client.get(f"/report-drafts/{report['id']}/export/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    reader = PdfReader(BytesIO(pdf.content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert report["title"] in text and "R$ 70.00" in text
    assert "GMV theo tháng" in text and "GMV theo ngành hàng" in text
    assert "<script>Nhận xét</script>" in text and "SELECT COUNT(*)" in text
    assert all("/Annots" not in page for page in reader.pages)


def test_null_rate_stays_missing_in_exports_and_empty_scope_is_explicit(client):
    spec = {"kind": "monthly", "metric": "late_rate", "chart_type": "line", "title": "Tỷ lệ trễ"}
    report = create(client, filters={"start": "2018-01-01", "end": "2018-01-31", "state": "RJ"}, charts=[spec])
    response = client.get(f"/report-drafts/{report['id']}/export/xlsx")
    workbook = load_workbook(BytesIO(response.content))
    assert workbook["Bieu do 1"]["B3"].value is None
    pdf = client.get(f"/report-drafts/{report['id']}/export/pdf")
    text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf.content)).pages)
    assert "Chưa đủ dữ liệu để vẽ biểu đồ." in text


def test_import_chat_uses_stored_scope_and_labels_incomplete_source(client):
    from olist.agent_team import _storage
    run = "a"*32
    filters = {"start": "2018-01-01", "end": "2018-01-31", "state": "SP"}
    result = {"status": "incomplete", "answer": "Cần đối chiếu thêm tài liệu.", "filters": filters,
              "evidence": [{"tool": "business_kpis", "result": {}}]}
    with _storage() as conn:
        conn.execute("INSERT INTO team_runs VALUES (?,?,?,?,?)", (run, "b"*32, "hash", json.dumps(result), database.now()))
        conn.execute("INSERT INTO team_turns VALUES (?,?,?,?,?,?)", (run, "b"*32, "KPI tháng một", "answer", json.dumps(filters), database.now()))
    report = create(client, source_run_id=run, filters={"start": "2018-02-01", "end": "2018-02-28"})
    assert report["filters"] == filters
    assert report["source"]["status"] == "incomplete" and report["source"]["filters"] == filters
    assert report["notes"] == result["answer"]
    assert report["snapshot"]["kpis"]["values"]["product_gmv"] == 70
    text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(client.get(f"/report-drafts/{report['id']}/export/pdf").content)).pages)
    assert "Chat nguồn chưa hoàn tất" in text


@pytest.mark.parametrize("changes", [
    {"snapshot": {"kpis": {"product_gmv": 999}}},
    {"charts": [{"kind": "category", "metric": "late_rate", "chart_type": "bar"}]},
    {"charts": [{"kind": "state", "metric": "orders", "chart_type": "line"}]},
    {"charts": [{"kind": "monthly", "metric": "profit", "chart_type": "line"}]},
    {"notes": "bad\x00text"}, {"title": " "},
])
def test_invalid_report_requests_are_rejected(client, changes):
    assert client.post("/report-drafts", json=changes).status_code == 422
    assert client.get("/report-drafts").json() == []


def test_auth_csrf_missing_reports_and_missing_chat(client):
    anonymous = TestClient(app)
    assert anonymous.get("/report-drafts").status_code == 401
    anonymous.post("/session", json={"key": "local-test-token"})
    assert anonymous.post("/report-drafts", json={}).status_code == 403
    assert anonymous.post("/report-drafts", json={}, headers={"X-Olist-Request": "1", "Origin": "https://evil.test"}).status_code == 403
    assert client.get("/report-drafts/missing").status_code == 404
    assert client.get("/report-drafts/missing/export/pdf").status_code == 404
    assert client.post("/report-drafts", json={"source_run_id": "c"*32}).status_code == 422
