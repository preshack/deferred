"""Deferred API — Event Bus (RabbitMQ).

Publishes domain events for webhooks and async processing.
Best-effort: failures don't block API responses.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config import settings
from app.observability import get_logger

logger = get_logger("event_bus")


class EventBus:
    """Publishes domain events to RabbitMQ.

    Events are published best-effort — failures are logged but don't
    block the API response. Consumers process events asynchronously.
    """

    EXCHANGE = "deferred.events"

    def __init__(self):
        self._connection = None
        self._channel = None

    async def connect(self) -> None:
        """Connect to RabbitMQ (best-effort)."""
        try:
            import aio_pika
            self._connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
            self._channel = await self._connection.channel()
            await self._channel.declare_exchange(
                self.EXCHANGE,
                aio_pika.ExchangeType.TOPIC,
                durable=True,
            )
            logger.info("event_bus_connected")
        except Exception as e:
            logger.warning("event_bus_connection_failed", error=str(e))
            self._connection = None
            self._channel = None

    async def publish(
        self,
        event_type: str,
        data: Dict[str, Any],
        routing_key: Optional[str] = None,
    ) -> None:
        """Publish an event to the message bus.

        Args:
            event_type: Event name (e.g., 'payment.created', 'settlement.guaranteed')
            data: Event payload
            routing_key: RabbitMQ routing key (defaults to event_type)
        """
        if not self._channel:
            logger.debug("event_bus_not_connected", event_type=event_type)
            return

        try:
            import aio_pika

            message = aio_pika.Message(
                body=json.dumps({
                    "event": event_type,
                    "data": data,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }).encode(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            )

            exchange = await self._channel.get_exchange(self.EXCHANGE)
            await exchange.publish(
                message,
                routing_key=routing_key or event_type,
            )

            logger.debug("event_published", event_type=event_type)
        except Exception as e:
            logger.warning("event_publish_failed", event_type=event_type, error=str(e))

    async def close(self) -> None:
        """Close the connection."""
        if self._connection:
            await self._connection.close()
            logger.info("event_bus_disconnected")


# Domain event names
class Events:
    WALLET_CREATED = "wallet.created"
    TOPUP_CREATED = "topup.created"
    TOPUP_SUCCEEDED = "topup.succeeded"
    PAYMENT_CREATED = "payment.created"
    PAYMENT_SYNC_SUCCEEDED = "payment.sync_succeeded"
    PAYMENT_SYNC_FAILED = "payment.sync_failed"
    SETTLEMENT_GUARANTEED = "settlement.guaranteed"
    SETTLEMENT_SETTLED = "settlement.settled"
    DOUBLE_SPEND_DETECTED = "double_spend.detected"


# Module-level instance
event_bus = EventBus()
