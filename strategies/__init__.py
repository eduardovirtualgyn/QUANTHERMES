"""
QUANT HERMES — Módulo de Estratégias Quantitativas
Módulo: strategies
"""
from strategies.base import BaseStrategy
from strategies.breakout.volatility_breakout import VolatilityBreakoutStrategy
from strategies.mean_reversion.statistical_reversion import StatisticalMeanReversionStrategy
from strategies.momentum.momentum_surge import MomentumSurgeStrategy
from strategies.pullback.trend_pullback import TrendPullbackStrategy
from strategies.scalping.micro_momentum import MicroMomentumScalpingStrategy
from strategies.smc.structure_break import SMCStructureStrategy
from strategies.swing.macro_swing import MacroSwingStrategy

__all__ = [
    "BaseStrategy",
    "MicroMomentumScalpingStrategy",
    "VolatilityBreakoutStrategy",
    "MomentumSurgeStrategy",
    "TrendPullbackStrategy",
    "StatisticalMeanReversionStrategy",
    "SMCStructureStrategy",
    "MacroSwingStrategy",
]
