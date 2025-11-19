"""Email service for sending notifications with retry logic."""
import smtplib
from email.mime.text import MIMEText
from typing import List, Optional
import logging

from src.core.config import settings
from src.core.retry_utils import retry_smtp_operation

logger = logging.getLogger(__name__)


class EmailService:
    """Handle email operations with automatic retry on transient failures."""
    
    def __init__(self):
        """Initialize email service with settings."""
        self.smtp_server = settings.SMTP_SERVER
        self.smtp_port = settings.SMTP_PORT
        self.smtp_user = settings.SMTP_USER
        self.smtp_pass = settings.SMTP_PASS
        self.support_email = settings.SUPPORT_EMAIL
        self.smtp_timeout = settings.SMTP_TIMEOUT
    
    def is_configured(self) -> bool:
        """
        Check if SMTP is properly configured.
        
        Returns:
            True if SMTP credentials are set, False otherwise
        """
        return all([self.smtp_user, self.smtp_pass, self.support_email])
    
    async def send_handoff_notification(
        self,
        conversation_id: str,
        query: str,
        context: str,
        recipient_emails: Optional[List[str]] = None
    ) -> bool:
        """
        Send handoff email notification with automatic retry.

        Args:
            conversation_id: ID of the conversation being escalated
            query: User's query text
            context: Context from knowledge base
            recipient_emails: List of email addresses to send notification to (defaults to support_email)

        Returns:
            True if email sent successfully, False otherwise
        """
        recipients = recipient_emails or ([self.support_email] if self.support_email else [])
        logger.info(f"📧 EMAIL DEBUG - Starting handoff notification for conv: {conversation_id}")
        logger.info(f"📧 EMAIL DEBUG - SMTP Config - Server: {self.smtp_server}, Port: {self.smtp_port}, User: {self.smtp_user}, Recipients: {recipients}")

        if not self.is_configured():
            logger.warning("SMTP not configured, skipping email notification")
            return False

        if not recipients:
            logger.warning("No recipient emails specified, skipping email notification")
            return False

        try:
            await self._send_email_with_retry(conversation_id, query, context, recipients)
            logger.info(f"✅ Handoff email sent for conversation {conversation_id} to {len(recipients)} recipients")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"❌ SMTP authentication failed: {e}")
            return False  # Don't retry auth errors

        except Exception as e:
            logger.error(f"❌ Failed to send handoff email after retries: {e}")
            return False
    
    @retry_smtp_operation(max_attempts=2)
    async def _send_email_with_retry(
        self,
        conversation_id: str,
        query: str,
        context: str,
        recipients: List[str]
    ) -> None:
        """
        Send email with automatic retry on connection errors.

        This method is wrapped with retry decorator to handle transient failures.
        """
        msg = self._create_handoff_message(conversation_id, query, context, recipients)
        self._send_smtp_message(msg, recipients)
    
    def _create_handoff_message(
        self,
        conv_id: str,
        query: str,
        context: str,
        recipients: List[str]
    ) -> MIMEText:
        """
        Create email message for handoff notification.

        Args:
            conv_id: Conversation ID
            query: User query
            context: Knowledge base context (truncated to 500 chars)
            recipients: List of email addresses to send to

        Returns:
            MIMEText email message
        """
        body = f"""
Human handoff requested for conversation {conv_id}

User Query: {query}

Context: {context[:500]}...

Please review and respond to the user.
        """

        msg = MIMEText(body)
        msg['Subject'] = f"Human Handoff: Conversation {conv_id}"
        msg['From'] = self.smtp_user
        msg['To'] = ', '.join(recipients)  # Multiple recipients in To field

        return msg
    
    def _send_smtp_message(self, msg: MIMEText, recipients: List[str]) -> None:
        """
        Send email message via SMTP.

        Args:
            msg: Email message to send
            recipients: List of email addresses to send to

        Raises:
            smtplib.SMTPException: On SMTP errors
            ConnectionError: On connection failures
        """
        logger.info(f"📧 EMAIL DEBUG - Connecting to SMTP: {self.smtp_server}:{self.smtp_port}, Timeout: {self.smtp_timeout}")
        try:
            with smtplib.SMTP_SSL(
                self.smtp_server,
                self.smtp_port,
                timeout=self.smtp_timeout
            ) as server:
                logger.info("📧 EMAIL DEBUG - SMTP connection established")
                logger.info(f"📧 EMAIL DEBUG - Attempting login for user: {self.smtp_user}")
                server.login(self.smtp_user, self.smtp_pass)
                logger.info("📧 EMAIL DEBUG - SMTP login successful")
                logger.info(f"📧 EMAIL DEBUG - Sending email from {self.smtp_user} to {recipients}")
                server.sendmail(
                    self.smtp_user,
                    recipients,
                    msg.as_string()
                )
                logger.info("📧 EMAIL DEBUG - Email sent successfully")
        except Exception as e:
            logger.error(f"📧 EMAIL DEBUG - SMTP operation failed: {e}")
            raise


# Global email service instance
email_service = EmailService()
