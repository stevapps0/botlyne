"""Evolution API client for WhatsApp integration."""
import httpx
import logging
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager
from src.core.config import settings

logger = logging.getLogger(__name__)


class EvolutionAPIClient:
    """Client for interacting with Evolution API."""

    def __init__(self):
        self.base_url = settings.EVOLUTION_API_BASE_URL.rstrip('/')
        self.global_key = settings.EVOLUTION_API_GLOBAL_KEY
        self.timeout = 30.0

    @asynccontextmanager
    async def _get_client(self):
        """Get HTTP client with proper configuration."""
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers={
                'Content-Type': 'application/json',
                'apikey': self.global_key
            }
        ) as client:
            yield client

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make HTTP request to Evolution API with modern error handling."""
        url = f"{self.base_url}{endpoint}"

        async with self._get_client() as client:
            try:
                match method.upper():
                    case 'GET':
                        response = await client.get(url, params=params)
                    case 'POST':
                        response = await client.post(url, json=data)
                    case 'DELETE':
                        response = await client.delete(url)
                    case _:
                        raise ValueError(f"Unsupported HTTP method: {method}")

                response.raise_for_status()

                # Parse response with better error handling
                content_type = response.headers.get('content-type', '')
                if 'application/json' in content_type:
                    return response.json()
                else:
                    # Return text response wrapped in dict for consistency
                    return {'text': response.text}

            except httpx.HTTPStatusError as e:
                error_msg = f"Evolution API error: {e.response.status_code}"
                if e.response.text:
                    error_msg += f" - {e.response.text}"
                logger.error(error_msg)
                raise Exception(error_msg) from e
            except httpx.RequestError as e:
                error_msg = f"Evolution API request failed: {e}"
                logger.error(error_msg)
                raise Exception(f"Failed to communicate with Evolution API: {e}") from e
            except Exception as e:
                error_msg = f"Unexpected error in Evolution API request: {e}"
                logger.error(error_msg, exc_info=True)
                raise Exception(f"Evolution API communication error: {e}") from e

    async def create_instance(self, instance_name: str) -> Dict[str, Any]:
        """Create a new WhatsApp instance."""
        logger.info(f"Creating Evolution API instance: {instance_name}")

        # Instance creation with required parameters
        data = {
            "instanceName": instance_name,
            "integration": "WHATSAPP-BAILEYS",
            "token": self.global_key
        }

        result = await self._make_request('POST', '/instance/create', data)
        logger.info(f"Instance {instance_name} created successfully")

        # Evolution API v2 returns instance data
        if isinstance(result, dict) and "instance" in result:
            return result
        elif isinstance(result, dict):
            return result
        else:
            # Fallback for string responses
            return {"instance": {"instanceName": instance_name, "status": "created"}}

    async def get_qr_code(self, instance_name: str) -> Dict[str, Any]:
        """Get QR code/connection info for WhatsApp instance."""
        logger.info(f"Getting connection info for instance: {instance_name}")
        result = await self._make_request('GET', f'/instance/connect/{instance_name}')
        return result

    async def set_webhook(
        self,
        instance_name: str,
        webhook_url: str,
        secret: Optional[str] = None
    ) -> Dict[str, Any]:
        """Set webhook URL for instance."""
        logger.info(f"Setting webhook for instance {instance_name}: {webhook_url}")

        # Evolution API expects webhook config nested under "webhook" key
        data = {
            "webhook": {
                "enabled": True,
                "url": webhook_url,
                "webhookByEvents": True,
                "events": [
                    "MESSAGES_UPSERT",
                    "MESSAGES_UPDATE",
                    "CONNECTION_UPDATE"
                ]
            }
        }

        if secret:
            data["webhook"]["secret"] = secret

        result = await self._make_request('POST', f'/webhook/set/{instance_name}', data)
        logger.info(f"Webhook set for instance {instance_name}")
        return result

    async def send_message(
        self,
        instance_name: str,
        number: str,
        message: str
    ) -> Dict[str, Any]:
        """Send text message via WhatsApp."""
        logger.info(f"Sending message to {number} via instance {instance_name}")
        data = {
            "number": number,
            "text": message
        }
        result = await self._make_request('POST', f'/message/sendText/{instance_name}', data)
        logger.info(f"Message sent successfully to {number}")
        return result

    async def delete_instance(self, instance_name: str) -> Dict[str, Any]:
        """Delete WhatsApp instance."""
        logger.info(f"Deleting instance: {instance_name}")
        result = await self._make_request('DELETE', f'/instance/delete/{instance_name}')
        logger.info(f"Instance {instance_name} deleted successfully")
        return result

    async def get_instance_status(self, instance_name: str) -> Dict[str, Any]:
        """Get instance connection status."""
        logger.info(f"Getting status for instance: {instance_name}")
        result = await self._make_request('GET', f'/instance/connectionState/{instance_name}')
        return result


# Global client instance
evolution_api_client = EvolutionAPIClient()