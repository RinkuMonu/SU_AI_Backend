import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import asyncio
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

from fastapi import HTTPException, status

class EmailService:
    @staticmethod
    async def send_otp_email(to_email: str, otp: str):
        # Run synchronous SMTP code in an executor
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, EmailService._send_otp_email_sync, to_email, otp)

    @staticmethod
    def _send_otp_email_sync(to_email: str, otp: str):
        if not settings.SMTP_HOST or not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
            if settings.ENVIRONMENT == "development":
                # Silently skip sending email in development if SMTP is unconfigured. 
                # (OTP is hardcoded to 123456 in development).
                return
            else:
                logger.error("SMTP is not configured in production.")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Email service is unavailable. SMTP is not configured."
                )
        
        try:
            msg = MIMEMultipart()
            msg['From'] = settings.SMTP_FROM_EMAIL
            msg['To'] = to_email
            msg['Subject'] = "Your SevenUnique AI Verification Code"
            
            body = f"Your verification code is: {otp}\n\nThis code will expire in 10 minutes."
            msg.attach(MIMEText(body, 'plain'))
            
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(msg)
            server.quit()
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            logger.info(f"OTP for {to_email} is {otp}")
            # If in development or if SMTP fails, do not block signup
            # Simply log it and return
            return
