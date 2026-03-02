"""
A2A Server for Purchase Order Agent.
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

from agent import PurchaseOrderAgent

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.servicebus import (
    ServiceBusTransport,
    PO_REQUEST_QUEUE, PO_RESPONSE_QUEUE,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class POAgentExecutor(AgentExecutor):
    """Executor that handles A2A requests for PO management."""

    def __init__(self):
        self.agent = PurchaseOrderAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_input = context.get_user_input()
        logger.info(f"PO agent received: {user_input}")

        try:
            data = json.loads(user_input)
        except (json.JSONDecodeError, TypeError):
            data = {
                "vendor_id": "V001",
                "requester": "demo-user",
                "items": [{"description": "Demo item", "quantity": 1, "unit_price": 500}],
                "raw_request": user_input,
            }

        # Determine skill from the data
        skill_id = data.pop("skill_id", "create_po")

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=False,
                status=TaskStatus(state=TaskState.working, message=Message(role=Role.agent, message_id=str(uuid.uuid4()), parts=[TextPart(text="Processing purchase order...")])),
            )
        )

        if skill_id == "get_po_status":
            result = await self.agent.get_po_status(data.get("po_number", ""))
        else:
            result = await self.agent.create_purchase_order(data)

        result_text = json.dumps(result, indent=2, default=str)

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
        name="Purchase Order Agent",
        description="Manages purchase orders including creation, approval, and status tracking",
        url=os.getenv("AGENT_URL", "http://localhost:8002"),
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
                id="create_po",
                name="Create Purchase Order",
                description="Creates a new purchase order with budget validation and vendor lookup",
                tags=["purchase-order", "procurement", "vendor"],
                examples=[
                    "Create a PO for office supplies",
                    "Submit a purchase request for V001",
                ],
            ),
            AgentSkill(
                id="get_po_status",
                name="Get PO Status",
                description="Retrieves the status and details of an existing purchase order",
                tags=["purchase-order", "status", "tracking"],
                examples=[
                    "What is the status of PO-2024-001?",
                    "Check my purchase order",
                ],
            ),
        ],
    )


def create_app():
    agent_card = create_agent_card()
    task_store = InMemoryTaskStore()
    queue_manager = InMemoryQueueManager()
    executor = POAgentExecutor()

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
_sb_agent = PurchaseOrderAgent()


async def _handle_sb_message(payload: dict) -> dict:
    """Process a Service Bus message through the PO workflow."""
    skill_id = payload.pop("skill_id", "create_po")
    if skill_id == "get_po_status":
        return await _sb_agent.get_po_status(payload.get("po_number", ""))
    return await _sb_agent.create_purchase_order(payload)


async def _start_servicebus_consumer():
    """Start consuming from po-requests queue in the background."""
    transport = ServiceBusTransport()
    logger.info("Starting Service Bus consumer for po-requests queue")
    await transport.consume_queue(
        PO_REQUEST_QUEUE,
        handler=_handle_sb_message,
        response_queue=PO_RESPONSE_QUEUE,
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8002))
    use_servicebus = os.getenv("USE_SERVICEBUS", "false").lower() == "true"

    if use_servicebus:
        async def _run():
            config = uvicorn.Config(app, host="0.0.0.0", port=port)
            server = uvicorn.Server(config)
            await asyncio.gather(
                server.serve(),
                _start_servicebus_consumer(),
            )

        logger.info(f"Starting PO Agent on port {port} WITH Service Bus consumer")
        asyncio.run(_run())
    else:
        logger.info(f"Starting Purchase Order Agent on port {port}")
        uvicorn.run(app, host="0.0.0.0", port=port)
