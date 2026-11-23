"""Native virtual quotations, saved evidence and local matching for product advice."""
import json
import re
import unicodedata
from pathlib import Path

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError

CATALOG = json.loads((Path(__file__).resolve().parents[1]/'data/advisor_catalog.json').read_text(encoding='utf-8'))
CATEGORIES = {c for value in CATALOG.values() for c in value['categories']}
REASONS = {'category_match': 'Thuộc nhóm nhu cầu đã chọn', 'lower_cost': 'Thuộc mức chi phí thấp trong ngân sách', 'alternative': 'Phương án thay thế trong nhóm nhu cầu'}


def normalized(text):
    return re.sub(r'[^a-z0-9_]+', ' ', ''.join(c for c in unicodedata.normalize('NFD',text.lower().replace('đ','d')) if unicodedata.category(c)!='Mn')).strip()


def category(product):
    slug = normalized(product.categ_id.name or '')
    if slug in CATEGORIES: return slug
    match = re.fullmatch(r'DEMO ([a-z_]+) [a-f0-9]{8}',product.name or '')
    return match[1] if match and match[1] in CATEGORIES else None


def intent_for(need, selected):
    if selected in CATALOG: return selected
    text = ' '+normalized(need)+' '
    found = [key for key,value in CATALOG.items() if any(' '+word+' ' in text for word in value['terms'])]
    if len(found)!=1:
        raise UserError('Chưa xác định được một nhóm nhu cầu. Chọn nhóm bên dưới để tránh gợi ý sai phạm vi.')
    return found[0]


def check_partner(env, partner):
    if not env.user.has_group('sales_team.group_sale_salesman'):
        raise AccessError('Cần quyền nhân viên bán hàng.')
    partner.ensure_one(); partner.check_access('read')
    if not partner.active or not (partner.ref or '').startswith('OLIST-DEMO:') or partner.company_id not in (env.company,env['res.company']):
        raise AccessError('Chỉ chọn khách DEMO được phép đọc trong công ty hiện tại.')


def pricelist(env):
    result=env['product.pricelist'].search([('name','=','OLIST DEMO BRL'),('currency_id.name','=','BRL'),
        ('company_id','in',[False,env.company.id])],limit=2)
    if len(result)!=1 or not result.currency_id.active:
        raise UserError('Cần đúng một bảng giá OLIST DEMO BRL đang hoạt động trong công ty hiện tại.')
    return result


def priced_option(advice, product):
    env=advice.env
    check_partner(env,advice.partner_id)
    product.ensure_one(); product.check_access('read')
    if (not product.active or not product.sale_ok or not (product.default_code or '').startswith('OLIST-DEMO:')
        or product.default_code=='OLIST-DEMO:FREIGHT' or product.company_id not in (env.company,env['res.company'])):
        raise AccessError('Sản phẩm không còn thuộc phạm vi gợi ý.')
    price_list=pricelist(env)
    order=env['sale.order'].new({'partner_id':advice.partner_id.id,'company_id':env.company.id,'pricelist_id':price_list.id,
        'date_order':fields.Datetime.now(),'order_line':[Command.create({'product_id':product.id,'product_uom_qty':advice.quantity})]})
    line=order.order_line
    if order.currency_id!=price_list.currency_id or len(line)!=1:
        raise UserError('Odoo chưa trả cấu hình báo giá hợp lệ.')
    price_date=fields.Date.to_date(order.date_order)
    rates=[]
    rule=line.pricelist_item_id._origin
    position=order.fiscal_position_id._origin
    fixed=bool(rule and rule.compute_price=='fixed')
    for currency in env.company.currency_id | price_list.currency_id:
        rate=env['res.currency.rate'].search([('currency_id','=',currency.id),('name','<=',price_date),
            ('company_id','in',[False,env.company.root_id.id])],order='company_id.id,name desc,id desc',limit=1)
        if env.company.currency_id!=price_list.currency_id and not fixed and (not rate or rate.rate<=0):
            raise UserError('Thiếu tỷ giá cấu hình có hiệu lực để tính giá BRL; hãy kiểm tra bảng giá Odoo.')
        rates.append({'currency':currency.name,'date':str(rate.name) if rate else '', 'rate':rate.rate if rate else None,'write_date':str(rate.write_date) if rate else ''})
    root_taxes=line.tax_ids._origin
    taxes=root_taxes
    pending=taxes.mapped('children_tax_ids')-taxes
    while pending:
        taxes |= pending
        if len(taxes)>100: raise UserError('Nhóm thuế vượt giới hạn đối chiếu.')
        pending=pending.mapped('children_tax_ids')-taxes
    money=lambda value: price_list.currency_id.round(value)
    values={'partner_id':order.partner_id._origin.id,'partner_invoice_id':order.partner_invoice_id._origin.id,'partner_shipping_id':order.partner_shipping_id._origin.id,
        'company_id':env.company.id,'pricelist_id':price_list.id,'fiscal_position_id':position.id or False,
        'order_line':[[0,0,{'product_id':product.id,'product_uom_qty':advice.quantity,'price_unit':line.price_unit,
            'discount':line.discount,'tax_ids':[[6,0,root_taxes.ids]]}]]}
    return {'values':values,'currency':'BRL','unit_price':line.price_unit,'discount':line.discount,
        'subtotal':money(order.amount_untaxed),'tax':money(order.amount_tax),'total':money(order.amount_total),
        'category':category(product),'tax_ids':root_taxes.ids,'price_rule_id':rule.id or False,
        'price_date':str(price_date),'rates':rates,'fixed_price':fixed,
        'source':{'product':str(product.write_date),'template':str(product.product_tmpl_id.write_date),'partner':str(advice.partner_id.write_date),
            'partner_name':advice.partner_id.with_context(lang=False).name,'partner_ref':advice.partner_id.ref or '',
            'pricelist':str(price_list.write_date),'rule':str(rule.write_date) if rule else '',
            'company':str(env.company.write_date),'fiscal_position':str(position.write_date) if position else '',
            'taxes':[[tax.id,str(tax.write_date)] for tax in taxes.sorted('id')]}}


def check_created(order, snapshot):
    values=snapshot['values']; line=order.order_line.filtered(lambda l:not l.display_type)
    expected=values['order_line'][0][2]
    if (order.state!='draft' or len(line)!=1 or order.partner_id.id!=values['partner_id'] or order.company_id.id!=values['company_id']
        or order.partner_invoice_id.id!=values['partner_invoice_id'] or order.partner_shipping_id.id!=values['partner_shipping_id']
        or order.pricelist_id.id!=values['pricelist_id'] or order.currency_id.name!='BRL' or order.fiscal_position_id.id!=(values['fiscal_position_id'] or False)
        or line.product_id.id!=expected['product_id'] or line.product_uom_qty!=expected['product_uom_qty'] or line.price_unit!=expected['price_unit']
        or line.discount!=expected['discount'] or sorted(line.tax_ids.ids)!=sorted(expected['tax_ids'][0][2])
        or any(order.currency_id.compare_amounts(actual,snapshot[key]) for key,actual in [('subtotal',order.amount_untaxed),('tax',order.amount_tax),('total',order.amount_total)])):
        raise UserError('Báo giá vừa tạo chưa khớp phương án đã duyệt; giao dịch được hoàn tác.')
