# -*- encoding: utf-8 -*-
##############################################################################
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see http://www.gnu.org/licenses/.
#
##############################################################################

from openerp import models, fields, api
from dateutil.relativedelta import relativedelta


class WizLoadPurchaseFromPlan(models.TransientModel):

    _name = 'wiz.load.purchase.from.plan'

    def _get_default_partner(self):
        model = self.env.context.get('active_model', False)
        partner = False
        if model == 'purchase.order':
            record = self.env[model].browse(self.env.context.get('active_id'))
            partner = record.partner_id
        return partner

    def _get_default_purchase(self):
        model = self.env.context.get('active_model', False)
        purchase = False
        if model == 'purchase.order':
            record = self.env[model].browse(self.env.context.get('active_id'))
            purchase = record.id
        return purchase

    def _get_default_date_from(self):
        model = self.env.context.get('active_model', False)
        record = self.env[model].browse(self.env.context.get('active_id'))
        date_from = False
        if model == 'purchase.order':
            date_from = record.date_order
        elif model == 'procurement.plan':
            date_from = fields.Date.from_string(record.from_date).replace(
                year=fields.Date.from_string(record.from_date).year-1)
        return date_from

    def _get_default_date_to(self):
        model = self.env.context.get('active_model', False)
        record = self.env[model].browse(self.env.context.get('active_id'))
        date_to = False
        if model == 'purchase.order':
            date_to = record.date_order
        elif model == 'procurement.plan':
            date_to = fields.Date.from_string(record.to_date).replace(
                year=fields.Date.from_string(record.to_date).year-1)
        return date_to

    partner_id = fields.Many2one("res.partner", string="Supplier",
                                 default=_get_default_partner)
    date_from = fields.Date(string="Date from", default=_get_default_date_from)
    date_to = fields.Date(string="Date to", default=_get_default_date_to)
    purchase_id = fields.Many2one(
        "purchase.order", "Purchase", default=_get_default_purchase)
    product_categ_id = fields.Many2one("product.category", string="Category")
    product_tmpl_id = fields.Many2one("product.template", string="Template")
    product_id = fields.Many2one("product.product", string="Product")
    factor = fields.Float(string="Factor", default=1)

    @api.onchange('purchase_id')
    def purchase_onchange(self):
        if self.purchase_id:
            self.partner_id = self.purchase_id.partner_id.id
            self.date_from = self.purchase_id.date_order
            self.date_to = self.purchase_id.date_order

    @api.multi
    def load_purchases(self):
        self.ensure_one()
        procurement_obj = self.env['procurement.order']
        plan = self.env['procurement.plan'].browse(
            self.env.context['active_id'])
        purchase_lines = self.get_purchase_lines()
        date_list = self.get_date_list(plan)
        date_start = fields.Date.from_string(self.date_from)
        date_end = fields.Date.from_string(self.date_to)
        month_count = ((date_end.year - date_start.year) * 12 +
                       date_end.month - date_start.month + 1)
        result = self.match_purchases(purchase_lines, self.factor)
        for date in date_list:
            for partner in result.keys():
                for product in result[partner].keys():
                    prod_vals = result[partner][product]
                    vals = {'name': plan.name,
                            'origin': plan.sequence,
                            'product_id': product,
                            'plan': plan.id,
                            'main_project_id': plan.project_id.id,
                            'product_qty': prod_vals['qty'] / month_count,
                            'warehouse_id': plan.warehouse_id.id,
                            'location_id':  plan.warehouse_id.lot_stock_id.id,
                            'date_planned': date
                            }
                    vals.update(
                        procurement_obj.onchange_product_id(product)['value'])
                    procurement_obj.create(vals)
        return True

    @api.multi
    def get_purchase_lines(self):
        purchase_line_obj = self.env['purchase.order.line']
        purchase_obj = self.env['purchase.order']
        product_obj = self.env['product.product']
        self.ensure_one()
        purchases = []
        if self.purchase_id:
            purchases = self.purchase_id
        else:
            purchase_domain = [('date_order', '>=', self.date_from),
                               ('date_order', '<=', self.date_to)]
            if self.partner_id:
                purchase_domain += [('partner_id', '=', self.partner_id.id)]
            purchases = purchase_obj.search(purchase_domain)
        purchase_line_domain = [('order_id', 'in', purchases.ids)]
        if self.product_id:
            purchase_line_domain += [('product_id', '=', self.product_id.id)]
        elif self.product_tmpl_id:
            purchase_line_domain += [
                ('product_id', 'in',
                 self.product_tmpl_id.product_variant_ids.ids)]
        elif self.product_categ_id:
            products = product_obj.search([('categ_id', '=',
                                            self.product_categ_id.id)])
            purchase_line_domain += [('product_id', 'in', products.ids)]
        purchase_lines = purchase_line_obj.search(purchase_line_domain)
        return purchase_lines

    @api.multi
    def get_date_list(self, plan):
        self.ensure_one()
        date_list = []
        date_start = fields.Date.from_string(plan.from_date)
        date_end = fields.Date.from_string(plan.to_date)
        month_count = ((date_end.year - date_start.year) * 12 +
                       date_end.month - date_start.month)
        date = '-'.join([str(date_start.year), str(date_start.month), str(1)])
        first_date = fields.Date.from_string(date)
        date_list.append(date)
        while month_count:
            next_date = first_date + relativedelta(months=month_count)
            date_list.append(fields.Date.to_string(next_date))
            month_count -= 1
        return date_list

    @api.multi
    def match_purchases(self, purchases, factor):
        self.ensure_one()
        res = {}
        for purchase in purchases:
            product = purchase.product_id.id
            partner = self.partner_id.id
            if partner not in res:
                res[partner] = {}
            if product not in res[partner]:
                res[partner][product] = {'qty': 0.0, 'amount': 0.0}
            product_dict = res[partner][product]
            sum_qty = product_dict['qty'] + purchase.product_qty
            product_dict['qty'] = sum_qty * factor
        return res
