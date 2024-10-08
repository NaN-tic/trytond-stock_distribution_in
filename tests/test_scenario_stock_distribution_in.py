import datetime
import unittest
from decimal import Decimal

from proteus import Model
from trytond.exceptions import UserError
from trytond.modules.account.tests.tools import (create_chart,
                                                 create_fiscalyear,
                                                 get_accounts)
from trytond.modules.account_invoice.tests.tools import (
    create_payment_term, set_fiscalyear_invoice_sequences)
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class Test(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):

        today = datetime.date.today()

        # Activate stock_distribution_in
        config = activate_modules('stock_distribution_in')

        # Create company
        _ = create_company()
        company = get_company()

        # Reload the context
        User = Model.get('res.user')
        config._context = User.get_preferences(True, config.context)

        # Create fiscal year
        fiscalyear = set_fiscalyear_invoice_sequences(
            create_fiscalyear(company))
        fiscalyear.click('create_period')

        # Create chart of accounts
        _ = create_chart(company)
        accounts = get_accounts(company)
        revenue = accounts['revenue']
        expense = accounts['expense']

        # Create parties
        Party = Model.get('party.party')
        supplier = Party(name='Supplier')
        supplier.save()
        customer = Party(name='Customer')
        customer.save()

        # Get stock locations
        Location = Model.get('stock.location')
        warehouse_loc, = Location.find([('code', '=', 'WH')])
        storage_loc, = Location.find([('code', '=', 'STO')])
        production_loc, = Location.find([('code', '=', 'PROD')])
        input_loc, = Location.find([('code', '=', 'IN')])

        # Create account category
        ProductCategory = Model.get('product.category')
        account_category = ProductCategory(name="Account Category")
        account_category.accounting = True
        account_category.account_expense = expense
        account_category.account_revenue = revenue
        account_category.save()

        # Create product
        ProductUom = Model.get('product.uom')
        ProductTemplate = Model.get('product.template')
        unit, = ProductUom.find([('name', '=', 'Unit')])
        template = ProductTemplate()
        template.name = 'Product'
        template.default_uom = unit
        template.type = 'goods'
        template.list_price = Decimal('20')
        template.purchasable = True
        template.account_category = account_category
        template.save()
        product, = template.products
        location = product.locations.new()
        location.warehouse = warehouse_loc
        location.location = storage_loc
        product.save()

        # Create payment term
        payment_term = create_payment_term()
        payment_term.save()

        # Create one production in wait state
        Production = Model.get('production')
        production1 = Production()
        input_move = production1.inputs.new()
        input_move.product = product
        input_move.unit = unit
        input_move.quantity = 5
        input_move.from_location = storage_loc
        input_move.to_location = production_loc
        input_move.planned_date = today
        input_move.effective_date = today
        input_move.company = company
        production1.click('wait')
        self.assertEqual(production1.state, 'waiting')

        # Create another production in draft state
        production2 = Production()
        input_move = production2.inputs.new()
        input_move.product = product
        input_move.unit = unit
        input_move.quantity = 3
        input_move.from_location = storage_loc
        input_move.to_location = production_loc
        input_move.planned_date = today
        input_move.effective_date = today
        input_move.company = company
        production2.save()
        self.assertEqual(production2.state, 'draft')

        # Create purchase
        Purchase = Model.get('purchase.purchase')
        PurchaseLine = Model.get('purchase.line')
        purchase = Purchase()
        purchase.party = supplier
        purchase.payment_term = payment_term
        purchase.invoice_method = 'shipment'
        purchase_line = PurchaseLine()
        purchase.lines.append(purchase_line)
        purchase_line.product = product
        purchase_line.quantity = 10
        purchase_line.unit_price = Decimal('10')
        purchase.click('quote')
        purchase.click('confirm')
        purchase.click('process')
        self.assertEqual(purchase.state, 'processing')
        self.assertEqual(len(purchase.moves), 1)
        self.assertEqual(len(purchase.shipment_returns), 0)
        self.assertEqual(len(purchase.invoices), 0)

        # Create distribution
        DistributionIn = Model.get('stock.distribution.in')
        StockMove = Model.get('stock.move')
        incoming_move = StockMove(purchase.moves[0].id)
        distribution = DistributionIn()
        distribution.effective_date = today
        distribution.moves.append(incoming_move)
        distribution.click('distribute')
        incoming_move.reload()
        line1, line2, line3 = sorted(incoming_move.distribution_lines,
                                     key=lambda x: x.production.id
                                     if x.production else 1000)
        self.assertEqual(line1.production.id, production1.id)
        self.assertEqual(line1.quantity, 5.0)
        self.assertEqual(line2.production, production2)
        self.assertEqual(line2.quantity, 3.0)
        self.assertEqual(line3.location, storage_loc)
        self.assertEqual(line3.quantity, 2.0)

        distribution.save()

        # Ensure that a distribution not properly spread cannot be done
        line1.quantity = 7
        line1.save()

        with self.assertRaises(UserError):
            distribution.click('do')

        distribution.reload()
        self.assertEqual(distribution.state, 'draft')

        # Ensure that unlinking a move from the distribution automatically removes its

        # distribution lines
        distribution.click('distribute')
        incoming_move.reload()
        self.assertNotEqual(incoming_move.distribution_lines, [])

        incoming_move.distribution = None
        incoming_move.save()
        self.assertEqual(incoming_move.distribution_lines, [])

        incoming_move = StockMove(incoming_move.id)
        distribution.moves.append(incoming_move)
        distribution.click('distribute')

        # Ensure that a distribution cannot be done if there is enough stock
        move = StockMove()
        move.product = product
        move.from_location = input_loc
        move.to_location = storage_loc
        move.quantity = 5
        move.click('do')

        with self.assertRaises(UserError):
            distribution.click('do')

        move = StockMove()
        move.product = product
        move.from_location = storage_loc
        move.to_location = input_loc
        move.quantity = 5
        move.click('do')

        # Check that when the distribution is done, everything is correct
        distribution.click('do')
        self.assertEqual(distribution.state, 'done')

        distribution.reload()
        incoming_move.reload()
        self.assertEqual(incoming_move.state, 'done')
        self.assertEqual(incoming_move.quantity, 8.0)

        line1, line2 = incoming_move.distribution_lines
        self.assertEqual(line1.quantity + line2.quantity, 8.0)

        move1, move2 = distribution.moves
        self.assertEqual(move1.quantity + move2.quantity, 10.0)
        self.assertEqual(move1.state, 'done')
        self.assertEqual(
            move1.quantity,
            sum([x.quantity for x in move1.distribution_lines])
        )
        self.assertEqual(move2.state, 'done')
        self.assertEqual(
            move2.quantity,
            sum([x.quantity for x in move2.distribution_lines])
        )

        # Check invoice lines exist
        purchase.reload()
        self.assertEqual(purchase.shipment_state, 'received')
        self.assertEqual(len(purchase.invoices), 1)

        # Check both productions have been reserved
        production1.reload()
        self.assertEqual(production1.state, 'assigned')
        self.assertEqual(production1.inputs[0].state, 'done')

        production2.reload()
        self.assertEqual(production2.state, 'assigned')
        self.assertEqual(production2.inputs[0].state, 'done')
