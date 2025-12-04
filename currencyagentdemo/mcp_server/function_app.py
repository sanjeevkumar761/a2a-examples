import json
import logging
import os

import azure.functions as func
import httpx
from azure.storage.blob import BlobServiceClient


app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# Initialize Azurite blob storage client
def get_blob_service_client():
    """Get BlobServiceClient connected to local Azurite."""
    connection_string = os.getenv(
        'AzureWebJobsStorage',
        'DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;'
        'AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;'
        'BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;'
    )
    return BlobServiceClient.from_connection_string(connection_string)


@app.generic_trigger(
    arg_name='context',
    type='mcpToolTrigger',
    toolName='hello_mcp',
    description='Hello world.',
    toolProperties='[]',
)
def hello_mcp(context) -> None:
    """A simple function that returns a greeting message.

    Args:
        context: The trigger context (not used in this function).

    Returns:
        str: A greeting message.
    """
    return 'Hello I am MCPTool!'


@app.generic_trigger(
    arg_name='context',
    type='mcpToolTrigger',
    tool_name='get_exchange_rate',
    description='A simple currency function that leverages Frankfurter for exchange rates',
    toolProperties="""[
        {
            "propertyName": "currency_from", 
            "propertyType": "string", 
            "description": "Currency code to convert from, e.g. USD"
        },
        {
            "propertyName": "currency_to",
            "propertyType": "string",
            "description": "Currency code to convert to, e.g. EUR or INR"
        }
    ]""",
)
def get_exchange_rate(context) -> str:
    try:
        content = json.loads(context)
        arguments = content.get('arguments', {})

        currency_from = arguments.get('currency_from')
        currency_to = arguments.get('currency_to')
        logging.info(
            f'Currency conversion from {currency_from} to {currency_to}'
        )
        response = httpx.get(
            'https://api.frankfurter.app/latest',
            params={'from': currency_from, 'to': currency_to},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        if 'rates' not in data or currency_to not in data['rates']:
            return (
                f'Could not retrieve rate for {currency_from} to {currency_to}'
            )
        rate = data['rates'][currency_to]
        return f'1 {currency_from} = {rate} {currency_to}'
    except Exception as e:
        return f'Currency API call failed: {e!s}'
