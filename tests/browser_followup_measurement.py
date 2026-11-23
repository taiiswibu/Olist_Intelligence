"""Explicit browser QA in a database created by test_odoo_ai.py --keep-database only."""
import argparse
import json
import secrets
import sys
import xmlrpc.client
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from olist import followup_trials

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".openai/qa"
URL = "http://127.0.0.1:8069"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    marker = "QA_DATABASE=" + args.database
    setup_log = OUT / "measurement-native-browser-setup.log"
    assert args.database.startswith("olist_ai_test_") and marker in setup_log.read_text(encoding="utf-8")
    common = xmlrpc.client.ServerProxy(URL + "/xmlrpc/2/common")
    models = xmlrpc.client.ServerProxy(URL + "/xmlrpc/2/object")
    admin = common.authenticate(args.database, "admin", "admin", {})
    assert admin, "Disposable database authentication failed"
    def admin_call(model, method, *values, **kw):
        return models.execute_kw(args.database, admin, "admin", model, method, list(values), kw)
    def xmlid(name):
        module, record = name.split(".")
        return admin_call("ir.model.data", "search_read", [["module", "=", module], ["name", "=", record]], fields=["res_id"])[0]["res_id"]
    password = secrets.token_urlsafe(28)
    group = xmlid("sales_team.group_sale_salesman")
    fields = admin_call("res.users", "fields_get", ["group_ids", "groups_id"])
    group_field = "group_ids" if "group_ids" in fields else "groups_id"
    for index in range(3):
        login = "qa_measure_" + secrets.token_hex(5)
        user = admin_call("res.users", "create", {"name": "Measurement browser fixture", "login": login, "password": password,
            group_field: [[6, 0, [group]]]}, context={"no_reset_password": True, "mail_create_nosubscribe": True})
        if user % 3 == 0: break  # First cyclic assignment must be manual: no production backend fixtures.
    assert user % 3 == 0
    partner = admin_call("res.partner", "create", {"name": "Measurement test customer", "ref": "OLIST-DEMO:browser-measurement"})
    product = admin_call("product.product", "create", {"name": "Measurement test service", "type": "service"})
    quote = admin_call("sale.order", "create", {"partner_id": partner, "user_id": user, "origin": "OLIST-TEST:measurement-browser",
        "order_line": [[0, 0, {"product_id": product, "product_uom_qty": 1, "price_unit": 100, "tax_ids": [[5, 0, 0]]}]]})
    quote_name = admin_call("sale.order", "read", [quote], fields=["name"])[0]["name"]
    def call(model, method, *values, **kw):
        return models.execute_kw(args.database, user, password, model, method, list(values), kw)
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        auth = context.request.post(URL + "/web/session/authenticate", data={"jsonrpc": "2.0", "params": {
            "db": args.database, "login": login, "password": password}}).json()
        assert auth.get("result", {}).get("uid") == user
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        page.goto(URL + "/odoo/action-" + str(xmlid("olist_sales_ai.queue_action")))
        target = page.locator(".o_list_view .o_data_row").filter(has_text=quote_name).first
        target.wait_for(timeout=60000)
        target.get_by_role("button", name="Bắt đầu lượt đo", exact=True).click()
        page.locator(".o_form_view [name=trial_method]").wait_for(timeout=30000)
        assert "Soạn tay" in page.locator("[name=trial_method]").inner_text()
        review = call("olist.ai.followup.review", "search_read", [["order_id", "=", quote]],
                      fields=["id", "trial_started_at", "trial_finished_at", "state", "activity_id", "trace"])[0]
        assert review["state"] == "ready" and not review["activity_id"] and not review["trial_finished_at"]
        assert json.loads(review["trace"])["strategy"] == "manual"
        resumed = call("sale.order", "action_olist_measure", [quote])
        assert resumed["res_id"] == review["id"]
        page.locator("[name=summary] input").fill("Rà soát lịch chăm sóc")
        page.locator("[name=note] textarea").fill("Kiểm tra báo giá và chuẩn bị nội dung trao đổi với khách.")
        page.evaluate("document.querySelector('.o_content')?.scrollTo(0, 0)")
        page.screenshot(path=str(OUT / "measurement-ready-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(OUT / "measurement-ready-mobile.png"), full_page=True)
        page.locator("[name=note]").scroll_into_view_if_needed()
        page.screenshot(path=str(OUT / "measurement-note-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.locator("[name=approval_checked] input").check()
        page.get_by_role("button", name="Duyệt tạo việc", exact=True).click()
        page.locator(".modal-dialog").get_by_role("button", name="Ok", exact=True).click()
        page.wait_for_function("!document.querySelector('.modal-dialog')", timeout=15000)
        page.locator(".o_form_view [name=trial_method]").wait_for(state="detached", timeout=15000)
        approved = call("olist.ai.followup.review", "read", [review["id"]], fields=["state", "activity_id", "trial_finished_at", "trial_outcome"])[0]
        assert approved["state"] == approved["trial_outcome"] == "approved" and approved["trial_finished_at"]
        assert approved["activity_id"]
        assert call("sale.order", "read", [quote], fields=["state"])[0]["state"] == "draft"
        page.goto(URL + "/odoo/action-" + str(xmlid("olist_sales_ai.trials_action")))
        target = page.locator(".o_data_row").filter(has_text=quote_name).first
        target.wait_for(timeout=30000)
        target.locator(".o_list_record_selector input").check()
        with page.expect_download(timeout=15000) as download:
            page.get_by_role("button", name="Tải CSV lượt đo", exact=True).click()
        output = OUT / "measurement-browser-fixture.csv"
        download.value.save_as(output)
        metrics = followup_trials.summarize(output)
        assert metrics["trials"] == 1 and metrics["methods"]["manual"]["outcomes"] == {"approved": 1}
        assert not metrics["benefit_claim_ready"]
        assert "Measurement test customer" not in output.read_text(encoding="utf-8-sig")
        assert not errors
        context.close(); browser.close()
    report = {"database": args.database, "kind": "automated_test_fixture_not_human_pilot", "manual_trial_browser": True,
        "resume_keeps_same_trial": True, "explicit_approval_creates_activity": True, "quotation_still_draft": True,
        "private_csv_download_parsed": True, "customer_text_omitted": True, "desktop_mobile_screenshots": True,
        "javascript_errors": errors, "human_ratings_collected": 0}
    (OUT / "measurement-browser-qa.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
