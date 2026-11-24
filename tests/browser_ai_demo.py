"""Opt-in local browser QA and recording. Uses existing data; never approves ERP writes."""
import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from olist.config import ROOT,settings
from olist.erp import Odoo


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record',action='store_true')
    parser.add_argument('--followup-review',type=int,help='Read an existing proposal only; never create or approve it.')
    args=parser.parse_args()
    cfg=settings();odoo=Odoo()
    output=ROOT/'.openai/exports/ai-demo'
    output.mkdir(parents=True,exist_ok=True)
    def counts():return {m:odoo.call(m,'search_count',[[]]) for m in ['sale.order','sale.order.line','account.move','mail.activity']}
    before=counts();errors=[];responses=[]
    review=None
    if args.followup_review:
        review=odoo.call('olist.ai.followup.review','read',[[args.followup_review]],{'fields':['state','order_id','trace','trial_started_at']})[0]
        assert review['state']=='ready' and not review['trial_started_at']
        assert json.loads(review['trace'])['privacy_version']=='followup-plan-minimized-v2'
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        options={'viewport':{'width':1440,'height':1000}}
        if args.record:options.update(record_video_dir=str(output/'recording'),record_video_size={'width':1440,'height':1000})
        context=browser.new_context(**options)
        auth=context.request.post(cfg.api_url+'/session',headers={'Origin':cfg.api_url},data={'key':cfg.app_token})
        assert auth.status==200
        page=context.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        def caption(text):
            page.evaluate("""text=>{let el=document.querySelector('#demo-caption');if(!el){el=document.createElement('div');el.id='demo-caption';el.style.cssText='position:fixed;bottom:8px;left:15%;right:15%;z-index:10000;padding:12px;background:#103c34;color:white;border-radius:8px;text-align:center;font:16px sans-serif;pointer-events:none';document.body.append(el);}el.textContent=text;}""",text)
        page.goto(cfg.api_url+'/#overview')
        page.locator('#sidebar-status').filter(has_text='Dữ liệu sẵn sàng').wait_for(timeout=30000)
        caption('Demo kỹ thuật · Dữ liệu Olist công khai và Odoo DEMO · Không phải đánh giá người dùng')
        page.wait_for_timeout(1800)
        page.locator('.sidebar [data-page=knowledge]').click()
        expect(page.locator('#knowledge-query')).to_be_visible()
        caption('Tra cứu tài liệu: embedding local, tìm nguồn trong kho vector')
        page.locator('#knowledge-query').fill('Giao buổi tối trong đúng ngày hẹn có bị tính trễ không?')
        with page.expect_response(lambda r:r.url.endswith('/rag/answer'),timeout=90000) as response:
            page.locator('#knowledge-form button[type=submit]').click()
        result=response.value.json();responses.append(result)
        expect(page.locator('#knowledge-results')).to_contain_text('Trả lời từ tài liệu')
        assert result['method']=='hybrid_sqlite_vec' and result['generation']=='local_extractive'
        assert result['citations'] and all(q['quote'] in next(s['text'] for s in result['sources'] if s['id']==q['source_id']) for q in result['citations'])
        caption('Câu trả lời trích nguyên văn, có mã nguồn để đối chiếu')
        page.screenshot(path=str(output/'rag-source-desktop.png'),full_page=True)
        page.wait_for_timeout(2200)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        page.screenshot(path=str(output/'rag-source-mobile.png'),full_page=True)
        page.set_viewport_size({'width':1440,'height':1000})
        page.locator('#knowledge-query').fill('Dự báo thời tiết Hà Nội ngày mai thế nào?')
        with page.expect_response(lambda r:r.url.endswith('/rag/answer'),timeout=90000) as response:
            page.locator('#knowledge-form button[type=submit]').click()
        refused=response.value.json();responses.append(refused)
        expect(page.locator('#knowledge-results')).to_contain_text('Chưa đủ bằng chứng')
        assert refused['generation']=='not_called' and not refused['sources']
        caption('Không có bằng chứng: từ chối trả lời, không gọi model sinh nội dung')
        page.screenshot(path=str(output/'rag-refusal.png'),full_page=True)
        page.wait_for_timeout(1800)
        auth=context.request.post(cfg.odoo_url+'/web/session/authenticate',data={'jsonrpc':'2.0','params':{'db':cfg.odoo_db,'login':cfg.odoo_login,'password':cfg.odoo_password}}).json()
        assert auth.get('result',{}).get('uid')
        page.goto(cfg.odoo_url+'/odoo')
        page.locator('.o_navbar_apps_menu button').click(timeout=60000)
        page.locator('.o_app[data-menu-xmlid="olist_sales_ai.root_menu"]').click()
        page.locator('.o_list_view').wait_for(timeout=30000)
        caption('Odoo DEMO: dữ liệu và phê duyệt nghiệp vụ nằm trong ERP')
        page.wait_for_timeout(1200)
        page.locator('.o_menu_sections [data-menu-xmlid="olist_sales_ai.product_advice_history_menu"]').click()
        rows=page.locator('.o_data_row').filter(has_text='200,00')
        rows.first.click(timeout=30000)
        expect(page.locator('[name=shown_option_ids] .o_kanban_record:not(.o_kanban_ghost)')).to_have_count(2)
        caption('Phương án theo ngân sách; tạo báo giá vẫn cần chọn và duyệt riêng')
        page.screenshot(path=str(output/'odoo-budget-proposal.png'),full_page=True,mask=[page.locator('[name=partner_id]')])
        page.wait_for_timeout(2200)
        if review:
            page.locator('.o_menu_sections [data-menu-xmlid="olist_sales_ai.pending_menu"]').click()
            page.locator('.o_data_row').filter(has_text=review['order_id'][1]).first.click()
            strategy=json.loads(review['trace'])['strategy']
            expect(page.locator('[name=explanation]')).to_contain_text('AI chọn góc trao đổi' if strategy=='assisted' else 'Mẫu quy tắc dự phòng')
            expect(page.get_by_role('button',name='Duyệt tạo việc',exact=True)).to_be_visible()
            expect(page.locator('[name=approval_checked] input')).not_to_be_checked()
            caption('AI chọn góc trao đổi; nội dung local, người dùng kiểm tra rồi mới duyệt tạo việc')
            page.screenshot(path=str(output/'odoo-followup-v2.png'),full_page=True)
            page.wait_for_timeout(2400)
        video=page.video
        context.close()
        if video:video.save_as(str(output/'demo-ai-local.webm'))
        browser.close()
    after=counts()
    assert before==after and not errors
    report={'kind':'automated_real_data_browser_qa_not_human_pilot','rag_method':responses[0]['method'],
        'generation':responses[0]['generation'],'validated_citations':len(responses[0]['citations']),
        'unknown_refused':not responses[1]['answerable'],'desktop_mobile':True,'odoo_existing_options':2,
        'business_record_counts_unchanged':before==after,'no_erp_proposal_or_approval':True,'javascript_errors':errors,
        'followup_review_read':args.followup_review,'video':'demo-ai-local.webm' if args.record else None}
    (output/('browser-qa-recorded.json' if args.record else 'browser-qa.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
