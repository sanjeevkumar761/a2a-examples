# A2A Server & Client Development Checklist

This checklist guides you through building an Agent-to-Agent (A2A) server with Azure AI Foundry and creating a test client.

## 📋 Development Steps

### 1. Environment Setup
- [ ] Create `.env` file with required environment variables:
  ```
  AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=<your-endpoint>
  AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME=<your-model>
  ```
- [ ] Configure `pyproject.toml` with dependencies:
  - `a2a-sdk` - A2A protocol implementation
  - `azure-ai-agents` - Azure AI Foundry agents SDK
  - `azure-identity` - Authentication
  - `starlette` - Web framework
  - `uvicorn` - ASGI server
  - `python-dotenv` - Environment variables
  - `httpx` - HTTP client (for test client)
- [ ] Run `uv sync` to install dependencies

### 2. Create Main Server Entry Point (`__main__.py`)
- [ ] Import required modules:
  - A2A server components (`A2AStarletteApplication`, `DefaultRequestHandler`, `InMemoryTaskStore`)
  - A2A types (`AgentCard`, `AgentSkill`, `AgentCapabilities`)
  - Starlette components (`Starlette`, `Route`)
  - Your agent executor
- [ ] Load environment variables using `dotenv`
- [ ] Configure logging
- [ ] Define agent skills:
  - Skill ID and name
  - Description
  - Tags
  - Example queries
- [ ] Create agent card:
  - Agent name and description
  - Version
  - Input/output modes
  - Capabilities (e.g., streaming)
  - Skills list
- [ ] Initialize agent executor with agent card
- [ ] Create request handler with executor and task store
- [ ] Initialize A2A Starlette application
- [ ] Add custom routes (e.g., health check endpoint)
- [ ] Create Starlette app with all routes
- [ ] Run server with `uvicorn.run()`

### 3. Create Agent Executor (`foundry_agent_executor.py`)
- [ ] Import required modules:
  - A2A server execution components (`AgentExecutor`, `RequestContext`, `EventQueue`, `TaskUpdater`)
  - A2A types (`AgentCard`, `Part`, `TextPart`, `FilePart`, `TaskState`)
  - Your Foundry agent implementation
- [ ] Define `FoundryAgentExecutor` class inheriting from `AgentExecutor`
- [ ] Implement `__init__` to store agent card and initialize state
- [ ] Implement `_get_or_create_agent()` to lazily create the Foundry agent
- [ ] Implement `_get_or_create_thread()` to manage conversation threads per context
- [ ] Implement `_process_request()`:
  - Convert A2A message parts to text
  - Get/create agent and thread
  - Update task status to "working"
  - Run conversation through agent
  - Send responses via task updater
  - Mark task as complete or failed
- [ ] Implement `_convert_parts_to_text()` to extract text from A2A message parts
- [ ] Implement `execute()` method:
  - Create task updater
  - Submit task if new
  - Start work
  - Process request
- [ ] Implement `cancel()` to handle task cancellation
- [ ] Implement `cleanup()` to clean up agent resources
- [ ] Create factory function `create_foundry_agent_executor()`

### 4. Create Foundry Agent Implementation (`foundry_agent.py`)
- [ ] Import required modules:
  - Azure AI Agents SDK (`AgentsClient`, `Agent`, `AgentThread`, `ThreadRun`, `ToolOutput`)
  - Azure Identity (`DefaultAzureCredential`)
  - Standard libraries (`json`, `logging`, `os`, `time`, `datetime`)
- [ ] Define `FoundryCalendarAgent` class
- [ ] Implement `__init__`:
  - Load Azure AI Foundry endpoint from environment
  - Initialize credentials
  - Set up agent and thread tracking
- [ ] Implement `_get_client()` to create AgentsClient instances
- [ ] Implement `create_agent()`:
  - Create agent with model, name, instructions, and tools
  - Use `client.agents.create_agent()`
- [ ] Implement `_get_calendar_instructions()`:
  - Define agent personality and capabilities
  - Provide usage guidelines
  - Include current date/time context
- [ ] Implement `_get_calendar_tools()`:
  - Define function tools with names, descriptions, and parameters
  - Follow OpenAI function calling format
- [ ] Implement `_handle_tool_calls()`:
  - Extract tool calls from run
  - Execute tool logic (or simulate for demo)
  - Format tool outputs
  - Submit outputs using `client.agent_threads.submit_tool_outputs()`
- [ ] Implement `create_thread()` using `client.agent_threads.create_thread()`
- [ ] Implement `run_conversation()`:
  - Add user message to thread
  - Create and execute run
  - Poll for completion
  - Handle tool calls if required
  - Retrieve and return assistant messages
- [ ] Implement `cleanup_agent()` to delete agent resources
- [ ] Create factory function `create_foundry_calendar_agent()`

### 5. Create A2A Test Client (`test_client.py`)
- [ ] Import required modules:
  - A2A client components (`A2ACardResolver`, `A2AClient`)
  - A2A types (`AgentCard`, `MessageSendParams`, `SendMessageRequest`, `SendStreamingMessageRequest`)
  - HTTP client (`httpx`)
  - Utilities (`logging`, `uuid`)
- [ ] Implement `test_agent_health()`:
  - Check server health endpoint
  - Verify server is responsive
- [ ] Implement `print_detailed_response()`:
  - Extract response from JSON-RPC result
  - Display task status
  - Show agent's response text from status message and history
- [ ] Implement `main()` function:
  - Load environment variables
  - Configure logging
  - Get base URL from environment
  - Create HTTP client with timeout
- [ ] Test agent health before proceeding
- [ ] Initialize `A2ACardResolver` with HTTP client and base URL
- [ ] Fetch public agent card:
  - Attempt to get agent card from well-known path
  - Display agent name, description, and skills
- [ ] (Optional) Fetch extended/authenticated agent card if supported
- [ ] Initialize `A2AClient` with HTTP client and agent card
- [ ] Define test messages for your agent's domain
- [ ] For each test message:
  - Create message payload with role, parts, and message ID
  - Test regular message sending with `SendMessageRequest`
  - Display response
  - Test streaming with `SendStreamingMessageRequest`
  - Process streaming chunks
- [ ] Display test summary
- [ ] Add command-line entry point with error handling

### 6. Run the A2A Server
- [ ] Ensure environment variables are set
- [ ] Run: `uv run .` (executes `__main__.py`)
- [ ] Verify server starts successfully
- [ ] Check logs for:
  - Agent card information
  - Skills loaded
  - Server listening address
- [ ] Test health endpoint: `curl http://localhost:10007/health`

### 7. Run the A2A Test Client
- [ ] Ensure server is running
- [ ] Run: `uv run test_client.py`
- [ ] Verify client can:
  - Connect to server
  - Fetch agent card
  - Send messages
  - Receive responses (both regular and streaming)
- [ ] Review logs to confirm:
  - Successful agent card retrieval
  - Messages sent and received
  - Response text displayed correctly
  - Streaming chunks processed

## 🔍 Verification Checklist

After completing all steps:
- [ ] Server starts without errors
- [ ] Health check endpoint responds
- [ ] Agent card is accessible via well-known path
- [ ] Client can fetch and parse agent card
- [ ] Client can send messages successfully
- [ ] Server processes messages and returns responses
- [ ] Streaming responses work correctly
- [ ] Tool calls (if any) are handled properly
- [ ] Error handling works for invalid requests
- [ ] Logs provide useful debugging information

## 📚 Additional Resources

- A2A Protocol Specification: https://agent-to-agent-protocol.com/
- Azure AI Foundry Documentation: https://learn.microsoft.com/azure/ai-foundry/
- Azure AI Agents SDK: https://learn.microsoft.com/python/api/overview/azure/ai-agents/

## 🎯 Next Steps

After completing this checklist:
1. Customize agent instructions for your specific use case
2. Implement real tool functions (replace simulations)
3. Add authentication and authorization
4. Implement proper error handling and retry logic
5. Add monitoring and telemetry
6. Deploy to production environment
7. Create additional test scenarios
8. Document your agent's capabilities and API
