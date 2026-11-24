import json
from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install','-at_install')
class TestProductAdvisor(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        context={'no_reset_password':True,'mail_create_nosubscribe':True}
        cls.staff=new_test_user(cls.env,login='advisor_staff',groups='sales_team.group_sale_salesman',context=context)
        cls.other=new_test_user(cls.env,login='advisor_other',groups='sales_team.group_sale_salesman',context=context)
        cls.manager=new_test_user(cls.env,login='advisor_manager',groups='sales_team.group_sale_manager',context=context)
        cls.env['crm.team'].create({'name':'Advisor fixture team','user_id':cls.manager.id,'member_ids':[Command.set(cls.staff.ids)],'company_id':cls.env.company.id})
        cls.partner=cls.env['res.partner'].create({'name':'PRIVATE_PARTNER_CANARY','ref':'OLIST-DEMO:advisor-fixture'})
        cls.currency=cls.env['res.currency'].with_context(active_test=False).search([('name','=','BRL')],limit=1)
        cls.currency.active=True
        cls.price_list=cls.env['product.pricelist'].create({'name':'OLIST DEMO BRL','currency_id':cls.currency.id,'company_id':cls.env.company.id})
        cls.tax=cls.env['account.tax'].create({'name':'Fixture advisor ten percent','amount':10,'type_tax_use':'sale','price_include_override':'tax_excluded'})
        cls.products=cls.env['product.product']
        cls.rules=cls.env['product.pricelist.item']
        for index,price in enumerate([50,80,120,200]):
            product=cls.env['product.product'].create({'name':f'DEMO health_beauty {index:08x}','default_code':f'OLIST-DEMO:advisor-{index}',
                'type':'service','list_price':999,'taxes_id':[Command.set(cls.tax.ids)]})
            rule=cls.env['product.pricelist.item'].create({'pricelist_id':cls.price_list.id,'applied_on':'0_product_variant',
                'product_id':product.id,'compute_price':'fixed','fixed_price':price})
            cls.products+=product;cls.rules+=rule

    def advice(self,**changes):
        return self.env['olist.ai.product.advice'].with_user(self.staff).create({'partner_id':self.partner.id,
            'need':'PRIVATE_NEED_CANARY muốn làm đẹp','intent':'detect','quantity':1,'budget':150,**changes})

    def test_native_prices_taxes_budget_and_no_quote_before_approval(self):
        before=self.env['sale.order'].search_count([])
        advice=self.advice()
        self.assertEqual(advice.intent,'beauty')
        self.assertEqual(len(advice.option_ids),3)
        self.assertEqual(advice.option_ids.mapped('unit_price'),[50,80,120])
        self.assertEqual(advice.option_ids.mapped('total'),[55,88,132])
        self.assertTrue(all(o.remaining>=0 for o in advice.option_ids))
        self.assertEqual(self.env['sale.order'].search_count([]),before)
        self.assertEqual(advice.team_id.user_id,self.manager)
        self.assertIn('1 vượt ngân sách',advice.message)

    def test_unknown_need_empty_budget_and_wrong_product_do_not_invent_choices(self):
        with self.assertRaises(UserError):self.advice(need='nhu cầu chưa rõ')
        with self.assertRaises(UserError):self.advice(budget=0)
        self.assertFalse(self.advice(budget=10).option_ids)
        self.assertFalse(self.advice(intent='pets').option_ids)
        self.products[0].active=False
        self.products[1].sale_ok=False
        self.assertEqual(len(self.advice().option_ids),1)

    def test_explicit_proposal_checkbox_and_idempotent_draft_creation(self):
        advice=self.advice();option=advice.option_ids[0]
        with self.assertRaises(UserError):option.action_approve()
        option.action_propose()
        with self.assertRaises(UserError):option.action_approve()
        option.write({'approval_checked':True})
        option.action_approve()
        quote=option.quote_id
        self.assertTrue(quote)
        self.assertEqual(quote.state,'draft')
        self.assertEqual(quote.amount_total,55)
        self.assertEqual(quote.user_id,self.staff)
        self.assertEqual(option.approved_by,self.staff)
        self.assertFalse(quote.invoice_ids)
        self.assertFalse(quote.activity_ids)
        option.action_approve()
        self.assertEqual(option.quote_id,quote)
        self.assertEqual(self.env['sale.order'].search_count([('origin','=',quote.origin)]),1)

    def test_price_tax_partner_and_day_changes_block_creation(self):
        option=self.advice().option_ids[0]
        option.action_propose();option.approval_checked=True
        self.rules[0].fixed_price=51
        with self.assertRaises(UserError):option.action_approve()
        self.assertFalse(option.quote_id)
        fresh=self.advice().option_ids[0]
        self.tax.amount=15
        with self.assertRaises(UserError):fresh.action_propose()
        fresh=self.advice().option_ids[0]
        self.partner.name='Changed fixture partner'
        with self.assertRaises(UserError):fresh.action_propose()
        fresh=self.advice().option_ids[0]
        self.env.cr.execute('UPDATE olist_ai_product_advice SET source_date=%s WHERE id=%s',(fields.Date.today()-timedelta(days=1),fresh.advice_id.id))
        fresh.advice_id.invalidate_recordset()
        with self.assertRaises(UserError):fresh.action_propose()

    def test_scope_and_immutable_server_fields(self):
        advice=self.advice(); option=advice.option_ids[0]
        advice.with_user(self.manager).read(['need'])
        for record in [advice,option]:
            with self.assertRaises(AccessError):record.with_user(self.other).read(['owner_id'])
        with self.assertRaises(AccessError):advice.write({'budget':9999})
        with self.assertRaises(AccessError):option.write({'unit_price':1})
        with self.assertRaises(AccessError):option.create({'advice_id':advice.id,'product_id':self.products[0].id})
        with self.assertRaises(AccessError):option.unlink()
        with self.assertRaises(AccessError):self.advice(owner_id=self.other.id)
        company=self.env['res.company'].create({'name':'Advisor other fixture company'})
        self.manager.company_ids=[Command.link(company.id)]
        with self.assertRaises(AccessError):option.with_user(self.manager).with_company(company).action_propose()

    def test_native_currency_conversion_and_missing_rate_are_explicit(self):
        self.rules[0].unlink()
        for currency,rate in [(self.env.company.currency_id,1),(self.currency,5)]:
            self.env['res.currency.rate'].create({'currency_id':currency.id,'name':fields.Date.today(),'rate':rate,'company_id':self.env.company.root_id.id})
        advice=self.advice(budget=10000)
        converted=advice.option_ids.filtered(lambda o:o.product_id==self.products[0])
        self.assertEqual(converted.unit_price,4995)
        self.assertEqual(converted.total,5494.5)
        self.assertFalse(json.loads(converted.snapshot_json)['fixed_price'])
        self.env['res.currency.rate'].search([('currency_id','=',self.currency.id),('company_id','in',[False,self.env.company.root_id.id])]).unlink()
        with self.assertRaises(UserError):self.advice(budget=10000)

    def test_lost_rank_post_recovers_same_job_and_sends_no_private_values(self):
        advice=self.advice(); requests=[]
        def bridge(record,method,path,payload=None):
            requests.append((method,payload))
            if method=='POST':raise UserError('Fixture response lost')
            return {'state':'complete','request_id':record.request_key,'strategy':'pipeline','picks':[
                {'alias':o.alias,'reason':'category_match'} for o in record.option_ids.sorted('rank',reverse=True)[:3]]}
        with patch.object(type(advice),'_bridge',bridge):
            advice.action_rank();advice.action_rank()
            self.assertEqual([r[0] for r in requests],['POST'])
            self.assertNotIn('PRIVATE_',json.dumps(requests))
            self.assertEqual(set(requests[0][1]['features']),{'intent','candidates'})
            self.assertEqual(advice.poll_state(),'ranked')
        self.assertEqual(advice.shown_option_ids[0].unit_price,120)
        self.assertFalse(advice.option_ids.quote_id)

    def test_bad_rank_and_timeout_keep_local_options(self):
        for result in [{'state':'complete','request_id':'wrong','picks':[]},{'state':'failed','error':'Fixture unavailable'}]:
            advice=self.advice();original=advice.option_ids.mapped('rank')
            with patch.object(type(advice),'_bridge',return_value=result):
                advice.action_rank()
                self.assertEqual(advice.poll_state(),'failed')
            self.assertEqual(advice.option_ids.mapped('rank'),original)
        advice=self.advice()
        with patch.object(type(advice),'_bridge',return_value={'state':'pending'}):
            advice.action_rank();advice.flush_recordset(['job_started_at'])
            self.env.cr.execute('UPDATE olist_ai_product_advice SET job_started_at=%s WHERE id=%s',(fields.Datetime.now()-timedelta(minutes=3),advice.id))
            advice.invalidate_recordset()
            self.assertEqual(advice.poll_state(),'failed')
