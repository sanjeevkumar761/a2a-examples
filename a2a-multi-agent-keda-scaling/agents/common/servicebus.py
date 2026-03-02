"""
Shared Azure Service Bus transport for A2A agent communication.
Provides async send/receive with correlation IDs for request-response patterns.
Uses DefaultAzureCredential for passwordless auth (works with Managed Identity on AKS).
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Any

from azure.identity.aio import DefaultAzureCredential
from azure.servicebus.aio import ServiceBusClient, ServiceBusSender, ServiceBusReceiver
from azure.servicebus import ServiceBusMessage

logger = logging.getLogger(__name__)

# Queue names for the A2A agent messaging topology
INVOICE_REQUEST_QUEUE = "invoice-requests"
INVOICE_RESPONSE_QUEUE = "invoice-responses"
PO_REQUEST_QUEUE = "po-requests"
PO_RESPONSE_QUEUE = "po-responses"


class ServiceBusTransport:
    """Async Azure Service Bus transport for inter-agent communication."""

    def __init__(self, fully_qualified_namespace: str | None = None):
        self.fqdn = fully_qualified_namespace or os.getenv("SERVICEBUS_FQDN", "")
        self._credential = None
        self._client = None

    async def _ensure_client(self):
        if self._client is None:
            self._credential = DefaultAzureCredential()
            self._client = ServiceBusClient(
                fully_qualified_namespace=self.fqdn,
                credential=self._credential,
            )
            logger.info(f"Service Bus client connected to {self.fqdn}")

    async def send_message(
        self,
        queue_name: str,
        payload: dict | str,
        correlation_id: str | None = None,
    ) -> str:
        """Send a message to a Service Bus queue.

        Returns the correlation_id used (auto-generated if not provided).
        """
        await self._ensure_client()
        correlation_id = correlation_id or str(uuid.uuid4())

        body = payload if isinstance(payload, str) else json.dumps(payload)
        message = ServiceBusMessage(
            body=body,
            correlation_id=correlation_id,
            content_type="application/json",
        )

        sender: ServiceBusSender
        async with self._client.get_queue_sender(queue_name) as sender:
            await sender.send_messages(message)

        logger.info(f"Sent message to {queue_name} (correlation_id={correlation_id})")
        return correlation_id

    async def receive_response(
        self,
        queue_name: str,
        correlation_id: str,
        timeout: float = 120.0,
    ) -> dict | None:
        """Wait for a response message matching the given correlation_id.

        Polls the response queue until a matching message arrives or timeout is reached.
        """
        await self._ensure_client()
        deadline = asyncio.get_event_loop().time() + timeout

        receiver: ServiceBusReceiver
        async with self._client.get_queue_receiver(
            queue_name, max_wait_time=5
        ) as receiver:
            while asyncio.get_event_loop().time() < deadline:
                messages = await receiver.receive_messages(
                    max_message_count=10, max_wait_time=5
                )
                for msg in messages:
                    if msg.correlation_id == correlation_id:
                        body = str(msg)
                        await receiver.complete_message(msg)
                        logger.info(
                            f"Received correlated response from {queue_name} "
                            f"(correlation_id={correlation_id})"
                        )
                        try:
                            return json.loads(body)
                        except json.JSONDecodeError:
                            return {"raw": body}
                    else:
                        # Not our message — abandon so another consumer can pick it up
                        await receiver.abandon_message(msg)

        logger.warning(
            f"Timeout waiting for response on {queue_name} "
            f"(correlation_id={correlation_id})"
        )
        return None

    async def consume_queue(
        self,
        queue_name: str,
        handler,
        response_queue: str | None = None,
    ):
        """Continuously consume messages from a queue and call handler.

        If response_queue is provided, the handler's return value is sent
        back as a correlated response.
        """
        await self._ensure_client()
        logger.info(f"Starting consumer for queue: {queue_name}")

        async with self._client.get_queue_receiver(
            queue_name, max_wait_time=5
        ) as receiver:
            while True:
                messages = await receiver.receive_messages(
                    max_message_count=1, max_wait_time=10
                )
                for msg in messages:
                    correlation_id = msg.correlation_id
                    try:
                        body = json.loads(str(msg))
                        logger.info(
                            f"Processing message from {queue_name} "
                            f"(correlation_id={correlation_id})"
                        )

                        result = await handler(body)

                        if response_queue and correlation_id:
                            await self.send_message(
                                response_queue, result, correlation_id
                            )

                        await receiver.complete_message(msg)
                        logger.info(
                            f"Completed message from {queue_name} "
                            f"(correlation_id={correlation_id})"
                        )
                    except Exception as e:
                        logger.error(
                            f"Error processing message from {queue_name}: {e}"
                        )
                        # Dead-letter after failure so KEDA still sees the queue drain
                        await receiver.dead_letter_message(
                            msg, reason="ProcessingError", error_description=str(e)
                        )

                # Brief pause to avoid tight-loop when queue is empty
                if not messages:
                    await asyncio.sleep(1)

    async def close(self):
        """Clean up resources."""
        if self._client:
            await self._client.close()
        if self._credential:
            await self._credential.close()
