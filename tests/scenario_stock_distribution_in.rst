==============================
Stock Distribution In Scenario
==============================

Imports::

    >>> import datetime
    >>> from dateutil.relativedelta import relativedelta
    >>> from decimal import Decimal
    >>> from proteus import config, Model
    >>> from trytond.tests.tools import activate_modules
    >>> from trytond.modules.company.tests.tools import create_company, \
    ...     get_company
    >>> from trytond.modules.account.tests.tools import create_fiscalyear, \
    ...     create_chart, get_accounts, create_tax
    >>> from trytond.modules.account_invoice.tests.tools import \
    ...     set_fiscalyear_invoice_sequences, create_payment_term
    >>> today = datetime.date.today()

Activate stock_distribution_in::

    >>> config = activate_modules('stock_distribution_in')

Create company::

    >>> _ = create_company()
    >>> company = get_company()

Reload the context::

    >>> User = Model.get('res.user')
    >>> config._context = User.get_preferences(True, config.context)

Create fiscal year::

    >>> fiscalyear = set_fiscalyear_invoice_sequences(
    ...     create_fiscalyear(company))
    >>> fiscalyear.click('create_period')

Create chart of accounts::

    >>> _ = create_chart(company)
    >>> accounts = get_accounts(company)
    >>> revenue = accounts['revenue']
    >>> expense = accounts['expense']
    >>> cash = accounts['cash']

Create parties::

    >>> Party = Model.get('party.party')
    >>> supplier = Party(name='Supplier')
    >>> supplier.save()
    >>> customer = Party(name='Customer')
    >>> customer.save()

Get stock locations::

    >>> Location = Model.get('stock.location')
    >>> warehouse_loc, = Location.find([('code', '=', 'WH')])
    >>> supplier_loc, = Location.find([('code', '=', 'SUP')])
    >>> customer_loc, = Location.find([('code', '=', 'CUS')])
    >>> output_loc, = Location.find([('code', '=', 'OUT')])
    >>> storage_loc, = Location.find([('code', '=', 'STO')])
    >>> production_loc, = Location.find([('code', '=', 'PROD')])
    >>> input_loc, = Location.find([('code', '=', 'IN')])

Create account category::

    >>> ProductCategory = Model.get('product.category')
    >>> account_category = ProductCategory(name="Account Category")
    >>> account_category.accounting = True
    >>> account_category.account_expense = expense
    >>> account_category.account_revenue = revenue
    >>> account_category.save()

Create product::

    >>> ProductUom = Model.get('product.uom')
    >>> ProductTemplate = Model.get('product.template')
    >>> unit, = ProductUom.find([('name', '=', 'Unit')])
    >>> template = ProductTemplate()
    >>> template.name = 'Product'
    >>> template.default_uom = unit
    >>> template.type = 'goods'
    >>> template.list_price = Decimal('20')
    >>> template.purchasable = True
    >>> template.account_category = account_category
    >>> template.save()
    >>> product, = template.products
    >>> location = product.locations.new()
    >>> location.warehouse = warehouse_loc
    >>> location.location = storage_loc
    >>> product.save()

Create payment term::

    >>> payment_term = create_payment_term()
    >>> payment_term.save()

Create one production in wait state::

    >>> Production = Model.get('production')
    >>> production1 = Production()
    >>> input_move = production1.inputs.new()
    >>> input_move.product = product
    >>> input_move.unit = unit
    >>> input_move.quantity = 5
    >>> input_move.from_location = storage_loc
    >>> input_move.to_location = production_loc
    >>> input_move.planned_date = today
    >>> input_move.effective_date = today
    >>> input_move.company = company
    >>> input_move.unit_price = Decimal('1')
    >>> input_move.currency = company.currency
    >>> production1.click('wait')
    >>> production1.state
    'waiting'

Create another production in draft state::

    >>> production2 = Production()
    >>> input_move = production2.inputs.new()
    >>> input_move.product = product
    >>> input_move.unit = unit
    >>> input_move.quantity = 3
    >>> input_move.from_location = storage_loc
    >>> input_move.to_location = production_loc
    >>> input_move.planned_date = today
    >>> input_move.effective_date = today
    >>> input_move.company = company
    >>> input_move.unit_price = Decimal('1')
    >>> input_move.currency = company.currency
    >>> production2.save()
    >>> production2.state
    'draft'

Create purchase::

    >>> Purchase = Model.get('purchase.purchase')
    >>> PurchaseLine = Model.get('purchase.line')
    >>> purchase = Purchase()
    >>> purchase.party = supplier
    >>> purchase.payment_term = payment_term
    >>> purchase.invoice_method = 'shipment'
    >>> purchase_line = PurchaseLine()
    >>> purchase.lines.append(purchase_line)
    >>> purchase_line.product = product
    >>> purchase_line.quantity = 10
    >>> purchase.click('quote')
    >>> purchase.click('confirm')
    >>> purchase.click('process')
    >>> purchase.state
    'processing'
    >>> len(purchase.moves), len(purchase.shipment_returns), len(purchase.invoices)
    (1, 0, 0)

Create distribution::

    >>> DistributionIn = Model.get('stock.distribution.in')
    >>> StockMove = Model.get('stock.move')
    >>> incoming_move = StockMove(purchase.moves[0].id)
    >>> distribution = DistributionIn()
    >>> distribution.effective_date = today
    >>> distribution.moves.append(incoming_move)
    >>> distribution.click('distribute')
    >>> incoming_move.reload()
    >>> line1, line2, line3 = sorted(incoming_move.distribution_lines,
    ...     key=lambda x: x.production.id if x.production else 1000)
    >>> line1.production.id == production1.id
    True
    >>> line1.quantity
    5.0
    >>> line2.production == production2
    True
    >>> line2.quantity
    3.0
    >>> line3.location == storage_loc
    True
    >>> line3.quantity
    2.0
    >>> distribution.save()

Ensure that a distribution not properly spread cannot be done::

    >>> line1.quantity = 7
    >>> line1.save()
    >>> distribution.click('do')  # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
        ...
    UserError: ...
    >>> distribution.reload()
    >>> distribution.state
    'draft'

Ensure that unlinking a move from the distribution automatically removes its
distribution lines::

    >>> distribution.click('distribute')
    >>> incoming_move.reload()
    >>> incoming_move.distribution_lines != []
    True
    >>> incoming_move.distribution = None
    >>> incoming_move.save()
    >>> incoming_move.distribution_lines
    []
    >>> incoming_move = StockMove(incoming_move.id)
    >>> distribution.moves.append(incoming_move)
    >>> distribution.click('distribute')

Ensure that a distribution cannot be done if there is enough stock::

    >>> move = StockMove()
    >>> move.product = product
    >>> move.from_location = input_loc
    >>> move.to_location = storage_loc
    >>> move.quantity = 5
    >>> move.click('do')
    >>> distribution.click('do')  # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
        ...
    UserError: ...
    >>> move = StockMove()
    >>> move.product = product
    >>> move.from_location = storage_loc
    >>> move.to_location = input_loc
    >>> move.quantity = 5
    >>> move.click('do')

Check that when the distribution is done, everything is correct::

    >>> distribution.click('do')
    >>> distribution.state
    'done'
    >>> distribution.reload()
    >>> incoming_move.reload()
    >>> incoming_move.state
    'done'
    >>> incoming_move.quantity
    8.0
    >>> line1, line2 = incoming_move.distribution_lines
    >>> line1.quantity + line2.quantity
    8.0
    >>> move1, move2 = distribution.moves
    >>> move1.quantity + move2.quantity
    10.0
    >>> move1.state
    'done'
    >>> move1.quantity == sum([x.quantity for x in move1.distribution_lines])
    True
    >>> move2.state
    'done'
    >>> move2.quantity == sum([x.quantity for x in move2.distribution_lines])
    True

Check invoice lines exist::

    >>> purchase.reload()
    >>> purchase.shipment_state
    'received'
    >>> len(purchase.invoices)
    1

Check both productions have been reserved::

    >>> production1.reload()
    >>> production1.state
    'assigned'
    >>> production1.inputs[0].state
    'done'
    >>> production2.reload()
    >>> production2.state
    'assigned'
    >>> production2.inputs[0].state
    'done'
