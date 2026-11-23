import json
import math
import secrets
import uuid
from datetime import timedelta

from markupsafe import Markup, escape
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from . import advisor_pricing as pricing
from .risk_handling import clean_context

INTENTS = [(key,value['label']) for key,value in pricing.CATALOG.items()]


class ProductAdvice(models.Model):
    _name = 'olist.ai.product.advice'
    _description = 'Gợi ý sản phẩm theo ngân sách'
    _rec_name = 'need'
    _order = 'id desc'

    partner_id = fields.Many2one('res.partner',string='Khách DEMO',required=True,readonly=True)
    need = fields.Text('Nhu cầu',required=True,readonly=True)
    intent = fields.Selection(INTENTS,string='Nhóm nhu cầu',required=True,readonly=True)
    quantity = fields.Integer('Số lượng mỗi phương án',required=True,readonly=True)
    budget = fields.Monetary('Ngân sách gồm thuế',required=True,readonly=True)
    currency_id = fields.Many2one('res.currency',required=True,readonly=True)
    owner_id = fields.Many2one('res.users',string='Người lập',required=True,readonly=True)
    company_id = fields.Many2one('res.company',required=True,readonly=True)
    team_id = fields.Many2one('crm.team',string='Nhóm bán hàng',readonly=True)
    checked_at = fields.Datetime('Thời điểm đọc giá',readonly=True)
    source_date = fields.Date(readonly=True)
    option_ids = fields.One2many('olist.ai.product.option','advice_id',readonly=True)
    shown_option_ids = fields.Many2many('olist.ai.product.option',compute='_compute_shown',string='Phương án')
    state = fields.Selection([('prepared','Đã lọc theo Odoo'),('pending','Đang xếp hạng'),('ranked','Đã nhận xếp hạng'),('failed','Chưa có xếp hạng AI')],default='prepared',readonly=True)
    message = fields.Text('Kết quả đối chiếu',readonly=True)
    trace = fields.Text('Lịch sử model',readonly=True)
    request_key = fields.Char(readonly=True)
    job_started = fields.Boolean(readonly=True)
    job_started_at = fields.Datetime(readonly=True)

    @api.depends('option_ids.rank')
    def _compute_shown(self):
        for record in self: record.shown_option_ids=record.option_ids.filtered(lambda o:o.rank<=3).sorted('rank')

    def _check_scope(self):
        self.check_access('read')
        for record in self:
            if record.company_id!=self.env.company or not self.env.user.has_group('sales_team.group_sale_salesman'):
                raise AccessError('Không thuộc công ty bán hàng hiện tại.')
            if record.owner_id!=self.env.user and not (self.env.user.has_group('sales_team.group_sale_manager') and record.team_id.user_id==self.env.user):
                raise AccessError('Chỉ người lập và quản lý nhóm được xử lý lượt này.')
            pricing.check_partner(self.env,record.partner_id)

    def _open_action(self):
        self.ensure_one()
        return {'type':'ir.actions.act_window','name':'Gợi ý sản phẩm','res_model':self._name,'view_mode':'form','res_id':self.id,'target':'current'}

    @api.model_create_multi
    def create(self, values_list):
        records=self.browse()
        for values in values_list:
            if set(values)!={'partner_id','need','intent','quantity','budget'}:
                raise AccessError('Chỉ nhập khách, nhu cầu, nhóm, số lượng và ngân sách.')
            need=values['need'].strip() if isinstance(values['need'],str) else ''
            quantity=values['quantity']; budget=values['budget']
            if not 5<=len(need)<=1000 or type(quantity)!=int or not 1<=quantity<=1000 or not isinstance(budget,(int,float)) or not math.isfinite(budget) or not 0<budget<=100000000:
                raise UserError('Nhập nhu cầu từ năm đến một nghìn ký tự, số lượng nguyên từ một đến một nghìn và ngân sách dương hợp lệ.')
            partner=self.env['res.partner'].browse(values['partner_id'])
            pricing.check_partner(self.env,partner)
            price_list=pricing.pricelist(self.env)
            intent=pricing.intent_for(need,values['intent'])
            team=self.env['crm.team'].search([('member_ids','in',[self.env.uid]),('company_id','in',[False,self.env.company.id])],limit=1,order='id')
            record=super(ProductAdvice,clean_context(self)).create({**values,'need':need,'intent':intent,'budget':price_list.currency_id.round(budget),
                'currency_id':price_list.currency_id.id,'company_id':self.env.company.id,'owner_id':self.env.uid,'team_id':team.id or False,
                'checked_at':fields.Datetime.now(),'source_date':fields.Date.context_today(self),'request_key':uuid.uuid4().hex})
            products=self.env['product.product'].search([('default_code','=like','OLIST-DEMO:%'),('default_code','!=','OLIST-DEMO:FREIGHT'),
                ('active','=',True),('sale_ok','=',True),('company_id','in',[False,self.env.company.id])],limit=501,order='id')
            if len(products)>500: raise UserError('Danh mục vượt năm trăm sản phẩm DEMO; chưa đọc một phần để gợi ý.')
            matched=products.filtered(lambda p:pricing.category(p) in pricing.CATALOG[intent]['categories'])
            options=[]; over_budget=0; unsuitable=0
            for product in matched:
                snapshot=pricing.priced_option(record,product)
                if snapshot['unit_price']<=0 or snapshot['total']<=0 or not 0<=snapshot['discount']<=100:
                    unsuitable+=1; continue
                if record.currency_id.compare_amounts(snapshot['total'],record.budget)>0:
                    over_budget+=1; continue
                options.append((snapshot['total'],product.id,snapshot))
            options.sort(key=lambda row:(row[0],row[1]))
            prepared=[]
            for rank,(_,product_id,snapshot) in enumerate(options[:12],1):
                ratio=snapshot['total']/record.budget
                prepared.append({'advice_id':record.id,'product_id':product_id,'snapshot_json':json.dumps(snapshot,sort_keys=True),
                    'unit_price':snapshot['unit_price'],'subtotal':snapshot['subtotal'],'tax':snapshot['tax'],'total':snapshot['total'],
                    'remaining':record.currency_id.round(record.budget-snapshot['total']),'rank':rank,
                    'category':snapshot['category'],'price_band':'low' if ratio<=1/3 else 'medium' if ratio<=2/3 else 'high',
                    'alias':'ITEM_'+secrets.token_hex(8),'reason':'category_match','request_key':uuid.uuid4().hex})
            self.env['olist.ai.product.option']._seed(prepared)
            message=f'Đã đọc {len(products)} sản phẩm DEMO; {len(matched)} khớp nhóm, {len(options)} hợp ngân sách, {over_budget} vượt ngân sách, {unsuitable} chưa có giá dương hợp lệ. Hiển thị tối đa ba phương án; AI xếp hạng trong tối đa mười hai ứng viên rẻ nhất.'
            if not options: message+=' Chưa có phương án phù hợp; điều chỉnh nhu cầu hoặc ngân sách rồi tạo lượt mới.'
            super(ProductAdvice,record).write({'message':message})
            records+=record
        return records

    def write(self, values):
        raise AccessError('Lượt gợi ý giữ nguyên dữ liệu; tạo lượt mới khi đổi nhu cầu hoặc ngân sách.')

    def _bridge(self, method, path, payload=None):
        return self.env['olist.ai.followup.review']._bridge(method,path,payload)

    def action_rank(self):
        self.ensure_one(); self._check_scope()
        self.env.cr.execute('SELECT id FROM olist_ai_product_advice WHERE id=%s FOR UPDATE',(self.id,))
        self.invalidate_recordset()
        if self.job_started: return True
        if not self.option_ids: raise UserError('Chưa có ứng viên để xếp hạng.')
        for option in self.option_ids: option._check_fresh()
        super().write({'state':'pending','job_started':True,'job_started_at':fields.Datetime.now()})
        features={'intent':self.intent,'candidates':[{'alias':o.alias,'category':o.category,'price_band':o.price_band} for o in self.option_ids.sorted('rank')]}
        payload={'request_id':self.request_key,'database':self.env.cr.dbname,'user_id':self.owner_id.id,'company_id':self.company_id.id,'features':features}
        try: self._bridge('POST','/odoo-ai/product-advice',payload)
        except UserError: super().write({'message':self.message+'\nChưa nhận phản hồi; giữ mã lượt để lấy lại kết quả.'})
        return True

    def poll_state(self):
        self.ensure_one(); self._check_scope()
        if self.state!='pending': return self.state
        try: result=self._bridge('GET','/odoo-ai/product-advice/'+self.request_key,{'database':self.env.cr.dbname,'user_id':self.owner_id.id,'company_id':self.company_id.id})
        except UserError: result={'state':'pending'}
        self.env.cr.execute('SELECT id FROM olist_ai_product_advice WHERE id=%s FOR UPDATE',(self.id,))
        self.invalidate_recordset()
        if self.state!='pending': return self.state
        if result.get('state')=='complete':
            known={o.alias:o for o in self.option_ids}; picks=result.get('picks')
            valid=(result.get('request_id')==self.request_key and isinstance(picks,list) and len(picks)==min(3,len(known))
                and all(isinstance(p,dict) and isinstance(p.get('alias'),str) and p.get('alias') in known and p.get('reason') in pricing.REASONS for p in picks))
            if valid:
                valid=len({p['alias'] for p in picks})==len(picks) and all(p['reason']!='lower_cost' or known[p['alias']].price_band=='low' for p in picks)
            if not valid:
                super().write({'state':'failed','trace':json.dumps(result.get('trace',[])),'message':self.message+'\nKết quả xếp hạng không khớp ứng viên; giữ phương án local.'})
            else:
                for option in self.option_ids:
                    super(ProductOption,option).write({'rank':100+option.id})
                for rank,pick in enumerate(picks,1):
                    super(ProductOption,known[pick['alias']]).write({'rank':rank,'reason':pick['reason']})
                super().write({'state':'ranked','trace':json.dumps({k:result.get(k) for k in ('trace','privacy_version','strategy','skills')},ensure_ascii=False)})
        elif result.get('state') in {'failed','interrupted'} or fields.Datetime.now()-self.job_started_at>timedelta(seconds=150):
            super().write({'state':'failed','trace':json.dumps(result.get('trace',[])),'message':self.message+'\n'+(result.get('error') or 'Hết thời gian chờ xếp hạng; giữ phương án local.')})
        return self.state


class ProductOption(models.Model):
    _name='olist.ai.product.option'
    _description='Phương án sản phẩm và đề xuất báo giá'
    _rec_name='product_id'
    _order='rank,id'

    advice_id=fields.Many2one('olist.ai.product.advice',required=True,readonly=True,ondelete='restrict')
    owner_id=fields.Many2one(related='advice_id.owner_id',store=True)
    company_id=fields.Many2one(related='advice_id.company_id',store=True)
    team_id=fields.Many2one(related='advice_id.team_id',store=True)
    currency_id=fields.Many2one(related='advice_id.currency_id')
    partner_id=fields.Many2one(related='advice_id.partner_id',string='Khách')
    product_id=fields.Many2one('product.product',string='Sản phẩm',required=True,readonly=True)
    category=fields.Char(readonly=True)
    price_band=fields.Char(readonly=True)
    unit_price=fields.Monetary('Đơn giá',readonly=True)
    subtotal=fields.Monetary('Trước thuế',readonly=True)
    tax=fields.Monetary('Thuế',readonly=True)
    total=fields.Monetary('Tổng gồm thuế',readonly=True)
    remaining=fields.Monetary('Ngân sách còn lại',readonly=True)
    rank=fields.Integer(readonly=True)
    reason=fields.Selection(list(pricing.REASONS.items()),string='Lý do',readonly=True)
    snapshot_json=fields.Text(readonly=True)
    alias=fields.Char(readonly=True)
    request_key=fields.Char(readonly=True)
    source_html=fields.Html('Nguồn giá',compute='_compute_source')
    state=fields.Selection([('suggested','Phương án'),('proposed','Đề xuất chờ duyệt'),('done','Đã tạo báo giá nháp')],default='suggested',readonly=True)
    approval_checked=fields.Boolean('Tôi đã đối chiếu phương án và đồng ý tạo báo giá nháp')
    quote_id=fields.Many2one('sale.order',string='Báo giá đã tạo',readonly=True)
    approved_by=fields.Many2one('res.users',string='Người duyệt',readonly=True)
    approved_at=fields.Datetime('Thời điểm duyệt',readonly=True)

    @api.depends('snapshot_json')
    def _compute_source(self):
        for option in self:
            snapshot=json.loads(option.snapshot_json or '{}')
            text='Giá do Odoo tính từ OLIST DEMO BRL. '+('Áp dụng giá cố định của bảng giá.' if snapshot.get('fixed_price') else 'Áp dụng quy tắc và quy đổi theo cấu hình Odoo; chưa phải tỷ giá thị trường hiện tại.')
            rates='; '.join(f"{r['currency']}: {r['rate']} · ngày {r['date']}" for r in snapshot.get('rates',[]))
            option.source_html=Markup('<p>%s</p><p>%s</p><p>Chưa có bằng chứng tồn kho hoặc thông số kỹ thuật; cần đối chiếu trước khi chào khách.</p>')%(escape(text),escape(rates))

    @api.model_create_multi
    def create(self, values_list):
        raise AccessError('Phương án do server tính từ Odoo.')

    def _seed(self, values):
        return super(ProductOption,clean_context(self)).create(values)

    def write(self, values):
        if set(values)!={'approval_checked'} or any(o.state!='proposed' for o in self):
            raise AccessError('Chỉ tick đồng ý trên đề xuất đang chờ duyệt.')
        self._check_scope()
        return super().write(values)

    def unlink(self):
        raise AccessError('Không xóa lịch sử phương án hoặc đề xuất.')

    def _check_scope(self):
        self.check_access('read')
        self.advice_id._check_scope()

    def _check_fresh(self):
        self.ensure_one(); self._check_scope()
        if self.advice_id.source_date!=fields.Date.context_today(self):
            raise UserError('Lượt gợi ý thuộc ngày trước; tạo lượt mới để đọc giá hiện tại.')
        snapshot=pricing.priced_option(self.advice_id,self.product_id)
        if snapshot!=json.loads(self.snapshot_json) or self.currency_id.compare_amounts(snapshot['total'],self.advice_id.budget)>0:
            raise UserError('Giá, thuế hoặc dữ liệu Odoo đã đổi; tạo lượt gợi ý mới trước khi lập báo giá.')
        return snapshot

    def _open_action(self):
        self.ensure_one()
        return {'type':'ir.actions.act_window','name':'Đề xuất từ phương án sản phẩm','res_model':self._name,'res_id':self.id,'view_mode':'form','target':'current'}

    def action_propose(self):
        self.ensure_one(); self._check_scope()
        self.env.cr.execute('SELECT id FROM olist_ai_product_option WHERE id=%s FOR UPDATE',(self.id,))
        self.invalidate_recordset()
        if self.state=='suggested':
            self._check_fresh()
            super().write({'state':'proposed','approval_checked':False})
        return self._open_action()

    def action_approve(self):
        self.ensure_one(); self._check_scope()
        self.env.cr.execute('SELECT id FROM olist_ai_product_option WHERE id=%s FOR UPDATE',(self.id,))
        self.invalidate_recordset()
        if self.quote_id:
            return {'type':'ir.actions.act_window','res_model':'sale.order','view_mode':'form','res_id':self.quote_id.id,'target':'current'}
        if self.state!='proposed' or not self.approval_checked:
            raise UserError('Lập đề xuất, đọc phương án và tick đồng ý trước khi duyệt tạo báo giá nháp.')
        snapshot=self._check_fresh()
        origin='OLIST-AI-PRODUCT:'+self.request_key
        with self.env.cr.savepoint():
            orders=self.env['sale.order'].search([('origin','=',origin)],limit=2)
            if len(orders)>1: raise UserError('Có nhiều chứng từ cùng mã; cần đối chiếu thủ công.')
            order=orders or self.env['sale.order'].create({**snapshot['values'],'origin':origin,'user_id':self.owner_id.id,'team_id':self.team_id.id or False})
            pricing.check_created(order,snapshot)
            super().write({'state':'done','quote_id':order.id,'approved_by':self.env.uid,'approved_at':fields.Datetime.now()})
        return {'type':'ir.actions.act_window','res_model':'sale.order','view_mode':'form','res_id':order.id,'target':'current'}


class ProductAdviceWizard(models.TransientModel):
    _name='olist.ai.product.advice.wizard'
    _description='Nhập nhu cầu và ngân sách'

    partner_id=fields.Many2one('res.partner',string='Khách DEMO',required=True,domain="[('ref','=like','OLIST-DEMO:%'),('active','=',True)]")
    need=fields.Text('Nhu cầu',required=True)
    intent=fields.Selection([('detect','Tự nhận diện nhóm')]+INTENTS,string='Nhóm nhu cầu',default='detect',required=True)
    quantity=fields.Integer('Số lượng mỗi phương án',default=1,required=True)
    currency_id=fields.Many2one('res.currency',default=lambda s:pricing.pricelist(s.env).currency_id,readonly=True)
    budget=fields.Monetary('Ngân sách gồm thuế',required=True)

    def action_generate(self):
        self.ensure_one(); self.check_access('read')
        advice=self.env['olist.ai.product.advice'].create({key:self[key].id if key=='partner_id' else self[key] for key in ['partner_id','need','intent','quantity','budget']})
        return advice._open_action()
