# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
from trytond.pool import Pool
import configuration
import distribution

def register():
    Pool.register(
        configuration.Configuration,
        distribution.Distribution,
        distribution.DistributionLine,
        distribution.Move,
        distribution.Production,
        distribution.Location,
        module='stock_distribution_in', type_='model')
