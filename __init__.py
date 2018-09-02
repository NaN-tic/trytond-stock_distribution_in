# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
from . import configuration
from . import distribution


def register():
    Pool.register(
        configuration.Configuration,
        configuration.ConfigurationSequence,
        distribution.Distribution,
        distribution.DistributionLine,
        distribution.Move,
        distribution.Production,
        distribution.Location,
        module='stock_distribution_in', type_='model')
