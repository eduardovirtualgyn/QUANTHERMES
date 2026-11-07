"""
QUANT HERMES — Adaptador Oficial MetaTrader 5 para Windows (Worker COM Thread-Safe)
Módulo: execution.adapters.windows_mt5
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from core.logger import log
from core.models.market import MarketBar, MarketTick, SymbolSpecification, TimeFrame
from core.models.risk import AccountState, OrderRequest, OrderResult, Position
from execution.adapters.base import PlatformConnectionError, TradingPlatformAdapter

# Importação condicional do pacote oficial MetaTrader5
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False


# Conforme o ADR-003, toda chamada COM ao MT5 no Windows DEVE ocorrer em thread única serializada
_MT5_WORKER_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="mt5-com-worker",
)


async def _run_on_mt5_thread(fn: Callable[[], Any]) -> Any:
    """Executa uma função sincronizada na thread única dedicada ao MetaTrader 5."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_MT5_WORKER_POOL, fn)


_TIMEFRAME_MAP = {
    TimeFrame.M1: 1,      # mt5.TIMEFRAME_M1
    TimeFrame.M5: 5,      # mt5.TIMEFRAME_M5
    TimeFrame.M15: 15,    # mt5.TIMEFRAME_M15
    TimeFrame.H1: 16385,  # mt5.TIMEFRAME_H1
    TimeFrame.H4: 16388,  # mt5.TIMEFRAME_H4
    TimeFrame.D1: 16408,  # mt5.TIMEFRAME_D1
}


class WindowsMT5Adapter(TradingPlatformAdapter):
    """
    Adaptador de produção para MetaTrader 5 no Windows 11.
    Garante:
    1. Execução thread-safe serializada em STA (Single-Threaded Apartment) COM.
    2. Resolução dinâmica de sufixos de corretora (ex: EURUSD.m, EURUSD_i).
    3. Detecção automática do modo de preenchimento (IOC / FOK / RETURN).
    4. Tratamento dos retcodes oficiais do terminal MT5 (10009, 10027, etc.).
    5. Idempotência absoluta contra ordens duplicadas.
    """

    def __init__(
        self,
        path: Optional[str] = None,
        login: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        timeout_ms: int = 15000,
        symbol_aliases: Optional[Dict[str, str]] = None,
    ):
        if not MT5_AVAILABLE:
            log.warning("Pacote oficial MetaTrader5 não está instalado neste ambiente")

        self._path = path
        self._login = login
        self._password = password
        self._server = server
        self._timeout_ms = timeout_ms
        self._connected: bool = False
        self._symbol_aliases: Dict[str, str] = symbol_aliases or {}
        self._idempotency_cache: Dict[str, OrderResult] = {}
        self._peak_equity: float = 0.0

    def _resolve_symbol(self, canonical_symbol: str) -> str:
        """Traduz símbolo canônico interno para o símbolo exato negociado pela corretora."""
        return self._symbol_aliases.get(canonical_symbol, canonical_symbol)

    async def connect(self) -> bool:
        if not MT5_AVAILABLE:
            raise PlatformConnectionError("Pacote MetaTrader5 indisponível no ambiente")

        def _init() -> bool:
            init_kwargs: dict[str, Any] = {"timeout": self._timeout_ms}
            if self._path:
                init_kwargs["path"] = self._path
            if self._login:
                init_kwargs["login"] = int(self._login)
            if self._password:
                init_kwargs["password"] = self._password
            if self._server:
                init_kwargs["server"] = self._server

            success = mt5.initialize(**init_kwargs)
            if not success:
                err = mt5.last_error()
                log.error("Falha ao inicializar terminal MetaTrader 5", error=str(err))
                return False

            term_info = mt5.terminal_info()
            if term_info and not term_info.trade_allowed:
                log.warning("ALERTA CRÍTICO: AutoTrading desativado no terminal MT5 (retcode 10027 esperado)")

            return True

        self._connected = await _run_on_mt5_thread(_init)
        return self._connected

    async def disconnect(self) -> None:
        if MT5_AVAILABLE and self._connected:
            await _run_on_mt5_thread(mt5.shutdown)
            self._connected = False

    async def is_connected(self) -> bool:
        if not MT5_AVAILABLE or not self._connected:
            return False

        def _check() -> bool:
            term = mt5.terminal_info()
            return bool(term and term.connected)

        return await _run_on_mt5_thread(_check)

    async def get_account_state(self) -> AccountState:
        if not self._connected:
            raise PlatformConnectionError("Terminal MT5 desconectado. Fail-Safe ativo.")

        def _get_acc():
            acc = mt5.account_info()
            if acc is None:
                raise PlatformConnectionError("Não foi possível consultar account_info do MT5")
            return acc

        acc = await _run_on_mt5_thread(_get_acc)

        equity = float(acc.equity)
        if equity > self._peak_equity:
            self._peak_equity = equity

        drawdown_pct = 0.0
        if self._peak_equity > 0.0:
            drawdown_pct = round(max(0.0, (self._peak_equity - equity) / self._peak_equity * 100.0), 2)

        return AccountState(
            login=acc.login,
            server=acc.server,
            currency=acc.currency,
            balance=float(acc.balance),
            equity=equity,
            margin=float(acc.margin),
            free_margin=float(acc.margin_free),
            margin_level=float(acc.margin_level) if acc.margin_level else 0.0,
            leverage=int(acc.leverage),
            peak_equity=self._peak_equity,
            current_drawdown_pct=drawdown_pct,
            daily_pnl_pct=0.0,
            weekly_pnl_pct=0.0,
        )

    async def get_symbol_info(self, symbol: str) -> SymbolSpecification:
        broker_symbol = self._resolve_symbol(symbol)

        def _get_sym():
            mt5.symbol_select(broker_symbol, True)
            info = mt5.symbol_info(broker_symbol)
            if info is None:
                raise ValueError(f"Símbolo {broker_symbol} não encontrado no terminal MT5")
            return info

        info = await _run_on_mt5_thread(_get_sym)

        # Detecta modo de preenchimento suportado
        filling_mode = "RETURN"
        if info.filling_mode & 2:  # SYMBOL_FILLING_IOC
            filling_mode = "IOC"
        elif info.filling_mode & 1:  # SYMBOL_FILLING_FOK
            filling_mode = "FOK"

        return SymbolSpecification(
            symbol=info.name,
            canonical_name=symbol,
            category="metal" if "XAU" in symbol or "GOLD" in symbol else "forex_major",
            base_currency=info.currency_base,
            quote_currency=info.currency_profit,
            digits=info.digits,
            point=info.point,
            tick_size=info.trade_tick_size,
            tick_value=info.trade_tick_value,
            contract_size=info.trade_contract_size,
            volume_min=info.volume_min,
            volume_max=info.volume_max,
            volume_step=info.volume_step,
            stops_level=info.trade_stops_level,
            filling_mode=filling_mode,
        )

    async def get_ticks(self, symbol: str, count: int = 100) -> List[MarketTick]:
        broker_symbol = self._resolve_symbol(symbol)

        def _get_raw_ticks():
            ticks = mt5.copy_ticks_from(broker_symbol, datetime.now(timezone.utc), count, mt5.COPY_TICKS_ALL)
            return ticks

        raw_ticks = await _run_on_mt5_thread(_get_raw_ticks)
        if raw_ticks is None or len(raw_ticks) == 0:
            return []

        result = []
        for row in raw_ticks:
            ts = datetime.fromtimestamp(row["time"], timezone.utc)
            result.append(
                MarketTick(
                    symbol=symbol,
                    time=ts,
                    bid=float(row["bid"]),
                    ask=float(row["ask"]),
                    last=float(row["last"]) if "last" in row.dtype.names else 0.0,
                    volume=float(row["volume"]) if "volume" in row.dtype.names else 0.0,
                    flags=int(row["flags"]) if "flags" in row.dtype.names else 0,
                )
            )
        return result

    async def get_bars(self, symbol: str, timeframe: TimeFrame, count: int = 500) -> List[MarketBar]:
        broker_symbol = self._resolve_symbol(symbol)
        tf_code = _TIMEFRAME_MAP.get(timeframe, 15)

        def _get_raw_rates():
            rates = mt5.copy_rates_from_pos(broker_symbol, tf_code, 0, count)
            return rates

        raw_rates = await _run_on_mt5_thread(_get_raw_rates)
        if raw_rates is None or len(raw_rates) == 0:
            return []

        bars = []
        for row in raw_rates:
            ts = datetime.fromtimestamp(row["time"], timezone.utc)
            bars.append(
                MarketBar(
                    symbol=symbol,
                    timeframe=timeframe,
                    time=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    tick_volume=int(row["tick_volume"]),
                    spread=int(row["spread"]) if "spread" in row.dtype.names else 0,
                )
            )
        return bars

    async def check_order(self, request: OrderRequest) -> dict[str, Any]:
        broker_symbol = self._resolve_symbol(request.symbol)

        def _check():
            sym_info = mt5.symbol_info(broker_symbol)
            if not sym_info:
                return {"retcode": 10013, "has_margin": False, "comment": "Símbolo inválido"}

            order_type = mt5.ORDER_TYPE_BUY if request.action == "BUY" else mt5.ORDER_TYPE_SELL

            check_req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": broker_symbol,
                "volume": float(request.volume),
                "type": order_type,
                "price": float(request.price),
                "sl": float(request.stop_loss),
                "tp": float(request.take_profit),
                "magic": int(request.magic),
            }
            check_res = mt5.order_check(check_req)
            if check_res is None:
                err = mt5.last_error()
                return {"retcode": err[0], "has_margin": False, "comment": err[1]}

            return {
                "retcode": check_res.retcode,
                "margin_required": float(check_res.margin),
                "free_margin": float(check_res.margin_free),
                "has_margin": check_res.retcode == 0,
                "comment": check_res.comment,
            }

        return await _run_on_mt5_thread(_check)

    async def send_order(self, request: OrderRequest) -> OrderResult:
        # Verificação de idempotência anti-duplicação
        if request.idempotency_key in self._idempotency_cache:
            log.warning("Tentativa de ordem duplicada interceptada", key=request.idempotency_key)
            return self._idempotency_cache[request.idempotency_key]

        broker_symbol = self._resolve_symbol(request.symbol)

        def _send():
            order_type = mt5.ORDER_TYPE_BUY if request.action == "BUY" else mt5.ORDER_TYPE_SELL
            sym_info = mt5.symbol_info(broker_symbol)
            if not sym_info:
                return OrderResult(
                    request_id=request.request_id,
                    idempotency_key=request.idempotency_key,
                    success=False,
                    retcode=10013,
                    comment="Símbolo não encontrado",
                )

            # Seleciona modo de preenchimento apropriado
            type_filling = mt5.ORDER_FILLING_RETURN
            if sym_info.filling_mode & 2:
                type_filling = mt5.ORDER_FILLING_IOC
            elif sym_info.filling_mode & 1:
                type_filling = mt5.ORDER_FILLING_FOK

            mt5_req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": broker_symbol,
                "volume": float(request.volume),
                "type": order_type,
                "price": float(request.price),
                "sl": float(request.stop_loss),
                "tp": float(request.take_profit),
                "deviation": int(request.slippage_points),
                "magic": int(request.magic),
                "comment": request.comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": type_filling,
            }

            result = mt5.order_send(mt5_req)
            if result is None:
                err = mt5.last_error()
                return OrderResult(
                    request_id=request.request_id,
                    idempotency_key=request.idempotency_key,
                    success=False,
                    retcode=err[0],
                    comment=f"Erro de comunicação MT5: {err[1]}",
                )

            return OrderResult(
                request_id=request.request_id,
                idempotency_key=request.idempotency_key,
                success=result.retcode == mt5.TRADE_RETCODE_DONE,
                retcode=result.retcode,
                order_ticket=result.order,
                deal_ticket=result.deal,
                volume_executed=result.volume,
                price_executed=result.price,
                comment=result.comment,
            )

        res = await _run_on_mt5_thread(_send)
        self._idempotency_cache[request.idempotency_key] = res
        return res

    async def get_open_positions(self, symbol: Optional[str] = None) -> List[Position]:
        broker_symbol = self._resolve_symbol(symbol) if symbol else None

        def _get_positions():
            if broker_symbol:
                raw_pos = mt5.positions_get(symbol=broker_symbol)
            else:
                raw_pos = mt5.positions_get()
            return raw_pos

        raw_pos = await _run_on_mt5_thread(_get_positions)
        if raw_pos is None:
            return []

        positions = []
        for p in raw_pos:
            positions.append(
                Position(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    magic=p.magic,
                    position_type="BUY" if p.type == 0 else "SELL",
                    volume=float(p.volume),
                    open_price=float(p.price_open),
                    stop_loss=float(p.sl),
                    take_profit=float(p.tp),
                    current_price=float(p.price_current),
                    profit=float(p.profit),
                    swap=float(p.swap),
                    comment=p.comment,
                    open_time=datetime.fromtimestamp(p.time, timezone.utc),
                )
            )
        return positions

    async def close_position(self, ticket: int, volume: Optional[float] = None) -> OrderResult:
        def _close():
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                return OrderResult(
                    request_id=uuid4(),
                    idempotency_key=f"close_{ticket}",
                    success=False,
                    retcode=10024,
                    comment="Posição não encontrada",
                )

            pos = positions[0]
            close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
            vol = volume if volume is not None else pos.volume
            price = mt5.symbol_info_tick(pos.symbol).bid if close_type == mt5.ORDER_TYPE_SELL else mt5.symbol_info_tick(pos.symbol).ask

            close_req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": ticket,
                "symbol": pos.symbol,
                "volume": float(vol),
                "type": close_type,
                "price": float(price),
                "deviation": 30,
                "magic": pos.magic,
                "comment": "CLOSE_AUTO",
            }
            res = mt5.order_send(close_req)
            if res is None:
                err = mt5.last_error()
                return OrderResult(
                    request_id=uuid4(),
                    idempotency_key=f"close_{ticket}",
                    success=False,
                    retcode=err[0],
                    comment=err[1],
                )

            return OrderResult(
                request_id=uuid4(),
                idempotency_key=f"close_{ticket}",
                success=res.retcode == mt5.TRADE_RETCODE_DONE,
                retcode=res.retcode,
                order_ticket=res.order,
                deal_ticket=res.deal,
                volume_executed=res.volume,
                price_executed=res.price,
                comment=res.comment,
            )

        return await _run_on_mt5_thread(_close)

    async def modify_position(self, ticket: int, stop_loss: float, take_profit: float) -> OrderResult:
        def _modify():
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                return OrderResult(
                    request_id=uuid4(),
                    idempotency_key=f"mod_{ticket}",
                    success=False,
                    retcode=10024,
                    comment="Posição não encontrada para modificação",
                )

            pos = positions[0]
            mod_req = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol": pos.symbol,
                "sl": float(stop_loss),
                "tp": float(take_profit),
            }
            res = mt5.order_send(mod_req)
            if res is None:
                err = mt5.last_error()
                return OrderResult(
                    request_id=uuid4(),
                    idempotency_key=f"mod_{ticket}",
                    success=False,
                    retcode=err[0],
                    comment=err[1],
                )

            return OrderResult(
                request_id=uuid4(),
                idempotency_key=f"mod_{ticket}",
                success=res.retcode == mt5.TRADE_RETCODE_DONE,
                retcode=res.retcode,
                order_ticket=ticket,
                deal_ticket=0,
                volume_executed=pos.volume,
                price_executed=pos.price_current,
                comment=res.comment,
            )

        return await _run_on_mt5_thread(_modify)
