"""
Testes Unitários do Barramento de Eventos Assíncrono e Priorizado
Arquivo: tests/unit/test_event_bus.py
"""
import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from core.event_bus import PrioritizedEventBus, EventPriority, EventMessage


@pytest.mark.asyncio
class TestPrioritizedEventBus:
    """Valida o funcionamento assíncrono, priorização e resiliência do Event Bus."""

    async def test_publish_and_subscribe(self):
        bus = PrioritizedEventBus()
        received_events = []

        def on_signal(event: EventMessage):
            received_events.append(event)

        bus.subscribe("signal.new", on_signal)
        await bus.publish("signal.new", {"symbol": "EURUSD", "direction": "BUY"})

        has_more = await bus.process_next()
        assert has_more is True
        assert len(received_events) == 1
        assert received_events[0].payload["symbol"] == "EURUSD"

    async def test_strict_priority_ordering(self):
        """
        Garante que um evento de EMERGÊNCIA (Kill Switch) fure a fila e seja processado
        ANTES de um evento NORMAL (sinal de trading), mesmo que publicado depois.
        """
        bus = PrioritizedEventBus()
        execution_order = []

        async def handler(event: EventMessage):
            execution_order.append(event.event_type)

        bus.subscribe("trade.signal", handler)
        bus.subscribe("emergency.kill_switch", handler)

        # 1. Publica evento normal primeiro
        await bus.publish(
            "trade.signal",
            {"signal": "BUY"},
            priority=EventPriority.NORMAL,  # Prioridade 2
        )

        # 2. Publica evento de emergência depois
        await bus.publish(
            "emergency.kill_switch",
            {"action": "FREEZE_ALL"},
            priority=EventPriority.EMERGENCY,  # Prioridade 0 (Máxima)
        )

        # Processa os dois eventos
        await bus.process_next()
        await bus.process_next()

        # O evento de emergência DEVE ter sido executado primeiro!
        assert execution_order == ["emergency.kill_switch", "trade.signal"]

    async def test_heartbeat_monitoring(self):
        bus = PrioritizedEventBus()
        component = "mt5_terminal"

        # Antes de registrar batimento, deve estar morto
        assert bus.is_heartbeat_alive(component) is False

        # Registra batimento atual
        bus.record_heartbeat(component)
        assert bus.is_heartbeat_alive(component, max_age_seconds=2.0) is True

        # Simula batimento expirado
        bus._heartbeats[component] = datetime.now(timezone.utc) - timedelta(seconds=10)
        assert bus.is_heartbeat_alive(component, max_age_seconds=5.0) is False

    async def test_dead_letter_queue_on_handler_error(self):
        bus = PrioritizedEventBus()

        def failing_handler(event: EventMessage):
            raise RuntimeError("Falha intencional de teste no handler")

        bus.subscribe("test.error", failing_handler)
        await bus.publish("test.error", {"data": 123})

        # Não deve levantar exceção no barramento
        processed = await bus.process_next()
        assert processed is True
        assert len(bus._dead_letter_queue) == 1
        failed_event, err_msg = bus._dead_letter_queue[0]
        assert failed_event.event_type == "test.error"
        assert "Falha intencional de teste" in err_msg
