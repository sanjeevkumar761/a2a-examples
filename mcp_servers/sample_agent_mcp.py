# pylint: disable=line-too-long,useless-suppression
# ------------------------------------
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# ------------------------------------

"""
DESCRIPTION:
    This sample demonstrates how to run Prompt Agent operations
    using MCP (Model Context Protocol) tools and a synchronous client.

USAGE:
    python sample_agent_mcp.py

    Before running the sample:

    pip install "azure-ai-projects>=2.0.0b1" python-dotenv

    Set these environment variables with your own values:
    1) AZURE_AI_PROJECT_ENDPOINT - The Azure AI Project endpoint, as found in the Overview
       page of your Microsoft Foundry portal.
    2) AZURE_AI_MODEL_DEPLOYMENT_NAME - The deployment name of the AI model, as found under the "Name" column in
       the "Models + endpoints" tab in your Microsoft Foundry project.
"""

import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, MCPTool, Tool
from openai.types.responses.response_input_param import McpApprovalResponse, ResponseInputParam


load_dotenv()

# Get configuration from environment variables
endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT") or os.environ["AZURE_AI_PROJECT_ENDPOINT"]
model_deployment = os.getenv("AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME") or os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"]

print(f"🤖 Creating Prompt Agent with MCP Tool...")
print(f"   Project: {endpoint}")
print(f"   Model: {model_deployment}\n")

with (
    DefaultAzureCredential() as credential,
    AIProjectClient(endpoint=endpoint, credential=credential) as project_client,
    project_client.get_openai_client() as openai_client,
):
    # [START tool_declaration]
    # MCP tool connects to GitHub repository via gitmcp.io
    mcp_tool = MCPTool(
        server_label="api-specs",
        server_url="https://gitmcp.io/Azure/azure-rest-api-specs",
        require_approval="always",  # Require manual approval for MCP tool calls
    )
    # [END tool_declaration]

    print(f"📋 Creating agent with MCP tool...")
    agent = project_client.agents.create_version(
        agent_name="MyAgent",
        definition=PromptAgentDefinition(
            model=model_deployment,
            instructions="You are a helpful agent that can use MCP tools to assist users. Use the available MCP tools to answer questions and perform tasks.",
            tools=[mcp_tool],
        ),
    )
    print(f"✅ Agent created (id: {agent.id}, name: {agent.name}, version: {agent.version})\n")

    # Create a conversation thread to maintain context across multiple interactions
    print(f"💬 Creating conversation thread...")
    conversation = openai_client.conversations.create()
    print(f"✅ Created conversation (id: {conversation.id})\n")

    # Send initial request that will trigger the MCP tool
    print(f"📝 User: Please summarize the Azure REST API specifications Readme")
    print(f"🤖 Agent: Processing request (may request MCP tool approval)...\n")
    
    response = openai_client.responses.create(
        conversation=conversation.id,
        input="Please summarize the Azure REST API specifications Readme",
        extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
    )

    # Process any MCP approval requests that were generated
    input_list: ResponseInputParam = []
    approval_count = 0
    
    for item in response.output:
        if item.type == "mcp_approval_request":
            if item.server_label == "api-specs" and item.id:
                approval_count += 1
                print(f"🔐 MCP Approval Request #{approval_count}:")
                print(f"   Server: {item.server_label}")
                print(f"   Request ID: {item.id}")
                
                # Automatically approve the MCP request to allow the agent to proceed
                # In production, you might want to implement more sophisticated approval logic
                input_list.append(
                    McpApprovalResponse(
                        type="mcp_approval_response",
                        approve=True,
                        approval_request_id=item.id,
                    )
                )
                print(f"   ✅ Auto-approved\n")

    if approval_count > 0:
        print(f"📤 Sending {approval_count} approval response(s) back to agent...\n")
        
        # Send the approval response back to continue the agent's work
        # This allows the MCP tool to access the GitHub repository and complete the original request
        response = openai_client.responses.create(
            input=input_list,
            previous_response_id=response.id,
            extra_body={"agent": {"name": agent.name, "type": "agent_reference"}},
        )

    print(f"🤖 Agent Response:")
    print(f"{response.output_text}\n")

    # Clean up resources by deleting the agent version
    # This prevents accumulation of unused agent versions in your project
    print(f"🧹 Cleaning up...")
    project_client.agents.delete_version(agent_name=agent.name, agent_version=agent.version)
    print(f"✅ Agent deleted")