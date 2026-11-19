"""
QUANT HERMES — Adaptador Oficial MetaTrader 5 para Windows (Worker COM Thread-Safe)
Módulo: execution.adapters.windows_mt5
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from core.logger import log
from core.models.market import MarketBar, MarketTick, SymbolSpecification, TimeFrame
from core.models.risk import AccountState, OrderRequest, OrderResult, Position
from execution.account_pnl import pnl_percent, realized_from_deals, unrealized_from_positions
from execution.adapters.base import PlatformConnectionError, TradingPlatformAdapter
from execution.symbols import SymbolMapper

# Retcodes oficiais do terminal. Usados quando o pacote não está importado (testes).
TRADE_RETCODE_REQUOTE = 10004
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_DONE_PARTIAL = 10010
TRADE_RETCODE_TIMEOUT = 10012
TRADE_RETCODE_PRICE_CHANGED = 10020
TRADE_RETCODE_PRICE_OFF = 10021
TRADE_RETCODE_CONNECTION = 10031
RETRYABLE_RETCODES = {
    TRADE_RETCODE_REQUOTE,
    TRADE_RETCODE_TIMEOUT,
    TRADE_RETCODE_PRICE_CHANGED,
    TRADE_RETCODE_PRICE_OFF,
    TRADE_RETCODE_CONNECTION,
}
SUCCESS_RETCODES = {TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL}

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
        symbol_suffix: str = "",
        symbol_mapper: Optional[SymbolMapper] = None,
        max_retry_attempts: int = 3,
        retry_delay_seconds: float = 0.5,
    ):
        if not MT5_AVAILABLE:
            log.warning("Pacote oficial MetaTrader5 não está instalado neste ambiente")

        self._path = path
        self._login = login
        self._password = password
        self._server = server
        self._timeout_ms = timeout_ms
        self._connected: bool = False
        self.symbol_mapper = symbol_mapper or SymbolMapper(suffix=symbol_suffix, aliases=symbol_aliases)
        self._symbol_aliases: Dict[str, str] = dict(self.symbol_mapper.aliases)
        self._idempotency_cache: Dict[str, OrderResult] = {}
        self._peak_equity: float = 0.0
        self._max_retry_attempts = max(1, int(max_retry_attempts))
        self._retry_delay_seconds = max(0.0, float(retry_delay_seconds))

    def _resolve_symbol(self, canonical_symbol: str) -> str:
        """Traduz símbolo canônico interno para o símbolo exato negociado pela corretora."""
        return self.symbol_mapper.to_broker(canonical_symbol)

    def restore_peak_equity(self, peak_equity: float) -> None:
        """Restaura o pico persistido. Um restart não zera o drawdown."""
        if peak_equity > self._peak_equity:
            self._peak_equity = float(peak_equity)

    def current_peak_equity(self) -> float:
        return self._peak_equity

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

        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())

        def _pnl_sources():
            deals_day = mt5.history_deals_get(day_start, now) if hasattr(mt5, "history_deals_get") else None
            deals_week = mt5.history_deals_get(week_start, now) if hasattr(mt5, "history_deals_get") else None
            positions = mt5.positions_get() if hasattr(mt5, "positions_get") else None
            return deals_day, deals_week, positions

        deals_day, deals_week, open_positions = await _run_on_mt5_thread(_pnl_sources)
        unrealized = unrealized_from_positions(open_positions)
        balance = float(acc.balance)
        daily_pnl_pct = pnl_percent(balance, realized_from_deals(deals_day), unrealized)
        weekly_pnl_pct = pnl_percent(balance, realized_from_deals(deals_week), unrealized)

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
            current_drawdown_pct=min(100.0, drawdown_pct),
            daily_pnl_pct=daily_pnl_pct,
            weekly_pnl_pct=weekly_pnl_pct,
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

        swap_mode_code = int(getattr(info, "swap_mode", 0) or 0)
        if swap_mode_code in (1, 3, 4):
            swap_mode = "account_currency"
        elif swap_mode_code in (2, 5, 6):
            swap_mode = "interest"
        else:
            swap_mode = "points"

        return SymbolSpecification(
            symbol=info.name,
            canonical_name=self.symbol_mapper.to_logical(symbol),
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
            swap_long=float(getattr(info, "swap_long", 0.0) or 0.0),
            swap_short=float(getattr(info, "swap_short", 0.0) or 0.0),
            swap_rollover3days=int(getattr(info, "swap_rollover3days", 3) or 3),
            swap_mode=swap_mode,
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
                return {"retcode": 10013, "has_margin": False, "comment": "Símbolo inválido", "margin_required": 0.0}

            order_type = mt5.ORDER_TYPE_BUY if request.action == "BUY" else mt5.ORDER_TYPE_SELL
            margin_required = None
            if hasattr(mt5, "order_calc_margin"):
                margin_required = mt5.order_calc_margin(
                    order_type, broker_symbol, float(request.volume), float(request.price)
                )
            account = mt5.account_info() if hasattr(mt5, "account_info") else None
            free_margin = float(account.margin_free) if account is not None else 0.0

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
            if check_res is None and margin_required is None:
                err = mt5.last_error()
                return {"retcode": err[0], "has_margin": False, "comment": err[1], "margin_required": 0.0}

            if margin_required is None and check_res is not None:
                margin_required = float(check_res.margin)
            margin_required = float(margin_required or 0.0)
            retcode = check_res.retcode if check_res is not None else 0
            comment = check_res.comment if check_res is not None else "order_calc_margin"
            if check_res is not None:
                free_margin = float(check_res.margin_free)
            return {
                "retcode": retcode,
                "margin_required": margin_required,
                "free_margin": free_margin,
                "has_margin": retcode == 0 and free_margin + 1e-9 >= margin_required,
                "comment": comment,
            }

        return await _run_on_mt5_thread(_check)

    def _retcode(self, name: str, fallback: int) -> int:
        if mt5 is None:
            return fallback
        return int(getattr(mt5, name, fallback))

    async def reconnect(self) -> bool:
        """Reconecta o terminal com backoff exponencial limitado."""
        delay = self._retry_delay_seconds
        for _attempt in range(self._max_retry_attempts):
            try:
                await self.disconnect()
            except Exception:
                self._connected = False
            try:
                connected = await self.connect()
            except PlatformConnectionError:
                connected = False
            if connected:
                healthy = await self.is_connected()
                if healthy:
                    return True
            if delay > 0:
                await asyncio.sleep(delay)
            delay = min(delay * 2 if delay else 0.5, 30.0)
        return False

    async def send_order(self, request: OrderRequest) -> OrderResult:
        # Verificação de idempotência anti-duplicação. O cache só guarda o resultado final.
        if request.idempotency_key in self._idempotency_cache:
            log.warning("Tentativa de ordem duplicada interceptada", key=request.idempotency_key)
            return self._idempotency_cache[request.idempotency_key]

        broker_symbol = self._resolve_symbol(request.symbol)
        price = float(request.price)
        done = self._retcode("TRADE_RETCODE_DONE", TRADE_RETCODE_DONE)
        partial = self._retcode("TRADE_RETCODE_DONE_PARTIAL", TRADE_RETCODE_DONE_PARTIAL)
        requote = self._retcode("TRADE_RETCODE_REQUOTE", TRADE_RETCODE_REQUOTE)
        price_changed = self._retcode("TRADE_RETCODE_PRICE_CHANGED", TRADE_RETCODE_PRICE_CHANGED)
        price_off = self._retcode("TRADE_RETCODE_PRICE_OFF", TRADE_RETCODE_PRICE_OFF)
        timeout = self._retcode("TRADE_RETCODE_TIMEOUT", TRADE_RETCODE_TIMEOUT)
        connection = self._retcode("TRADE_RETCODE_CONNECTION", TRADE_RETCODE_CONNECTION)
        retryable = {requote, price_changed, price_off, timeout, connection}

        def _quote() -> Optional[float]:
            if not hasattr(mt5, "symbol_info_tick"):
                return None
            tick = mt5.symbol_info_tick(broker_symbol)
            if tick is None:
                return None
            return float(tick.ask if request.action == "BUY" else tick.bid)

        def _send_once(limit_price: float) -> OrderResult:
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
                "price": float(limit_price),
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

            filled = result.retcode in (done, partial) and float(result.volume or 0.0) > 0.0 and int(result.order or 0) > 0
            comment = result.comment or ""
            if result.retcode == partial:
                comment = f"PARTIAL_FILL: {comment}".strip()
            return OrderResult(
                request_id=request.request_id,
                idempotency_key=request.idempotency_key,
                success=filled,
                retcode=result.retcode,
                order_ticket=int(result.order or 0),
                deal_ticket=int(result.deal or 0),
                volume_executed=float(result.volume or 0.0),
                price_executed=float(result.price or 0.0),
                comment=comment,
            )

        result = OrderResult(
            request_id=request.request_id,
            idempotency_key=request.idempotency_key,
            success=False,
            retcode=10031,
            comment="Sem tentativa de envio",
        )
        for attempt in range(self._max_retry_attempts):
            result = await _run_on_mt5_thread(lambda limit_price=price: _send_once(limit_price))
            if result.success:
                break
            if result.retcode not in retryable or attempt == self._max_retry_attempts - 1:
                break
            if result.retcode == connection:
                reconnected = await self.reconnect()
                if not reconnected:
                    result = OrderResult(
                        request_id=request.request_id,
                        idempotency_key=request.idempotency_key,
                        success=False,
                        retcode=connection,
                        comment="RECONNECT_FAILED",
                    )
                    break
            if result.retcode in (requote, price_changed, price_off):
                refreshed = await _run_on_mt5_thread(_quote)
                if refreshed and refreshed > 0:
                    price = refreshed
            if self._retry_delay_seconds > 0:
                await asyncio.sleep(self._retry_delay_seconds)

        self._idempotency_cache[request.idempotency_key] = result
        return result

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
                    symbol=self.symbol_mapper.to_logical(p.symbol),
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

