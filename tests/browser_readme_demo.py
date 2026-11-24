"""Capture real local flows for README. Never confirm, invoice or approve ERP writes."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
from pypdf import PdfReader
from openpyxl import load_workbook

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from olist.config import ROOT,settings
from olist.erp import Odoo


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',choices=['web','team','erp','odoo'],required=True)
    parser.add_argument('--existing-risk',type=int,help='Reuse a review created during a previous capture.')
    parser.add_argument('--existing-advice',type=int,help='Reuse advice created during a previous capture.')
    args=parser.parse_args()
    cfg=settings();erp=Odoo()
    output=ROOT/'.openai/qa/readme-demo'
    output.mkdir(parents=True,exist_ok=True)
    report={'kind':'automated_demo_not_human_evaluation','phase':args.phase,'checks':[],'screenshots':[],'javascript_errors':[]}
    def add(name,**values):report['checks'].append({'name':name,**values})
    def business():
        result={}
        for table in ['sale_order','sale_order_line','res_partner','mail_activity','account_move']:
            sql="SELECT count(*)::text||':'||md5(COALESCE(string_agg(row_to_json(t)::text,E'\\n' ORDER BY id),'')) FROM "+table+' t'
            result[table]=subprocess.run(['docker','exec','olist-intelligence-odoo-db-1','psql','-U','odoo','-d',cfg.odoo_db,'-At','-c',sql],capture_output=True,text=True,check=True).stdout.strip()
        return result
    before=business()
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        options={'viewport':{'width':1440,'height':1000},'accept_downloads':True}
        context=browser.new_context(**options)
        assert context.request.post(cfg.api_url+'/session',headers={'Origin':cfg.api_url},data={'key':cfg.app_token}).status==200
        auth=context.request.post(cfg.odoo_url+'/web/session/authenticate',data={'jsonrpc':'2.0','params':{'db':cfg.odoo_db,'login':cfg.odoo_login,'password':cfg.odoo_password}}).json()
        assert auth.get('result',{}).get('uid')
        page=context.new_page()
        page.on('pageerror',lambda error:report['javascript_errors'].append(str(error)))
        page.set_default_timeout(30000)
        def shot(name,text,*,full=False):
            assert page.locator('#demo-caption').count()==0
            if full:page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(output/(name+'.jpg')),type='jpeg',quality=85,full_page=full,animations='disabled')
            report['screenshots'].append(name+'.jpg')
            report.setdefault('screenshot_descriptions',{})[name+'.jpg']=text
            page.wait_for_timeout(850)
        def nav(name,ready):
            if page.url.startswith(cfg.api_url):
                page.locator('.sidebar [data-page="'+name+'"]').last.click()
            else:
                page.goto(cfg.api_url+'/#'+name)
            page.locator(ready).first.wait_for(timeout=60000)
        def download(locator,name):
            with page.expect_download(timeout=90000) as event:locator.click()
            file=event.value
            assert file.failure() is None
            path=output/name;file.save_as(path)
            assert path.stat().st_size>100
            return path
        def pdf(path):
            reader=PdfReader(path)
            assert len(reader.pages)>0 and (reader.pages[0].extract_text() or '').strip()
            return len(reader.pages)
        def native_action(name,record=None):
            ids=erp.call('ir.model.data','search_read',[[['module','=','olist_sales_ai'],['name','=',name]]],{'fields':['res_id'],'limit':1})
            assert len(ids)==1
            page.goto(cfg.odoo_url+'/odoo/action-'+str(ids[0]['res_id'])+('/'+str(record) if record else ''))
            page.locator('.o_form_view' if record else '.o_list_view').wait_for(timeout=60000)
        def latest(model,domain,fields):return erp.call(model,'search_read',[domain],{'fields':fields,'order':'id desc','limit':1})[0]
        def prepare_quote():
            nav('erp','#sales-connect')
            page.locator('#sales-connect').click()
            page.locator('[data-sales-partner]').first.wait_for()
            order=context.request.get(cfg.api_url+'/erp/quotations/21').json()
            assert order['state'] in ['draft','sent']
            page.locator(f'[data-sales-partner="{order["partner_id"][0]}"]').click()
            line=next(l for l in order['lines'] if l['price_unit']>0)
            product=line['product_id'][0]
            if page.locator(f'[data-sales-add="{product}"]').count()==0:
                data=erp.call('product.product','read',[[product]],{'fields':['default_code']})[0]
                page.locator('#sales-product-query').fill(data['default_code'])
                page.locator('#sales-find-product').click()
            page.locator(f'[data-sales-add="{product}"]').click()
            for key,value in [('quantity',line['product_uom_qty']),('unit_price',line['price_unit']),('discount',line['discount'])]:
                page.locator('[data-sales-line="0"][data-sales-field='+key+']').fill(str(value))
            return order
        try:
            if args.phase=='web':
                nav('overview','#main-chart')
                page.locator('#filter-start').fill('2018-01-01')
                page.locator('#filter-end').fill('2018-12-31')
                page.locator('#filter-state').select_option('SP')
                page.locator('#filters button[type=submit]').click()
                page.wait_for_function("state.cache.k?.filters?.state==='SP'")
                shot('01-tong-quan','Olist thật · Lọc năm 2018, bang SP · GMV hàng hóa, không phải lợi nhuận')
                csv=download(page.locator('#export-button'),'dashboard.csv')
                assert len(csv.read_text(encoding='utf-8-sig').splitlines())>1
                add('dashboard_filters_and_csv',download_bytes=csv.stat().st_size)

                nav('assistant','#chat-input')
                page.locator('#chat-mode').select_option('single')
                page.locator('#chat-input').fill('Tổng quan KPI tháng 2/2018 bang SP')
                page.locator('#chat-form button[type=submit]').click()
                page.wait_for_function('!state.busy',timeout=90000)
                result=page.evaluate('state.history.at(-1)?.response')
                assert result and result['tool']=='kpis' and result['data'] and result['sql']
                shot('02-tro-ly','Trợ lý cơ bản · Số liệu lấy từ công cụ BI và có truy vấn đối chiếu',full=True)
                add('basic_assistant',tool=result['tool'],routing=result['routing']['mode'],has_sql=bool(result['sql']))

                nav('reports','#report-new')
                existing=page.locator('.report-draft').filter(has_text='Báo cáo DEMO Olist - dữ liệu lịch sử')
                if existing.count():existing.first.click()
                else:page.locator('#report-new').click()
                page.locator('#report-title').fill('Báo cáo DEMO Olist - dữ liệu lịch sử')
                page.locator('#report-notes').fill('Minh họa dữ liệu Olist lịch sử. GMV là giá trị hàng hóa, chưa gồm cước; chưa phải doanh thu ròng.')
                page.locator('#report-save').click()
                expect(page.locator('#report-save-state')).to_contain_text('Đã lưu')
                shot('03-bao-cao','Báo cáo thật từ công cụ BI · Chỉnh nhận xét, biểu đồ, lưu và tải file')
                file=download(page.locator('[data-report-download=pdf]'),'bao-cao.pdf')
                pages=pdf(file)
                file=download(page.locator('[data-report-download=xlsx]'),'bao-cao.xlsx')
                workbook=load_workbook(file)
                assert len(workbook.sheetnames)>=2 and any(ws._charts for ws in workbook.worksheets)
                add('report_pdf_excel_charts',pdf_pages=pages,excel_sheets=len(workbook.sheetnames),excel_native_charts=True)

                nav('knowledge','#knowledge-query')
                page.locator('#knowledge-query').fill('Giao buổi tối trong đúng ngày hẹn có bị tính trễ không?')
                with page.expect_response(lambda r:r.url.endswith('/rag/answer'),timeout=90000) as event:page.locator('#knowledge-form button').click()
                result=event.value.json()
                expect(page.locator('#knowledge-results')).to_contain_text('Trả lời từ tài liệu')
                assert result['method']=='hybrid_sqlite_vec' and result['citations']
                shot('04-rag','RAG local · Model chọn trích đoạn, backend đối chiếu nguyên văn với nguồn')
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                shot('05-rag-mobile','RAG trên điện thoại',full=True)
                page.set_viewport_size({'width':1440,'height':1000})
                page.locator('#knowledge-query').fill('Dự báo thời tiết Hà Nội ngày mai thế nào?')
                with page.expect_response(lambda r:r.url.endswith('/rag/answer'),timeout=90000) as event:page.locator('#knowledge-form button').click()
                result=event.value.json()
                expect(page.locator('#knowledge-results')).to_contain_text('Chưa đủ bằng chứng')
                assert not result['sources'] and result['generation']=='not_called'
                shot('06-rag-tu-choi','Ngoài phạm vi tài liệu · Từ chối trả lời và không gọi model sinh nội dung')
                add('local_rag_and_refusal',method='hybrid_sqlite_vec',unknown_generation='not_called',mobile_no_overflow=True)

                nav('delivery','#risk-sample')
                options=page.locator('#risk-sample option').evaluate_all('(items)=>items.map(x=>x.value).filter(Boolean)')
                assert options
                page.locator('#risk-sample').select_option(options[0])
                with page.expect_response(lambda r:'/ml/order/' in r.url,timeout=60000) as response:
                    page.locator('#risk-form button').click()
                prediction=response.value.json()
                assert response.value.status==200 and 0<=prediction['risk_score']<=1
                expect(page.locator('#risk-result')).to_contain_text(prediction['model'],timeout=60000)
                shot('07-ml-giao-tre','ML thử nghiệm · Đọc điểm cùng giới hạn holdout; không tự ra quyết định')
                add('historical_ml_prediction',holdout_retrained=False,model=prediction['model'],risk_score=prediction['risk_score'])

                prepare_quote()
                page.locator('#sales-preview').click()
                expect(page.locator('#sales-review')).to_contain_text('Tổng',timeout=60000)
                page.locator('#sales-review').scroll_into_view_if_needed()
                shot('08-doi-soat-erp','Đối soát giá và thuế bằng Odoo · Giá BRL lấy từ dòng báo giá DEMO đang có')
                page.locator('[data-sales-order="21"]').click()
                page.locator('[data-sales-pdf="21"]').wait_for()
                file=download(page.locator('[data-sales-pdf="21"]'),'bao-gia.pdf')
                add('erp_lookup_preview_quote_pdf',pdf_pages=pdf(file),quote_created=False)
                nav('verification','.summary-stat')
                shot('09-kiem-chung','Đối soát CSV, số dòng, checksum và nhật ký · Không thay dữ liệu thiếu bằng số giả')
                add('data_verification',source='real_olist_csv')

            elif args.phase=='team':
                nav('assistant','#chat-mode')
                page.locator('#chat-mode').select_option('team')
                page.locator('#chat-input').fill('Tính GMV hàng hóa và AOV tháng 2/2018 bang SP, giải thích công thức AOV theo tài liệu.')
                page.locator('#chat-form button[type=submit]').click()
                page.wait_for_function('!state.busy',timeout=150000)
                result=page.evaluate('state.history.at(-1)?.response')
                assert result and result.get('evidence'), 'No grounded team result'
                shot('10-doi-agent','Đội agent · Tách công cụ BI, nguồn tài liệu và bước kiểm tra; có thể chưa hoàn tất khi API lỗi',full=True)
                add('multi_agent',status=result.get('status'),evidence_tools=[e.get('tool') for e in result['evidence']],trace_entries=len(result.get('trace',[])),model_calls=result.get('model_calls'),tool_calls=result.get('tool_calls'))

            elif args.phase=='erp':
                prepare_quote()
                page.locator('#sales-agent-review').click()
                page.wait_for_function('!state.busy && (state.history.length>0 || state.chatFailure)',timeout=150000)
                result=page.evaluate('state.history.at(-1)?.response')
                assert result and any(e.get('tool')=='review_current_quotation' for e in result.get('evidence',[]))
                shot('21-agent-erp','Agent kiểm tra bản chụp form · Số lấy từ Odoo, chưa lưu đề xuất hoặc ghi báo giá',full=True)
                add('agent_current_quotation_review',status=result.get('status'),model_calls=result.get('model_calls'),evidence_tools=[e.get('tool') for e in result['evidence']],new_quote_created=False)
                native_action('risk_action',1)
                expect(page.locator('[name=explanation]')).not_to_be_empty()
                shot('22-ai-rui-ro-da-luu','Đọc diễn giải AI đã lưu từ bản cũ · Nguồn đã đổi phải kiểm tra lại',full=True)
                add('risk_ai_saved_explanation',new_cloud_call=False,old_review_read=True)
            else:
                native_action('pending_action',10)
                expect(page.locator('[name=explanation]')).to_contain_text('AI chọn góc trao đổi')
                expect(page.locator('[name=approval_checked] input')).not_to_be_checked()
                shot('11-cham-soc-odoo','Đề xuất chăm sóc đã có · Có nguồn và model/skill; chưa tick duyệt tạo việc')
                add('native_followup_existing_proposal',new_activity_created=False)
                native_action('trials_action')
                shot('12-do-thao-tac','Lượt đo thao tác đã lưu · Giữ cả thất bại; không tạo kết quả chấm người dùng mới')
                add('user_measurement_existing_records',new_human_ratings=0)
                native_action('risk_action',args.existing_risk or 1)
                if not args.existing_risk:
                    with page.expect_response(lambda r:'/web/dataset/call_button' in r.url) as response:
                        page.get_by_role('button',name='Kiểm tra lại',exact=True).click()
                    response.value.finished()
                risk=latest('olist.ai.quote.risk.review',[['id','=',args.existing_risk]] if args.existing_risk else [['order_id','=',21]],['id','previous_review_id','state'])
                assert risk['previous_review_id']
                shot('13-rui-ro-bao-gia','Bản kiểm tra mới · Cờ rủi ro do quy tắc Odoo, chưa phải đánh giá tín dụng')
                page.get_by_role('tab',name='Trước/sau',exact=True).click()
                shot('14-truoc-sau','So hai bản kiểm tra · Giữ nguồn và cờ cũ, không tự kế thừa xác nhận')
                page.get_by_role('button',name='Ghi nhận xử lý',exact=True).click()
                page.locator('.modal-dialog').wait_for()
                shot('15-ghi-nhan','Cửa sổ ghi nhận xử lý · Chỉ mở để xem, chưa lưu kết luận nghiệp vụ')
                page.locator('.modal-dialog').get_by_role('button',name='Hủy',exact=True).click()
                file=download(page.get_by_role('button',name='Tải báo cáo PDF',exact=True),'rui-ro.pdf')
                pages=pdf(file)
                file=download(page.get_by_role('button',name='Tải báo cáo Excel',exact=True),'rui-ro.xlsx')
                assert len(load_workbook(file).sheetnames)==3
                add('quote_risk_comparison_disposition_dialog_and_exports',review_id=risk['id'],pdf_pages=pages,excel_sheets=3,disposition_saved=False)
                if args.existing_advice:
                    native_action('product_advice_history',args.existing_advice)
                else:
                    page.locator('.o_menu_sections [data-menu-xmlid="olist_sales_ai.product_advice_menu"]').click()
                    dialog=page.locator('.modal-dialog')
                    customer=erp.call('sale.order','read',[[21]],{'fields':['partner_id']})[0]['partner_id'][1]
                    dialog.locator('[name=partner_id] input').fill(customer)
                    page.locator('.o-autocomplete--dropdown-item').filter(has_text=customer).first.click()
                    dialog.locator('[name=need] textarea').fill('tìm quà sinh nhật')
                    dialog.locator('[name=budget] input').fill('200')
                    dialog.get_by_role('button',name='Xem phương án',exact=True).click()
                cards=page.locator('[name=shown_option_ids] .o_kanban_record:not(.o_kanban_ghost)')
                expect(cards).to_have_count(2)
                advice=latest('olist.ai.product.advice',[['id','=',args.existing_advice]] if args.existing_advice else [],['id','state','option_ids','job_started'])
                if not advice['job_started']:
                    with page.expect_response(lambda r:'/web/dataset/call_button' in r.url) as response:
                        page.get_by_role('button',name='Nhờ AI xếp hạng',exact=True).click()
                    response.value.finished()
                limit=time.monotonic()+150
                while time.monotonic()<limit:
                    state=erp.call('olist.ai.product.advice','poll_state',[[advice['id']]])
                    if state!='pending':break
                    page.wait_for_timeout(1500)
                page.reload();cards.first.wait_for()
                expect(cards).to_have_count(2)
                shot('16-goi-y-san-pham','Danh mục DEMO thật · Odoo lọc ngân sách; '+('AI đã xếp hạng' if state=='ranked' else 'AI chưa có kết quả hợp lệ, giữ phương án local'))
                cards.first.get_by_role('button',name='Chọn để lập đề xuất',exact=True).click()
                expect(page.get_by_role('button',name='Duyệt tạo báo giá nháp',exact=True)).to_be_visible()
                expect(page.locator('[name=approval_checked] input')).not_to_be_checked()
                shot('17-de-xuat-bao-gia','Bước duyệt riêng · Chưa tick, chưa tạo báo giá mới')
                add('product_budget_rank_and_proposal',advice_id=advice['id'],ranking_state=state,budget_brl=200,options=2,new_quote_created=False)

            assert not report['javascript_errors']
            after=business()
            assert before==after,'Business rows changed during capture; inspect before claiming a read-only demo'
            report.update(business_rows_unchanged=True,no_confirmation_invoice_or_activity_approval=True)
        except Exception as exc:
            report['failure']=type(exc).__name__
            page.screenshot(path=str(output/(args.phase+'-debug.jpg')),type='jpeg',quality=85)
            raise
        finally:
            (output/('report-'+args.phase+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            with (output/'attempts.jsonl').open('a',encoding='utf-8') as history:
                history.write(json.dumps(report,ensure_ascii=False)+'\n')
            context.close()
            browser.close()
    print(json.dumps(report,ensure_ascii=True))


if __name__=='__main__':main()
