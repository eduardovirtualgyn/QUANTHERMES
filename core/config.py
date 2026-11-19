"""
QUANT HERMES — Carregador de Configurações com Pisos de Risco Invioláveis
Módulo: core.config
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List
import yaml
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv

# Carrega variáveis do .env se existir
load_dotenv()


class SecurityConfigurationError(Exception):
    """Exceção levantada quando uma tentativa de violar os pisos de segurança de risco é detectada."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
# PISOS INVIOLÁVEIS CODIFICADOS NO NÚCLEO (_HARDCODED_FLOOR)
# Nenhuma configuração em YAML, parâmetro de agente ou LLM pode relaxar estes limites.
# ─────────────────────────────────────────────────────────────────────────────
_HARDCODED_FLOOR: Dict[str, float | int | bool] = {
    "max_risk_per_trade_pct": 0.50,       # Piso máximo absoluto: 0.50% de risco por trade
    "max_daily_loss_pct": 2.00,           # Piso máximo de perda diária: 2.00%
    "max_weekly_loss_pct": 4.00,          # Piso máximo de perda semanal: 4.00%
    "max_drawdown_limit_pct": 8.00,       # Piso máximo de drawdown de emergência: 8.00%
    "max_open_positions": 5,              # Máximo de posições simultâneas
    "mandatory_stop_loss": True,          # Stop loss obrigatório em todas as ordens
}


class SystemConfig(BaseModel):
    name: str = "QUANT_HERMES"
    version: str = "0.1.0"
    environment: str = "development"
    timezone: str = "UTC"
    locale: str = "pt_BR"


class ExecutionConfig(BaseModel):
    platform: str = "metatrader5"
    mode: str = "paper"
    single_thread_com: bool = True
    max_retry_attempts: int = 3
    retry_delay_seconds: float = 0.5
    order_timeout_ms: int = 10000


class BrokerConfig(BaseModel):
    """Conta-alvo. ProCent usa moeda USC e pode publicar símbolos com sufixo."""

    name: str = "roboforex_procent"
    account_currency: str = "USC"
    symbol_suffix: str = ""
    symbol_aliases: Dict[str, str] = Field(default_factory=dict)
    max_leverage: int = Field(default=2000, gt=0, le=2000)
    stop_out_level_pct: float = Field(default=30.0, ge=30.0, le=100.0)


class InstrumentConfig(BaseModel):
    category: str
    base_currency: str
    quote_currency: str
    broker_symbols: List[str]
    timeframes: List[str]
    max_spread_pips: float
    pip_size: float
    point_size: float
    min_volume: float
    max_volume: float
    volume_step: float
    typical_spread_price: float = 0.0
    slippage_price: float = 0.0
    swap_long: float = 0.0
    swap_short: float = 0.0
    commission_per_lot: float = 0.0


class RiskConfig(BaseModel):
    risk_percentage: float = Field(default=0.25, ge=0.01, le=0.50)
    max_risk_percentage_hard_cap: float = Field(default=0.50, le=0.50)
    require_stop_loss: bool = True
    min_stop_distance_atr_multiplier: float = 1.0

    max_aggregate_open_risk_pct: float = Field(default=1.00, le=2.00)
    max_open_positions: int = Field(default=3, le=5)
    max_positions_per_symbol: int = 1
    max_correlated_pairs_open: int = 2
    max_correlation_threshold: float = 0.70

    daily_loss_limit_pct: float = Field(default=1.50, le=2.00)
    weekly_loss_limit_pct: float = Field(default=3.00, le=4.00)
    emergency_kill_switch_drawdown_pct: float = Field(default=8.00, le=8.00)

    max_spread_multiplier: float = 2.0
    max_slippage_points: int = 30
    friday_closing_utc_hour: int = 20
    news_blackout_minutes: int = 15
    max_margin_usage_pct: float = Field(default=20.0, gt=0.0, le=80.0)
    stop_out_level_pct: float = Field(default=30.0, ge=30.0, le=100.0)

    @field_validator("risk_percentage")
    @classmethod
    def validate_risk_per_trade(cls, v: float) -> float:
        floor = float(_HARDCODED_FLOOR["max_risk_per_trade_pct"])
        if v > floor:
            raise SecurityConfigurationError(
                f"Violação de Risco Inviolável: risco por operação ({v}%) excede o piso máximo ({floor}%)"
            )
        return v

    @field_validator("daily_loss_limit_pct")
    @classmethod
    def validate_daily_loss(cls, v: float) -> float:
        floor = float(_HARDCODED_FLOOR["max_daily_loss_pct"])
        if v > floor:
            raise SecurityConfigurationError(
                f"Violação de Risco Inviolável: limite diário ({v}%) excede o piso máximo ({floor}%)"
            )
        return v

    @field_validator("emergency_kill_switch_drawdown_pct")
    @classmethod
    def validate_drawdown(cls, v: float) -> float:
        floor = float(_HARDCODED_FLOOR["max_drawdown_limit_pct"])
        if v > floor:
            raise SecurityConfigurationError(
                f"Violação de Risco Inviolável: drawdown limite ({v}%) excede o piso de emergência ({floor}%)"
            )
        return v

    @field_validator("require_stop_loss")
    @classmethod
    def validate_stop_loss_requirement(cls, v: bool) -> bool:
        if not v:
            raise SecurityConfigurationError(
                "Violação de Risco Inviolável: Stop Loss obrigatório não pode ser desativado"
            )
        return v


class HermesConfig(BaseModel):
    system: SystemConfig
    execution: ExecutionConfig
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    instruments: Dict[str, InstrumentConfig]
    risk: RiskConfig
    raw_strategies: Dict[str, Any] = Field(default_factory=dict)
    raw_models: Dict[str, Any] = Field(default_factory=dict)


def load_yaml(file_path: Path) -> dict[str, Any]:
    """Carrega um arquivo YAML retornando um dicionário python."""
    if not file_path.exists():
        raise FileNotFoundError(f"Arquivo de configuração ausente: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_hermes_config(config_dir: str | Path | None = None) -> HermesConfig:
    """
    Carrega todas as configurações do sistema aplicando validação estrita
    e enforcement dos pisos invioláveis de risco.
    """
    if config_dir is None:
        # Padrão: diretório config/ na raiz do projeto
        config_dir = Path(__file__).resolve().parents[1] / "config"
    else:
        config_dir = Path(config_dir)

    sys_raw = load_yaml(config_dir / "system.yaml")
    inst_raw = load_yaml(config_dir / "instruments.yaml")
    strat_raw = load_yaml(config_dir / "strategies.yaml")
    risk_raw = load_yaml(config_dir / "risk.yaml")
    models_raw = load_yaml(config_dir / "models.yaml")

    broker_raw = sys_raw.get("broker", {}) or {}

    # Flatten risk sections to match RiskConfig model
    risk_flat = {}
    if "per_trade" in risk_raw:
        risk_flat.update(risk_raw["per_trade"])
    if "portfolio_limits" in risk_raw:
        risk_flat.update(risk_raw["portfolio_limits"])
    if "drawdown_circuit_breakers" in risk_raw:
        risk_flat.update(risk_raw["drawdown_circuit_breakers"])
    if "execution_filters" in risk_raw:
        risk_flat.update(risk_raw["execution_filters"])

    # Converte instrumentos
    instruments_dict = {}
    for sym, data in inst_raw.get("instruments", {}).items():
        instruments_dict[sym] = InstrumentConfig(**data)

    return HermesConfig(
        system=SystemConfig(**sys_raw.get("system", {})),
        execution=ExecutionConfig(**sys_raw.get("execution", {})),
        broker=BrokerConfig(**broker_raw),
        instruments=instruments_dict,
        risk=RiskConfig(**risk_flat),
        raw_strategies=strat_raw.get("families", {}),
        raw_models=models_raw,
    )

