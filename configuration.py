from trytond.model import fields
from trytond.pyson import Eval
from trytond.pool import PoolMeta, Pool
from trytond.modules.stock.configuration import default_func, default_sequence

__all__ = ['Configuration', 'ConfigurationSequence']


class Configuration(metaclass=PoolMeta):
    __name__ = 'stock.configuration'
    distribution_in_sequence = fields.MultiValue(fields.Many2One('ir.sequence',
        'Supplier Distribution Sequence', domain=[
            ('company', 'in',
                [Eval('context', {}).get('company', -1), None]),
            ('code', '=', 'stock.distribution.in'),
            ], required=True))

    default_distribution_in_sequence = default_func('distribution_in_sequence')

    @classmethod
    def multivalue_model(cls, field):
        if field == 'distribution_in_sequence':
            return Pool().get('stock.configuration.sequence')
        return super(Configuration, cls).multivalue_model(field)


class ConfigurationSequence(metaclass=PoolMeta):
    __name__ = 'stock.configuration.sequence'

    distribution_in_sequence = fields.Many2One('ir.sequence',
        "Supplier Distribution Sequence", required=True,
        domain=[
            ('company', 'in', [Eval('company', -1), None]),
            ('code', '=', 'stock.distribution.in'),
            ],
        depends=['company'])
    default_shipment_in_sequence = default_sequence('sequence_distribution_in')
