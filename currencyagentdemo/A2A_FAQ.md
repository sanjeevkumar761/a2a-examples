# A2A Agent Development - Frequently Asked Questions

## Table of Contents
- [Environment Setup](#environment-setup)
- [Azure AI Foundry](#azure-ai-foundry)
- [A2A Server](#a2a-server)
- [Agent Implementation](#agent-implementation)
- [MCP Integration](#mcp-integration)
- [Event Queue & Tasks](#event-queue--tasks)
- [Client Integration](#client-integration)
- [Authentication](#authentication)
- [Debugging & Troubleshooting](#debugging--troubleshooting)
- [Performance & Best Practices](#performance--best-practices)

---

## Environment Setup

### Q: What environment variables are required?
**A:** Minimum required variables:
```bash
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://your-project.services.ai.azure.com/api/projects/your-project
AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=gpt-4
MCP_ENDPOINT=http://localhost:7071/runtime/webhooks/mcp/sse  # If using MCP tools
A2A_HOST=localhost
A2A_PORT=47128
```

### Q: Should I use `.env` or `local.settings.json`?
**A:** 
- `.env` - For A2A agent configuration (Python apps)
- `local.settings.json` - For Azure Functions (MCP server)
- Use `python-dotenv` to load `.env` in Python: `load_dotenv()`

### Q: How do I install Azure Functions Core Tools?
**A:** Choose one method:
```bash
# NPM
npm install -g azure-functions-core-tools@4

# Chocolatey (Windows)
choco install azure-functions-core-tools

# Winget (Windows)
winget install Microsoft.Azure.FunctionsCoreTools

# Homebrew (Mac)
brew tap azure/functions
brew install azure-functions-core-tools@4
```

### Q: What Python version should I use?
**A:** Python 3.10+ is recommended. Azure AI Agents SDK requires Python 3.8 minimum.

---

## Azure AI Foundry

### Q: What's the difference between project endpoint and API key authentication?
**A:**
- **Project Endpoint** (Recommended): Uses `DefaultAzureCredential` with identity-based auth (Azure CLI, Managed Identity, etc.)
  ```python
  credential = DefaultAzureCredential()
  client = AgentsClient(endpoint=endpoint, credential=credential)
  ```
- **API Key**: Uses `AzureKeyCredential` with static key
  ```python
  credential = AzureKeyCredential(api_key)
  client = AgentsClient(endpoint=endpoint, credential=credential)
  ```

### Q: Why do I need `az login`?
**A:** `DefaultAzureCredential` tries multiple authentication methods in order:
1. Environment variables
2. Managed Identity (in Azure)
3. **Azure CLI** (local development) ← Requires `az login`
4. Visual Studio Code
5. Azure PowerShell

For local development, Azure CLI is the primary method.

### Q: How long do Azure CLI credentials last?
**A:** Azure CLI tokens typically expire after 1 hour. Run `az account get-access-token` to check expiry, or just run `az login` when you see authentication errors.

### Q: Can I use service principal instead of `az login`?
**A:** Yes! Set environment variables:
```bash
AZURE_CLIENT_ID=your-client-id
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_SECRET=your-client-secret
```
`DefaultAzureCredential` will automatically use these.

### Q: What models can I use?
**A:** Any model deployed in your Azure AI Foundry project:
- GPT-4, GPT-4 Turbo
- GPT-3.5 Turbo
- GPT-4o, GPT-4o mini
- Or other models you've deployed

Specify via `AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME`.

---

## A2A Server

### Q: What is A2A protocol?
**A:** Agent-to-Agent (A2A) is Microsoft's protocol for agent communication using JSON-RPC 2.0 over HTTP. It enables:
- Standardized agent invocation
- Task management
- Streaming responses
- Context preservation across messages

### Q: How do I create an A2A server?
**A:** Minimum setup:
```python
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

# Create components
agent_card = AgentCard(...)
agent_executor = YourAgentExecutor()
request_handler = DefaultRequestHandler(
    agent_executor=agent_executor,
    task_store=InMemoryTaskStore()
)

# Create A2A app
a2a_app = A2AStarletteApplication(
    agent_card=agent_card,
    http_handler=request_handler
)

# Run with uvicorn
app = a2a_app.build()
uvicorn.run(app, host='localhost', port=47128)
```

### Q: What's the difference between `InMemoryTaskStore` and other stores?
**A:** 
- `InMemoryTaskStore` - Tasks stored in memory, lost on restart (good for development)
- Custom stores - Persist tasks to database, Redis, etc. (production)

Implement `TaskStore` interface for custom storage.

### Q: Do I need push notifications?
**A:** Push notifications are optional and used for:
- Notifying clients of task updates
- Real-time status changes
- Background task completion

For synchronous request/response, you don't need them. Example setup:
```python
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
)

push_config_store = InMemoryPushNotificationConfigStore()
push_sender = BasePushNotificationSender(httpx_client, push_config_store)

request_handler = DefaultRequestHandler(
    agent_executor=executor,
    task_store=task_store,
    push_config_store=push_config_store,
    push_sender=push_sender,
)
```

### Q: What methods does A2A support?
**A:** JSON-RPC methods:
- `message/send` - Send message to agent
- `task/get` - Get task status
- `task/cancel` - Cancel running task
- `card/get` - Get agent card
- Custom methods can be added

---

## Agent Implementation

### Q: What's the role of `AgentExecutor`?
**A:** `AgentExecutor` is the bridge between A2A protocol and your agent logic. It:
1. Receives requests from A2A server
2. Calls your agent implementation
3. Streams events back via `EventQueue`
4. Manages task lifecycle

Must implement:
```python
class YourExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue):
        # Your logic here
        pass
    
    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        # Handle cancellation
        pass
```

### Q: How do I stream responses?
**A:** Use `EventQueue` to send events:
```python
async def execute(self, context: RequestContext, event_queue: EventQueue):
    # Working state
    await event_queue.enqueue_event(
        TaskStatusUpdateEvent(
            status=TaskStatus(state=TaskState.working),
            context_id=task.context_id,
            task_id=task.id,
        )
    )
    
    # Result
    await event_queue.enqueue_event(
        TaskArtifactUpdateEvent(
            artifact=new_text_artifact(text="Result"),
            context_id=task.context_id,
            task_id=task.id,
        )
    )
    
    # Completed
    await event_queue.enqueue_event(
        TaskStatusUpdateEvent(
            status=TaskStatus(state=TaskState.completed),
            final=True,
            context_id=task.context_id,
            task_id=task.id,
        )
    )
```

### Q: What are task states?
**A:**
- `working` - Task in progress
- `input_required` - Waiting for user input
- `completed` - Task finished successfully
- `failed` - Task failed with error
- `cancelled` - Task was cancelled

### Q: How do I handle multi-turn conversations?
**A:** Use threads to maintain context:
```python
# Create thread once
thread = client.threads.create()
thread_id = thread.id

# Reuse thread_id for follow-up messages
message1 = client.messages.create(thread_id=thread_id, role="user", content="Hello")
message2 = client.messages.create(thread_id=thread_id, role="user", content="Follow-up")
```

Store `thread_id` in your agent and associate with `context_id` from A2A.

### Q: Should I create a new agent for each request?
**A:** No! Reuse the agent instance:
```python
class YourAgent:
    def __init__(self):
        self.agent = None
    
    async def get_agent(self):
        if not self.agent:
            with self._get_client() as client:
                self.agent = client.create_agent(...)
        return self.agent
```

Agents are stateless; conversations are in threads.

---

## MCP Integration

### Q: What is MCP?
**A:** Model Context Protocol - a standard for providing external tools/context to LLMs. It's a server that exposes:
- Tools (functions the LLM can call)
- Resources (data/files the LLM can read)
- Prompts (reusable prompt templates)

### Q: Why use MCP instead of direct tool calling?
**A:**
- **Separation of concerns** - Tools in separate service
- **Reusability** - One MCP server, many agents
- **Security** - Isolated execution environment
- **Language agnostic** - MCP server can be in any language

### Q: What's the correct MCP endpoint format?
**A:** For Azure Functions MCP server with SSE (Server-Sent Events):
```
http://localhost:7071/runtime/webhooks/mcp/sse
```

NOT just `http://localhost:7071` - you'll get 405 Method Not Allowed.

### Q: How do I convert MCP tools to Azure AI Agents format?
**A:**
```python
# MCP tool definition
mcp_tool = {
    "name": "get_weather",
    "description": "Get weather for location",
    "input_schema": {
        "type": "object",
        "properties": {
            "location": {"type": "string"}
        },
        "required": ["location"]
    }
}

# Convert to Azure format
azure_tool = {
    "type": "function",
    "function": {
        "name": mcp_tool["name"],
        "description": mcp_tool["description"],
        "parameters": mcp_tool["input_schema"],
    }
}
```

### Q: How do I execute MCP tools from my agent?
**A:** Two approaches:

**1. Via MCP Client (Recommended):**
```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("tool_name", arguments={...})
```

**2. Via HTTP Request:**
```python
import httpx

response = await httpx_client.post(
    mcp_endpoint,
    json={
        "tool": "tool_name",
        "arguments": {...}
    }
)
```

### Q: Can I use multiple MCP servers?
**A:** Yes! Create multiple `MCPToolManager` instances:
```python
weather_tools = MCPToolManager("http://localhost:7071/weather/sse")
calendar_tools = MCPToolManager("http://localhost:7072/calendar/sse")

await weather_tools.initialize()
await calendar_tools.initialize()

all_tools = {**weather_tools.get_tools(), **calendar_tools.get_tools()}
```

---

## Event Queue & Tasks

### Q: Why do I get "RuntimeWarning: coroutine was never awaited"?
**A:** You forgot `await` on an async function:
```python
# WRONG ❌
event_queue.enqueue_event(event)

# CORRECT ✅
await event_queue.enqueue_event(event)
```

### Q: What's the difference between `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent`?
**A:**
- `TaskStatusUpdateEvent` - Changes task state (working → completed)
- `TaskArtifactUpdateEvent` - Sends result data (text, files, etc.)

You need both: artifacts for data, status for lifecycle.

### Q: When should I set `final=True`?
**A:** Set `final=True` on the last event for a task:
```python
# Intermediate updates - final=False
await event_queue.enqueue_event(
    TaskStatusUpdateEvent(
        status=TaskStatus(state=TaskState.working),
        final=False,  # More updates coming
        ...
    )
)

# Last update - final=True
await event_queue.enqueue_event(
    TaskStatusUpdateEvent(
        status=TaskStatus(state=TaskState.completed),
        final=True,  # No more updates
        ...
    )
)
```

### Q: Can I send multiple artifacts?
**A:** Yes! Use different artifact names:
```python
# First artifact
await event_queue.enqueue_event(
    TaskArtifactUpdateEvent(
        artifact=new_text_artifact(name="summary", text="Summary..."),
        ...
    )
)

# Second artifact
await event_queue.enqueue_event(
    TaskArtifactUpdateEvent(
        artifact=new_text_artifact(name="details", text="Details..."),
        ...
    )
)
```

### Q: What's the `append` parameter in `TaskArtifactUpdateEvent`?
**A:**
- `append=True` - Add to existing artifact (streaming)
- `append=False` - Replace artifact (complete result)

Example streaming:
```python
for chunk in stream_response():
    await event_queue.enqueue_event(
        TaskArtifactUpdateEvent(
            append=True,  # Accumulate chunks
            artifact=new_text_artifact(name="response", text=chunk),
            last_chunk=(chunk == final_chunk),
            ...
        )
    )
```

---

## Client Integration

### Q: How do I call an A2A agent?
**A:** Use JSON-RPC 2.0 over HTTP POST:
```python
import httpx

payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "message/send",
    "params": {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": "Your message"}],
            "messageId": "unique-id"
        }
    }
}

response = await httpx.AsyncClient().post(
    "http://localhost:47128",
    json=payload
)
```

### Q: What should I use for `messageId`?
**A:** Any unique string. Common patterns:
- UUID: `str(uuid.uuid4())`
- Timestamp: `f"msg-{int(time.time()*1000)}"`
- Sequential: `f"msg-{counter}"`

### Q: How do I maintain conversation context?
**A:** Use `contextId` in requests:
```python
# First message - creates context
response1 = await client.post(url, json={
    "method": "message/send",
    "params": {"message": {...}}
})
context_id = response1.json()["result"]["contextId"]

# Follow-up message - reuse context
response2 = await client.post(url, json={
    "method": "message/send",
    "params": {
        "contextId": context_id,  # Maintains conversation
        "message": {...}
    }
})
```

### Q: How do I handle streaming responses?
**A:** A2A uses HTTP long-polling or SSE. For basic clients, just await the response:
```python
response = await client.post(url, json=payload, timeout=30.0)
result = response.json()
```

The agent streams internally, but returns complete result to client.

### Q: Can I call A2A agents from JavaScript?
**A:** Yes! Same JSON-RPC protocol:
```javascript
const response = await fetch('http://localhost:47128', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'message/send',
        params: {
            message: {
                role: 'user',
                parts: [{kind: 'text', text: 'Hello'}],
                messageId: 'msg-1'
            }
        }
    })
});
const result = await response.json();
```

---

## Authentication

### Q: What authentication does A2A server use?
**A:** By default, no authentication. In production, add middleware:
```python
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware

app = Starlette(
    routes=routes,
    middleware=[
        Middleware(AuthenticationMiddleware, backend=YourAuthBackend())
    ]
)
```

### Q: How do I secure my Azure AI Foundry connection?
**A:** Use managed identity in production:
```python
from azure.identity import ManagedIdentityCredential

# In Azure (App Service, Functions, etc.)
credential = ManagedIdentityCredential()
client = AgentsClient(endpoint=endpoint, credential=credential)
```

No need for `az login` or secrets in Azure environment.

### Q: Should I commit `.env` file?
**A:** **NO!** Add to `.gitignore`:
```
.env
.env.local
local.settings.json
```

Use `.env.template` with placeholder values for documentation.

### Q: How do I rotate API keys?
**A:** If using API keys:
1. Generate new key in Azure AI Foundry
2. Update environment variable
3. Restart agent service
4. Revoke old key

With `DefaultAzureCredential`, tokens auto-refresh.

---

## Debugging & Troubleshooting

### Q: How do I enable debug logging?
**A:**
```python
import logging

logging.basicConfig(
    level=logging.DEBUG,  # or INFO, WARNING
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# For specific loggers
logging.getLogger('azure').setLevel(logging.DEBUG)
logging.getLogger('a2a').setLevel(logging.DEBUG)
```

### Q: Agent creation works but subsequent requests fail with auth timeout
**A:** Azure CLI token expired. Run:
```bash
az login
# Or check token
az account get-access-token
```

### Q: I get "405 Method Not Allowed" on MCP endpoint
**A:** Wrong endpoint. Use SSE endpoint:
```
http://localhost:7071/runtime/webhooks/mcp/sse
```
NOT `http://localhost:7071`

### Q: Tool calls fail with "Tool not found"
**A:** Check:
1. MCP server is running (`func start`)
2. Tools are registered in agent creation
3. Tool names match exactly (case-sensitive)
4. Tool definitions are valid JSON schemas

### Q: How do I test my agent locally?
**A:**
```bash
# 1. Start MCP server (if using)
cd mcp_server
func start

# 2. Start A2A agent
cd agent
uv run .

# 3. Test with curl
curl -X POST http://localhost:47128 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","parts":[{"kind":"text","text":"test"}],"messageId":"test-1"}}}'
```

### Q: How do I debug tool execution?
**A:** Add logging in your tool handler:
```python
@app.generic_trigger(...)
def my_tool(context) -> str:
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"Tool called with context: {context}")
    
    try:
        result = do_work()
        logger.info(f"Tool result: {result}")
        return result
    except Exception as e:
        logger.error(f"Tool failed: {e}", exc_info=True)
        return f"Error: {str(e)}"
```

### Q: Agent hangs or times out
**A:** Check for:
- Missing `await` on async calls
- Infinite loops in streaming
- No final task status update (`final=True`)
- MCP server not responding (check `func start` output)

---

## Performance & Best Practices

### Q: Should I create a new client for each request?
**A:** No! Reuse clients with context managers:
```python
# WRONG ❌ - Creates client every time
def call_agent():
    client = AgentsClient(endpoint, credential)
    agent = client.create_agent(...)

# CORRECT ✅ - Reuse agent, use context manager
class MyAgent:
    def __init__(self):
        self.agent = None
    
    def _get_client(self):
        return AgentsClient(self.endpoint, self.credential)
    
    async def call(self):
        if not self.agent:
            with self._get_client() as client:
                self.agent = client.create_agent(...)
```

### Q: How many threads should I create?
**A:** One thread per conversation/user session. Don't create thread per message.

### Q: Should I use streaming?
**A:** Yes for:
- Long responses (>5 seconds)
- Better UX (progressive display)
- Large result sets

No for:
- Quick responses (<1 second)
- Simple queries

### Q: How do I handle rate limits?
**A:** Implement retry with backoff:
```python
from azure.core.exceptions import HttpResponseError
import asyncio

async def call_with_retry(func, max_retries=3):
    for i in range(max_retries):
        try:
            return await func()
        except HttpResponseError as e:
            if e.status_code == 429:  # Rate limit
                wait = 2 ** i  # Exponential backoff
                await asyncio.sleep(wait)
            else:
                raise
    raise Exception("Max retries exceeded")
```

### Q: Can I run multiple agents on one A2A server?
**A:** Not recommended. One agent per server for:
- Clear separation of concerns
- Independent scaling
- Isolated failures

Use multiple A2A servers on different ports if needed.

### Q: How do I deploy to production?
**A:**
1. Use managed identity (not `az login`)
2. Use persistent task store (not `InMemoryTaskStore`)
3. Add authentication middleware
4. Configure HTTPS/TLS
5. Set up monitoring and logging
6. Use environment-specific configs
7. Container-based deployment (Docker/AKS)

### Q: What's the recommended project structure?
**A:**
```
my-agent/
├── .env.template          # Template with placeholders
├── .gitignore            # Exclude .env, __pycache__, etc.
├── pyproject.toml        # Dependencies
├── __main__.py           # Entry point
├── agent.py              # Agent implementation
├── agent_executor.py     # A2A executor
├── tools/                # Tool implementations
│   ├── __init__.py
│   └── my_tools.py
└── tests/                # Unit tests
    └── test_agent.py
```

---

## Additional Resources

- [Azure AI Foundry Documentation](https://learn.microsoft.com/azure/ai-studio/)
- [A2A Protocol Specification](https://github.com/microsoft/agent-protocol)
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- [Azure Functions Documentation](https://learn.microsoft.com/azure/azure-functions/)
- [Python Azure Identity](https://learn.microsoft.com/python/api/overview/azure/identity-readme)

---

## Quick Reference

### Common Imports
```python
# Azure AI Foundry
from azure.ai.agents import AgentsClient
from azure.identity import DefaultAzureCredential

# A2A Server
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import InMemoryTaskStore

# A2A Types
from a2a.types import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
)

# A2A Utils
from a2a.utils import (
    new_task,
    new_text_artifact,
    new_agent_text_message,
)
```

### Common Commands
```bash
# Azure CLI
az login
az account show
az account get-access-token

# Azure Functions
func start                    # Start MCP server
func start --verbose          # Verbose output

# Python
uv run .                      # Run agent
uv add package-name          # Add dependency
python -m pip install -r requirements.txt
```

### Environment Variables Template
```bash
# .env.template
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://your-project.services.ai.azure.com/api/projects/your-project
AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=gpt-4
MCP_ENDPOINT=http://localhost:7071/runtime/webhooks/mcp/sse
A2A_HOST=localhost
A2A_PORT=47128
LOG_LEVEL=INFO
```
