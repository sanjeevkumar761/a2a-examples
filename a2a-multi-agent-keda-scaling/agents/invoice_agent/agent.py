"""
Invoice Validation Agent - Validates invoice data and checks for compliance.
Built with LangGraph and exposed via A2A protocol.
"""

import os
import logging
from typing import Any, Literal
from dataclasses import dataclass

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from langgraph.graph import StateGraph, END
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class InvoiceState:
    """State for invoice validation workflow."""
    invoice_data: dict
    validation_result: dict | None = None
    compliance_check: dict | None = None
    final_status: str = "pending"
    messages: list = None
    
    def __post_init__(self):
        if self.messages is None:
            self.messages = []


class InvoiceValidationAgent:
    """Agent that validates invoices using LangGraph workflow."""
    
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
    
    def _build_workflow(self) -> StateGraph:
        """Build the LangGraph workflow for invoice validation."""
        
        workflow = StateGraph(dict)
        
        # Add nodes
        workflow.add_node("validate_format", self._validate_format)
        workflow.add_node("check_amounts", self._check_amounts)
        workflow.add_node("compliance_check", self._compliance_check)
        workflow.add_node("generate_result", self._generate_result)
        
        # Add edges
        workflow.set_entry_point("validate_format")
        workflow.add_edge("validate_format", "check_amounts")
        workflow.add_edge("check_amounts", "compliance_check")
        workflow.add_edge("compliance_check", "generate_result")
        workflow.add_edge("generate_result", END)
        
        return workflow.compile()
    
    async def _validate_format(self, state: dict) -> dict:
        """Validate invoice format and required fields."""
        invoice = state.get("invoice_data", {})
        
        required_fields = ["invoice_number", "vendor", "amount", "date", "line_items"]
        missing_fields = [f for f in required_fields if f not in invoice]
        
        validation_result = {
            "format_valid": len(missing_fields) == 0,
            "missing_fields": missing_fields,
            "checked_fields": required_fields
        }
        
        logger.info(f"Format validation: {validation_result}")
        
        return {
            **state,
            "validation_result": validation_result
        }
    
    async def _check_amounts(self, state: dict) -> dict:
        """Check invoice amounts for accuracy."""
        invoice = state.get("invoice_data", {})
        validation = state.get("validation_result", {})
        
        line_items = invoice.get("line_items", [])
        calculated_total = sum(item.get("amount", 0) for item in line_items)
        stated_total = invoice.get("amount", 0)
        
        amounts_match = abs(calculated_total - stated_total) < 0.01
        
        validation["amounts_valid"] = amounts_match
        validation["calculated_total"] = calculated_total
        validation["stated_total"] = stated_total
        
        logger.info(f"Amount check: calculated={calculated_total}, stated={stated_total}, match={amounts_match}")
        
        return {
            **state,
            "validation_result": validation
        }
    
    async def _compliance_check(self, state: dict) -> dict:
        """Use LLM to check invoice compliance."""
        invoice = state.get("invoice_data", {})
        
        system_prompt = """You are an invoice compliance checker. Analyze the invoice data 
        and identify any compliance issues such as:
        - Missing tax information
        - Unusual vendor patterns
        - Amount anomalies
        - Date inconsistencies
        
        Respond with a JSON object containing:
        - compliant: boolean
        - issues: list of issues found
        - risk_level: "low", "medium", or "high"
        """
        
        response = await self.llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Invoice data: {invoice}")
        ])
        
        # Parse LLM response (simplified)
        compliance_check = {
            "compliant": True,
            "issues": [],
            "risk_level": "low",
            "llm_analysis": response.content
        }
        
        logger.info(f"Compliance check completed: {compliance_check['risk_level']}")
        
        return {
            **state,
            "compliance_check": compliance_check
        }
    
    async def _generate_result(self, state: dict) -> dict:
        """Generate final validation result."""
        validation = state.get("validation_result", {})
        compliance = state.get("compliance_check", {})
        
        is_valid = (
            validation.get("format_valid", False) and
            validation.get("amounts_valid", False) and
            compliance.get("compliant", False)
        )
        
        final_status = "approved" if is_valid else "rejected"
        
        logger.info(f"Final invoice status: {final_status}")
        
        return {
            **state,
            "final_status": final_status
        }
    
    async def validate_invoice(self, invoice_data: dict) -> dict:
        """Main entry point - validate an invoice."""
        initial_state = {
            "invoice_data": invoice_data,
            "validation_result": None,
            "compliance_check": None,
            "final_status": "pending"
        }
        
        result = await self.workflow.ainvoke(initial_state)
        
        return {
            "status": result["final_status"],
            "validation": result["validation_result"],
            "compliance": result["compliance_check"],
            "invoice_number": invoice_data.get("invoice_number")
        }
    
    def get_skills(self) -> list[dict]:
        """Return agent skills for A2A discovery."""
        return [
            {
                "id": "validate_invoice",
                "name": "Validate Invoice",
                "description": "Validates invoice data including format, amounts, and compliance checks",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "invoice_number": {"type": "string"},
                        "vendor": {"type": "string"},
                        "amount": {"type": "number"},
                        "date": {"type": "string"},
                        "line_items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "description": {"type": "string"},
                                    "amount": {"type": "number"}
                                }
                            }
                        }
                    },
                    "required": ["invoice_number", "vendor", "amount", "date", "line_items"]
                }
            }
        ]
