# A2A Agent Developer Guide

This guide provides step-by-step examples for building Azure AI Foundry agents with A2A (Agent-to-Agent) protocol integration.

## Table of Contents
- [A2A Server Components](#a2a-server-components)
  - [1. Main Entry Point](#1-main-entry-point)
  - [2. Agent Executor](#2-agent-executor)
  - [3. Agent Implementation](#3-agent-implementation)
  - [4. A2A Agent Card](#4-a2a-agent-card)
  - [5. Create Foundry Agent](#5-create-foundry-agent)
  - [6. Create Thread](#6-create-thread)
  - [7. Create Message](#7-create-message)
  - [8. Create and Update Task](#8-create-and-update-task)
- [A2A Client Usage](#a2a-client-usage)
  - [9. Use Agent](#9-use-agent)
  - [10. Invoke Agent](#10-invoke-agent)

---

## A2A Server Components

### 1. Main Entry Point

The main entry point sets up the A2A server with agent card, request handler, and HTTP server.

**File: `__main__.py`**

```python
import logging
import click
import httpx
from dotenv import load_dotenv

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
)
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from agent_executor import CurrencyAgentExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


@click.command()
@click.option('--host', default='localhost')
@click.option('--port', default=47128)
def main(host, port):
    """Starts the Currency Agent server using A2A."""
    logger.info(f'Starting Currency Agent server on {host}:{port}')

    httpx_client = httpx.AsyncClient()
    agent_card = get_agent_card(host, port)

    # Create task store with proper configuration
    task_store = InMemoryTaskStore()
    logger.info('Created task store')

    # Create push notification components
    push_config_store = InMemoryPushNotificationConfigStore()
    push_sender = BasePushNotificationSender(httpx_client, push_config_store)
    logger.info('Created push notification sender')

    # Create the executor and request handler
    executor = CurrencyAgentExecutor()
    logger.info('Created agent executor')

    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
        push_config_store=push_config_store,
        push_sender=push_sender,
    )
    logger.info('Created request handler')

    # Configure the server with proper JSON-RPC methods
    server = A2AStarletteApplication(
        agent_card=agent_card, http_handler=request_handler
    )
    logger.info('Created A2A server application')

    # Add middleware for debugging requests
    app = server.build()

    @app.middleware('http')
    async def log_requests(request, call_next):
        body = await request.body()
        logger.info(f'Incoming request: {request.method} {request.url}')
        logger.info(
            f'Request body: {body.decode("utf-8") if body else "Empty"}'
        )
        response = await call_next(request)
        return response

    import uvicorn

    logger.info(f'Starting uvicorn server at http://{host}:{port}')
    uvicorn.run(app, host=host, port=port)


def get_agent_card(host: str, port: int):
    """Returns the Agent Card for the Currency Agent."""
    capabilities = AgentCapabilities(streaming=True)
    
    skill = AgentSkill(
        id='currency_exchange_agent',
        name='Currency Exchange Agent',
        description=(
            'Handles currency exchange queries and conversions using real-time exchange rates '
            'from the Frankfurter API.'
        ),
        tags=['currency', 'exchange', 'conversion', 'finance'],
        examples=[
            'How much is 1 USD to EUR?',
            'What is the current exchange rate for USD to JPY?',
            'Convert 100 GBP to USD',
        ],
    )

    agent_card = AgentCard(
        name='Currency Exchange Agent',
        description=(
            'A specialized currency exchange agent that provides real-time currency conversion rates.'
        ),
        url=f'http://{host}:{port}/',
        version='1.0.0',
        default_input_modes=['text'],
        default_output_modes=['text'],
        capabilities=capabilities,
        skills=[skill],
    )

    return agent_card


if __name__ == '__main__':
    main()
```

**Key Points:**
- Load environment variables with `load_dotenv()`
- Create task store, push notification components
- Initialize agent executor and request handler
- Build A2A Starlette application with agent card
- Start Uvicorn HTTP server

---

### 2. Agent Executor

The agent executor bridges between A2A protocol and your agent implementation.

**File: `agent_executor.py`**

```python
import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import (
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils import (
    new_agent_text_message,
    new_task,
    new_text_artifact,
)
from agent import CurrencyAgent


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CurrencyAgentExecutor(AgentExecutor):
    """Currency Agent Executor - handles A2A protocol integration."""

    def __init__(self):
        self.agent = CurrencyAgent()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Execute agent and stream results back to A2A."""
        query = context.get_user_input()
        task = context.current_task
        
        # Create task if not exists
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        # Stream agent responses
        async for partial in self.agent.stream(query, task.context_id):
            require_input = partial['require_user_input']
            is_done = partial['is_task_complete']
            text_content = partial['content']

            if require_input:
                # Task requires user input
                await event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        status=TaskStatus(
                            state=TaskState.input_required,
                            message=new_agent_text_message(
                                text_content,
                                task.context_id,
                                task.id,
                            ),
                        ),
                        final=True,
                        context_id=task.context_id,
                        task_id=task.id,
                    )
                )
            elif is_done:
                # Task completed - send final result
                await event_queue.enqueue_event(
                    TaskArtifactUpdateEvent(
                        append=False,
                        context_id=task.context_id,
                        task_id=task.id,
                        last_chunk=True,
                        artifact=new_text_artifact(
                            name='current_result',
                            description='Result of request to agent.',
                            text=text_content,
                        ),
                    )
                )
                await event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        status=TaskStatus(state=TaskState.completed),
                        final=True,
                        context_id=task.context_id,
                        task_id=task.id,
                    )
                )
            else:
                # Task in progress - send status update
                await event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        status=TaskStatus(
                            state=TaskState.working,
                            message=new_agent_text_message(
                                text_content,
                                task.context_id,
                                task.id,
                            ),
                        ),
                        final=False,
                        context_id=task.context_id,
                        task_id=task.id,
                    )
                )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception('cancel not supported')
```

**Key Points:**
- Inherit from `AgentExecutor`
- Implement `execute()` method that streams events
- Use `await event_queue.enqueue_event()` for all events
- Handle three states: `input_required`, `working`, `completed`

---

### 3. Agent Implementation

The agent wraps Azure AI Foundry agents with MCP tool integration.

**File: `agent.py`** (Core methods)

```python
import os
from azure.ai.agents import AgentsClient
from azure.identity import DefaultAzureCredential
from utils.mcp_tool_manager import MCPToolManager


class CurrencyAgent:
    INSTRUCTION = (
        'You are a specialized assistant for currency conversions. '
        "Use the 'get_exchange_rate' tool to answer currency questions."
    )

    def __init__(self):
        # Validate environment variables
        if 'AZURE_AI_FOUNDRY_PROJECT_ENDPOINT' not in os.environ:
            raise ValueError('AZURE_AI_FOUNDRY_PROJECT_ENDPOINT not set')

        self.endpoint = os.environ['AZURE_AI_FOUNDRY_PROJECT_ENDPOINT']
        self.credential = DefaultAzureCredential()
        self.agent = None
        self.threads = {}
        self.mcp_server_url = os.environ.get('MCP_ENDPOINT')
        self.mcp_tool_manager = None

    def _get_client(self) -> AgentsClient:
        """Get a new AgentsClient instance."""
        return AgentsClient(
            endpoint=self.endpoint,
            credential=self.credential,
        )
```

**Key Points:**
- Store endpoint and credentials
- Use `DefaultAzureCredential()` for Azure authentication
- Initialize MCP tool manager for external tools
- Create client factory method

---

### 4. A2A Agent Card

The agent card defines capabilities, skills, and metadata.

```python
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

def get_agent_card(host: str, port: int) -> AgentCard:
    """Create agent card with capabilities and skills."""
    
    # Define capabilities
    capabilities = AgentCapabilities(
        streaming=True,  # Supports streaming responses
    )
    
    # Define skills
    skill = AgentSkill(
        id='currency_exchange_agent',
        name='Currency Exchange Agent',
        description='Provides real-time currency conversion rates',
        tags=['currency', 'exchange', 'conversion'],
        examples=[
            'Convert 100 USD to EUR',
            'What is the exchange rate for USD to JPY?',
        ],
    )

    # Create agent card
    agent_card = AgentCard(
        name='Currency Exchange Agent',
        description='Specialized currency exchange agent',
        url=f'http://{host}:{port}/',
        version='1.0.0',
        default_input_modes=['text'],
        default_output_modes=['text'],
        capabilities=capabilities,
        skills=[skill],
    )

    return agent_card
```

**Key Points:**
- `AgentCapabilities` defines what the agent can do
- `AgentSkill` describes specific capabilities
- `AgentCard` is the complete agent metadata
- Include examples to help users understand usage

---

### 5. Create Foundry Agent

Create the Azure AI Foundry agent with tools.

```python
async def create_agent(self) -> Agent:
    """Create the AI Foundry agent with MCP tools."""
    if self.agent:
        return self.agent

    # Initialize MCP tool manager
    self.mcp_tool_manager = MCPToolManager(self.mcp_server_url)
    await self.mcp_tool_manager.initialize()

    # Get MCP tool definitions
    mcp_tools = self.mcp_tool_manager.get_tools()
    
    if not mcp_tools:
        raise ValueError('No MCP tools found')

    # Convert MCP tools to Azure AI Agents format
    azure_tools = []
    for tool_name, tool_def in mcp_tools.items():
        azure_tool_def = {
            'type': 'function',
            'function': {
                'name': tool_def['name'],
                'description': tool_def['description'],
                'parameters': tool_def['input_schema'],
            },
        }
        azure_tools.append(azure_tool_def)

    # Create agent with tools
    with self._get_client() as client:
        self.agent = client.create_agent(
            model=os.environ['AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME'],
            name='currency-agent',
            instructions=self.INSTRUCTION,
            tools=azure_tools,
        )
        return self.agent
```

**Key Points:**
- Initialize external tool manager (MCP)
- Convert tool definitions to Azure format
- Create agent with model, instructions, and tools
- Use context manager for client lifecycle

---

### 6. Create Thread

Create a conversation thread for the agent.

```python
async def create_thread(self, thread_id: str | None = None) -> AgentThread:
    """Create or retrieve a conversation thread."""
    if thread_id and thread_id in self.threads:
        # Reuse existing thread
        pass

    with self._get_client() as client:
        thread = client.threads.create()
        self.threads[thread.id] = thread.id
        return thread
```

**Key Points:**
- Threads maintain conversation context
- Store thread IDs for reuse
- Each user session should have its own thread

---

### 7. Create Message

Send a message to the thread.

```python
async def send_message(
    self, thread_id: str, content: str, role: str = 'user'
) -> ThreadMessage:
    """Send a message to the conversation thread."""
    with self._get_client() as client:
        message = client.messages.create(
            thread_id=thread_id, 
            role=role, 
            content=content
        )
        return message
```

**Key Points:**
- Messages are added to threads
- Role can be 'user' or 'assistant'
- Messages persist in the thread

---

### 8. Create and Update Task

Tasks are managed through the event queue in the executor.

```python
# In agent_executor.py

async def execute(self, context: RequestContext, event_queue: EventQueue):
    """Execute agent and manage task lifecycle."""
    
    # 1. Create task
    task = new_task(context.message)
    await event_queue.enqueue_event(task)
    
    # 2. Update task to working state
    await event_queue.enqueue_event(
        TaskStatusUpdateEvent(
            status=TaskStatus(
                state=TaskState.working,
                message=new_agent_text_message(
                    'Processing request...',
                    task.context_id,
                    task.id,
                ),
            ),
            final=False,
            context_id=task.context_id,
            task_id=task.id,
        )
    )
    
    # 3. Update task with result
    await event_queue.enqueue_event(
        TaskArtifactUpdateEvent(
            append=False,
            context_id=task.context_id,
            task_id=task.id,
            last_chunk=True,
            artifact=new_text_artifact(
                name='current_result',
                description='Result of request',
                text='Result content here',
            ),
        )
    )
    
    # 4. Mark task as completed
    await event_queue.enqueue_event(
        TaskStatusUpdateEvent(
            status=TaskStatus(state=TaskState.completed),
            final=True,
            context_id=task.context_id,
            task_id=task.id,
        )
    )
```

**Key Points:**
- Always `await` event queue operations
- Task states: `working`, `input_required`, `completed`, `failed`
- Use `TaskStatusUpdateEvent` for status changes
- Use `TaskArtifactUpdateEvent` for results

---

## A2A Client Usage

### 9. Use Agent

Call the agent via HTTP JSON-RPC.

**Python Example:**

```python
import httpx
import json

async def use_agent():
    """Call the A2A agent via HTTP."""
    url = "http://localhost:47128"
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "kind": "text",
                        "text": "Convert 100 USD to EUR"
                    }
                ],
                "messageId": "msg-123"
            },
            "metadata": {}
        }
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        result = response.json()
        print(json.dumps(result, indent=2))
```

**cURL Example:**

```bash
curl -X POST http://localhost:47128 \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [
          {
            "kind": "text",
            "text": "Convert 100 USD to EUR"
          }
        ],
        "messageId": "msg-123"
      },
      "metadata": {}
    }
  }'
```

---

### 10. Invoke Agent

Complete client example with error handling.

```python
import httpx
import asyncio
from typing import Dict, Any


class A2AClient:
    """Client for invoking A2A agents."""
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.request_id = 0
    
    async def invoke_agent(
        self, 
        message: str, 
        context_id: str = None
    ) -> Dict[Any, Any]:
        """Invoke the agent with a message."""
        self.request_id += 1
        
        payload = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [
                        {
                            "kind": "text",
                            "text": message
                        }
                    ],
                    "messageId": f"msg-{self.request_id}"
                },
                "metadata": {}
            }
        }
        
        if context_id:
            payload["params"]["contextId"] = context_id
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    self.base_url, 
                    json=payload
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                print(f"HTTP error: {e}")
                raise
            except Exception as e:
                print(f"Error: {e}")
                raise


# Usage example
async def main():
    client = A2AClient("http://localhost:47128")
    
    # First message
    result1 = await client.invoke_agent("Convert 100 USD to EUR")
    print("Response 1:", result1)
    
    # Follow-up message in same context
    if "result" in result1:
        context_id = result1["result"].get("contextId")
        result2 = await client.invoke_agent(
            "What about USD to JPY?", 
            context_id=context_id
        )
        print("Response 2:", result2)


if __name__ == "__main__":
    asyncio.run(main())
```

**Key Points:**
- Use JSON-RPC 2.0 protocol
- Include `messageId` for tracking
- Reuse `contextId` for conversation continuity
- Handle errors appropriately
- Set appropriate timeouts

---

## Environment Configuration

**`.env` file:**

```bash
# Azure AI Foundry Configuration
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://your-project.services.ai.azure.com/api/projects/your-project
AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=gpt-4

# MCP Server Endpoint
MCP_ENDPOINT=http://localhost:7071/runtime/webhooks/mcp/sse

# A2A Server Configuration
A2A_HOST=localhost
A2A_PORT=47128

# Logging
LOG_LEVEL=INFO
```

---

## Running the Agent

1. **Start MCP Server** (if using external tools):
```bash
cd mcp_server
func start
```

2. **Start A2A Agent**:
```bash
cd currencyagent
uv run .
```

3. **Test the Agent**:
```bash
curl -X POST http://localhost:47128 \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"kind": "text", "text": "Convert 100 USD to EUR"}],
        "messageId": "test-1"
      }
    }
  }'
```

---

## Best Practices

1. **Always await event queue operations** - Missing `await` causes runtime warnings
2. **Use context managers** for Azure clients - Ensures proper cleanup
3. **Handle authentication properly** - Use `az login` or configure credentials
4. **Validate environment variables** - Check required config at startup
5. **Stream responses** - Better user experience for long-running operations
6. **Include error handling** - Graceful degradation for tool failures
7. **Log appropriately** - Help with debugging without overwhelming output
8. **Reuse threads** - Maintain conversation context efficiently

---

## Troubleshooting

### Agent fails to start
- Check `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` is set
- Run `az login` to authenticate
- Verify MCP server is running (if using tools)

### RuntimeWarning: coroutine was never awaited
- Add `await` to all `event_queue.enqueue_event()` calls

### Connection timeout to MCP server
- Check MCP endpoint URL (should end with `/sse` for SSE)
- Verify MCP server is running on correct port
- Check firewall settings

### Authentication errors
- Run `az login` to refresh credentials
- Check Azure CLI is installed
- Verify project endpoint is correct

---

## Additional Resources

- [Azure AI Foundry Documentation](https://learn.microsoft.com/azure/ai-studio/)
- [A2A Protocol Specification](https://github.com/microsoft/agent-protocol)
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
