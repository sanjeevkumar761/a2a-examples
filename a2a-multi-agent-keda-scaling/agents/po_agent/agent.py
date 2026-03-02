"""
Purchase Order Agent - Manages purchase orders and vendor interactions.
Built with LangGraph and exposed via A2A protocol.
"""

import os
import logging
from typing import Any
from datetime import datetime, timedelta
import random

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from langgraph.graph import StateGraph, END
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PurchaseOrderAgent:
    """Agent that manages purchase orders using LangGraph workflow."""
    
    def __init__(self):
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        self.llm = AzureChatOpenAI(
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
            azure_ad_token_provider=token_provider,
            temperature=0.1,
        )
        self.workflow = self._build_workflow()
        # Simulated PO database
        self.po_database = {}
    
    def _build_workflow(self) -> StateGraph:
        """Build the LangGraph workflow for PO management."""
        
        workflow = StateGraph(dict)
        
        # Add nodes
        workflow.add_node("validate_request", self._validate_request)
        workflow.add_node("check_budget", self._check_budget)
        workflow.add_node("vendor_lookup", self._vendor_lookup)
        workflow.add_node("create_po", self._create_po)
        workflow.add_node("generate_response", self._generate_response)
        
        # Add edges
        workflow.set_entry_point("validate_request")
        workflow.add_edge("validate_request", "check_budget")
        workflow.add_edge("check_budget", "vendor_lookup")
        workflow.add_edge("vendor_lookup", "create_po")
        workflow.add_edge("create_po", "generate_response")
        workflow.add_edge("generate_response", END)
        
        return workflow.compile()
    
    async def _validate_request(self, state: dict) -> dict:
        """Validate the PO request."""
        request = state.get("request", {})
        
        required_fields = ["vendor_id", "items", "requester"]
        missing_fields = [f for f in required_fields if f not in request]
        
        validation = {
            "valid": len(missing_fields) == 0,
            "missing_fields": missing_fields
        }
        
        logger.info(f"Request validation: {validation}")
        
        return {
            **state,
            "validation": validation
        }
    
    async def _check_budget(self, state: dict) -> dict:
        """Check if budget is available for the PO."""
        request = state.get("request", {})
        items = request.get("items", [])
        
        total_amount = sum(
            item.get("quantity", 1) * item.get("unit_price", 0) 
            for item in items
        )
        
        # Simulated budget check
        budget_available = 100000  # $100k available
        budget_approved = total_amount <= budget_available
        
        budget_check = {
            "total_amount": total_amount,
            "budget_available": budget_available,
            "approved": budget_approved
        }
        
        logger.info(f"Budget check: {budget_check}")
        
        return {
            **state,
            "budget_check": budget_check,
            "total_amount": total_amount
        }
    
    async def _vendor_lookup(self, state: dict) -> dict:
        """Look up vendor information."""
        request = state.get("request", {})
        vendor_id = request.get("vendor_id", "")
        
        # Simulated vendor database
        vendors = {
            "V001": {"name": "Acme Corp", "rating": 4.5, "payment_terms": "Net 30"},
            "V002": {"name": "Tech Solutions", "rating": 4.8, "payment_terms": "Net 45"},
            "V003": {"name": "Office Supplies Inc", "rating": 4.2, "payment_terms": "Net 15"}
        }
        
        vendor_info = vendors.get(vendor_id, {
            "name": "Unknown Vendor",
            "rating": 0,
            "payment_terms": "COD"
        })
        
        logger.info(f"Vendor lookup: {vendor_info}")
        
        return {
            **state,
            "vendor_info": vendor_info
        }
    
    async def _create_po(self, state: dict) -> dict:
        """Create the purchase order."""
        request = state.get("request", {})
        budget_check = state.get("budget_check", {})
        vendor_info = state.get("vendor_info", {})
        
        if not budget_check.get("approved", False):
            return {
                **state,
                "po_created": False,
                "po_number": None,
                "error": "Budget not approved"
            }
        
        # Generate PO number
        po_number = f"PO-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
        
        po_data = {
            "po_number": po_number,
            "vendor_id": request.get("vendor_id"),
            "vendor_name": vendor_info.get("name"),
            "items": request.get("items", []),
            "total_amount": state.get("total_amount", 0),
            "requester": request.get("requester"),
            "status": "created",
            "created_date": datetime.now().isoformat(),
            "expected_delivery": (datetime.now() + timedelta(days=14)).isoformat()
        }
        
        # Store in database
        self.po_database[po_number] = po_data
        
        logger.info(f"PO created: {po_number}")
        
        return {
            **state,
            "po_created": True,
            "po_number": po_number,
            "po_data": po_data
        }
    
    async def _generate_response(self, state: dict) -> dict:
        """Generate final response with LLM enhancement."""
        po_data = state.get("po_data", {})
        po_created = state.get("po_created", False)
        
        if po_created:
            status = "success"
            message = f"Purchase order {po_data.get('po_number')} has been created successfully."
        else:
            status = "failed"
            message = f"Failed to create purchase order: {state.get('error', 'Unknown error')}"
        
        return {
            **state,
            "status": status,
            "message": message
        }
    
    async def create_purchase_order(self, request: dict) -> dict:
        """Main entry point - create a purchase order."""
        initial_state = {
            "request": request,
            "validation": None,
            "budget_check": None,
            "vendor_info": None,
            "po_created": False,
            "po_number": None
        }
        
        result = await self.workflow.ainvoke(initial_state)
        
        return {
            "status": result.get("status", "failed"),
            "message": result.get("message", ""),
            "po_number": result.get("po_number"),
            "po_data": result.get("po_data"),
            "total_amount": result.get("total_amount", 0)
        }
    
    async def get_po_status(self, po_number: str) -> dict:
        """Get the status of a purchase order."""
        po_data = self.po_database.get(po_number)
        
        if po_data:
            return {
                "found": True,
                "po_data": po_data
            }
        return {
            "found": False,
            "error": f"PO {po_number} not found"
        }
    
    def get_skills(self) -> list[dict]:
        """Return agent skills for A2A discovery."""
        return [
            {
                "id": "create_po",
                "name": "Create Purchase Order",
                "description": "Creates a new purchase order with budget validation and vendor lookup",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "vendor_id": {"type": "string"},
                        "requester": {"type": "string"},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string"},
                                    "quantity": {"type": "number"},
                                    "unit_price": {"type": "number"}
                                }
                            }
                        }
                    },
                    "required": ["vendor_id", "requester", "items"]
                }
            },
            {
                "id": "get_po_status",
                "name": "Get PO Status",
                "description": "Retrieves the status and details of an existing purchase order",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "po_number": {"type": "string"}
                    },
                    "required": ["po_number"]
                }
            }
        ]
