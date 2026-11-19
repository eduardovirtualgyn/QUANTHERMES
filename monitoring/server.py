"""
QUANT HERMES — SERVIDOR DE DASHBOARD E TELEMETRIA FASTAPI
Módulo: monitoring.server

Responsabilidade:
- Expor endpoints REST de consulta de telemetria, posições e status de risco.
- Fornecer streaming em tempo real via WebSockets (/ws/telemetry).
- Disponibilizar interface HTML5 reativa para monitoramento operacional e controle de emergência.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from core.logger import get_logger
from core.secrets import require_env, tokens_equal
from monitoring.telemetry import TelemetryProvider

logger = get_logger("monitoring.server")


class KillSwitchEngageRequest(BaseModel):
    """Payload para acionamento do Kill Switch."""
    reason: str = Field(..., min_length=3, description="Motivo do acionamento de emergência")
    operator: str = Field(default="OPERATOR_MANUAL", description="Identificador do operador ou sistema")


class KillSwitchDisengageRequest(BaseModel):
    """Payload para desarme do Kill Switch."""
    operator_token: str = Field(..., min_length=6, description="Token seguro de desarme")
    reason: str = Field(default="OPERATOR_API_DISENGAGE", description="Motivo do desarme")


class ModelRollbackRequest(BaseModel):
    """Payload para reversão atômica de modelo."""
    symbol: str = Field(..., description="Símbolo do ativo (ex: EURUSD)")
    reason: str = Field(..., min_length=3, description="Justificativa técnica da reversão")


class WebSocketConnectionManager:
    """Gerenciador de conexões WebSockets ativas para streaming de telemetria."""

    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info("Cliente WebSocket conectado à telemetria", extra={"total": len(self.active_connections)})

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)
        logger.info("Cliente WebSocket desconectado", extra={"remaining": len(self.active_connections)})

    async def broadcast(self, message: Dict[str, Any]) -> None:
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)

        for conn in disconnected:
            self.disconnect(conn)


def create_monitoring_app(
    provider: Optional[TelemetryProvider] = None,
    operator_token: Optional[str] = None,
) -> FastAPI:
    """
    Fábrica da aplicação FastAPI para o Dashboard e Monitoramento do QUANT HERMES.
    """
    app = FastAPI(
        title="QUANT HERMES — Dashboard & Telemetry API",
        version="1.0.0",
        description="Painel de controle quantitativo multiagente, governança de risco e execução.",
    )

    telemetry = provider or TelemetryProvider()
    ws_manager = WebSocketConnectionManager()
    expected_token = operator_token.strip() if operator_token else require_env("HERMES_OPERATOR_TOKEN")

    def require_operator(authorization: Optional[str] = Header(None)) -> None:
        """Exige Bearer token em todo endpoint que altera estado."""
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token de operador ausente",
            )
        presented = authorization.split("Bearer ", 1)[1].strip()
        if not tokens_equal(presented, expected_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Token de operador inválido",
            )

    # Injeta nas dependências do app
    app.state.telemetry = telemetry
    app.state.ws_manager = ws_manager

    # -------------------------------------------------------------
    # ENDPOINTS REST
    # -------------------------------------------------------------

    @app.get("/api/v1/health", tags=["Status"])
    async def get_health() -> Dict[str, Any]:
        """Consulta saúde geral do sistema e subsistemas."""
        return await telemetry.get_system_health()

    @app.get("/api/v1/account", tags=["Financeiro"])
    async def get_account() -> Dict[str, Any]:
        """Retorna telemetria da conta (saldo, equity, margem, drawdown atual)."""
        return await telemetry.get_account_state()

    @app.get("/api/v1/positions", tags=["Execução"])
    async def get_positions() -> List[Dict[str, Any]]:
        """Retorna lista de posições atualmente abertas no broker/simulador."""
        return await telemetry.get_open_positions()

    @app.get("/api/v1/risk/status", tags=["Risco"])
    async def get_risk_status() -> Dict[str, Any]:
        """Consulta status dos Circuit Breakers e Kill Switch."""
        return telemetry.get_risk_status()

    @app.post("/api/v1/risk/kill-switch/engage", tags=["Risco"], dependencies=[Depends(require_operator)])
    async def engage_kill_switch(payload: KillSwitchEngageRequest) -> Dict[str, Any]:
        """Aciona a trava de emergência global e liquida ordens."""
        if not telemetry.risk_engine:
            raise HTTPException(status_code=503, detail="Risk Engine não inicializado")

        ks = telemetry.risk_engine.kill_switch
        ks.engage(reason=payload.reason, triggered_by=payload.operator)

        # Se houver adapter conectado, executa liquidação compulsória
        if telemetry.adapter:
            try:
                await ks.execute_emergency_liquidation(telemetry.adapter)
            except Exception as e:
                logger.error("Falha ao executar liquidação compulsória", extra={"error": str(e)})

        # Notifica todos os clientes conectados via WebSocket
        await ws_manager.broadcast({
            "event": "KILL_SWITCH_ENGAGED",
            "reason": payload.reason,
            "operator": payload.operator,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return {
            "success": True,
            "status": "EMERGENCY_HALT",
            "message": f"Kill Switch ativado: {payload.reason}",
        }

    @app.post("/api/v1/risk/kill-switch/disengage", tags=["Risco"], dependencies=[Depends(require_operator)])
    async def disengage_kill_switch(payload: KillSwitchDisengageRequest) -> Dict[str, Any]:
        """Desarma a trava de emergência global com token seguro de operador."""
        if not telemetry.risk_engine:
            raise HTTPException(status_code=503, detail="Risk Engine não inicializado")

        if not tokens_equal(payload.operator_token, expected_token):
            raise HTTPException(status_code=403, detail="Token de operador inválido para desarme")

        ks = telemetry.risk_engine.kill_switch
        success = ks.disengage(operator_token=payload.operator_token, reason=payload.reason)

        if not success:
            raise HTTPException(status_code=403, detail="Token de operador inválido para desarme")

        await ws_manager.broadcast({
            "event": "KILL_SWITCH_DISENGAGED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        return {
            "success": True,
            "status": "NORMAL_OPERATIONS",
            "message": "Kill Switch desarmado com sucesso",
        }

    @app.get("/api/v1/agents/status", tags=["Inteligência"])
    async def get_agents_status() -> Dict[str, Any]:
        """Retorna o status dos 8 agentes especializados e regimes por ativo."""
        orchestrator = telemetry.orchestrator
        agents_info = {}
        if orchestrator:
            for ag_id, ag in orchestrator.agents.items():
                agents_info[ag_id] = {
                    "name": getattr(ag, "name", ag_id),
                    "quality_factor": getattr(ag, "quality_factor", 1.0),
                }

        active_regimes = {}
        if orchestrator:
            active_regimes = {
                sym: reg.active_regime.value
                for sym, reg in orchestrator._current_regimes.items()
            }

        return {
            "agents": agents_info,
            "active_regimes": active_regimes,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/api/v1/models", tags=["Machine Learning"])
    async def list_models(symbol: str = "EURUSD") -> List[Dict[str, Any]]:
        """Lista histórico de modelos registrados para o símbolo."""
        models = telemetry.model_registry.list_models(symbol)
        return [
            {
                "model_id": m.model_id,
                "symbol": m.symbol,
                "engine": m.engine,
                "stage": m.stage.value,
                "created_at_utc": m.created_at_utc,
                "sha256": m.sha256_checksum[:8],
                "validation_status": m.validation_status,
                "oos_metrics": m.oos_metrics,
            }
            for m in models
        ]

    @app.post("/api/v1/models/rollback", tags=["Machine Learning"], dependencies=[Depends(require_operator)])
    async def rollback_model(payload: ModelRollbackRequest) -> Dict[str, Any]:
        """Aciona rollback atômico para a versão de produção anterior."""
        restored = telemetry.model_registry.rollback_production_model(
            symbol=payload.symbol,
            reason=payload.reason,
        )
        if not restored:
            raise HTTPException(status_code=400, detail="Nenhum modelo arquivado disponível para rollback")

        return {
            "success": True,
            "symbol": payload.symbol,
            "restored_model_id": restored,
            "reason": payload.reason,
        }

    # -------------------------------------------------------------
    # WEBSOCKET STREAMING
    # -------------------------------------------------------------

    @app.websocket("/ws/telemetry")
    async def websocket_telemetry_endpoint(websocket: WebSocket) -> None:
        """Endpoint de streaming em tempo real via WebSockets."""
        await ws_manager.connect(websocket)
        try:
            while True:
                # Envia snapshot a cada 1 segundo ou sob demanda
                snapshot = await telemetry.get_telemetry_snapshot()
                await websocket.send_json(snapshot)
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)
        except Exception as e:
            logger.warning("Conexão WebSocket encerrada", extra={"error": str(e)})
            ws_manager.disconnect(websocket)

    # -------------------------------------------------------------
    # DASHBOARD WEB HTML5
    # -------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
    @app.get("/dashboard", response_class=HTMLResponse, tags=["Dashboard"])
    async def render_dashboard_html() -> str:
        """Renderiza a página principal do Dashboard operacional em HTML5 responsivo."""
        return DASHBOARD_HTML_TEMPLATE

    return app


DASHBOARD_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QUANT HERMES — Autonomous Trading System</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
        .card { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; }
        .badge-green { background-color: rgba(46, 160, 67, 0.2); color: #3fb950; border: 1px solid #238636; }
        .badge-red { background-color: rgba(248, 81, 73, 0.2); color: #f85149; border: 1px solid #da3633; }
        .badge-yellow { background-color: rgba(210, 153, 34, 0.2); color: #d29922; border: 1px solid #9e6a03; }
    </style>
</head>
<body class="p-6">
    <header class="flex justify-between items-center mb-6 pb-4 border-b border-gray-800">
        <div>
            <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-3">
                <span class="text-blue-500 font-mono">⚡ QUANT HERMES</span>
                <span class="text-xs px-2 py-0.5 rounded badge-green font-normal">Autonomous Multi-Agent v1.0</span>
            </h1>
            <p class="text-xs text-gray-400 mt-1">MetaTrader 5 & Paper Trading Quantitative Infrastructure</p>
        </div>
        <div class="flex items-center gap-4">
            <div id="connectionStatus" class="flex items-center gap-2 text-xs font-mono px-3 py-1.5 rounded card">
                <span class="h-2 w-2 rounded-full bg-yellow-500 animate-pulse" id="statusDot"></span>
                <span id="statusText">Conectando WebSocket...</span>
            </div>
            <button onclick="engageEmergencyKillSwitch()" class="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded text-xs font-bold tracking-wider uppercase transition shadow-lg flex items-center gap-2">
                🛑 KILL SWITCH
            </button>
        </div>
    </header>

    <!-- CARDS DE TELEMETRIA FINANCEIRA -->
    <div class="grid grid-cols-1 md:grid-cols-5 gap-4 mb-6">
        <div class="card p-4">
            <span class="text-xs text-gray-400 uppercase font-semibold">Balance</span>
            <div class="text-2xl font-bold font-mono text-white mt-1" id="valBalance">$0.00</div>
            <span class="text-xs text-gray-500" id="valCurrency">USD</span>
        </div>
        <div class="card p-4">
            <span class="text-xs text-gray-400 uppercase font-semibold">Equity</span>
            <div class="text-2xl font-bold font-mono text-white mt-1" id="valEquity">$0.00</div>
            <span class="text-xs text-gray-500" id="valFreeMargin">Margem Livre: $0.00</span>
        </div>
        <div class="card p-4">
            <span class="text-xs text-gray-400 uppercase font-semibold">Drawdown Atual</span>
            <div class="text-2xl font-bold font-mono text-yellow-400 mt-1" id="valDrawdown">0.00%</div>
            <span class="text-xs text-gray-500">Pico: <span id="valPeakEquity">$0.00</span></span>
        </div>
        <div class="card p-4">
            <span class="text-xs text-gray-400 uppercase font-semibold">PnL Diário</span>
            <div class="text-2xl font-bold font-mono text-green-400 mt-1" id="valDailyPnl">0.00%</div>
            <span class="text-xs text-gray-500">Teto de Perda: 1.50%</span>
        </div>
        <div class="card p-4">
            <span class="text-xs text-gray-400 uppercase font-semibold">Posições Abertas</span>
            <div class="text-2xl font-bold font-mono text-blue-400 mt-1" id="valOpenPositionsCount">0</div>
            <span class="text-xs text-gray-500">Máximo Permitido: 3</span>
        </div>
    </div>

    <!-- TABELA DE POSIÇÕES E MATRIZ DE AGENTES -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- POSIÇÕES ABERTAS -->
        <div class="lg:col-span-2 card p-5">
            <h2 class="text-sm font-bold uppercase tracking-wider text-gray-300 mb-4 flex items-center justify-between">
                <span>Posições Ativas no Terminal</span>
                <span class="text-xs font-mono text-gray-500" id="reconcileNotice">Auto-Reconciliação Ativa</span>
            </h2>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-xs">
                    <thead>
                        <tr class="border-b border-gray-800 text-gray-400 font-mono">
                            <th class="pb-2">Ticket</th>
                            <th class="pb-2">Ativo</th>
                            <th class="pb-2">Tipo</th>
                            <th class="pb-2">Lote</th>
                            <th class="pb-2">Preço Entrada</th>
                            <th class="pb-2">Stop Loss</th>
                            <th class="pb-2">Take Profit</th>
                            <th class="pb-2 text-right">Lucro Flutuante</th>
                        </tr>
                    </thead>
                    <tbody id="positionsTableBody">
                        <tr><td colspan="8" class="text-center py-6 text-gray-500">Nenhuma posição aberta no momento.</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- STATUS DE RISCO E AGENTES -->
        <div class="space-y-6">
            <!-- STATUS DOS CIRCUIT BREAKERS -->
            <div class="card p-5">
                <h2 class="text-sm font-bold uppercase tracking-wider text-gray-300 mb-3">Circuit Breakers Soberanos</h2>
                <div class="space-y-2 text-xs">
                    <div class="flex justify-between items-center p-2 rounded bg-gray-900 border border-gray-800">
                        <span>Daily Loss Guard (1.50%)</span>
                        <span id="cbDaily" class="px-2 py-0.5 rounded badge-green">NORMAL</span>
                    </div>
                    <div class="flex justify-between items-center p-2 rounded bg-gray-900 border border-gray-800">
                        <span>Weekly Loss Guard (3.00%)</span>
                        <span id="cbWeekly" class="px-2 py-0.5 rounded badge-green">NORMAL</span>
                    </div>
                    <div class="flex justify-between items-center p-2 rounded bg-gray-900 border border-gray-800">
                        <span>Emergency Drawdown (8.00%)</span>
                        <span id="cbDrawdown" class="px-2 py-0.5 rounded badge-green">NORMAL</span>
                    </div>
                    <div class="flex justify-between items-center p-2 rounded bg-gray-900 border border-gray-800">
                        <span>Weekend Risk Guard (Sexta 20h UTC)</span>
                        <span id="cbWeekend" class="px-2 py-0.5 rounded badge-green">NORMAL</span>
                    </div>
                </div>
            </div>

            <!-- REGIMES DE MERCADO -->
            <div class="card p-5">
                <h2 class="text-sm font-bold uppercase tracking-wider text-gray-300 mb-3">Regimes Detectados (HMM)</h2>
                <div id="regimesContainer" class="space-y-2 text-xs font-mono">
                    <div class="text-gray-500 text-center py-2">Aguardando dados...</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${window.location.host}/ws/telemetry`;
        let socket;

        function connectWebSocket() {
            socket = new WebSocket(wsUrl);

            socket.onopen = () => {
                document.getElementById('statusDot').className = 'h-2 w-2 rounded-full bg-green-500';
                document.getElementById('statusText').innerText = 'Online (Live)';
            };

            socket.onmessage = (event) => {
                const data = JSON.parse(event.data);
                updateDashboard(data);
            };

            socket.onclose = () => {
                document.getElementById('statusDot').className = 'h-2 w-2 rounded-full bg-red-500';
                document.getElementById('statusText').innerText = 'Reconectando...';
                setTimeout(connectWebSocket, 2000);
            };

            socket.onerror = () => socket.close();
        }

        function updateDashboard(data) {
            if (data.account) {
                document.getElementById('valBalance').innerText = `$${data.account.balance.toFixed(2)}`;
                document.getElementById('valEquity').innerText = `$${data.account.equity.toFixed(2)}`;
                document.getElementById('valFreeMargin').innerText = `Margem Livre: $${data.account.free_margin.toFixed(2)}`;
                document.getElementById('valDrawdown').innerText = `${(data.account.current_drawdown_pct * 100).toFixed(2)}%`;
                document.getElementById('valPeakEquity').innerText = `$${data.account.peak_equity.toFixed(2)}`;
                
                const dailyPnl = (data.account.daily_pnl_pct * 100).toFixed(2);
                const elDaily = document.getElementById('valDailyPnl');
                elDaily.innerText = `${dailyPnl}%`;
                elDaily.className = `text-2xl font-bold font-mono mt-1 ${dailyPnl >= 0 ? 'text-green-400' : 'text-red-400'}`;
            }

            if (data.positions) {
                document.getElementById('valOpenPositionsCount').innerText = data.positions.length;
                const tbody = document.getElementById('positionsTableBody');
                if (data.positions.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8" class="text-center py-6 text-gray-500">Nenhuma posição aberta no momento.</td></tr>';
                } else {
                    tbody.innerHTML = data.positions.map(p => `
                        <tr class="border-b border-gray-800 font-mono hover:bg-gray-800 transition">
                            <td class="py-2 text-gray-400">#${p.ticket}</td>
                            <td class="font-bold text-white">${p.symbol}</td>
                            <td><span class="px-1.5 py-0.5 rounded text-[10px] ${p.position_type === 'BUY' ? 'badge-green' : 'badge-red'}">${p.position_type}</span></td>
                            <td>${p.volume.toFixed(2)}</td>
                            <td>${p.open_price.toFixed(5)}</td>
                            <td class="text-red-400">${p.stop_loss.toFixed(5)}</td>
                            <td class="text-green-400">${p.take_profit.toFixed(5)}</td>
                            <td class="text-right font-bold ${p.profit >= 0 ? 'text-green-400' : 'text-red-400'}">${p.profit >= 0 ? '+' : ''}$${p.profit.toFixed(2)}</td>
                        </tr>
                    `).join('');
                }
            }

            if (data.risk && data.risk.circuit_breakers) {
                const cb = data.risk.circuit_breakers;
                updateBadge('cbDaily', cb.daily_loss_guard?.is_tripped);
                updateBadge('cbWeekly', cb.weekly_loss_guard?.is_tripped);
                updateBadge('cbDrawdown', cb.emergency_drawdown_guard?.is_tripped);
                updateBadge('cbWeekend', cb.weekend_risk_guard?.is_tripped);
            }

            if (data.active_regimes) {
                const container = document.getElementById('regimesContainer');
                const entries = Object.entries(data.active_regimes);
                if (entries.length > 0) {
                    container.innerHTML = entries.map(([sym, reg]) => `
                        <div class="flex justify-between items-center p-2 rounded bg-gray-900 border border-gray-800">
                            <span class="font-bold text-white">${sym}</span>
                            <span class="px-2 py-0.5 rounded text-[10px] badge-yellow">${reg}</span>
                        </div>
                    `).join('');
                }
            }
        }

        function updateBadge(id, isTripped) {
            const el = document.getElementById(id);
            if (!el) return;
            if (isTripped) {
                el.className = 'px-2 py-0.5 rounded badge-red';
                el.innerText = 'DESARMADO';
            } else {
                el.className = 'px-2 py-0.5 rounded badge-green';
                el.innerText = 'NORMAL';
            }
        }

        async function engageEmergencyKillSwitch() {
            if (!confirm('CONFIRMAR BLOQUEIO DE EMERGÊNCIA GLOBAL (KILL SWITCH)?\\nTodas as posições serão imediatamente encerradas e novas operações bloqueadas.')) return;
            try {
                const res = await fetch('/api/v1/risk/kill-switch/engage', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({reason: 'Acionamento manual via Dashboard', operator: 'DASHBOARD_USER'})
                });
                const data = await res.json();
                alert(data.message || 'Kill Switch acionado!');
            } catch (e) {
                alert('Falha ao acionar Kill Switch: ' + e);
            }
        }

        connectWebSocket();
    </script>
</body>
</html>
"""

