"""Integration schemas for external services like WhatsApp."""
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime


class IntegrationConfig(BaseModel):
    """Schema for integration configuration key-value pairs."""
    key: str = Field(..., description="Configuration key")
    value: str = Field(..., description="Configuration value")
    is_secret: bool = Field(False, description="Whether this config contains sensitive data")


class IntegrationCreate(BaseModel):
    """Schema for creating a new integration."""
    type: str = Field(..., description="Integration type (whatsapp, email, api, etc.)")
    name: str = Field(..., description="Human-readable name for the integration")
    kb_id: Optional[str] = Field(None, description="Linked knowledge base ID, null for org default")
    configs: Dict[str, str] = Field(default_factory=dict, description="Integration-specific configurations")


class IntegrationResponse(BaseModel):
    """Schema for integration response."""
    id: str
    org_id: str
    type: str
    name: str
    status: str
    kb_id: Optional[str]
    configs: List[IntegrationConfig]
    created_at: datetime
    updated_at: datetime


class IntegrationEvent(BaseModel):
    """Schema for integration events (webhooks, messages)."""
    id: str
    integration_id: str
    event_type: str
    payload: Dict[str, Any]
    status: str
    created_at: datetime


class WhatsAppWebhookPayload(BaseModel):
    """Schema for WhatsApp webhook payload from Evolution API."""
    instance: str
    apikey: str
    message: Optional[Dict[str, Any]] = None
    # Other fields like contact, chat, etc. can be added as needed


class WhatsAppMessageSend(BaseModel):
    """Schema for sending WhatsApp messages."""
    number: str = Field(..., description="Recipient phone number")
    message: str = Field(..., description="Message text to send")