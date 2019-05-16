from sql.aggregate import Sum
from trytond.model import fields, ModelSQL, ModelView, Workflow
from trytond.pyson import Eval, If, Bool
from trytond.pool import PoolMeta, Pool
from trytond.transaction import Transaction
from trytond.i18n import gettext
from trytond.exceptions import UserError

__all__ = ['Distribution', 'DistributionLine', 'Move', 'Production', 'Location']

STATES = [
    ('draft', 'Draft'),
    ('done', 'Done'),
    ]

# TODO: We should treat stock.distribution.in as a stock.shipment for moves so
# dates are properly set


class Distribution(Workflow, ModelSQL, ModelView):
    'Supplier Distribution'
    __name__ = 'stock.distribution.in'
    _states = {
        'readonly': Eval('state') != 'draft',
        }
    number = fields.Char('Number', readonly=True)
    effective_date = fields.Date('Effective Date', states=_states)
    warehouse = fields.Many2One('stock.location', 'Warehouse', required=True,
        domain=[('type', '=', 'warehouse')], states=_states)
    warehouse_input = fields.Function(fields.Many2One('stock.location',
            'Warehouse Input'),
        'on_change_with_warehouse_input')
    company = fields.Many2One('company.company', 'Company', required=True,
        states=_states,
        domain=[
            ('id', If(Eval('context', {}).contains('company'), '=', '!='),
                Eval('context', {}).get('company', -1)),
            ],
        depends=['state'])
    moves = fields.One2Many('stock.move', 'distribution', 'Moves', add_remove=[
            ('shipment', '=', None),
            ('from_location.type', '=', 'supplier'),
            ('state', '=', 'draft'),
            ('distribution', '=', None),
            ], domain=[
            ('from_location.type', '=', 'supplier'),
            ], states=_states, depends=['state'])
    lines = fields.One2Many('stock.distribution.in.line', 'distribution',
        'Lines', states=_states)
    productions = fields.Many2Many('stock.distribution.in.line',
        'distribution', 'production', 'Productions', readonly=True, context={
            'distribution': Eval('active_id'),
            })
    locations = fields.Many2Many('stock.distribution.in.line', 'distribution',
        'location', 'Locations', readonly=True)
    state = fields.Selection(STATES, 'State', readonly=True, required=True)

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_state():
        return 'draft'

    @classmethod
    def default_warehouse(cls):
        Location = Pool().get('stock.location')
        locations = Location.search(cls.warehouse.domain)
        if len(locations) == 1:
            return locations[0].id

    @classmethod
    def default_warehouse_input(cls):
        warehouse = cls.default_warehouse()
        if warehouse:
            return cls(warehouse=warehouse).on_change_with_warehouse_input()

    @classmethod
    def __setup__(cls):
        super(Distribution, cls).__setup__()
        cls._buttons.update({
                'distribute': {
                    'icon': 'tryton-refresh',
                    'invisible': Eval('state') != 'draft',
                    },
                'do': {
                    'icon': 'tryton-ok',
                    'invisible': Eval('state') != 'draft',
                    }
                })
        cls._transitions |= set((
                ('draft', 'done'),
                ))

    @classmethod
    def validate(cls, distributions):
        super(Distribution, cls).validate(distributions)
        for distribution in distributions:
            distribution.check_duplicates()

    def check_duplicates(self):
        # Ensure there's no other distribution in draft state in the same
        # warehouse
        if self.state != 'draft':
            return
        others = self.search([
                ('state', '=', 'draft'),
                ('warehouse', '=', self.warehouse.id),
                ('id', '!=', self.id),
                ])
        if others:
            raise UserError(gettext(
                'stock_distribution_in.other_draft_distribution',
                    distribution=others[0].rec_name,
                    warehouse=self.warehouse.rec_name,
                    ))

    @classmethod
    def create(cls, vlist):
        pool = Pool()
        Sequence = pool.get('ir.sequence')
        Config = pool.get('stock.configuration')

        vlist = [x.copy() for x in vlist]
        config = Config(1)
        for values in vlist:
            if values.get('number') is None:
                values['number'] = Sequence.get_id(
                    config.distribution_in_sequence)
        return super(Distribution, cls).create(vlist)

    @classmethod
    def copy(cls, distributions, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('number')
        default.setdefault('moves', None)
        default.setdefault('lines', None)
        default.setdefault('productions', None)
        default.setdefault('locations', None)
        default.setdefault('state', 'draft')
        return super(Distribution, cls).copy(distributions, default)

    @classmethod
    def delete(cls, distributions):
        for distribution in distributions:
            if distribution.state == 'done':
                raise UserError(gettext(
                    'stock_distribution_in.cannot_delete_done',
                    distribution=distribution.rec_name))
        super(Distribution, cls).delete(distributions)

    @fields.depends('warehouse')
    def on_change_with_warehouse_input(self, name=None):
        if self.warehouse:
            return self.warehouse.input_location.id

    @classmethod
    @ModelView.button
    def distribute(cls, distributions):
        pool = Pool()
        Line = pool.get('stock.distribution.in.line')
        Move = pool.get('stock.move')

        to_remove = []
        for distribution in distributions:
            to_remove += [x for x in distribution.lines]
        Line.delete(to_remove)

        table = Move.__table__()
        # TODO: planned_date may potentially be different in two different
        # target moves for the same production.
        query = table.select(
            table.product,
            table.production_input,
            Sum(table.internal_quantity),
            group_by=(table.product, table.production_input,
                table.planned_date),
            where=(table.state == 'draft') & (table.production_input != None),
            order_by=table.planned_date)
        cursor = Transaction().connection.cursor()
        cursor.execute(*query)
        target_moves = {}
        for record in cursor.fetchall():
            target_moves.setdefault(record[0], []).append({
                    'production': record[1],
                    'quantity': record[2],
                    })

        lines = []
        for distribution in distributions:
            for move in distribution.moves:
                remaining = move.quantity
                for target_move in target_moves.get(move.product.id, []):
                    if remaining <= 0:
                        break
                    quantity = min(remaining, target_move['quantity'])
                    if quantity <= 0:
                        continue
                    target_move['quantity'] -= quantity
                    line = Line()
                    line.distribution = distribution
                    line.move = move
                    line.quantity = quantity
                    line.production = target_move['production']
                    lines.append(line)
                    remaining -= quantity
                if remaining:
                    target_location = distribution.warehouse.storage_location
                    for location in move.product.locations:
                        if location.warehouse == distribution.warehouse:
                            target_location = location.location
                            break
                    line = Line()
                    line.distribution = distribution
                    line.move = move
                    line.quantity = remaining
                    line.location = target_location
                    lines.append(line)

        Line.create([x._save_values for x in lines])

    @classmethod
    @ModelView.button
    @Workflow.transition('done')
    def do(cls, distributions):
        pool = Pool()
        Move = pool.get('stock.move')
        Date = pool.get('ir.date')
        Production = pool.get('production')
        Line = pool.get('stock.distribution.in.line')
        PurchaseLine = pool.get('purchase.line')
        Purchase = pool.get('purchase.purchase')

        to_save = []
        to_copy = []
        to_copy_lines = []
        purchase_ids = set()
        inputs = {}
        for distribution in distributions:
            mismatches = []
            for move in distribution.moves:
                to_save.append(move)
                quantity = 0.0
                move_quantity = move.quantity
                if isinstance(move.origin, PurchaseLine):
                    purchase_ids.add(move.origin.purchase.id)

                locations = {}
                for line in move.distribution_lines:
                    quantity += line.quantity

                    if line.production:
                        inputs.setdefault(line.production.id,
                            {}).setdefault(line.move.product.id, 0.0)
                        inputs[line.production.id][line.move.product.id] += (
                            line.quantity)

                    location = line.location or distribution.warehouse_input
                    locations.setdefault(location, {
                            'quantity': 0.0,
                            'lines': [],
                            })
                    locations[location]['quantity'] += line.quantity
                    locations[location]['lines'].append(line)

                # Ensure move distribution line quantities match moves
                # quantities
                if move_quantity != quantity:
                    mismatches.append({
                            'move': move.rec_name,
                            'move_quantity': move_quantity,
                            'accumulated_quantity': quantity,
                            })
                    if len(mismatches) > 10:
                        break

                first = True
                for location, data in locations.items():
                    if first:
                        first = False
                        move.quantity = data['quantity']
                        move.to_location = location
                        continue
                    to_copy.append(move)
                    to_copy_lines.append(line)


            if mismatches:
                raise UserError(gettext(
                    'stock_distribution_in.move_quantity_mismatch',
                        distribution=distribution.rec_name,
                        moves='\n'.join([ '%s: %.0f != %.0f' % (x['move'],
                                    x['move_quantity'],
                                    x['accumulated_quantity'])
                                for x in mismatches]),
                        ))

        new_moves = []
        for move, line in zip(to_copy, to_copy_lines):
            new, = Move.copy([move])
            new_moves.append(new)
            new.distribution = move.distribution
            new.quantity = line.quantity
            new.to_location = line.location or move.to_location
            new.origin = move.origin
            line.move = new

        Move.save(new_moves)
        Line.save(to_copy_lines)

        Move.do(to_save + new_moves)
        cls.write([x for x in distributions if not x.effective_date], {
                'effective_date': Date.today(),
                })

        productions = Production.browse(inputs.keys())
        Production.wait(productions)
        to_assign = []
        move_quantities = {}
        for production in productions:
            for input_ in production.inputs:
                if input_.state != 'draft':
                    continue
                quantity = inputs[production.id].get(input_.product.id, 0.0)
                if quantity > 0.0:
                    quantity = min(input_.quantity, quantity)
                    if quantity < input_.quantity:
                        moves = input_.split(quantity, input_.uom, count=1)
                        for move in moves:
                            if move.quantity == quantity:
                                break
                    else:
                        move = input_
                    move.from_location = (
                        production.warehouse.input_location.id)
                    move.save()
                    to_assign.append(move)
                    move_quantities[move.id] = move.quantity
                    inputs[production.id][input_.product.id] -= quantity
        if to_assign:
            # By assigning move by move instead of using production's
            # assign_try we intend to prevent cases in which a product is
            # reserved by the wrong production
            #
            # For example if production A requires product 1 and 2 but only
            # product 1 has been distributed to it. And the distribution has
            # distributed product 2 to another production B, then by running
            # assign_try on production A first, would probably mean that
            # production A also assigns product 2, which is wrong.
            Move.assign_try(to_assign)
            to_do = []
            not_assigned_quantities = ''
            for move in to_assign:
                if move.quantity == move_quantities[move.id]:
                    to_do.append(move)
                else:
                    not_assigned_quantities = ('\n' +
                        move.from_location.rec_name + ': ' +
                        move.product.rec_name + ': ' + str(
                            move_quantities[move.id]))
            if not_assigned_quantities:
                raise UserError(
                    gettext('stock_distribution_in.not_assigned_quantities',
                    distribution=distribution.rec_name,
                    quantities=not_assigned_quantities))
            else:
                Move.do(to_do)

            # Once individual moves have been assigned, we can safely run
            # assign_try
            for production in productions:
                # We must assign production by production as assign_try()
                # only updates production states if all moves of all
                # productions are assigned
                # TODO: That should probably be fixed in core
                Production.assign_try([production])

        Purchase.process(Purchase.browse(purchase_ids))


class DistributionLine(ModelSQL, ModelView):
    'Distribution In Line'
    __name__ = 'stock.distribution.in.line'
    _states = {
        'readonly': Eval('distribution_state') != 'draft',
        }
    _depends = ['distribution_state']

    distribution = fields.Function(fields.Many2One('stock.distribution.in',
            'Distribution'), 'get_distribution', searcher='search_distribution')
    move = fields.Many2One('stock.move', 'Move', required=True, states=_states,
        depends=_depends)
    quantity = fields.Float('Quantity', required=True, states=_states,
        digits=(16, Eval('uom_digits', 2)), depends=_depends + ['uom_digits'])
    uom = fields.Function(fields.Many2One('product.uom', 'UoM'), 'get_uom')
    uom_digits = fields.Function(fields.Integer('UoM Digits'),
        'on_change_with_uom_digits')
    production = fields.Many2One('production', 'Production', states={
            'readonly': ((Eval('distribution_state') != 'draft')
                | (Bool(Eval('location')) == True))
            }, depends=['distribution_state', 'location'])
    location = fields.Many2One('stock.location', 'Location', domain=[
            ('type', 'in', ['storage', 'view']),
            ], states={
            'readonly': ((Eval('distribution_state') != 'draft')
                | (Bool(Eval('production')) == True))
            }, depends=['distribution_state', 'production'])
    distribution_state = fields.Function(fields.Selection(STATES,
                'Distribution State'), 'on_change_with_distribution_state')

    @classmethod
    def validate(cls, lines):
        for line in lines:
            line.check_production_location()

    def check_production_location(self):
        if self.production and self.location:
            raise UserError(gettext(
                'stock_distribution_in.only_production_or_location',
                    line=self.rec_name))
        if not self.production and not self.location:
            raise UserError(gettext(
                'stock_distribution_in.empty_production_and_location',
                    line=self.rec_name))

    def get_distribution(self, name):
        return self.move.distribution.id if self.move.distribution else None

    @classmethod
    def search_distribution(cls, name, clause):
        return [('move.' + clause[0],) + clause[1:]]

    def get_uom(self, name):
        return self.move.uom.id

    @fields.depends('move')
    def on_change_with_uom_digits(self, name=None):
        if self.move and self.move.uom:
            return self.move.uom.digits
        return 2

    @fields.depends('move')
    def on_change_with_distribution_state(self, name=None):
        if self.move and self.move.distribution:
            return self.move.distribution.state
        return 'draft'


class Move(metaclass=PoolMeta):
    __name__ = 'stock.move'

    distribution = fields.Many2One('stock.distribution.in', 'Distribution')
    distribution_lines = fields.One2Many('stock.distribution.in.line', 'move',
        'Distribution Lines')
    distribution_productions = fields.Function(fields.Text(
            'Distribution Productions'), 'get_distribution_productions')
    distribution_locations = fields.Function(fields.Text(
            'Distribution Locations'), 'get_distribution_locations')

    @classmethod
    def write(cls, *args):
        """
        When a stock move is unlinked from a distribution, delete all
        distribution lines linked to the move.
        """
        DistributionLine = Pool().get('stock.distribution.in.line')
        to_delete = []
        actions = iter(args)
        for moves, values in zip(actions, actions):
            if 'distribution' in values and not values['distribution']:
                for move in moves:
                    to_delete += move.distribution_lines
        if to_delete:
            DistributionLine.delete(DistributionLine.browse(to_delete))
        super(Move, cls).write(*args)

    @classmethod
    def copy(cls, moves, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('distribution', None)
        default.setdefault('distribution_lines', None)
        return super(Move, cls).copy(moves, default)

    def get_distribution_productions(self, name):
        return '\n'.join(['%.0f     %s' % (x.quantity, x.production.rec_name)
                for x in self.distribution_lines if x.production])

    def get_distribution_locations(self, name):
        return '\n'.join(['%.0f     %s' % (x.quantity, x.location.rec_name)
                for x in self.distribution_lines if x.location])


class Production(metaclass=PoolMeta):
    __name__ = 'production'

    distribution_lines = fields.One2Many('stock.distribution.in.line',
        'production', 'Distribution Lines')
    distribution_products = fields.Function(fields.Text(
            'Distribution Products'), 'get_distribution_products')
    distribution_assigned_products = fields.Function(fields.Text(
            'Other Assigned Products'), 'get_distribution_assigned_products')
    distribution_pending_products = fields.Function(fields.Text(
            'Other Pending Products'), 'get_distribution_pending_products')

    @classmethod
    def copy(cls, productions, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('distribution_lines', None)
        return super(Production, cls).copy(productions, default)

    def get_distribution_products(self, name):
        current_distribution = Transaction().context.get('distribution')
        return '\n'.join(['%.0f     %s' % (x.quantity, x.move.product.rec_name)
                for x in self.distribution_lines
                if x.distribution.id == current_distribution])

    def get_distribution_assigned_products(self, name):
        pool = Pool()
        Move = pool.get('stock.move')
        Location = pool.get('stock.location')

        locations = Location.search([
                ('parent', 'child_of', self.warehouse.storage_location.id),
                ])
        moves = Move.search([
                ('production_input', '=', self.id),
                ('from_location', 'in', [x.id for x in locations]),
                ('state', '=', 'assigned'),
                ])
        products = {}
        for move in moves:
            products.setdefault(move.product, 0.0)
            products[move.product] += move.internal_quantity
        for line in self.distribution_lines:
            if line.distribution_state != 'done':
                continue
            product = line.move.product
            if not product in products:
                continue
            products[product] -= line.quantity
        return '\n'.join(['%.0f     %s' % (q, p.rec_name) for p, q in
                products.items() if q > 0])

    def get_distribution_pending_products(self, name):
        pool = Pool()
        Move = pool.get('stock.move')
        Location = pool.get('stock.location')

        locations = Location.search([
                ('parent', 'child_of', self.warehouse.storage_location.id),
                ])
        moves = Move.search([
                ('production_input', '=', self.id),
                ('from_location', 'in', [x.id for x in locations]),
                ('state', '=', 'draft'),
                ])
        products = {}
        for move in moves:
            products.setdefault(move.product, 0.0)
            products[move.product] += move.internal_quantity
        for line in self.distribution_lines:
            product = line.move.product
            if not product in products:
                continue
            products[product] -= line.quantity
        return '\n'.join(['%.0f     %s' % (q, p.rec_name) for p, q in
                products.items() if q > 0])


class Location(metaclass=PoolMeta):
    __name__ = 'stock.location'

    distribution_lines = fields.One2Many('stock.distribution.in.line',
        'location', 'Distribution Lines')
    distribution_products = fields.Function(fields.Text(
            'Distribution Products'), 'get_distribution_products')

    @classmethod
    def copy(cls, locations, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('distribution_lines', None)
        return super(Location, cls).copy(locations, default)

    def get_distribution_products(self, name):
        return '\n'.join(['%.0f     %s' % (x.quantity, x.move.product.code) for
                x in self.distribution_lines])
