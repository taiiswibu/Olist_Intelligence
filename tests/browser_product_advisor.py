"""Exercise product advice and explicit approval only in an owned disposable Odoo database."""
import argparse
import json
import re
import secrets
import xmlrpc.client
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.openai/qa'
URL='http://127.0.0.1:8069'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--setup-log',choices=['product-advisor-native-setup.log','sales-entry-native-setup.log'],default='product-advisor-native-setup.log')
    args=parser.parse_args()
    assert re.fullmatch(r'olist_ai_test_[a-f0-9]{10}',args.database)
    assert 'QA_DATABASE='+args.database in (OUT/args.setup_log).read_text(encoding='utf-8')
    common=xmlrpc.client.ServerProxy(URL+'/xmlrpc/2/common')
    models=xmlrpc.client.ServerProxy(URL+'/xmlrpc/2/object')
    admin=common.authenticate(args.database,'admin','admin',{})
    assert admin
    def root(model,method,*values,**kw):return models.execute_kw(args.database,admin,'admin',model,method,list(values),kw)
    def xmlid(name):
        module,record=name.split('.')
        return root('ir.model.data','search_read',[['module','=',module],['name','=',record]],fields=['res_id'])[0]['res_id']
    password=secrets.token_urlsafe(28);login='qa_advisor_'+secrets.token_hex(5)
    groups=root('res.users','fields_get',['group_ids','groups_id'])
    group_field='group_ids' if 'group_ids' in groups else 'groups_id'
    user=root('res.users','create',{'name':'Advisor browser fixture','login':login,'password':password,
        group_field:[[6,0,[xmlid('sales_team.group_sale_salesman')]]]},context={'no_reset_password':True})
    def call(model,method,*values,**kw):return models.execute_kw(args.database,user,password,model,method,list(values),kw)
    partner_name='Advisor browser customer '+secrets.token_hex(3)
    partner=root('res.partner','create',{'name':partner_name,'ref':'OLIST-DEMO:advisor-browser'})
    currency=root('res.currency','search',[['name','=','BRL']],context={'active_test':False})[0]
    root('res.currency','write',[currency],{'active':True})
    previous_products=root('product.product','search',[['default_code','=like','OLIST-DEMO:advisor-browser-%']])
    if previous_products:root('product.product','write',previous_products,{'active':False})
    lists=root('product.pricelist','search',[['name','=','OLIST DEMO BRL']])
    assert len(lists)<=1
    price_list=lists[0] if lists else root('product.pricelist','create',{'name':'OLIST DEMO BRL','currency_id':currency})
    taxes=root('account.tax','search',[['name','=','Advisor browser tax fixture']])
    tax=taxes[0] if taxes else root('account.tax','create',{'name':'Advisor browser tax fixture','amount':10,'type_tax_use':'sale','price_include_override':'tax_excluded'})
    for index,price in enumerate([50,80,120,200]):
        product=root('product.product','create',{'name':f'DEMO health_beauty {index:08x}','default_code':f'OLIST-DEMO:advisor-browser-{index}',
            'type':'service','list_price':999,'taxes_id':[[6,0,[tax]]]})
        root('product.pricelist.item','create',{'pricelist_id':price_list,'applied_on':'0_product_variant','product_id':product,'compute_price':'fixed','fixed_price':price})
    before=root('sale.order','search_count',[])
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1000})
        auth=context.request.post(URL+'/web/session/authenticate',data={'jsonrpc':'2.0','params':{'db':args.database,'login':login,'password':password}}).json()
        assert auth.get('result',{}).get('uid')==user
        page=context.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(URL+'/odoo')
        page.locator('.o_navbar_apps_menu button').click(timeout=60000)
        queue_action=xmlid('olist_sales_ai.queue_action')
        def queue_ran(response):
            if not response.url.endswith('/web/action/run'):return False
            data=response.request.post_data_json or {}
            return data.get('params',{}).get('action_id')==queue_action
        with page.expect_response(queue_ran,timeout=30000):
            page.locator('.o_app[data-menu-xmlid="olist_sales_ai.root_menu"]').click()
        page.locator('.o_list_view').wait_for(timeout=30000)
        expect(page.locator('.modal-dialog')).to_have_count(0)
        page.screenshot(path=str(OUT/'sales-app-default-entry.png'),full_page=True)
        page.locator('.o_menu_sections [data-menu-xmlid="olist_sales_ai.product_advice_menu"]').click()
        dialog=page.locator('.modal-dialog')
        customer=dialog.locator('[name=partner_id] input')
        customer.fill(partner_name)
        page.locator('.o-autocomplete--dropdown-item').filter(has_text=partner_name).click()
        dialog.locator('[name=need] textarea').fill('Tìm sản phẩm làm đẹp, chăm sóc cá nhân')
        dialog.locator('[name=budget] input').fill('150')
        dialog.get_by_role('button',name='Xem phương án',exact=True).click()
        page.locator('.o_form_view [name=shown_option_ids]').wait_for(timeout=30000)
        cards=page.locator('[name=shown_option_ids] .o_kanban_record:not(.o_kanban_ghost)')
        try:
            expect(cards).to_have_count(3,timeout=15000)
        except Exception:
            page.screenshot(path=str(OUT/'product-advisor-debug.png'),full_page=True)
            (OUT/'product-advisor-debug.html').write_text(page.content(),encoding='utf-8')
            print(json.dumps({'javascript_errors':errors}))
            raise
        page.get_by_role('button',name='Nhờ AI xếp hạng',exact=True).wait_for()
        assert 'R$' in cards.first.inner_text()
        advice=call('olist.ai.product.advice','search_read',[['partner_id','=',partner]],fields=['id','shown_option_ids','job_started'])[0]
        options=call('olist.ai.product.option','read',advice['shown_option_ids'],fields=['unit_price','tax','total','remaining','state'])
        assert sorted(o['total'] for o in options)==[55,88,132]
        assert not advice['job_started'] and root('sale.order','search_count',[])==before
        page.screenshot(path=str(OUT/'product-advisor-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        cards.first.scroll_into_view_if_needed()
        page.screenshot(path=str(OUT/'product-advisor-mobile.png'),full_page=True)
        page.set_viewport_size({'width':1440,'height':1000})
        cards.first.get_by_role('button',name='Chọn để lập đề xuất',exact=True).click()
        page.locator('.o_form_view [name=approval_checked] input').wait_for(timeout=15000)
        assert root('sale.order','search_count',[])==before
        option=call('olist.ai.product.option','search_read',[['advice_id','=',advice['id']],['state','=','proposed']],fields=['id'])[0]
        page.locator('[name=approval_checked] input').check()
        page.get_by_role('button',name='Duyệt tạo báo giá nháp',exact=True).click()
        page.locator('.modal-dialog').get_by_role('button',name='Ok',exact=True).click()
        page.locator('.o_form_view [name=order_line]').wait_for(timeout=30000)
        result=call('olist.ai.product.option','read',[option['id']],fields=['quote_id','state','approved_by'])[0]
        assert result['state']=='done' and result['approved_by'][0]==user
        quote=call('sale.order','read',[result['quote_id'][0]],fields=['state','amount_total','invoice_ids','activity_ids'])[0]
        assert quote['state']=='draft' and quote['amount_total']==55 and not quote['invoice_ids'] and not quote['activity_ids']
        call('olist.ai.product.option','action_approve',[option['id']])
        assert root('sale.order','search_count',[])==before+1
        assert not errors,errors
        context.close();browser.close()
    report={'kind':'automated_test_fixture_not_human_pilot','native_budget_and_tax':True,'no_quote_before_explicit_approval':True,
        'app_entry_opens_queue':True,'advisor_requires_explicit_menu':True,
        'one_draft_after_approval':True,'idempotent_approval':True,'desktop_mobile':True,'model_calls':0,'javascript_errors':errors}
    (OUT/'product-advisor-browser-qa.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
