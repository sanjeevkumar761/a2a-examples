# MCP Tool Usage Scenarios with Azure AI Foundry Agents

## Overview
Model Context Protocol (MCP) enables agents to access external tools and services through standardized interfaces. Below are 5 practical scenarios demonstrating different MCP integration patterns.

---

## 1. Local Calculator Tool (MCPStdioTool.py)
**Scenario:** Mathematical computation using a locally-run MCP server via stdio communication.  
**Use Case:** The agent uses `uvx mcp-server-calculator` to perform accurate calculations (e.g., "What is 15 * 23 + 45?") without relying on LLM arithmetic, ensuring precision for financial or scientific applications.  
**Key Feature:** Stdio-based MCP tools run as subprocess commands, ideal for local utilities like calculators, file processors, or data validators.

---

## 2. HTTP API Documentation Search (MCPStreamableHTTPTool.py)
**Scenario:** Querying Microsoft Learn documentation through an HTTP-based MCP server endpoint.  
**Use Case:** The agent searches Azure CLI documentation (e.g., "How to create an Azure storage account?") by connecting to `https://learn.microsoft.com/api/mcp`, providing developers with accurate, up-to-date technical guidance.  
**Key Feature:** HTTP-based MCP tools integrate with web APIs, enabling agents to access remote services, databases, or enterprise knowledge bases.

---

## 3. API Gateway Protected Documentation (MCPStreamableHTTPTool_AI_Gateway.py)
**Scenario:** Accessing MCP services through Azure API Management Gateway for enterprise security and monitoring.  
**Use Case:** The agent queries documentation behind a secured gateway (`https://testgatewayeastus.azure-api.net/...`) with authentication tokens, enabling enterprise-grade access control and usage tracking.  
**Key Feature:** Gateway-protected MCP tools provide rate limiting, authentication, and audit logging for production deployments.

---

## 4. Real-time WebSocket Data Streams (MCPWebsocketTool.py)
**Scenario:** Connecting to live data sources via WebSocket for real-time information retrieval.  
**Use Case:** The agent monitors streaming data (e.g., "What is the current market status?") from a WebSocket MCP server at `wss://api.example.com/mcp`, ideal for financial dashboards, IoT sensors, or live event tracking.  
**Key Feature:** WebSocket-based MCP tools enable bidirectional, persistent connections for scenarios requiring continuous data updates.

---

## 5. GitHub Repository Analysis with Approval Workflow (sample_agent_mcp.py)
**Scenario:** Agent accessing external GitHub repositories through MCP with human-in-the-loop approval.  
**Use Case:** The agent analyzes Azure REST API specifications from `https://gitmcp.io/Azure/azure-rest-api-specs`, but requires explicit approval before accessing the repository, ensuring security and compliance in sensitive environments.  
**Key Feature:** Approval-based MCP tools (`require_approval="always"`) enable controlled access to external resources, with conversation-based interaction for approval requests and responses.

---

## Key Takeaways

- **MCPStdioTool**: Best for local command-line utilities (calculators, file tools)
- **MCPStreamableHTTPTool**: Best for web APIs and remote services (documentation, databases)
- **MCPWebsocketTool**: Best for real-time streaming data (market feeds, IoT, live events)
- **Approval Workflows**: Essential for security-sensitive scenarios requiring human oversight
- **Azure AI Foundry Integration**: All patterns use `AzureAIAgentClient` for managed agent infrastructure with streaming responses

## Next Steps

1. Start with **MCPStdioTool.py** for simple local tool integration
2. Explore **MCPStreamableHTTPTool_AI_Gateway.py** for enterprise-grade deployments
3. Review **sample_agent_mcp.py** to understand approval workflows for production use
4. Customize MCP tools based on your specific domain requirements (finance, healthcare, manufacturing)
