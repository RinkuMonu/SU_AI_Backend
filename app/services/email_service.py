import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class EmailService:
    @staticmethod
    async def send_verification_email(to_email: str, verification_link: str, full_name: Optional[str] = None):
        """Send verification email without external SMTP dependency."""
        recipient_name = full_name or to_email.split('@')[0]
        logger.info(f"🔗 [VERIFICATION EMAIL] To: {to_email} ({recipient_name}) | Verification Link: {verification_link}")
        return True

    @staticmethod
    def _send_verification_email_sync(to_email: str, verification_link: str, full_name: Optional[str] = None):
        recipient_name = full_name or to_email.split('@')[0]
        logger.info(f"🔗 [VERIFICATION EMAIL SYNC] To: {to_email} ({recipient_name}) | Link: {verification_link}")
        return True

    @staticmethod
    async def send_password_reset_email(to_email: str, reset_link: str, full_name: Optional[str] = None):
        """Send password reset email without external SMTP dependency."""
        recipient_name = full_name or to_email.split('@')[0]
        logger.info(f"🔑 [PASSWORD RESET EMAIL] To: {to_email} ({recipient_name}) | Reset Link: {reset_link}")
        return True

    @staticmethod
    def _send_password_reset_email_sync(to_email: str, reset_link: str, full_name: Optional[str] = None):
        recipient_name = full_name or to_email.split('@')[0]
        logger.info(f"🔑 [PASSWORD RESET EMAIL SYNC] To: {to_email} ({recipient_name}) | Reset Link: {reset_link}")
        return True

    @staticmethod
    async def send_otp_email(to_email: str, otp: str):
        """Send OTP verification code without external SMTP dependency."""
        logger.info(f"🔢 [OTP EMAIL] To: {to_email} | OTP Code: {otp}")
        return True

    @staticmethod
    def _send_otp_email_sync(to_email: str, otp: str):
        logger.info(f"🔢 [OTP EMAIL SYNC] To: {to_email} | OTP Code: {otp}")
        return True

    @staticmethod
    def _send_email_sync(to_email: str, subject: str, text_body: str, html_body: str, logo_cid: Optional[str] = None):
        """Universal email dispatch stub (SMTP removed)."""
        logger.info(f"📧 [EMAIL SERVICE - SMTP REMOVED] To: {to_email} | Subject: {subject}")
        return True
