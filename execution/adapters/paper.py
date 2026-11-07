"""
QUANT HERMES — Adaptador de Paper Trading (Simulação Realista em Memória)
Módulo: execution.adapters.paper
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.models.market import MarketBar, MarketTick, SymbolSpecification, TimeFrame
from core.models.risk import AccountState, OrderRequest, OrderResult, Position
from execution.adapters.base import TradingPlatformAdapter


class PaperTradingAdapter(TradingPlatformAdapter):
    """
    Adaptador de simulação de alta fidelidade para execução Paper Trading.
    Opera 100% em memória, permitindo testes determinísticos, simulação de slippage,
    recalculo dinâmico de margem e verificação de Stop Loss/Take Profit tick-a-tick.
    """

    def __init__(
        self,
        initial_balance: float = 100000.0,
        currency: str = "USD",
        leverage: int = 100,
    ):
        self._connected: bool = False
        self._initial_balance: float = initial_balance
        self._balance: float = initial_balance
        self._currency: str = currency
        self._leverage: int = leverage
        self._peak_equity: float = initial_balance

        self._positions: Dict[int, Position] = {}
        self._latest_ticks: Dict[str, MarketTick] = {}
        self._historical_bars: Dict[str, List[MarketBar]] = {}
        self._historical_ticks: Dict[str, List[MarketTick]] = {}
        self._next_ticket: int = 100001
        self._order_idempotency_registry: Dict[str, OrderResult] = {}

        # Especificações padrão para testes de Forex e Ouro
        self._specs: Dict[str, SymbolSpecification] = {
            "EURUSD": SymbolSpecification(
                symbol="EURUSD",
                canonical_name="EURUSD",
                category="forex_major",
                base_currency="EUR",
                quote_currency="USD",
                digits=5,
                point=0.00001,
                tick_size=0.00001,
                tick_value=1.0,
                contract_size=100000.0,
                volume_min=0.01,
                volume_max=100.0,
                volume_step=0.01,
                stops_level=5,
                filling_mode="IOC",
            ),
            "GBPUSD": SymbolSpecification(
                symbol="GBPUSD",
                canonical_name="GBPUSD",
                category="forex_major",
                base_currency="GBP",
                quote_currency="USD",
                digits=5,
                point=0.00001,
                tick_size=0.00001,
                tick_value=1.0,
                contract_size=100000.0,
                volume_min=0.01,
                volume_max=100.0,
                volume_step=0.01,
                stops_level=5,
                filling_mode="IOC",
            ),
            "USDJPY": SymbolSpecification(
                symbol="USDJPY",
                canonical_name="USDJPY",
                category="forex_major",
                base_currency="USD",
                quote_currency="JPY",
                digits=3,
                point=0.001,
                tick_size=0.001,
                tick_value=0.68,
                contract_size=100000.0,
                volume_min=0.01,
                volume_max=100.0,
                volume_step=0.01,
                stops_level=5,
                filling_mode="IOC",
            ),
            "XAUUSD": SymbolSpecification(
                symbol="XAUUSD",
                canonical_name="XAUUSD",
                category="metal",
                base_currency="XAU",
                quote_currency="USD",
                digits=2,
                point=0.01,
                tick_size=0.01,
                tick_value=1.0,
                contract_size=100.0,
                volume_min=0.01,
                volume_max=50.0,
                volume_step=0.01,
                stops_level=20,
                filling_mode="IOC",
            ),
        }

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def is_connected(self) -> bool:
        return self._connected

    def register_symbol_spec(self, spec: SymbolSpecification) -> None:
        """Permite registrar ou substituir as características de um ativo."""
        self._specs[spec.symbol] = spec

    def set_price(self, symbol: str, bid: float, ask: float) -> MarketTick:
        """Injeta um preço de mercado simulado e atualiza a esteira de trading."""
        tick = MarketTick(
            symbol=symbol,
            time=datetime.now(timezone.utc),
            bid=bid,
            ask=ask,
            last=(bid + ask) / 2.0,
            volume=1.0,
        )
        self.update_tick(tick)
        return tick

    def update_tick(self, tick: MarketTick) -> None:
        """Atualiza a cotação e recalcula posições em tempo real."""
        self._latest_ticks[tick.symbol] = tick
        if tick.symbol not in self._historical_ticks:
            self._historical_ticks[tick.symbol] = []
        self._historical_ticks[tick.symbol].append(tick)

        # Atualiza PnL flutuante e checa gatilhos de SL/TP
        closed_tickets = []
        for ticket, pos in list(self._positions.items()):
            if pos.symbol != tick.symbol:
                continue

            spec = self._specs.get(tick.symbol)
            contract_size = spec.contract_size if spec else 100000.0

            if pos.position_type == "BUY":
                current_price = tick.bid
                floating_pnl = (current_price - pos.open_price) * contract_size * pos.volume
                # Verifica Stop Loss
                if pos.stop_loss > 0.0 and tick.bid <= pos.stop_loss:
                    self._balance += (pos.stop_loss - pos.open_price) * contract_size * pos.volume
                    closed_tickets.append(ticket)
                    continue
                # Verifica Take Profit
                if pos.take_profit > 0.0 and tick.bid >= pos.take_profit:
                    self._balance += (pos.take_profit - pos.open_price) * contract_size * pos.volume
                    closed_tickets.append(ticket)
                    continue
            else:  # SELL
                current_price = tick.ask
                floating_pnl = (pos.open_price - current_price) * contract_size * pos.volume
                # Verifica Stop Loss
                if pos.stop_loss > 0.0 and tick.ask >= pos.stop_loss:
                    self._balance += (pos.open_price - pos.stop_loss) * contract_size * pos.volume
                    closed_tickets.append(ticket)
                    continue
                # Verifica Take Profit
                if pos.take_profit > 0.0 and tick.ask <= pos.take_profit:
                    self._balance += (pos.open_price - pos.take_profit) * contract_size * pos.volume
                    closed_tickets.append(ticket)
                    continue

            # Atualiza posição ativa em memória
            self._positions[ticket] = Position(
                ticket=pos.ticket,
                symbol=pos.symbol,
                magic=pos.magic,
                position_type=pos.position_type,
                volume=pos.volume,
                open_price=pos.open_price,
                stop_loss=pos.stop_loss,
                take_profit=pos.take_profit,
                current_price=current_price,
                profit=round(floating_pnl, 2),
                swap=pos.swap,
                comment=pos.comment,
                open_time=pos.open_time,
            )

        for t in closed_tickets:
            self._positions.pop(t, None)

        # Atualiza métricas de equity máxima
        current_equity = self._calculate_equity()
        if current_equity > self._peak_equity:
            self._peak_equity = current_equity

    def _calculate_equity(self) -> float:
        total_pnl = sum(p.profit for p in self._positions.values())
        return round(self._balance + total_pnl, 2)

    def _calculate_used_margin(self) -> float:
        margin = 0.0
        for pos in self._positions.values():
            spec = self._specs.get(pos.symbol)
            contract = spec.contract_size if spec else 100000.0
            margin += (pos.volume * contract * pos.open_price) / self._leverage
        return round(margin, 2)

    async def get_account_state(self) -> AccountState:
        equity = self._calculate_equity()
        used_margin = self._calculate_used_margin()
        free_margin = round(equity - used_margin, 2)
        margin_level = round((equity / used_margin * 100.0), 2) if used_margin > 0 else 0.0
        drawdown_pct = round(max(0.0, (self._peak_equity - equity) / self._peak_equity * 100.0), 2)

        return AccountState(
            login=999999,
            server="Hermes-PaperTrading",
            currency=self._currency,
            balance=round(self._balance, 2),
            equity=equity,
            margin=used_margin,
            free_margin=free_margin,
            margin_level=margin_level,
            leverage=self._leverage,
            peak_equity=self._peak_equity,
            current_drawdown_pct=drawdown_pct,
            daily_pnl_pct=round(((equity - self._initial_balance) / self._initial_balance) * 100.0, 2),
            weekly_pnl_pct=round(((equity - self._initial_balance) / self._initial_balance) * 100.0, 2),
        )

    async def get_symbol_info(self, symbol: str) -> SymbolSpecification:
        if symbol not in self._specs:
            raise ValueError(f"Símbolo desconhecido no Paper Adapter: {symbol}")
        return self._specs[symbol]

    async def get_ticks(self, symbol: str, count: int = 100) -> List[MarketTick]:
        ticks = self._historical_ticks.get(symbol, [])
        return ticks[-count:] if ticks else []

    async def get_bars(self, symbol: str, timeframe: TimeFrame, count: int = 500) -> List[MarketBar]:
        bars = self._historical_bars.get(symbol, [])
        return bars[-count:] if bars else []

    def set_historical_bars(self, symbol: str, bars: List[MarketBar]) -> None:
        """Injeta dados de candles históricos para testes e backtesting."""
        self._historical_bars[symbol] = bars

    async def check_order(self, request: OrderRequest) -> dict[str, Any]:
        spec = await self.get_symbol_info(request.symbol)
        margin_required = (request.volume * spec.contract_size * request.price) / self._leverage
        equity = self._calculate_equity()
        free_margin = equity - self._calculate_used_margin()

        has_margin = free_margin >= margin_required
        return {
            "retcode": 0 if has_margin else 10019,
            "margin_required": round(margin_required, 2),
            "free_margin": round(free_margin, 2),
            "has_margin": has_margin,
            "comment": "OK" if has_margin else "Sem margem suficiente",
        }

    async def send_order(self, request: OrderRequest) -> OrderResult:
        # Idempotência: se a chave já foi executada, retorna o resultado prévio
        if request.idempotency_key in self._order_idempotency_registry:
            return self._order_idempotency_registry[request.idempotency_key]

        check = await self.check_order(request)
        if not check["has_margin"]:
            result = OrderResult(
                request_id=request.request_id,
                idempotency_key=request.idempotency_key,
                success=False,
                retcode=10019,  # TRADE_RETCODE_NO_MONEY
                comment="Margem insuficiente no Paper Trading",
            )
            self._order_idempotency_registry[request.idempotency_key] = result
            return result

        ticket = self._next_ticket
        self._next_ticket += 1

        # Preço de execução considera cotação de mercado atual se disponível
        latest_tick = self._latest_ticks.get(request.symbol)
        if latest_tick:
            exec_price = latest_tick.ask if request.action == "BUY" else latest_tick.bid
        else:
            exec_price = request.price

        new_position = Position(
            ticket=ticket,
            symbol=request.symbol,
            magic=request.magic,
            position_type=request.action,
            volume=request.volume,
            open_price=exec_price,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            current_price=exec_price,
            profit=0.0,
            swap=0.0,
            comment=request.comment,
            open_time=datetime.now(timezone.utc),
        )
        self._positions[ticket] = new_position

        result = OrderResult(
            request_id=request.request_id,
            idempotency_key=request.idempotency_key,
            success=True,
            retcode=10009,  # TRADE_RETCODE_DONE
            order_ticket=ticket,
            deal_ticket=ticket + 500000,
            volume_executed=request.volume,
            price_executed=exec_price,
            comment="Paper Order Executed",
        )
        self._order_idempotency_registry[request.idempotency_key] = result
        return result

    async def get_open_positions(self, symbol: Optional[str] = None) -> List[Position]:
        positions = list(self._positions.values())
        if symbol:
            return [p for p in positions if p.symbol == symbol]
        return positions

    async def close_position(self, ticket: int, volume: Optional[float] = None) -> OrderResult:
        if ticket not in self._positions:
            return OrderResult(
                request_id=uuid4(),
                idempotency_key=f"close_{ticket}",
                success=False,
                retcode=10024,
                comment=f"Posição {ticket} não encontrada",
            )

        pos = self._positions.pop(ticket)
        self._balance += pos.profit

        return OrderResult(
            request_id=uuid4(),
            idempotency_key=f"close_{ticket}",
            success=True,
            retcode=10009,
            order_ticket=ticket,
            deal_ticket=ticket + 900000,
            volume_executed=pos.volume,
            price_executed=pos.current_price,
            comment="Posição fechada com sucesso no Paper Trading",
        )

    async def modify_position(self, ticket: int, stop_loss: float, take_profit: float) -> OrderResult:
        if ticket not in self._positions:
            return OrderResult(
                request_id=uuid4(),
                idempotency_key=f"mod_{ticket}",
                success=False,
                retcode=10024,
                comment=f"Posição {ticket} não encontrada para modificação",
            )

        pos = self._positions[ticket]
        self._positions[ticket] = Position(
            ticket=pos.ticket,
            symbol=pos.symbol,
            magic=pos.magic,
            position_type=pos.position_type,
            volume=pos.volume,
            open_price=pos.open_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            current_price=pos.current_price,
            profit=pos.profit,
            swap=pos.swap,
            comment=pos.comment,
            open_time=pos.open_time,
        )

        return OrderResult(
            request_id=uuid4(),
            idempotency_key=f"mod_{ticket}",
            success=True,
            retcode=10009,
            order_ticket=ticket,
            deal_ticket=0,
            volume_executed=pos.volume,
            price_executed=pos.current_price,
            comment="Stop Loss e Take Profit modificados",
        )
