"""Browser regression in a disposable database owned by the native test runner."""
import argparse
import json
import re
import secrets
import xmlrpc.client
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".openai/qa"
URL = "http://127.0.0.1:8069"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--setup-log", choices=["risk-native-browser-setup.log", "risk-handling-native-setup.log"], default="risk-native-browser-setup.log")
    args = parser.parse_args()
    assert re.fullmatch(r"olist_ai_test_[a-f0-9]{10}", args.database)
    assert "QA_DATABASE="+args.database in (OUT/args.setup_log).read_text(encoding="utf-8")
    common = xmlrpc.client.ServerProxy(URL+"/xmlrpc/2/common")
    models = xmlrpc.client.ServerProxy(URL+"/xmlrpc/2/object")
    admin = common.authenticate(args.database, "admin", "admin", {})
    assert admin
    def rpc(uid, password, model, method, *values, **kw):
        return models.execute_kw(args.database, uid, password, model, method, list(values), kw)
    def root(model, method, *values, **kw): return rpc(admin, "admin", model, method, *values, **kw)
    def xmlid(name):
        module, name = name.split(".")
        return root("ir.model.data", "search_read", [["module", "=", module], ["name", "=", name]], fields=["res_id"])[0]["res_id"]
    password = secrets.token_urlsafe(28)
    login = "qa_risk_"+secrets.token_hex(5)
    user_fields = root("res.users", "fields_get", ["group_ids", "groups_id"])
    group_field = "group_ids" if "group_ids" in user_fields else "groups_id"
    user = root("res.users", "create", {"name": "Risk browser fixture", "login": login, "password": password,
        group_field: [[6, 0, [xmlid("sales_team.group_sale_salesman")]]]}, context={"no_reset_password": True})
    partner = root("res.partner", "create", {"name": "Risk browser customer fixture", "ref": "OLIST-DEMO:browser-risk"})
    product = root("product.product", "create", {"name": "Risk browser service fixture", "type": "service"})
    quote = root("sale.order", "create", {"partner_id": partner, "user_id": user, "origin": "OLIST-TEST:browser-risk",
        "validity_date": False, "payment_term_id": False,
        "order_line": [[0, 0, {"product_id": product, "product_uom_qty": 1, "price_unit": 100, "discount": 10, "tax_ids": [[5, 0, 0]]}]]})
    quote_fields = ["state", "write_date", "amount_total", "activity_ids", "invoice_ids", "order_line"]
    before = root("sale.order", "read", [quote], fields=quote_fields)[0]
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        auth = context.request.post(URL+"/web/session/authenticate", data={"jsonrpc": "2.0", "params": {
            "db": args.database, "login": login, "password": password}}).json()
        assert auth.get("result", {}).get("uid") == user
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(URL+f"/odoo/sales/{quote}")
        page.get_by_role("button", name="Kiểm tra rủi ro", exact=True).click(timeout=60000)
        page.locator(".o_form_view [name=findings_html]").wait_for(timeout=30000)
        findings = page.locator("[name=findings_html]").inner_text()
        for label in ["Chưa đặt hạn hiệu lực", "Có chiết khấu cần đối chiếu", "Có dòng chưa chọn thuế"]:
            assert label in findings
        assert "10.0%" in findings
        page.get_by_role("button", name="AI gợi ý câu hỏi đối chiếu", exact=True).wait_for()
        assert root("sale.order", "read", [quote], fields=quote_fields)[0] == before
        review = rpc(user, password, "olist.ai.quote.risk.review", "search_read", [["order_id", "=", quote]], fields=["id", "stale", "job_started"])[0]
        assert not review["stale"] and not review["job_started"]
        page.get_by_role("button", name="Ghi nhận xử lý", exact=True).click()
        dialog = page.locator(".modal-dialog")
        row = dialog.locator(".o_data_row").filter(has_text="Có dòng chưa chọn thuế")
        row.locator("[name=decision]").click()
        row.locator("[name=decision] input").click()
        page.locator(".o_select_menu_item").filter(has_text="Đúng chủ đích").click()
        row.locator("textarea").fill("Fixture: đã đối chiếu với người phụ trách cấu hình")
        dialog.get_by_role("button", name="Lưu ghi nhận", exact=True).click()
        page.locator(".modal-dialog").wait_for(state="detached", timeout=15000)
        page.wait_for_function("document.querySelector('[name=findings_html]')?.textContent.includes('Fixture: đã đối chiếu')")
        assert "Đúng chủ đích" in page.locator("[name=findings_html]").inner_text()
        page.screenshot(path=str(OUT/"risk-handling-desktop.png"), full_page=True)
        events = rpc(user, password, "olist.ai.quote.risk.decision", "search_read", [["review_id", "=", review["id"]]], fields=["actor_id", "decision", "reason"])
        assert len(events) == 1 and events[0]["actor_id"][0] == user and events[0]["decision"] == "intentional"
        assert root("sale.order", "read", [quote], fields=quote_fields)[0] == before
        page.get_by_role("tab", name="Lịch sử xử lý", exact=True).click()
        assert "Fixture: đã đối chiếu" in page.locator("[name=decision_ids]").inner_text()
        page.set_viewport_size({"width": 390, "height": 844})
        page.reload()
        page.locator(".o_form_view [name=findings_html]").wait_for(timeout=30000)
        page.screenshot(path=str(OUT/"risk-handling-mobile.png"), full_page=True)
        # Open through the mobile toolbar; Odoo selects its native kanban view.
        handle_button = page.get_by_role("button", name="Ghi nhận xử lý", exact=True)
        if not handle_button.is_visible():
            page.locator(".o_statusbar_buttons .dropdown-toggle").click()
        handle_button.click()
        mobile_dialog = page.locator(".modal-dialog")
        mobile_dialog.locator(".o_kanban_record").filter(has_text="Có dòng chưa chọn thuế").wait_for(timeout=30000)
        page.screenshot(path=str(OUT/"risk-handling-dialog-mobile.png"), full_page=True)
        card = mobile_dialog.locator(".o_kanban_record").filter(has_text="Có dòng chưa chọn thuế")
        card.click()
        child = page.locator(".modal-dialog").last
        child.locator("[name=reason] textarea").fill("Fixture: đã đối chiếu bằng màn hình nhỏ")
        child.get_by_role("button", name=re.compile(r"^Save(?: & Close)?$")).click()
        page.wait_for_function("document.querySelectorAll('.modal-dialog').length === 1", timeout=15000)
        page.get_by_role("button", name="Lưu ghi nhận", exact=True).click()
        page.wait_for_function("document.querySelector('[name=findings_html]')?.textContent.includes('Fixture: đã đối chiếu bằng màn hình nhỏ')", timeout=15000)
        assert "Fixture: đã đối chiếu bằng màn hình nhỏ" in page.locator("[name=findings_html]").inner_text()
        page.set_viewport_size({"width": 1440, "height": 1000})
        root("sale.order.line", "write", before["order_line"], {"discount": 0, "product_uom_qty": 0})
        page.reload()
        page.get_by_text("Nguồn đã đổi.", exact=False).wait_for(timeout=30000)
        assert page.get_by_role("button", name="AI gợi ý câu hỏi đối chiếu", exact=True).count() == 0
        assert page.get_by_role("button", name="Ghi nhận xử lý", exact=True).count() == 0
        assert "10.0%" in page.locator("[name=findings_html]").inner_text()
        page.get_by_role("button", name="Kiểm tra lại", exact=True).click()
        page.wait_for_function("document.querySelector('[name=findings_html]')?.textContent.includes('Có số lượng không dương')")
        assert "Đúng chủ đích" not in page.locator("[name=findings_html]").inner_text()
        page.get_by_role("tab", name="Trước/sau", exact=True).click()
        comparison = page.locator("[name=comparison_html]").inner_text()
        for label in ["Vẫn xuất hiện", "Mới xuất hiện", "Không còn xuất hiện", "Trước:", "Sau:"]:
            assert label in comparison
        page.locator("[name=comparison_html]").scroll_into_view_if_needed()
        page.screenshot(path=str(OUT/"risk-comparison-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("[name=comparison_html]").scroll_into_view_if_needed()
        page.screenshot(path=str(OUT/"risk-comparison-mobile.png"), full_page=True)
        reviews = rpc(user, password, "olist.ai.quote.risk.review", "search_read", [["order_id", "=", quote]], fields=["id", "job_started", "previous_review_id", "decision_ids"], order="id desc")
        assert len(reviews) == 2 and not any(r["job_started"] for r in reviews)
        assert reviews[0]["previous_review_id"][0] == review["id"] and not reviews[0]["decision_ids"]
        assert not errors, errors
        context.close(); browser.close()
    report = {"kind": "automated_test_fixture_not_customer_data", "local_flags_visible": True,
        "quotation_unchanged_by_checks": True, "stale_source_warning": True, "recheck_preserves_history": True,
        "human_disposition_saved": True, "disposition_history_visible": True, "new_review_unacknowledged": True, "three_comparison_categories": True,
        "mobile_card_edit_saved": True,
        "desktop_mobile": True, "model_calls": 0, "javascript_errors": errors}
    (OUT/"risk-browser-qa.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__": main()
