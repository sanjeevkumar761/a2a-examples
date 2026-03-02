"""
A2A Server for Orchestrator Agent.
Coordinates between Invoice and PO agents via A2A protocol.
"""

import json
import os
import logging
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

from agent import OrchestratorAgent

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OrchestratorExecutor(AgentExecutor):
    """Executor that handles A2A requests for workflow orchestration."""

    def __init__(self):
        self.agent = OrchestratorAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_input = context.get_user_input()
        logger.info(f"Orchestrator received: {user_input}")

        try:
            request_data = json.loads(user_input)
        except (json.JSONDecodeError, TypeError):
            request_data = {
                "type": "full_flow",
                "invoice_data": {
                    "invoice_number": "INV-DEMO-001",
                    "vendor": "Acme Corp",
                    "vendor_id": "V001",
                    "amount": 5000,
                    "date": "2026-02-19",
                    "line_items": [
                        {"description": "Consulting services", "amount": 3000},
                        {"description": "Software licenses", "amount": 2000},
                    ],
                },
                "requester": "demo-user",
                "raw_request": user_input,
            }

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                final=False,
                status=TaskStatus(state=TaskState.working, message=Message(role=Role.agent, message_id=str(uuid.uuid4()), parts=[TextPart(text="Orchestrating procurement workflow...")])),

            )
        )

        result = await self.agent.orchestrate(request_data)
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
        name="Procurement Orchestrator Agent",
        description="Orchestrates procurement workflows by coordinating Invoice Validation and Purchase Order agents",
        url=os.getenv("AGENT_URL", "http://localhost:8000"),
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
                id="orchestrate_procurement",
                name="Orchestrate Procurement Workflow",
                description="Orchestrates a full procurement workflow including invoice validation, PO creation, and payment scheduling",
                tags=["orchestration", "procurement", "workflow"],
                examples=[
                    "Process this invoice and create a PO",
                    "Run the full procurement workflow",
                ],
            )
        ],
    )


def create_app():
    agent_card = create_agent_card()
    task_store = InMemoryTaskStore()
    queue_manager = InMemoryQueueManager()
    executor = OrchestratorExecutor()

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


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting Orchestrator Agent on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
