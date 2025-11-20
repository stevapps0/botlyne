"""Integrations API endpoints for external services like WhatsApp."""
from fastapi import APIRouter, HTTPException, status, Depends, Header
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging
import secrets
import uuid
from datetime import datetime

from src.core.database import supabase
from src.core.auth import get_current_user
from src.core.auth_utils import TokenData
from src.core.config import settings
from src.services.evolution_api import evolution_api_client
from src.services.retrieval import retrieval_service
from src.services.ai_service import AIService
from src.schemas.integrations import (
    IntegrationCreate,
    IntegrationResponse,
    IntegrationConfig,
    IntegrationEvent,
    WhatsAppWebhookPayload
)
from src.api.v1.query import process_query_request
from src.schemas.query import QueryRequest

logger = logging.getLogger(__name__)

router = APIRouter()

# Standard API Response Model
class APIResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None
    error: Optional[str] = None


def generate_webhook_secret() -> str:
    """Generate a secure webhook secret."""
    return secrets.token_urlsafe(32)


def get_integration_configs(integration_id: str) -> Dict[str, str]:
    """Get integration configs as dict."""
    result = supabase.table("integration_configs").select("key", "value").eq("integration_id", integration_id).execute()
    return {config["key"]: config["value"] for config in result.data or []}


def set_integration_configs(integration_id: str, configs: Dict[str, str]) -> None:
    """Set integration configs."""
    # Delete existing configs
    supabase.table("integration_configs").delete().eq("integration_id", integration_id).execute()

    # Insert new configs
    config_data = [
        {
            "integration_id": integration_id,
            "key": key,
            "value": value,
            "is_secret": key in ["api_key", "webhook_secret"]
        }
        for key, value in configs.items()
    ]
    if config_data:
        supabase.table("integration_configs").insert(config_data).execute()


@router.post("/integrations", response_model=APIResponse)
async def create_integration(
    data: IntegrationCreate,
    current_user: TokenData = Depends(get_current_user)
):
    """Create a new integration."""
    try:
        logger.info(f"Creating {data.type} integration for org {current_user.org_id}")

        # Generate unique instance name for WhatsApp
        instance_name = f"{current_user.org_id}_{data.type}_{str(uuid.uuid4())[:8]}"

        # Create integration record
        integration_data = {
            "org_id": current_user.org_id,
            "type": data.type,
            "name": data.name,
            "status": "pending",
            "kb_id": data.kb_id
        }

        result = supabase.table("integrations").insert(integration_data).execute()
        integration = result.data[0]
        integration_id = integration["id"]

        # Handle type-specific setup
        if data.type == "whatsapp":
            try:
                # Create Evolution API instance
                evolution_result = await evolution_api_client.create_instance(instance_name)
                api_key = evolution_result.get("hash", {}).get("apikey", "")

                # Generate webhook URL and secret
                webhook_url = f"{settings.API_BASE_URL}/api/v1/integrations/webhook/{integration_id}"
                webhook_secret = generate_webhook_secret()

                # Set webhook
                await evolution_api_client.set_webhook(instance_name, webhook_url, webhook_secret)

                # Store configs
                configs = {
                    "instance_name": instance_name,
                    "api_key": api_key,
                    "webhook_url": webhook_url,
                    "webhook_secret": webhook_secret
                }
                set_integration_configs(integration_id, configs)

                # Update status to active
                supabase.table("integrations").update({"status": "active"}).eq("id", integration_id).execute()

                logger.info(f"WhatsApp integration {integration_id} created successfully")

            except Exception as e:
                logger.error(f"Failed to setup WhatsApp integration: {str(e)}")
                # Update status to error
                supabase.table("integrations").update({"status": "error"}).eq("id", integration_id).execute()
                raise HTTPException(status_code=500, detail=f"Failed to setup WhatsApp: {str(e)}")

        elif data.type == "webchat":
            try:
                # Get organization shortcode
                org_result = supabase.table("organizations").select("shortcode").eq("id", current_user.org_id).single().execute()
                if not org_result.data:
                    raise HTTPException(status_code=400, detail="Organization shortcode not found")

                shortcode = org_result.data["shortcode"]
                chat_endpoint = f"{settings.API_BASE_URL}/api/v1/chat/{shortcode}"

                # Store configs
                configs = {
                    "chat_endpoint": chat_endpoint,
                    "shortcode": shortcode
                }
                set_integration_configs(integration_id, configs)

                # Update status to active
                supabase.table("integrations").update({"status": "active"}).eq("id", integration_id).execute()

                logger.info(f"Webchat integration {integration_id} created successfully")

            except Exception as e:
                logger.error(f"Failed to setup webchat integration: {str(e)}")
                # Update status to error
                supabase.table("integrations").update({"status": "error"}).eq("id", integration_id).execute()
                raise HTTPException(status_code=500, detail=f"Failed to setup webchat: {str(e)}")

        # Get configs for response
        configs = get_integration_configs(integration_id)
        config_objects = [
            IntegrationConfig(key=k, value=v, is_secret=k in ["api_key", "webhook_secret"])
            for k, v in configs.items()
        ]

        response_data = IntegrationResponse(
            id=integration_id,
            org_id=current_user.org_id,
            type=data.type,
            name=data.name,
            status="active" if data.type in ["whatsapp", "webchat"] else "pending",
            kb_id=data.kb_id,
            configs=config_objects,
            created_at=datetime.fromisoformat(integration["created_at"]),
            updated_at=datetime.fromisoformat(integration["updated_at"])
        )

        return APIResponse(
            success=True,
            message=f"{data.type.title()} integration created successfully",
            data={"integration": response_data.dict()}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create integration: {str(e)}")
        return APIResponse(
            success=False,
            message="Failed to create integration",
            error=str(e)
        )


@router.get("/integrations", response_model=APIResponse)
async def list_integrations(current_user: TokenData = Depends(get_current_user)):
    """List organization's integrations."""
    try:
        result = supabase.table("integrations").select("*").eq("org_id", current_user.org_id).execute()

        integrations = []
        for integration in result.data:
            configs = get_integration_configs(integration["id"])
            config_objects = [
                IntegrationConfig(key=k, value="***" if k in ["api_key", "webhook_secret"] else v, is_secret=k in ["api_key", "webhook_secret"])
                for k, v in configs.items()
            ]

            integrations.append(IntegrationResponse(
                id=integration["id"],
                org_id=integration["org_id"],
                type=integration["type"],
                name=integration["name"],
                status=integration["status"],
                kb_id=integration["kb_id"],
                configs=config_objects,
                created_at=datetime.fromisoformat(integration["created_at"]),
                updated_at=datetime.fromisoformat(integration["updated_at"])
            ).dict())

        return APIResponse(
            success=True,
            message="Integrations retrieved successfully",
            data={"integrations": integrations}
        )

    except Exception as e:
        logger.error(f"Failed to list integrations: {str(e)}")
        return APIResponse(
            success=False,
            message="Failed to list integrations",
            error=str(e)
        )


@router.get("/integrations/{integration_id}", response_model=APIResponse)
async def get_integration(
    integration_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Get integration details."""
    try:
        # Verify ownership
        result = supabase.table("integrations").select("*").eq("id", integration_id).single().execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Integration not found")

        integration = result.data
        if integration["org_id"] != current_user.org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        configs = get_integration_configs(integration_id)
        config_objects = [
            IntegrationConfig(key=k, value="***" if k in ["api_key", "webhook_secret"] else v, is_secret=k in ["api_key", "webhook_secret"])
            for k, v in configs.items()
        ]

        response_data = IntegrationResponse(
            id=integration_id,
            org_id=integration["org_id"],
            type=integration["type"],
            name=integration["name"],
            status=integration["status"],
            kb_id=integration["kb_id"],
            configs=config_objects,
            created_at=datetime.fromisoformat(integration["created_at"]),
            updated_at=datetime.fromisoformat(integration["updated_at"])
        )

        return APIResponse(
            success=True,
            message="Integration retrieved successfully",
            data={"integration": response_data.dict()}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get integration: {str(e)}")
        return APIResponse(
            success=False,
            message="Failed to get integration",
            error=str(e)
        )


@router.delete("/integrations/{integration_id}", response_model=APIResponse)
async def delete_integration(
    integration_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Delete integration."""
    try:
        # Verify ownership
        result = supabase.table("integrations").select("*").eq("id", integration_id).single().execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Integration not found")

        integration = result.data
        if integration["org_id"] != current_user.org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Cleanup external resources
        if integration["type"] == "whatsapp":
            configs = get_integration_configs(integration_id)
            instance_name = configs.get("instance_name")
            if instance_name:
                try:
                    await evolution_api_client.delete_instance(instance_name)
                    logger.info(f"Deleted Evolution API instance: {instance_name}")
                except Exception as e:
                    logger.warning(f"Failed to delete Evolution API instance: {str(e)}")

        # Delete integration (cascade will handle configs and events)
        supabase.table("integrations").delete().eq("id", integration_id).execute()

        return APIResponse(
            success=True,
            message="Integration deleted successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete integration: {str(e)}")
        return APIResponse(
            success=False,
            message="Failed to delete integration",
            error=str(e)
        )


@router.get("/integrations/{integration_id}/qr", response_model=APIResponse)
async def get_qr_code(
    integration_id: str,
    current_user: TokenData = Depends(get_current_user)
):
    """Get QR code for WhatsApp integration setup."""
    try:
        # Verify ownership and type
        result = supabase.table("integrations").select("*").eq("id", integration_id).single().execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Integration not found")

        integration = result.data
        if integration["org_id"] != current_user.org_id:
            raise HTTPException(status_code=403, detail="Access denied")

        if integration["type"] != "whatsapp":
            raise HTTPException(status_code=400, detail="QR code only available for WhatsApp integrations")

        configs = get_integration_configs(integration_id)
        instance_name = configs.get("instance_name")
        if not instance_name:
            raise HTTPException(status_code=400, detail="Instance not properly configured")

        # Get QR code from Evolution API
        qr_result = await evolution_api_client.get_qr_code(instance_name)

        return APIResponse(
            success=True,
            message="QR code retrieved successfully",
            data={"qr_code": qr_result}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get QR code: {str(e)}")
        return APIResponse(
            success=False,
            message="Failed to get QR code",
            error=str(e)
        )


@router.post("/integrations/webhook/{integration_id}")
async def handle_webhook(
    integration_id: str,
    payload: WhatsAppWebhookPayload
):
    """Handle incoming webhooks from external services."""
    try:
        logger.info(f"Received webhook for integration {integration_id}")

        # Get integration details
        result = supabase.table("integrations").select("*").eq("id", integration_id).single().execute()
        if not result.data:
            logger.warning(f"Integration {integration_id} not found")
            raise HTTPException(status_code=404, detail="Integration not found")

        integration = result.data

        # Log the event
        supabase.table("integration_events").insert({
            "integration_id": integration_id,
            "event_type": "webhook_received",
            "payload": payload.dict(),
            "status": "processing"
        }).execute()

        # Handle WhatsApp messages
        if integration["type"] == "whatsapp" and payload.message:
            await handle_whatsapp_message(integration, payload)

        # Update event status
        supabase.table("integration_events").update({"status": "processed"}).eq("integration_id", integration_id).eq("event_type", "webhook_received").order("created_at", desc=True).limit(1).execute()

        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing failed: {str(e)}")
        # Update event status to failed
        supabase.table("integration_events").update({"status": "failed"}).eq("integration_id", integration_id).eq("event_type", "webhook_received").order("created_at", desc=True).limit(1).execute()
        raise HTTPException(status_code=500, detail="Webhook processing failed")


async def handle_whatsapp_message(integration: Dict[str, Any], payload: WhatsAppWebhookPayload):
    """Process incoming WhatsApp message."""
    try:
        message = payload.message
        if not message.get("body"):
            return  # Not a text message

        sender_number = message.get("from", "").split("@")[0]  # Remove @s.whatsapp.net
        message_text = message.get("body", "").strip()

        if not sender_number or not message_text:
            return

        logger.info(f"Processing WhatsApp message from {sender_number}: {message_text[:50]}...")

        # Use sender number as user_id
        user_id = sender_number

        # Get KB ID (from integration or org default)
        kb_id = integration.get("kb_id")
        if not kb_id:
            # Get org default KB
            org_result = supabase.table("knowledge_bases").select("id").eq("org_id", integration["org_id"]).limit(1).execute()
            if org_result.data:
                kb_id = org_result.data[0]["id"]

        if not kb_id:
            logger.warning("No KB available for WhatsApp integration")
            return

        # Create query request
        query_request = QueryRequest(
            message=message_text,
            user_id=user_id,
            kb_id=kb_id
        )

        # Process query using extracted function
        response = await process_query_request(query_request, integration["org_id"], kb_id)

        # Send response back via WhatsApp
        configs = get_integration_configs(integration["id"])
        instance_name = configs.get("instance_name")

        if instance_name and response.ai_response:
            await evolution_api_client.send_message(instance_name, sender_number, response.ai_response)
            logger.info(f"Sent WhatsApp response to {sender_number}")

        # Log successful message handling
        supabase.table("integration_events").insert({
            "integration_id": integration["id"],
            "event_type": "message_processed",
            "payload": {
                "sender": sender_number,
                "message": message_text[:100],
                "response": response.ai_response[:100] if response.ai_response else None
            },
            "status": "completed"
        }).execute()

    except Exception as e:
        logger.error(f"Failed to handle WhatsApp message: {str(e)}")
        # Log error
        supabase.table("integration_events").insert({
            "integration_id": integration["id"],
            "event_type": "message_error",
            "payload": {"error": str(e)},
            "status": "failed"
        }).execute()