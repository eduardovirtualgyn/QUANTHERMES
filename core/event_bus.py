"""
QUANT HERMES — Barramento de Eventos Assíncrono com Priorização
Módulo: core.event_bus
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Callable, Coroutine, Dict, List, Set
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field
from core.logger import log


class EventPriority(IntEnum):
    """Níveis de prioridade no processamento de eventos (menor número = maior prioridade)."""
    EMERGENCY = 0  # Kill Switch, Circuit Breakers, Veto compulsório
    HIGH = 1       # Execução de ordens, confirmações de fill, autorizações de risco
    NORMAL = 2     # Sinais de agentes, decisões de consenso, análise de estratégias
    TELEMETRY = 3  # Ticks, barras, métricas periódicas


class EventMessage(BaseModel):
    """Envelope de mensagem transportada pelo Event Bus."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    event_id: UUID = Field(default_factory=uuid4)
    priority: EventPriority = Field(default=EventPriority.NORMAL)
    event_type: str = Field(..., description="Tópico ou tipo do evento (ex: 'signal.new', 'risk.veto')")
    payload: Any = Field(..., description="Dados tipados do evento")
    source: str = Field(default="system", description="Módulo emissor do evento")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def __lt__(self, other: EventMessage) -> bool:
        """Comparador para fila de prioridade: prioridade menor vence; desempate por timestamp."""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.timestamp < other.timestamp


HandlerFunc = Callable[[EventMessage], Coroutine[Any, Any, None] | None]


class PrioritizedEventBus:
    """
    Barramento assíncrono orientado a prioridades com suporte a:
    - Fila de prioridade estrita (Kill Switch é processado antes de qualquer sinal).
    - Despacho assíncrono para múltiplos assinantes.
    - Monitoramento de Heartbeats de componentes vitais.
    - Dead-Letter Queue (DLQ) para eventos com falha de processamento.
    """

    def __init__(self, maxsize: int = 10000):
        self._queue: asyncio.PriorityQueue[EventMessage] = asyncio.PriorityQueue(maxsize=maxsize)
        self._subscribers: Dict[str, List[HandlerFunc]] = {}
        self._heartbeats: Dict[str, datetime] = {}
        self._dead_letter_queue: List[tuple[EventMessage, str]] = []
        self._worker_task: asyncio.Task | None = None
        self._running: bool = False

    def subscribe(self, event_type: str, handler: HandlerFunc) -> None:
        """Inscreve um handler em um tipo de evento ou '*' para todos."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        if handler not in self._subscribers[event_type]:
            self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: HandlerFunc) -> None:
        """Remove a inscrição de um handler."""
        if event_type in self._subscribers and handler in self._subscribers[event_type]:
            self._subscribers[event_type].remove(handler)

    async def publish(
        self,
        event_type: str,
        payload: Any,
        priority: EventPriority = EventPriority.NORMAL,
        source: str = "system",
    ) -> EventMessage:
        """Publica um evento na fila prioritária de forma não-bloqueante."""
        event = EventMessage(
            priority=priority,
            event_type=event_type,
            payload=payload,
            source=source,
        )
        await self._queue.put(event)
        return event

    def record_heartbeat(self, component_name: str) -> None:
        """Registra o batimento cardíaco mais recente de um componente."""
        self._heartbeats[component_name] = datetime.now(timezone.utc)

    def is_heartbeat_alive(self, component_name: str, max_age_seconds: float = 5.0) -> bool:
        """Verifica se o componente emitiu batimento dentro da janela de tolerância."""
        last_beat = self._heartbeats.get(component_name)
        if not last_beat:
            return False
        age = (datetime.now(timezone.utc) - last_beat).total_seconds()
        return age <= max_age_seconds

    async def start(self) -> None:
        """Inicia o processamento contínuo em segundo plano da fila de eventos."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._event_loop_worker())

    async def stop(self) -> None:
        """Encerra graciosamente o barramento de eventos."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def process_next(self) -> bool:
        """Processa um único evento da fila. Útil para testes síncronos e testes unitários."""
        if self._queue.empty():
            return False
        event = await self._queue.get()
        await self._dispatch(event)
        self._queue.task_done()
        return True

    async def _event_loop_worker(self) -> None:
        """Loop contínuo de consumo da fila com tratamento de erros."""
        while self._running:
            try:
                event = await self._queue.get()
                await self._dispatch(event)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Exceção não tratada no loop do EventBus", error=str(e))

    async def _dispatch(self, event: EventMessage) -> None:
        """Encaminha o evento para os inscritos registrados."""
        handlers: Set[HandlerFunc] = set()

        if event.event_type in self._subscribers:
            handlers.update(self._subscribers[event.event_type])
        if "*" in self._subscribers:
            handlers.update(self._subscribers["*"])

        for handler in handlers:
            try:
                res = handler(event)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:
                log.error(
                    "Falha ao executar handler de evento",
                    event_type=event.event_type,
                    error=str(exc),
                )
                self._dead_letter_queue.append((event, str(exc)))

