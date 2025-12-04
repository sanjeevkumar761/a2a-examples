"""
Test script to check if MCP tools endpoint is available
"""
import asyncio
import os
from dotenv import load_dotenv
from azure.identity.aio import DefaultAzureCredential
import httpx

load_dotenv()

async def test_endpoint():
    endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT_FOR_TOOLS") or os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
    
    if not endpoint:
        print("❌ No endpoint found in .env file")
        return
    
    print(f"Testing endpoint: {endpoint}")
    print(f"MCP URL: {endpoint}/mcp_tools?api-version=2025-05-15-preview\n")
    
    async with DefaultAzureCredential() as credential:
        # Get authentication token
        token = (await credential.get_token('https://ai.azure.com/.default')).token
        print(f"✅ Got authentication token (first 20 chars): {token[:20]}...\n")
        
        # Try different API versions
        api_versions = [
            "2025-05-15-preview",
            "2024-12-01-preview", 
            "2024-10-01-preview",
            "2024-08-01-preview",
        ]
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            for api_version in api_versions:
                url = f"{endpoint}/mcp_tools?api-version={api_version}"
                print(f"Testing: {url}")
                
                try:
                    response = await client.get(
                        url,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json"
                        }
                    )
                    print(f"  Status: {response.status_code}")
                    print(f"  Response: {response.text[:200]}...")
                    
                    if response.status_code == 200:
                        print(f"  ✅ Success!")
                        break
                    elif response.status_code == 404:
                        print(f"  ⚠️  Not found")
                    elif response.status_code == 401:
                        print(f"  ⚠️  Unauthorized")
                    elif response.status_code == 403:
                        print(f"  ⚠️  Forbidden")
                    else:
                        print(f"  ⚠️  Unexpected status")
                        
                except Exception as e:
                    print(f"  ❌ Error: {e}")
                
                print()
        
        print("\n💡 Notes:")
        print("  - If all versions return 404, MCP tools may not be enabled in this project")
        print("  - If you get 401/403, check your Azure credentials and project permissions")
        print("  - MCP tools feature might be in preview and not available in all regions")
        print("  - You may need to enable MCP tools in Azure AI Foundry portal")

if __name__ == "__main__":
    asyncio.run(test_endpoint())
