"""Integrations API endpoints for external services like WhatsApp."""
from fastapi import APIRouter, HTTPException, status, Depends, Header
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Annotated
import logging
import secrets
import time
from datetime import datetime

from src.core.database import supabase
from src.core.auth import get_current_user, require_admin
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

        # Get org shortcode for cleaner instance name
        org_result = supabase.table("organizations").select("shortcode").eq("id", current_user.org_id).single().execute()
        org_shortcode = org_result.data["shortcode"] if org_result.data else current_user.org_id[:8]

        # Check for existing integrations BEFORE creating to prevent duplicates
        existing_check = supabase.table("integrations").select("id", "status").eq("org_id", current_user.org_id).eq("type", data.type).execute()

        if existing_check.data:
            existing_active = [i for i in existing_check.data if i["status"] == "active"]
            if existing_active:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Organization already has an active {data.type} integration"
                )

            # Allow creation but log warning about existing failed integrations
            existing_failed = [i for i in existing_check.data if i["status"] in ["error", "pending"]]
            if existing_failed:
                logger.warning(f"Organization {current_user.org_id} has {len(existing_failed)} failed/pending {data.type} integrations. Creating new one.")

        # Generate unique instance name using org shortcode + timestamp + random for uniqueness
        import uuid
        timestamp = str(int(time.time()))
        random_suffix = str(uuid.uuid4())[:8]
        instance_name = f"{org_shortcode}_whatsapp_{timestamp}_{random_suffix}"

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
                # Check if org already has ANY WhatsApp integration (active, pending, or error)
                existing_integrations = supabase.table("integrations").select("id", "status", "name").eq("org_id", current_user.org_id).eq("type", "whatsapp").execute()

                if existing_integrations.data and len(existing_integrations.data) > 0:
                    active_count = sum(1 for i in existing_integrations.data if i["status"] == "active")
                    if active_count > 0:
                        logger.warning(f"Organization {current_user.org_id} already has an active WhatsApp integration")
                        raise HTTPException(status_code=400, detail="Organization already has an active WhatsApp integration. Delete the existing one first.")

                    # Allow cleanup of failed integrations, but warn about multiple pending
                    pending_count = sum(1 for i in existing_integrations.data if i["status"] == "pending")
                    if pending_count > 0:
                        logger.warning(f"Organization {current_user.org_id} has {pending_count} pending WhatsApp integrations. This may indicate previous failures.")

                # Create Evolution API instance
                evolution_result = await evolution_api_client.create_instance(instance_name)
                logger.info(f"Evolution result type: {type(evolution_result)}, value: {evolution_result}")

                # Handle different response formats
                if isinstance(evolution_result, dict):
                    hash_value = evolution_result.get("hash")
                    if isinstance(hash_value, dict):
                        api_key = hash_value.get("apikey", "")
                    elif isinstance(hash_value, str):
                        # Evolution API returns hash as the API key string
                        api_key = hash_value
                    else:
                        api_key = ""
                else:
                    # Evolution API returns string or other format
                    api_key = ""  # Use global key for all operations

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


@router.post("/integrations/cleanup", response_model=APIResponse)
async def cleanup_failed_integrations(
    current_user: TokenData = Depends(require_admin)
):
    """Clean up failed/pending integrations older than 24 hours (admin only)."""
    try:
        from datetime import datetime, timedelta

        # Find failed/pending integrations older than 24 hours
        cutoff_time = datetime.utcnow() - timedelta(hours=24)

        failed_integrations = supabase.table("integrations").select("id", "type", "status", "created_at") \
            .eq("org_id", current_user.org_id) \
            .in_("status", ["error", "pending"]) \
            .lt("created_at", cutoff_time.isoformat()) \
            .execute()

        cleaned_count = 0
        if failed_integrations.data:
            for integration in failed_integrations.data:
                try:
                    # Cleanup external resources for WhatsApp integrations
                    if integration["type"] == "whatsapp":
                        configs = get_integration_configs(integration["id"])
                        instance_name = configs.get("instance_name")
                        if instance_name:
                            try:
                                await evolution_api_client.delete_instance(instance_name)
                                logger.info(f"Cleaned up Evolution API instance: {instance_name}")
                            except Exception as e:
                                logger.warning(f"Failed to cleanup Evolution API instance {instance_name}: {str(e)}")

                    # Delete the integration
                    supabase.table("integrations").delete().eq("id", integration["id"]).execute()
                    cleaned_count += 1
                    logger.info(f"Cleaned up failed integration: {integration['id']}")

                except Exception as e:
                    logger.error(f"Failed to cleanup integration {integration['id']}: {str(e)}")

        return APIResponse(
            success=True,
            message=f"Cleaned up {cleaned_count} failed integrations",
            data={"cleaned_count": cleaned_count}
        )

    except Exception as e:
        logger.error(f"Failed to cleanup integrations: {str(e)}")
        return APIResponse(
            success=False,
            message="Failed to cleanup integrations",
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
        logger.info(f"QR result from Evolution API: {qr_result}")

        # Format response for frontend - Evolution API already provides base64!
        formatted_qr = {
            "code": qr_result.get("code", ""),
            "pairingCode": qr_result.get("pairingCode", ""),
            "base64": qr_result.get("base64", ""),  # Evolution API provides this!
            "ascii": "",   # TODO: Generate ASCII QR code if needed
            "url": ""      # TODO: Generate QR code URL if needed
        }

        return APIResponse(
            success=True,
            message="QR code retrieved successfully",
            data={"qr_code": formatted_qr}
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
@router.post("/integrations/webhook/{integration_id}/{event_type:path}")
async def handle_webhook(
    integration_id: str,
    payload: WhatsAppWebhookPayload,
    event_type: str = "messages-upsert"  # Default for Evolution API
) -> dict[str, str]:
    """Handle incoming webhooks from external services."""
    logger.info(f"📨 Received webhook for integration {integration_id}, event: {event_type}")
    logger.info(f"📦 Full payload: {payload.model_dump()}")

    try:
        # Get integration details with error handling
        integration_result = supabase.table("integrations").select("*").eq("id", integration_id).single().execute()
        if not integration_result.data:
            logger.warning(f"Integration {integration_id} not found")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found")

        integration = integration_result.data

        # Log the event with modern Pydantic serialization
        event_data = {
            "integration_id": integration_id,
            "event_type": f"webhook_{event_type}",
            "payload": payload.model_dump(),
            "status": "pending"  # Changed from "processing" to "pending"
        }

        supabase.table("integration_events").insert(event_data).execute()

        # Handle different integration types and event types
        match integration["type"]:
            case "whatsapp":
                # Extract event type from payload.event if available
                actual_event_type = getattr(payload, 'event', event_type) if hasattr(payload, 'event') else event_type
                logger.info(f"🔄 Processing WhatsApp event: {actual_event_type}")
                await _handle_whatsapp_event(integration, actual_event_type, payload, integration_id)
            case _:
                logger.warning(f"Unsupported integration type: {integration['type']} for webhook")

        # Update event status to processed
        supabase.table("integration_events") \
            .update({"status": "processed"}) \
            .eq("integration_id", integration_id) \
            .eq("event_type", f"webhook_{event_type}") \
            .eq("status", "pending") \
            .execute()

        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}", exc_info=True)

        # Update event status to failed (with error handling)
        try:
            supabase.table("integration_events") \
                .update({"status": "failed"}) \
                .eq("integration_id", integration_id) \
                .eq("event_type", f"webhook_{event_type}") \
                .eq("status", "pending") \
                .execute()
        except Exception as db_error:
            logger.error(f"Failed to update event status: {db_error}")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed"
        )


async def _handle_whatsapp_event(
    integration: dict[str, Any],
    event_type: str,
    payload: WhatsAppWebhookPayload,
    integration_id: str
) -> None:
    """Handle WhatsApp-specific webhook events."""
    # Normalize event type (Evolution API uses dots, we expect hyphens)
    normalized_event = event_type.replace('.', '-')
    logger.info(f"🔄 Normalized event type: {normalized_event} (from: {event_type})")

    match normalized_event:
        case "messages-upsert" | "messages-update":
            # Check if there's message data in the payload (Evolution API puts it in data.message)
            payload_dict = payload.model_dump()
            data = payload_dict.get('data', {})
            if data and data.get('message'):
                await handle_whatsapp_message(integration, payload)
                logger.info(f"Successfully processed WhatsApp message {normalized_event} for integration {integration_id}")
            else:
                logger.info(f"Received WhatsApp {normalized_event} event without message data for integration {integration_id}")
        case "connection-update":
            # Handle connection status updates
            payload_dict = payload.model_dump()
            data = payload_dict.get('data', {})
            state = data.get('state', 'unknown') if isinstance(data, dict) else 'unknown'
            logger.info(f"WhatsApp connection update for integration {integration_id}: {state}")
        case _:
            logger.info(f"Unhandled WhatsApp event type: {normalized_event} (original: {event_type}) for integration {integration_id}")


async def handle_whatsapp_message(integration: Dict[str, Any], payload: WhatsAppWebhookPayload):
    """Process incoming WhatsApp message."""
    try:
        logger.info(f"Processing WhatsApp message. Full payload: {payload.model_dump()}")

        # Evolution API puts message data in payload.data, not payload.message
        payload_dict = payload.model_dump()
        data = payload_dict.get('data', {})
        if not data:
            logger.info("No data object in payload")
            return

        # Check if this is a message sent by the bot itself (fromMe: true)
        key_info = data.get('key', {})
        from_me = key_info.get('fromMe', False)
        if from_me:
            logger.info("Ignoring message sent by bot itself (fromMe: true)")
            return

        # Get the actual message content
        message_data = data.get('message', {})
        if not message_data:
            logger.info("No message data in payload.data")
            return

        # Extract message text from conversation or extendedTextMessage
        message_text = None
        if 'conversation' in message_data:
            message_text = message_data['conversation']
        elif 'extendedTextMessage' in message_data:
            message_text = message_data['extendedTextMessage'].get('text', '')

        if not message_text:
            logger.info(f"No text content found in message: {message_data}")
            return

        message_text = message_text.strip()
        if not message_text:
            logger.info("Message text is empty after stripping")
            return

        # Get sender number
        sender_jid = key_info.get('remoteJid', '')
        sender_number = sender_jid.split('@')[0] if '@' in sender_jid else sender_jid

        if not sender_number:
            logger.warning(f"Could not extract sender number from: {sender_jid}")
            return

        logger.info(f"✅ Processing WhatsApp message from {sender_number}: '{message_text}'")

        # Use sender number as user_id
        user_id = sender_number

        # Get KB ID (from integration or org default)
        kb_id = integration.get("kb_id")
        logger.info(f"KB ID from integration: {kb_id}")

        if not kb_id:
            # Get org default KB
            logger.info(f"Getting default KB for org {integration['org_id']}")
            org_result = supabase.table("knowledge_bases").select("id").eq("org_id", integration["org_id"]).limit(1).execute()
            if org_result.data:
                kb_id = org_result.data[0]["id"]
                logger.info(f"Found default KB: {kb_id}")
            else:
                logger.warning(f"No knowledge bases found for org {integration['org_id']}")

        if not kb_id:
            logger.error("No KB available for WhatsApp integration - cannot process message")
            return

        logger.info(f"Using KB {kb_id} for message processing")

        # For WhatsApp users, generate a UUID (database expects UUID format)
        import uuid
        whatsapp_user_id = str(uuid.uuid4())

        # Create query request
        query_request = QueryRequest(
            message=message_text,
            user_id=whatsapp_user_id,
            kb_id=kb_id
        )

        logger.info(f"Processing query request: {query_request.model_dump()}")

        # Process query using extracted function with channel override
        response = await process_query_request(query_request, integration["org_id"], kb_id, channel_override="whatsapp")
        logger.info(f"Query response received: ai_response length = {len(response.ai_response) if response.ai_response else 0}")

        # Send response back via WhatsApp
        configs = get_integration_configs(integration["id"])
        instance_name = configs.get("instance_name")
        logger.info(f"Evolution API instance name: {instance_name}")

        if instance_name and response.ai_response:
            logger.info(f"Sending WhatsApp response to {sender_number}: '{response.ai_response[:100]}...'")
            await evolution_api_client.send_message(instance_name, sender_number, response.ai_response)
            logger.info(f"✅ Successfully sent WhatsApp response to {sender_number}")
        else:
            logger.warning(f"Cannot send response - instance_name: {instance_name}, ai_response: {bool(response.ai_response)}")

        # Log successful message handling
        supabase.table("integration_events").insert({
            "integration_id": integration["id"],
            "event_type": "message_processed",
            "payload": {
                "sender": sender_number,
                "message": message_text[:100],
                "response": response.ai_response[:100] if response.ai_response else None
            },
            "status": "processed"
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