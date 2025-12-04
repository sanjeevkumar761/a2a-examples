import asyncio
import os
from agent_framework import ChatAgent, MCPWebsocketTool
from agent_framework_azure_ai import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

async def websocket_mcp_example():
    """
    Example using a WebSocket-based MCP server with Azure AI Foundry.
    
    NOTE: This is a template/example code. To run this:
    1. Replace the WebSocket URL with your actual MCP server endpoint
    2. Ensure your MCP server is running and accessible
    3. Update headers/authentication as needed for your server
    
    Example real-world MCP WebSocket servers:
    - Your own custom MCP server deployed as a service
    - Third-party MCP servers that support WebSocket protocol
    """
    
    # Get configuration from environment variables
    project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
    model_deployment = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4.1")
    
    if not project_endpoint:
        raise ValueError(
            "AZURE_AI_PROJECT_ENDPOINT environment variable is required.\n"
            "Set it to: https://<your-project>.services.ai.azure.com/api/projects/<project-id>"
        )
    
    print(f"🤖 Initializing AI Foundry Agent with WebSocket MCP Tool...")
    print(f"   Project: {project_endpoint}")
    print(f"   Model: {model_deployment}\n")
    print(f"⚠️  NOTE: Replace 'wss://api.example.com/mcp' with your actual MCP server URL\n")
    
    async with DefaultAzureCredential() as credential:
        async with (
            MCPWebsocketTool(
                name="realtime-data",
                url="wss://api.example.com/mcp",  # ⚠️ Replace with your actual MCP WebSocket server URL
            ) as mcp_server,
            ChatAgent(
                chat_client=AzureAIAgentClient(
                    project_endpoint=project_endpoint,
                    model_deployment_name=model_deployment,
                    async_credential=credential,
                    agent_name="DataAgent",
                ),
                instructions="You provide real-time data insights.",
            ) as agent,
        ):
            print("📝 User: What is the current market status?")
            print("🤖 Agent: ", end="", flush=True)
            
            async for chunk in agent.run_stream(
                "What is the current market status?",
                tools=mcp_server
            ):
                if chunk.text:
                    print(chunk.text, end="", flush=True)
            print("\n")

if __name__ == "__main__":
    asyncio.run(websocket_mcp_example())