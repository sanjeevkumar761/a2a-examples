"""
A2A Server for Invoice Validation Agent.
Exposes the agent via A2A protocol for inter-agent communication.
Optionally consumes from Azure Service Bus for KEDA-scaled deployments.
"""

import asyncio
import json
import os
import logging
import sys
import uuid
from dotenv import load_dotenv

from a2a.server.apps import A2AStarletteApplication
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue, InMemoryQueueManager
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCard, AgentSkill, AgentCapabilities,
    TaskState, TaskStatus, TaskStatusUpdateEvent,
    Message, TextPart, Role,
)
import uvicorn

from agent import InvoiceValidationAgent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.servicebus import (
    ServiceBusTransport,
    INVOICE_REQUEST_QUEUE, INVOICE_RESPONSE_QUEUE,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class InvoiceAgentExecutor(AgentExecutor):
    """Executor that handles A2A requests for invoice validation."""

    def __init__(self):
        self.agent = InvoiceValidationAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_input = context.get_user_input()
        logger.info(f"Invoice agent received: {user_input}")

        # Try to parse JSON from user input, otherwise use as-is
        try:
            invoice_data = json.loads(user_input)
        except (json.JSONDecodeError, TypeError):
            invoice_data = {
                "invoice_number": "INV-DEMO-001",
                "vendor": "Demo Vendor",
                "amount": 1000,
                "date": "2026-02-19",
                "line_items": [{"description": "Demo item", "amount": 1000}],
                "raw_request": user_input,
            }

        # Publish working status
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=False,
                status=TaskStatus(state=TaskState.working, message=Message(role=Role.agent, message_id=str(uuid.uuid4()), parts=[TextPart(text="Validating invoice...")])),
            )
        )

        result = await self.agent.validate_invoice(invoice_data)
        result_text = json.dumps(result, indent=2, default=str)

        # Publish completed status
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=True,
                status=TaskStatus(state=TaskState.completed, message=Message(role=Role.agent, message_id=str(uuid.uuid4()), parts=[TextPart(text=result_text)])),
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=True,
                status=TaskStatus(state=TaskState.canceled, message=Message(role=Role.agent, message_id=str(uuid.uuid4()), parts=[TextPart(text="Cancelled")])),
            )
        )


def create_agent_card() -> AgentCard:
    return AgentCard(
        name="Invoice Validation Agent",
        description="Validates invoices for format compliance, amount accuracy, and regulatory compliance",
        url=os.getenv("AGENT_URL", "http://localhost:8001"),
        version="1.0.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(
            streaming=False,
            push_notifications=False,
            state_transition_history=True,
        ),
        skills=[
            AgentSkill(
                id="validate_invoice",
                name="Validate Invoice",
                description="Validates invoice data including format, amounts, and compliance checks",
                tags=["invoice", "validation", "compliance"],
                examples=[
                    "Validate this invoice for INV-2024-001",
                    "Check if the invoice amounts are correct",
                ],
            )
        ],
    )


def create_app():
    agent_card = create_agent_card()
    task_store = InMemoryTaskStore()
    queue_manager = InMemoryQueueManager()
    executor = InvoiceAgentExecutor()

    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        queue_manager=queue_manager,
    )

    app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    return app.build()


app = create_app()

# Shared agent instance for Service Bus consumer
_sb_agent = InvoiceValidationAgent()


async def _handle_sb_message(payload: dict) -> dict:
    """Process a Service Bus message through the invoice validation workflow."""
    return await _sb_agent.validate_invoice(payload)


async def _start_servicebus_consumer():
    """Start consuming from invoice-requests queue in the background."""
    transport = ServiceBusTransport()
    logger.info("Starting Service Bus consumer for invoice-requests queue")
    await transport.consume_queue(
        INVOICE_REQUEST_QUEUE,
        handler=_handle_sb_message,
        response_queue=INVOICE_RESPONSE_QUEUE,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8001))
    use_servicebus = os.getenv("USE_SERVICEBUS", "false").lower() == "true"

    if use_servicebus:
        async def _run():
            config = uvicorn.Config(app, host="0.0.0.0", port=port)
            server = uvicorn.Server(config)
            # Run HTTP server and Service Bus consumer concurrently
            await asyncio.gather(
                server.serve(),
                _start_servicebus_consumer(),
            )

        logger.info(f"Starting Invoice Agent on port {port} WITH Service Bus consumer")
        asyncio.run(_run())
    else:
        logger.info(f"Starting Invoice Validation Agent on port {port}")
        uvicorn.run(app, host="0.0.0.0", port=port)
