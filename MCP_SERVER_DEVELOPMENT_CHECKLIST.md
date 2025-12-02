# MCP Server Development Checklist

This checklist guides you through building a Model Context Protocol (MCP) server as an Azure Function and integrating it with an A2A agent.

## 📋 Development Steps

### 1. Create MCP Server Project Structure
- [ ] Create project root directory (e.g., `mcp_server/`)
- [ ] Initialize the directory structure:
  ```
  mcp_server/
  ├── host.json
  ├── local.settings.json
  ├── requirements.txt
  └── function_app.py
  ```

### 2. Configure Azure Functions Files

#### 2.1 Create `host.json`
- [ ] Create `host.json` file in the project root
- [ ] Add basic Azure Functions host configuration:
  ```json
  {
    "version": "2.0",
    "logging": {
      "applicationInsights": {
        "samplingSettings": {
          "isEnabled": true,
          "maxTelemetryItemsPerSecond": 20
        }
      }
    },
    "extensionBundle": {
      "id": "Microsoft.Azure.Functions.ExtensionBundle",
      "version": "[4.*, 5.0.0)"
    }
  }
  ```

#### 2.2 Create `local.settings.json`
- [ ] Create `local.settings.json` file
- [ ] Configure local development settings:
  ```json
  {
    "IsEncrypted": false,
    "Values": {
      "AzureWebJobsStorage": "UseDevelopmentStorage=true",
      "FUNCTIONS_WORKER_RUNTIME": "python",
      "AzureWebJobsFeatureFlags": "EnableWorkerIndexing"
    }
  }
  ```
- [ ] Add any API keys or environment variables your tools need
- [ ] Note: This file should be in `.gitignore`

#### 2.3 Create `requirements.txt`
- [ ] Create `requirements.txt` file
- [ ] Add required Python packages:
  ```txt
  azure-functions
  mcp
  requests
  # Add other dependencies your tools need
  ```

### 3. Implement MCP Server (`function_app.py`)

#### 3.1 Set Up Imports
- [ ] Import Azure Functions components:
  ```python
  import azure.functions as func
  import logging
  ```
- [ ] Import MCP SDK components:
  ```python
  from mcp.server import Server
  from mcp.types import Tool, TextContent
  ```
- [ ] Import additional libraries for your tools:
  ```python
  import json
  import os
  from datetime import datetime
  # Add other imports as needed
  ```

#### 3.2 Initialize Function App and MCP Server
- [ ] Create Azure Functions app instance:
  ```python
  app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
  ```
- [ ] Initialize MCP server:
  ```python
  mcp_server = Server("your-mcp-server-name")
  ```
- [ ] Configure logging:
  ```python
  logger = logging.getLogger(__name__)
  ```

#### 3.3 Define Tools

For each tool you want to expose:
- [ ] Define the tool metadata using `@mcp_server.list_tools()` decorator
- [ ] Specify tool name, description, and input schema
- [ ] Example structure:
  ```python
  @mcp_server.list_tools()
  async def list_tools() -> list[Tool]:
      return [
          Tool(
              name="tool_name",
              description="Clear description of what the tool does",
              inputSchema={
                  "type": "object",
                  "properties": {
                      "param1": {
                          "type": "string",
                          "description": "Parameter description"
                      }
                  },
                  "required": ["param1"]
              }
          )
      ]
  ```

#### 3.4 Implement Tool Functions

For each tool:
- [ ] Create tool implementation function with `@mcp_server.call_tool()` decorator
- [ ] Handle input parameter validation
- [ ] Implement tool logic
- [ ] Handle errors gracefully
- [ ] Return results in MCP format
- [ ] Example structure:
  ```python
  @mcp_server.call_tool()
  async def call_tool(name: str, arguments: dict) -> list[TextContent]:
      try:
          if name == "tool_name":
              # Extract parameters
              param1 = arguments.get("param1")
              
              # Implement tool logic
              result = perform_operation(param1)
              
              # Return result
              return [TextContent(
                  type="text",
                  text=json.dumps(result)
              )]
          else:
              raise ValueError(f"Unknown tool: {name}")
      except Exception as e:
          logger.error(f"Error in tool {name}: {e}")
          return [TextContent(
              type="text",
              text=json.dumps({"error": str(e)})
          )]
  ```

#### 3.5 Create HTTP Trigger Function
- [ ] Define Azure Function HTTP trigger endpoint:
  ```python
  @app.route(route="mcp", methods=["POST"])
  async def mcp_endpoint(req: func.HttpRequest) -> func.HttpResponse:
      try:
          # Parse request
          request_data = req.get_json()
          
          # Route to appropriate MCP server method
          method = request_data.get("method")
          params = request_data.get("params", {})
          
          # Handle different MCP methods
          if method == "tools/list":
              result = await list_tools()
          elif method == "tools/call":
              result = await call_tool(
                  params.get("name"),
                  params.get("arguments", {})
              )
          else:
              return func.HttpResponse(
                  json.dumps({"error": "Unknown method"}),
                  status_code=400
              )
          
          # Return response
          return func.HttpResponse(
              json.dumps({"result": result}),
              mimetype="application/json"
          )
      
      except Exception as e:
          logger.error(f"Error processing request: {e}")
          return func.HttpResponse(
              json.dumps({"error": str(e)}),
              status_code=500
          )
  ```

#### 3.6 Add Health Check Endpoint (Optional but Recommended)
- [ ] Create health check endpoint:
  ```python
  @app.route(route="health", methods=["GET"])
  async def health_check(req: func.HttpRequest) -> func.HttpResponse:
      return func.HttpResponse(
          json.dumps({"status": "healthy", "server": "your-mcp-server"}),
          mimetype="application/json"
      )
  ```

### 4. Set Up Local Development Environment

#### 4.1 Install Azure Functions Core Tools
- [ ] Install Azure Functions Core Tools (if not already installed):
  - Windows: `npm install -g azure-functions-core-tools@4 --unsafe-perm true`
  - macOS: `brew tap azure/functions && brew install azure-functions-core-tools@4`
  - Linux: See [official documentation](https://learn.microsoft.com/azure/azure-functions/functions-run-local)

#### 4.2 Install Python Dependencies
- [ ] Create virtual environment: `python -m venv .venv`
- [ ] Activate virtual environment:
  - Windows: `.venv\Scripts\activate`
  - macOS/Linux: `source .venv/bin/activate`
- [ ] Install dependencies: `pip install -r requirements.txt`

#### 4.3 Start Azurite (Azure Storage Emulator)
- [ ] Install Docker if not already installed
- [ ] Start Azurite container:
  ```bash
  docker run -p 10000:10000 -p 10001:10001 -p 10002:10002 mcr.microsoft.com/azure-storage/azurite
  ```
- [ ] Verify Azurite is running (check Docker containers)

### 5. Test MCP Server Locally

#### 5.1 Start the MCP Server
- [ ] Navigate to `mcp_server` directory
- [ ] Start Azure Functions host:
  ```bash
  func start
  ```
- [ ] Verify server starts without errors
- [ ] Note the function URLs displayed in console

#### 5.2 Test Health Endpoint
- [ ] Test health check endpoint:
  ```bash
  curl http://localhost:7071/api/health
  ```
- [ ] Verify response returns healthy status

#### 5.3 Test Tool Listing
- [ ] Test tools list endpoint:
  ```bash
  curl -X POST http://localhost:7071/api/mcp \
    -H "Content-Type: application/json" \
    -d '{"method": "tools/list", "params": {}}'
  ```
- [ ] Verify all tools are listed with correct metadata

#### 5.4 Test Tool Execution
- [ ] Test each tool with sample inputs:
  ```bash
  curl -X POST http://localhost:7071/api/mcp \
    -H "Content-Type: application/json" \
    -d '{
      "method": "tools/call",
      "params": {
        "name": "tool_name",
        "arguments": {"param1": "test_value"}
      }
    }'
  ```
- [ ] Verify tool returns expected results
- [ ] Test error handling with invalid inputs

### 6. Integrate with A2A Agent

#### 6.1 Configure A2A Agent with MCP Tool Manager
- [ ] In your A2A agent code, import MCP tool manager:
  ```python
  from a2a.tools import MCPToolManager
  ```
- [ ] Initialize MCP tool manager with server URL:
  ```python
  mcp_manager = MCPToolManager(
      server_url="http://localhost:7071/api/mcp"
  )
  ```
- [ ] Load tools from MCP server:
  ```python
  tools = await mcp_manager.list_tools()
  ```
- [ ] Register tools with agent executor

#### 6.2 Update Agent Instructions
- [ ] Update agent instructions to mention available MCP tools
- [ ] Provide examples of when to use each tool
- [ ] Add any domain-specific guidance

#### 6.3 Handle MCP Tool Calls in Agent
- [ ] Implement tool call handler in agent executor:
  ```python
  async def handle_tool_call(tool_name: str, arguments: dict):
      result = await mcp_manager.call_tool(tool_name, arguments)
      return result
  ```
- [ ] Integrate with agent's run conversation loop
- [ ] Handle tool call responses and continue conversation

### 7. Test End-to-End Integration

#### 7.1 Start All Services
- [ ] Start Azurite (if not already running)
- [ ] Start MCP server: `func start`
- [ ] Start A2A agent server: `uv run .` (or appropriate command)

#### 7.2 Test Agent with MCP Tools
- [ ] Use A2A test client to send messages that require tool usage
- [ ] Verify agent correctly identifies when to use MCP tools
- [ ] Confirm tool calls are executed successfully
- [ ] Check agent incorporates tool results into responses
- [ ] Test error scenarios (invalid tool calls, network errors, etc.)

#### 7.3 Monitor Logs
- [ ] Check MCP server logs for tool invocations
- [ ] Check A2A agent logs for tool call handling
- [ ] Verify no errors in either service
- [ ] Confirm proper request/response flow

### 8. Deploy to Production (Optional)

#### 8.1 Prepare for Deployment
- [ ] Create Azure Function App in Azure Portal
- [ ] Configure application settings (environment variables)
- [ ] Set up managed identity for authentication
- [ ] Configure networking and CORS if needed

#### 8.2 Deploy MCP Server
- [ ] Deploy using Azure Functions Core Tools:
  ```bash
  func azure functionapp publish <function-app-name>
  ```
- [ ] Verify deployment succeeds
- [ ] Test deployed endpoints

#### 8.3 Update A2A Agent Configuration
- [ ] Update MCP server URL to production endpoint
- [ ] Configure authentication if required
- [ ] Redeploy A2A agent with updated configuration
- [ ] Test production integration

## 🔍 Verification Checklist

After completing all steps:
- [ ] MCP server starts without errors
- [ ] All tools are listed via `tools/list` endpoint
- [ ] Each tool executes successfully via `tools/call`
- [ ] Health check endpoint responds correctly
- [ ] Azurite storage emulator is running
- [ ] A2A agent can connect to MCP server
- [ ] A2A agent can list MCP tools
- [ ] A2A agent can execute MCP tools
- [ ] Tool results are properly integrated into agent responses
- [ ] Error handling works for invalid tool calls
- [ ] Logs provide useful debugging information
- [ ] End-to-end conversation flow works smoothly

## 📚 Additional Resources

- [Azure Functions Python Developer Guide](https://learn.microsoft.com/azure/azure-functions/functions-reference-python)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [A2A Protocol Documentation](https://agent-to-agent-protocol.com/)
- [Azure Functions Local Development](https://learn.microsoft.com/azure/azure-functions/functions-develop-local)

## 🎯 Common MCP Tool Examples

Consider implementing these common tool types:
- **Data Retrieval**: Query databases, APIs, or files
- **Calculations**: Perform mathematical or statistical operations
- **External Services**: Currency conversion, weather, stock prices
- **File Operations**: Read/write files, process documents
- **Web Scraping**: Extract information from websites
- **Custom Business Logic**: Domain-specific operations

## 💡 Best Practices

- [ ] Use descriptive tool names and clear descriptions
- [ ] Validate all input parameters
- [ ] Implement comprehensive error handling
- [ ] Log all tool invocations for debugging
- [ ] Use type hints for better code maintainability
- [ ] Document each tool's purpose and usage
- [ ] Test tools independently before integration
- [ ] Monitor tool performance and errors
- [ ] Implement rate limiting if calling external APIs
- [ ] Cache responses when appropriate
