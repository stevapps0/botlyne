"""Evolution API client for WhatsApp integration."""
import httpx
import logging
from typing import Dict, Any, Optional
from src.core.config import settings

logger = logging.getLogger(__name__)


class EvolutionAPIClient:
    """Client for interacting with Evolution API."""

    def __init__(self):
        self.base_url = settings.EVOLUTION_API_BASE_URL.rstrip('/')
        self.global_key = settings.EVOLUTION_API_GLOBAL_KEY
        self.timeout = 30.0

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make HTTP request to Evolution API."""
        url = f"{self.base_url}{endpoint}"

        headers = {
            'Content-Type': 'application/json',
            'apikey': self.global_key
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                if method.upper() == 'GET':
                    response = await client.get(url, headers=headers, params=params)
                elif method.upper() == 'POST':
                    response = await client.post(url, headers=headers, json=data)
                elif method.upper() == 'DELETE':
                    response = await client.delete(url, headers=headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                response.raise_for_status()

                # Try to parse as JSON, fallback to text if not JSON
                try:
                    return response.json()
                except ValueError:
                    # Response is not JSON, return as text
                    return response.text

            except httpx.HTTPStatusError as e:
                logger.error(f"Evolution API error: {e.response.status_code} - {e.response.text}")
                raise Exception(f"Evolution API error: {e.response.status_code}")
            except Exception as e:
                logger.error(f"Evolution API request failed: {str(e)}")
                raise Exception(f"Failed to communicate with Evolution API: {str(e)}")

    async def create_instance(self, instance_name: str) -> Dict[str, Any]:
        """Create a new WhatsApp instance."""
        logger.info(f"Creating Evolution API instance: {instance_name}")
        data = {
            "instanceName": instance_name,
            "integration": "WHATSAPP-BAILEYS",
            "token": self.global_key
        }
        result = await self._make_request('POST', '/instance/create', data)
        logger.info(f"Instance {instance_name} created successfully")

        # Handle case where result might be a string or dict
        if isinstance(result, str):
            # Some Evolution API versions return success message as string
            return {"instanceName": instance_name, "status": "created"}
        elif isinstance(result, dict):
            return result
        else:
            return {"instanceName": instance_name}

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
        data = {
            "webhook": {
                "url": webhook_url,
                "enabled": True
            }
        }
        if secret:
            data["webhook"]["byEvents"] = True
            data["webhook"]["events"] = ["MESSAGES_UPSERT"]

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