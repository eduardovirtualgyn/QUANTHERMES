"""
Testes Unitários do Carregador de Configurações e Pisos Invioláveis de Risco
Arquivo: tests/unit/test_config_loader.py
"""
import pytest
from pydantic import ValidationError
from core.config import (
    load_hermes_config,
    RiskConfig,
    SecurityConfigurationError,
    _HARDCODED_FLOOR,
)


class TestConfigLoader:
    """Valida o carregamento das configurações do sistema e garantia dos pisos de risco."""

    def test_load_official_config(self):
        config = load_hermes_config()
        assert config.system.name == "QUANT_HERMES"
        assert config.risk.risk_percentage == 0.25
        assert config.risk.require_stop_loss is True
        assert "EURUSD" in config.instruments
        assert "XAUUSD" in config.instruments

    def test_risk_floor_constants(self):
        assert _HARDCODED_FLOOR["max_risk_per_trade_pct"] == 0.50
        assert _HARDCODED_FLOOR["max_daily_loss_pct"] == 2.00
        assert _HARDCODED_FLOOR["max_drawdown_limit_pct"] == 8.00
        assert _HARDCODED_FLOOR["mandatory_stop_loss"] is True

    def test_reject_risk_exceeding_hardcoded_floor(self):
        # Tentativa de afrouxar o risco para 0.75% deve ser bloqueada pelas travas do RiskConfig
        with pytest.raises(ValidationError):
            RiskConfig(
                risk_percentage=0.75,  # Piso máximo é 0.50%
                max_risk_percentage_hard_cap=0.50,
            )

    def test_reject_daily_loss_exceeding_hardcoded_floor(self):
        # Tentativa de afrouxar a perda diária para 5.0% deve ser bloqueada
        with pytest.raises(ValidationError):
            RiskConfig(
                risk_percentage=0.25,
                daily_loss_limit_pct=5.0,  # Piso máximo é 2.0%
            )

    def test_reject_emergency_drawdown_exceeding_floor(self):
        # Tentativa de permitir drawdown de 15% deve ser bloqueada
        with pytest.raises(ValidationError):
            RiskConfig(
                risk_percentage=0.25,
                emergency_kill_switch_drawdown_pct=15.0,  # Piso de emergência é 8.0%
            )

    def test_reject_disabling_mandatory_stop_loss(self):
        # Tentativa de operar sem Stop Loss deve ser terminantemente rejeitada
        with pytest.raises((ValidationError, SecurityConfigurationError)):
            RiskConfig(
                risk_percentage=0.25,
                require_stop_loss=False,  # Proibido pela Constituição
            )

    def test_stricter_risk_is_permitted(self):
        # O arquivo YAML pode TORNAR AS REGRAS MAIS RÍGIDAS (ex: reduzir risco para 0.10%)
        safer_config = RiskConfig(
            risk_percentage=0.10,
            daily_loss_limit_pct=1.00,
            weekly_loss_limit_pct=2.00,
            emergency_kill_switch_drawdown_pct=5.00,
        )
        assert safer_config.risk_percentage == 0.10
        assert safer_config.daily_loss_limit_pct == 1.00
