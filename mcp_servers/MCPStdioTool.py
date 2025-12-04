import asyncio
import os
from agent_framework import ChatAgent, MCPStdioTool
from agent_framework_azure_ai import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

async def local_mcp_example():
    """Example using a local MCP server via stdio with Azure AI Foundry."""
    
    # Get configuration from environment variables
    project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
    model_deployment = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4.1")
    
    if not project_endpoint:
        raise ValueError(
            "AZURE_AI_PROJECT_ENDPOINT environment variable is required.\n"
            "Set it to: https://<your-project>.services.ai.azure.com/api/projects/<project-id>"
        )
    
    print(f"🤖 Initializing AI Foundry Agent with MCP Calculator Tool...")
    print(f"   Project: {project_endpoint}")
    print(f"   Model: {model_deployment}\n")
    
    async with DefaultAzureCredential() as credential:
        async with (
            MCPStdioTool(
                name="calculator", 
                command="uvx", 
                args=["mcp-server-calculator"]
            ) as mcp_server,
            ChatAgent(
                chat_client=AzureAIAgentClient(
                    project_endpoint=project_endpoint,
                    model_deployment_name=model_deployment,
                    async_credential=credential,
                    agent_name="MathAgent",
                ),
                instructions="You are a helpful math assistant that can solve calculations using the calculator tool.",
            ) as agent,
        ):
            print("📝 User: What is 15 * 23 + 45?")
            print("🤖 Agent: ", end="", flush=True)
            
            async for chunk in agent.run_stream(
                "What is 15 * 23 + 45?", 
                tools=mcp_server
            ):
                if chunk.text:
                    print(chunk.text, end="", flush=True)
            print("\n")

if __name__ == "__main__":
    asyncio.run(local_mcp_example())