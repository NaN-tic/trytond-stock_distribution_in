from trytond.model import fields
from trytond.pyson import Eval
from trytond.pool import PoolMeta

__all__ = ['Configuration']


class Configuration:
    __name__ = 'stock.configuration'
    __metaclass__ = PoolMeta
    distribution_in_sequence = fields.Property(fields.Many2One('ir.sequence',
        'Supplier Distribution Sequence', domain=[
            ('company', 'in',
                [Eval('context', {}).get('company', -1), None]),
            ('code', '=', 'stock.distribution.in'),
            ], required=True))
