from trytond.model import fields
from trytond.pyson import Eval, Id
from trytond.pool import PoolMeta, Pool
from trytond.modules.stock.configuration import default_func, default_sequence

__all__ = ['Configuration', 'ConfigurationSequence']


class Configuration(metaclass=PoolMeta):
    __name__ = 'stock.configuration'
    distribution_in_sequence = fields.MultiValue(fields.Many2One('ir.sequence',
        'Supplier Distribution Sequence', domain=[
            ('company', 'in',
                [Eval('context', {}).get('company', -1), None]),
            ('sequence_type', '=', Id('stock_distribution_in',
                        'sequence_type_distribution_in')),
            ], required=True))

    @classmethod
    def multivalue_model(cls, field):
        pool = Pool()
        if field == 'distribution_in_sequence':
            return pool.get('stock.configuration.sequence')
        return super(Configuration, cls).multivalue_model(field)

    default_distribution_in_sequence = default_func('distribution_in_sequence')


class ConfigurationSequence(metaclass=PoolMeta):
    __name__ = 'stock.configuration.sequence'

    distribution_in_sequence = fields.Many2One('ir.sequence',
        "Supplier Distribution Sequence", required=True,
        domain=[
            ('company', 'in', [Eval('company', -1), None]),
            ('sequence_type', '=', Id('stock_distribution_in',
                        'sequence_type_distribution_in')),
            ],
        depends=['company'])

    @classmethod
    def default_distribution_in_sequence(cls):
        pool = Pool()
        ModelData = pool.get('ir.model.data')

        try:
            return ModelData.get_id('stock_distribution_in',
                'sequence_distribution_in')
        except:
            return None

